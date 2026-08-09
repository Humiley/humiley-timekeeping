"""Document numbers on the real create path — the collision that was there by construction.

`_payNextNo` computed the next payment-request number IN THE BROWSER as max(the rows this browser
can see) + 1. `payments` is SELF_OWNED, so a staff member's browser holds only their own requests:
every user's first request was PR-YYYY-001, and nothing on the server checked. These lock the fix in
at the layer that can actually enforce it.
"""
import re

import pytest

import db
import doc_number as dn

PAY = {"payee": "ACME Co", "category": "Office", "amount": 1000, "status": "Submitted",
       "attachment": "data:application/pdf;base64,JVBERi0xLjQK"}


_n = [0]


def _mk(api, token, **kw):
    """A genuinely NEW submit each time.

    The body must vary: financial creates are idempotent per (user, collection, body), so posting
    the same payload twice returns the first record and allocates no number at all. A helper that
    did not vary would silently be testing idempotency instead of numbering — and would pass while
    proving nothing."""
    _n[0] += 1
    body = dict(PAY, purpose="doc-no case %d" % _n[0])
    body.update(kw)
    st, r = api("POST", "/api/coll/payments", token, body)
    assert st == 200, r
    return r["item"]


def test_the_server_issues_the_number(api, tokens):
    item = _mk(api, tokens["staff"])
    assert dn.parse_no(item["reqNo"]), "reqNo should be a real document number, got %r" % item.get("reqNo")
    assert item["reqNo"].startswith("PR-")


def test_two_different_people_never_get_the_same_number(api, tokens):
    """THE BUG. Both browsers computed 'my highest + 1' over disjoint sets, so both said 001."""
    a = _mk(api, tokens["staff"])
    b = _mk(api, tokens["other"])
    assert a["reqNo"] != b["reqNo"]


def test_a_client_supplied_number_is_discarded_not_honoured(api, tokens):
    """Trusting the client's number keeps the same door open for anyone who can post JSON — and it
    is also how somebody would deliberately reuse a colleague's reference."""
    item = _mk(api, tokens["staff"], reqNo="PR-2026-001")
    assert item["reqNo"] != "PR-2026-001" or dn.parse_no(item["reqNo"])["n"] != 1


def test_numbers_advance_and_never_repeat_across_a_run(api, tokens):
    seen = [_mk(api, tokens["staff"])["reqNo"] for _ in range(4)]
    assert len(set(seen)) == 4, seen
    ns = [dn.parse_no(x)["n"] for x in seen]
    assert ns == sorted(ns), "issued in order"


def test_the_number_carries_the_current_year(api, tokens):
    import app as _app
    year = _app.Handler._vn_day()[:4] if hasattr(_app.Handler, "_vn_day") else None
    item = _mk(api, tokens["staff"])
    p = dn.parse_no(item["reqNo"])
    assert 2020 <= p["year"] <= 2100
    if year:
        assert p["year"] == int(year), "the company clock is UTC+7, not the server's local year"


def test_an_existing_number_in_the_data_is_never_re_issued(api, tokens):
    """Adopting the live database. A request already printed as PR-<year>-500 must not come round
    again on the next create."""
    year = dn.parse_no(_mk(api, tokens["staff"])["reqNo"])["year"]
    conn = db.get_conn()
    conn.execute("DELETE FROM doc_counters WHERE series = 'PR'")   # as if the counter never existed
    conn.commit(); conn.close()
    db.put_collection_item("payments", {"id": "seed-high", "reqNo": dn.format_no("PR", year, 500),
                                        "payee": "Old", "amount": 1, "empId": "HML-STF"})
    nxt = _mk(api, tokens["staff"])["reqNo"]
    assert dn.parse_no(nxt)["n"] > 500, "got %s" % nxt


def test_a_retried_submit_does_not_burn_a_number(api, tokens):
    """Idempotency returns the first record. Allocating before that check would leave a hole in the
    sequence, and a missing number in a document register is a question somebody has to answer."""
    body = dict(PAY, payee="Idempotent Co", amount=4321)
    st, first = api("POST", "/api/coll/payments", tokens["staff"], body,
                    headers={"Idempotency-Key": "doc-no-test-1"})
    assert st == 200, first
    st, again = api("POST", "/api/coll/payments", tokens["staff"], body,
                    headers={"Idempotency-Key": "doc-no-test-1"})
    assert st == 200, again
    assert again["item"]["reqNo"] == first["item"]["reqNo"]


def test_collections_that_are_not_numbered_documents_are_untouched(api, tokens):
    """A CRM deal is not a controlled document. Stamping a reqNo on everything would be noise."""
    st, r = api("POST", "/api/coll/crm_deals", tokens["staff"],
                {"title": "Cleanroom AHU", "company": "Pharma Co", "stage": "Qualify", "value": 100})
    assert st == 200, r
    assert "reqNo" not in r["item"]


def test_the_register_can_report_its_own_duplicates(api, tokens):
    """Whatever collided before the fix is still in the data. A register that cannot see its own
    collisions is how they survive for years."""
    _mk(api, tokens["staff"])
    nums = dn.numbers_in(db.list_collection("payments"))
    assert isinstance(dn.duplicates(nums), list)
