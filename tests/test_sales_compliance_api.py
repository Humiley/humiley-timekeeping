"""/api/sales/compliance — is the revenue side fit to be looked at?

The HR audit pack answers this for the people side. Nothing answered it for the money side. Each
item is a thing somebody has to go and fix, not a score — a compliance screen that produces a
percentage is a screen nobody acts on.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("crm_companies", "sales_quotes"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _get(api, token):
    return api("GET", "/api/sales/compliance", token)


def test_it_is_not_for_staff_or_a_line_manager(api, tokens):
    """It lists every customer's tax identity and every contract value."""
    assert _get(api, tokens["staff"])[0] == 403
    assert _get(api, tokens["mgr"])[0] == 403


def test_it_needs_a_session(api, tokens):
    assert _get(api, None)[0] == 401


def test_a_customer_that_cannot_be_billed_is_named_with_the_missing_field(api, tokens):
    db.put_collection_item("crm_companies", {"id": "c1", "name": "No Tax Code Co"})
    code, r = _get(api, tokens["management"])
    assert code == 200, r
    hit = [x for x in r["cannotBill"] if x["name"] == "No Tax Code Co"]
    assert hit and any("Tax code" in m for m in hit[0]["missing"])


def test_a_complete_customer_is_not_listed(api, tokens):
    db.put_collection_item("crm_companies", {"id": "c2", "name": "Complete Co",
                                             "legalNameVn": "Cty Complete", "mst": "0123456789",
                                             "regAddress": "HCM"})
    _, r = _get(api, tokens["management"])
    assert "Complete Co" not in {x["name"] for x in r["cannotBill"]}


def test_the_unrecorded_tax_treatment_is_itself_a_finding(api, tokens):
    """Until somebody records when retention and an advance become taxable, no VAT figure can be
    stated on any contract — so it is the single highest-leverage thing on this screen."""
    _, r = _get(api, tokens["management"])
    assert r["taxTreatment"]["ready"] is False
    qs = " ".join(m["question"] for m in r["taxTreatment"]["missing"])
    assert "retention" in qs and "advance" in qs


def test_a_quotation_past_its_validity_and_still_open_is_surfaced(api, tokens):
    """A win rate measured only on the ones somebody remembered to close always flatters."""
    db.put_collection_item("sales_quotes", {"id": "q1", "quoteNo": "QT-2026-0001", "status": "issued",
                                            "validUntil": "2020-01-01", "title": "Old quote"})
    _, r = _get(api, tokens["management"])
    assert [x["quoteNo"] for x in r["quotationsPastValidity"]] == ["QT-2026-0001"]


def test_a_quotation_still_inside_its_validity_is_left_alone(api, tokens):
    db.put_collection_item("sales_quotes", {"id": "q2", "quoteNo": "QT-2026-0002", "status": "issued",
                                            "validUntil": "2099-01-01"})
    _, r = _get(api, tokens["management"])
    assert r["quotationsPastValidity"] == []


def test_a_loss_with_no_reason_recorded_is_flagged(api, tokens):
    """Older rows predate the rule that a loss needs a reason; the register should say so rather
    than quietly charting an undiagnosable win rate."""
    db.put_collection_item("sales_quotes", {"id": "q3", "quoteNo": "QT-2026-0003", "status": "lost"})
    _, r = _get(api, tokens["management"])
    assert "QT-2026-0003" in r["lostWithoutReason"]


def test_what_the_portal_does_not_do_is_stated_plainly(api, tokens):
    """So nobody assumes otherwise — including whoever inherits this system."""
    _, r = _get(api, tokens["management"])
    blob = " ".join(r["doesNotDo"])
    assert "ký hiệu" in blob and "Decree 123/2020" in blob
    assert "never as confirmed" in blob


def test_the_open_questions_travel_with_it(api, tokens):
    _, r = _get(api, tokens["management"])
    topics = {u["topic"] for u in r["unresolved"]}
    assert "The retention tax point" in topics and "MST check digit" in topics


def test_a_clean_revenue_side_says_so_rather_than_showing_a_score(api, tokens):
    """It counts things to answer. A percentage is a number nobody acts on."""
    _, r = _get(api, tokens["management"])
    assert isinstance(r["findings"], int)
    assert "to answer" in r["statement"] or "Nothing outstanding" in r["statement"]
