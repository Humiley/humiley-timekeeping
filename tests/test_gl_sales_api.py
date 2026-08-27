"""A claim, a receipt and a credit note reaching the ledger over HTTP.

What only this level can test: which document a caller may post, whether they can choose the month
it lands in, and whether the same document can post twice. The last one is the expensive case —
posting a claim twice doubles revenue AND the receivable, so the ledger still balances and no report
says a word.
"""
import pytest

import db
import gl


PERIOD = "2026-06"


def _claim(cid="PA-GL-1", certified=2_000_000_000, vat=200_000_000, status="certified",
           when="2026-06-20T10:00:00Z", **kw):
    return db.put_collection_item("sales_applications", dict({
        "id": cid, "appNo": cid, "status": status, "certifiedAt": when,
        "certifiedThis": certified, "vatAmount": vat, "retentionThis": 100_000_000,
        "advanceRecovered": 300_000_000, "netPayable": certified - 400_000_000,
        "vatSet": True,
    }, **kw))


def _receipt(rid="RC-GL-1", amount=1_760_000_000, when="2026-06-25", method="Bank transfer"):
    return db.put_collection_item("sales_receipts", {
        "id": rid, "receiptNo": rid, "amount": amount, "receivedOn": when, "method": method,
        "allocations": {"PA-GL-1": amount},
    })


def _credit(nid="CN-GL-1", value=50_000_000, vat=5_000_000, status="issued", when="2026-06-28"):
    return db.put_collection_item("sales_credits", {
        "id": nid, "creditNo": nid, "status": status, "issuedOn": when,
        "creditThis": value, "vatAmount": vat,
    })


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM gl_entries")
    conn.execute("DELETE FROM gl_batches")
    conn.commit()
    conn.close()
    for coll in ("sales_applications", "sales_receipts", "sales_credits", db.GL_PERIODS):
        for d in db.list_collection(coll):
            if str(d.get("id", "")).startswith(("PA-GL", "RC-GL", "CN-GL")) or coll == db.GL_PERIODS:
                db.delete_collection_item(coll, d.get("id"))
    yield


# --- a certified claim ----------------------------------------------------------------------------

def test_a_certified_claim_posts_revenue_and_a_receivable(api, tokens):
    _claim()
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert s == 200, r
    assert r["period"] == PERIOD, "the claim landed in the month it was certified"

    s, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    by = {row["account"]: row for row in sm["trialBalance"]["rows"]}
    assert by["511"]["credit"] == 2_000_000_000
    assert by["3331"]["credit"] == 200_000_000
    assert by["131"]["debit"] == 2_200_000_000
    assert sm["trialBalance"]["balanced"]
    # And the P&L bottom line now says the company earned something.
    assert sm["result"]["income"] == 2_000_000_000


def test_a_draft_claim_does_not_post(api, tokens):
    _claim(status="draft")
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert s == 409
    assert "certified by e-signature" in r.get("error", "")


def test_the_same_claim_cannot_post_twice(api, tokens):
    """Doubling revenue AND the receivable keeps the ledger balanced, which is exactly why this
    cannot be left to whoever is clicking."""
    _claim()
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "invoice", "id": "PA-GL-1"})[0] == 200
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert s == 409 and "already been posted" in r.get("error", "")

    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert sm["result"]["income"] == 2_000_000_000, "revenue doubled"


def test_the_caller_cannot_choose_which_month_a_claim_lands_in(api, tokens):
    """The document's date decides. A caller passing a period would be choosing where revenue
    sits — which is the one thing the date exists to settle."""
    _claim(when="2026-06-20T10:00:00Z")
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "invoice", "id": "PA-GL-1", "period": "2026-01"})
    assert s == 200
    assert r["period"] == "2026-06"


def test_a_claim_with_no_date_at_all_is_refused_rather_than_dated_today(api, tokens):
    _claim(when="")
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert s == 409
    assert "no month to file it in" in r.get("error", "")


def test_a_claim_certifying_nothing_is_refused(api, tokens):
    _claim(certified=0, vat=0)
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert s == 409
    assert "certifies nothing" in r.get("error", "")


# --- cash and credits ------------------------------------------------------------------------------

def test_a_receipt_posts_cash_against_the_receivable(api, tokens):
    _receipt()
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "receipt", "id": "RC-GL-1"})
    assert s == 200, r
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    by = {row["account"]: row for row in sm["trialBalance"]["rows"]}
    assert by["112"]["debit"] == 1_760_000_000
    assert by["131"]["credit"] == 1_760_000_000


def test_a_credit_note_posts_only_once_issued(api, tokens):
    _credit(status="draft")
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "creditNote", "id": "CN-GL-1"})
    assert s == 409 and "has not been given to anybody" in r.get("error", "")

    db.put_collection_item("sales_credits", dict(db.get_collection_item("sales_credits", "CN-GL-1"),
                                                 status="issued"))
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "creditNote", "id": "CN-GL-1"})[0] == 200


# --- the month, end to end -------------------------------------------------------------------------

def test_claim_then_cash_then_credit_leaves_a_receivable_anybody_can_read(api, tokens):
    """The whole point of the spine: one number for what this customer still owes, arrived at by
    adding up documents rather than by asking somebody."""
    _claim(); _receipt(); _credit()
    for src, did in (("invoice", "PA-GL-1"), ("receipt", "RC-GL-1"), ("creditNote", "CN-GL-1")):
        s, r = api("POST", "/api/gl/post", tokens["management"], {"source": src, "id": did})
        assert s == 200, (src, r)

    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    tb = sm["trialBalance"]
    assert tb["balanced"], tb["difference"]
    by = {row["account"]: row for row in tb["rows"]}
    # 2,200,000,000 billed − 1,760,000,000 paid − 55,000,000 credited
    assert by["131"]["balance"] == 385_000_000
    assert sm["result"]["income"] == 1_950_000_000
    assert by["112"]["balance"] == 1_760_000_000


def test_the_summary_lists_every_sell_side_document_the_month_still_owes(api, tokens):
    _claim(); _receipt(); _credit()
    _, before = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert {p["source"] for p in before["pending"]} == {"invoice", "receipt", "creditNote"}

    for src, did in (("invoice", "PA-GL-1"), ("receipt", "RC-GL-1"), ("creditNote", "CN-GL-1")):
        api("POST", "/api/gl/post", tokens["management"], {"source": src, "id": did})
    _, after = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert after["pending"] == []


def test_a_document_in_another_month_is_not_listed_as_this_months_work(api, tokens):
    _claim(cid="PA-GL-2", when="2026-05-20T10:00:00Z")
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert all(p.get("id") != "PA-GL-2" for p in sm["pending"])


def test_an_unpriced_vat_line_travels_with_the_pending_row(api, tokens):
    """So the person about to post it sees the caveat before they click, not after."""
    _claim(vatSet=False)
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    row = next(p for p in sm["pending"] if p["source"] == "invoice")
    assert any("tax point" in w for w in row.get("warnings", []))


def test_a_closed_month_refuses_a_sell_side_document_too(api, tokens):
    _claim()
    api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-GL-1"})
    assert api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})[0] == 200

    _receipt()
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "receipt", "id": "RC-GL-1"})
    assert s == 409 and "is closed" in r.get("error", "")


def test_staff_cannot_post_a_claim(api, tokens):
    _claim()
    assert api("POST", "/api/gl/post", tokens["staff"],
               {"source": "invoice", "id": "PA-GL-1"})[0] == 403
