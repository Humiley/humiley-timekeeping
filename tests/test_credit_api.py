"""The credit note over the wire — and the four balances a negative claim would have missed."""
import pytest

import app
import db
import sales_contract as SC
import sales_credit as CN


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_credits"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO','CN')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _certified(api, tokens, claim=200_000_000):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], advancePct=30,
          retentionPct=5, warrantyMonths=12, recoveryRule=SC.REC_PRORATA,
          releaseRule=SC.REL_WARRANTY_END)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    _post(api, tokens["staff"], "/api/sales/receipt", kind="advance", contractId=c["id"],
          amount=300_000_000)
    c = db.get_collection_item("sales_contracts", c["id"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-08", claims={c["lines"][0]["uid"]: claim})[1]["item"]
    _post(api, tokens["management"], "/api/sales/application", action="certify", id=a["id"])
    return db.get_collection_item("sales_contracts", c["id"]), \
        db.get_collection_item("sales_applications", a["id"])


def _cn(api, tokens, a, amount=100_000_000, **kw):
    return _post(api, tokens["staff"], "/api/sales/credit", action="draft",
                 applicationId=a["id"], amount=amount, **dict({"reason": "rejected_work"}, **kw))


def _sign(api, token, cid):
    return api("POST", "/api/esign", token,
               {"coll": "sales_credits", "id": cid, "meaning": "Applied credit note",
                "setStatus": CN.APPLIED})


# ── raising one ──────────────────────────────────────────────────────────────────────────────────

def test_a_draft_shows_all_three_reversals_before_anybody_signs(api, tokens):
    c, a = _certified(api, tokens)
    st, r = _cn(api, tokens, a)
    assert st == 200, r
    assert r["effect"]["retentionReleased"] == 5_000_000
    assert r["effect"]["advanceRestored"] == 30_000_000
    assert r["effect"]["netCredit"] == 65_000_000


def test_issuing_takes_a_CN_number(api, tokens):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    assert st == 200, r
    assert r["item"]["creditNo"].startswith("CN-")


def test_a_credit_note_records_why(api, tokens):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a, reason="")[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    assert st == 400 and "records WHY" in r["error"]


def test_an_invented_reason_is_refused(api, tokens):
    c, a = _certified(api, tokens)
    assert _cn(api, tokens, a, reason="because")[0] == 400


def test_it_cannot_credit_more_than_the_claim_certified(api, tokens):
    c, a = _certified(api, tokens)
    st, r = _cn(api, tokens, a, amount=250_000_000)
    assert st == 400 and "still creditable" in r["error"]


def test_it_cannot_be_raised_against_an_uncertified_claim(api, tokens):
    c, a = _certified(api, tokens)
    a2 = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
               period="2026-09", claims={c["lines"][0]["uid"]: 1_000})[1]["item"]
    st, r = _cn(api, tokens, a2, amount=500)
    assert st == 400 and "CERTIFIED" in r["error"]


# ── applying it is a SIGNATURE ───────────────────────────────────────────────────────────────────

def test_applying_is_not_an_action_on_this_endpoint(api, tokens):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/credit", action="apply", id=cn["id"])
    assert st == 400 and "e-signature, not an action" in r["error"]


def test_a_signed_credit_moves_every_balance_the_claim_moved(api, tokens, signing):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    st, r = _sign(api, tokens["management"], cn["id"])
    assert st == 200, r
    c2 = db.get_collection_item("sales_contracts", c["id"])
    a2 = db.get_collection_item("sales_applications", a["id"])
    assert c2["certifiedToDate"] == 100_000_000
    assert c2["retentionHeld"] == 5_000_000
    assert c2["advanceOutstanding"] == 270_000_000
    assert c2["lines"][0]["certifiedAmt"] == 100_000_000, "the line can be re-certified"
    assert a2["creditedAmt"] == 100_000_000 and a2["netPayable"] == 65_000_000


def test_the_credited_work_can_be_certified_again(api, tokens, signing):
    """The point of restoring the line balance: work rejected, redone, and re-certified."""
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    _sign(api, tokens["management"], cn["id"])
    c2 = db.get_collection_item("sales_contracts", c["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="2026-09",
                  claims={c2["lines"][0]["uid"]: 100_000_000})
    assert st == 200, r


def test_a_draft_credit_note_cannot_be_signed_into_effect(api, tokens, signing):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    st, r = _sign(api, tokens["management"], cn["id"])
    assert st == 400 and "issued credit note" in r["error"]
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 200_000_000


def test_signing_it_twice_does_not_credit_twice(api, tokens, signing):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    assert _sign(api, tokens["management"], cn["id"])[0] == 200
    _sign(api, tokens["management"], cn["id"])
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 100_000_000


def test_management_cannot_apply_a_credit_note_IT_raised(api, tokens, signing):
    c, a = _certified(api, tokens)
    cn = _post(api, tokens["management"], "/api/sales/credit", action="draft",
               applicationId=a["id"], amount=10_000_000, reason="pricing")[1]["item"]
    _post(api, tokens["management"], "/api/sales/credit", action="issue", id=cn["id"])
    st, r = _sign(api, tokens["management"], cn["id"])
    assert st == 403 and "other than the person who raised it" in r["error"]


def test_applying_is_a_management_act(api, tokens, signing):
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    assert _sign(api, tokens["mgr"], cn["id"])[0] == 403


# ── the generic route stays shut ────────────────────────────────────────────────────────────────

def test_the_collection_route_cannot_create_one(api, tokens):
    st, r = api("POST", "/api/coll/sales_credits", tokens["management"], {"amount": 1})
    assert st == 400 and "/api/sales/credit" in r["error"]


def test_an_issued_credit_note_cannot_be_edited(api, tokens):
    """Otherwise the amount somebody is about to sign is not the amount they read."""
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    st, r = _cn(api, tokens, a, amount=180_000_000, id=cn["id"])
    assert st == 400 and "cannot be edited" in r["error"]
    assert db.get_collection_item("sales_credits", cn["id"])["amount"] == 100_000_000


def test_a_contract_that_moved_under_the_signature_is_retried_not_overwritten(api, tokens, signing,
                                                                              monkeypatch):
    """Same compare-and-swap as the variation: a plain write loses a concurrent claim's deduction."""
    import db as _db
    c, a = _certified(api, tokens)
    cn = _cn(api, tokens, a)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    real, calls = _db.put_collection_item_if_rev, {"n": 0}

    def flaky(coll, item, rev):
        calls["n"] += 1
        if coll == "sales_contracts" and calls["n"] == 1:
            return None
        return real(coll, item, rev)

    monkeypatch.setattr(_db, "put_collection_item_if_rev", flaky)
    st, r = _sign(api, tokens["management"], cn["id"])
    assert st == 200, r
    assert calls["n"] >= 2
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 100_000_000
