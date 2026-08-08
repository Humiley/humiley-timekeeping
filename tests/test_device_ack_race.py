"""Two people signing for the same stock line must not overwrite each other.

A device is a stock LINE, not one object: twenty safety helmets on one row, ten holders, everyone
acknowledging on their phone the same morning. Acknowledging rewrites the WHOLE document, so between
one signer's read and their write, anything that lands is lost — another signature, or a manager's
assignment together with its signed handover.

A mutex over the acknowledge path is not enough, because the write that destroys the signature is
often a manager's ordinary device PATCH, which takes no lock. The fix is a compare-and-swap in the
storage layer: write only while the stored `_rev` is still the one we read, and re-apply if it moved.

Measured on this code before the fix: twelve concurrent signatures on one row, ONE survived.
"""
import json
import threading
import urllib.error
import urllib.request

import db


def _post_ack(base_url, token, dev_id, img_tag):
    """One acknowledge request, as the browser sends it. Returns the HTTP status."""
    req = urllib.request.Request(
        base_url + "/api/coll/devices/" + dev_id,
        data=json.dumps({"ackSignature": {"image": "data:image/png;base64," + img_tag}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="PATCH")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_concurrent_signatures_on_one_stock_line_are_all_kept(api, tokens, base_url):
    """The headline case: several holders of the same line acknowledge at the same moment."""
    holders = [("HML-STF", "Staff One", tokens["staff"]),
               ("HML-OTH", "Other Staff", tokens["other"]),
               ("HML-MGR", "Dept Manager", tokens["mgr"]),
               ("HML-EDT", "Editor User", tokens["editor"])]
    st, b = api("POST", "/api/coll/devices", tokens["admin"], {
        "name": "Safety helmet", "category": "PPE", "qty": 20, "status": "Assigned",
        "assignments": [{"id": "a" + str(i), "empId": e, "name": n, "qty": 2}
                        for i, (e, n, _t) in enumerate(holders)]})
    assert st == 200, b
    dev = b["item"]

    ready = threading.Barrier(len(holders))
    codes = {}

    def sign(idx, token):
        ready.wait()                       # release them together, or there is no race to test
        codes[idx] = _post_ack(base_url, token, dev["id"], "AAA" + str(idx))

    ths = [threading.Thread(target=sign, args=(i, t)) for i, (_e, _n, t) in enumerate(holders)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()

    assert set(codes.values()) == {200}, "every acknowledge should succeed: %r" % codes
    row = db.get_collection_item("devices", dev["id"])
    signed = [a for a in (row.get("assignments") or []) if (a.get("signatures") or [])]
    assert len(signed) == len(holders), (
        "%d of %d signatures survived — a concurrent write overwrote the others"
        % (len(signed), len(holders)))
    # and each one is the RIGHT person's, not four copies of whoever wrote last
    assert {a["ackBy"] for a in signed} == {n for _e, n, _t in holders}


def test_a_signature_does_not_overwrite_a_concurrent_assignment(api, tokens, base_url):
    """The case a lock over the ack path cannot fix: the competing write is a manager's PATCH.

    Before the compare-and-swap this destroyed the new assignment, its quantity and its handover
    signature, while the register still added up — so nothing flagged it."""
    st, b = api("POST", "/api/coll/devices", tokens["admin"], {
        "name": "Impact driver", "category": "Tools", "qty": 10, "status": "Assigned",
        "assignments": [{"id": "a0", "empId": "HML-STF", "name": "Staff One", "qty": 1}]})
    assert st == 200, b
    dev = b["item"]

    ready = threading.Barrier(2)
    out = {}

    def ack():
        ready.wait()
        out["ack"] = _post_ack(base_url, tokens["staff"], dev["id"], "SIG")

    def assign():
        cur = db.get_collection_item("devices", dev["id"])
        body = dict(cur)
        body["assignments"] = list(cur.get("assignments") or []) + [
            {"id": "a1", "empId": "HML-OTH", "name": "Other Staff", "qty": 3,
             "signatures": [{"name": "Other Staff", "ack": True, "image": "data:image/png;base64,HAND"}]}]
        ready.wait()
        # tkApi attaches If-Match automatically to any full-object PATCH carrying _rev, which every
        # assign does — so this is the real request the manager's browser sends, precondition included.
        out["assign"] = api("PATCH", "/api/coll/devices/" + dev["id"], tokens["admin"], body,
                            headers={"If-Match": str(cur.get("_rev"))})[0]

    ts = [threading.Thread(target=ack), threading.Thread(target=assign)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    row = db.get_collection_item("devices", dev["id"])
    ids = {a.get("id") for a in (row.get("assignments") or [])}
    # The rule is: a request that reports SUCCESS must have kept its effect. Either write may lose the
    # race and be told so (409 for the assign, retry-then-409 for the ack) — what must never happen is
    # a 200 whose effect was silently erased by the other.
    assert out.get("assign") in (200, 409), out
    assert out.get("ack") in (200, 409), out
    if out.get("assign") == 200:
        assert "a1" in ids, "the manager's assignment reported success but was overwritten"
        a1 = [a for a in row["assignments"] if a.get("id") == "a1"][0]
        assert a1.get("signatures"), "the handover signature on the new assignment was lost"
    if out.get("ack") == 200:
        a0 = [a for a in row["assignments"] if a.get("id") == "a0"][0]
        assert a0.get("signatures"), "the acknowledgement reported success but was overwritten"


def test_the_acknowledgement_does_not_clobber_a_write_that_landed_after_its_read(
        api, tokens, base_url, monkeypatch):
    """The ack-side compare-and-swap, forced rather than raced for.

    Threads alone do not prove this: _ESIGN_LOCK already serialises ack-against-ack, so that test
    passes even with the conditional write removed. The write the lock CANNOT stop is a manager's
    ordinary PATCH, and catching it needs one exact interleaving. So we create it: a competing write
    is injected between the ack's read and the ack's write. The ack must notice the row moved,
    re-read and re-apply — never write its stale copy over the top."""
    st, b = api("POST", "/api/coll/devices", tokens["admin"], {
        "name": "Torque wrench", "category": "Tools", "qty": 5, "status": "Assigned",
        "assignments": [{"id": "a0", "empId": "HML-STF", "name": "Staff One", "qty": 1}]})
    assert st == 200, b
    dev = b["item"]

    orig_get = db.get_collection_item
    fired = {"done": False}

    def hooked(coll, item_id):
        row = orig_get(coll, item_id)
        if coll == "devices" and item_id == dev["id"] and not fired["done"]:
            fired["done"] = True                     # exactly once — the ack's FIRST read
            cur = orig_get("devices", dev["id"])
            cur["assignments"] = list(cur.get("assignments") or []) + [
                {"id": "a1", "empId": "HML-OTH", "name": "Other Staff", "qty": 2,
                 "signatures": [{"name": "Other Staff", "ack": True,
                                 "image": "data:image/png;base64,HANDOVER"}]}]
            db.put_collection_item("devices", cur)   # lands after the read, before the write
        return row

    monkeypatch.setattr(db, "get_collection_item", hooked)
    try:
        status = _post_ack(base_url, tokens["staff"], dev["id"], "MYSIG")
    finally:
        monkeypatch.setattr(db, "get_collection_item", orig_get)

    assert fired["done"], "the interleaving never happened — the test proved nothing"
    assert status == 200, "the acknowledgement should retry and succeed, got %s" % status
    row = db.get_collection_item("devices", dev["id"])
    by_id = {a["id"]: a for a in (row.get("assignments") or [])}
    assert "a1" in by_id, "the acknowledgement overwrote the assignment made after its read"
    assert by_id["a1"].get("signatures"), "the handover signature on that assignment was destroyed"
    assert by_id["a0"].get("signatures"), "the acknowledgement itself was not stored"
    assert by_id["a0"].get("ackBy") == "Staff One"


# ── the storage primitive underneath ─────────────────────────────────────────────────────────────

def test_compare_and_swap_writes_only_against_the_revision_it_read():
    item = db.put_collection_item("devices", {"name": "CAS probe", "qty": 1})
    try:
        rev = item["_rev"]
        assert db.put_collection_item_if_rev("devices", dict(item, note="first"), rev) is not None
        # the rev has moved on, so the same expectation must now fail rather than clobber
        assert db.put_collection_item_if_rev("devices", dict(item, note="stale"), rev) is None
        assert db.get_collection_item("devices", item["id"])["note"] == "first"
    finally:
        db.delete_collection_item("devices", item["id"])


def test_every_write_bumps_the_revision_exactly_once():
    """_rev is what every If-Match check in the API rests on. It used to be read in one statement and
    written in another, so concurrent writers duplicated it — twelve writes landed on rev 8."""
    item = db.put_collection_item("devices", {"name": "rev probe", "qty": 1})
    try:
        n, start = 10, threading.Barrier(10)

        def bump(_i):
            start.wait()
            db.put_collection_item("devices", dict(db.get_collection_item("devices", item["id"])))

        ths = [threading.Thread(target=bump, args=(i,)) for i in range(n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        assert db.get_collection_item("devices", item["id"])["_rev"] == item["_rev"] + n
    finally:
        db.delete_collection_item("devices", item["id"])


def test_the_audit_chain_is_not_reachable_through_the_swap():
    """audit is append-only with its own hash-chained writer — a CAS would corrupt the chain."""
    try:
        db.put_collection_item_if_rev("audit", {"id": "x", "action": "nope"}, 1)
        raise AssertionError("expected a refusal")
    except ValueError as e:
        assert "append-only" in str(e)
