"""Idempotency on financial submits: a retried identical POST (flaky field connection) must not
create a duplicate claim/payment/travel that could then be approved and paid twice."""
import threading
import db


def _count(reqno):
    return sum(1 for x in db.list_collection("payments") if x.get("reqNo") == reqno)


def _pay(reqno, amount=1000):
    return {"reqNo": reqno, "payee": "Vendor X", "amount": amount, "purpose": "parts",
            "attachment": "data:application/pdf;base64,QQ==", "status": "Submitted"}


def test_identical_retry_is_deduped(api, tokens):
    body = _pay("PR-IDEM-1")
    st1, b1 = api("POST", "/api/coll/payments", tokens["staff"], dict(body))
    st2, b2 = api("POST", "/api/coll/payments", tokens["staff"], dict(body))
    assert st1 == 200 and st2 == 200, (b1, b2)
    assert b1["item"]["id"] == b2["item"]["id"]        # the same record is returned, not a new one
    assert b2.get("idempotent") is True
    assert _count("PR-IDEM-1") == 1                     # exactly one row was created


def test_different_submits_create_distinct_records(api, tokens):
    _, b1 = api("POST", "/api/coll/payments", tokens["staff"], _pay("PR-IDEM-2", 1000))
    _, b2 = api("POST", "/api/coll/payments", tokens["staff"], _pay("PR-IDEM-2", 2000))   # different amount
    assert b1["item"]["id"] != b2["item"]["id"]


def test_dedup_is_scoped_per_user(api, tokens):
    body = _pay("PR-IDEM-3")
    _, b1 = api("POST", "/api/coll/payments", tokens["staff"], dict(body))
    _, b2 = api("POST", "/api/coll/payments", tokens["other"], dict(body))                # different requester
    assert b1["item"]["id"] != b2["item"]["id"]        # never merge two different people's submits


def test_concurrent_identical_submits_collapse_to_one(api, tokens):
    # The real transport-retry / double-tap case: several identical POSTs land CONCURRENTLY (the server
    # is threaded). The check + create must be atomic, so exactly one row is created and everyone gets
    # the same id — not one row per racing thread.
    body = _pay("PR-RACE")
    results, lock = [], threading.Lock()

    def submit():
        r = api("POST", "/api/coll/payments", tokens["staff"], dict(body))
        with lock:
            results.append(r)

    threads = [threading.Thread(target=submit) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok_ids = {r[1].get("item", {}).get("id") for r in results if r[0] == 200}
    assert len(ok_ids) == 1, "concurrent identical submits must collapse to ONE record; got %s" % ok_ids
    assert _count("PR-RACE") == 1, "exactly one row must exist for the raced submit"
