"""The contract record — Stage 3 over the wire.

sales_contract.py proves the arithmetic. These prove the document: that it can only come from an
ACCEPTED quotation with the trace intact, that an in-flight job can have its real balances loaded so
the screen is not structurally zero on day one, and that it cannot be activated on terms the engine
would refuse to compute.
"""
import pytest

import db
import sales_contract as SC
import sales_doc as S


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


LINES = [{"desc": "Cleanroom AHU", "qty": 2, "unitPrice": 500_000_000}]


def _q(api, token, **b):
    return api("POST", "/api/sales/quote", token, b)


def _c(api, token, **b):
    return api("POST", "/api/sales/contract", token, b)


def _accepted_quote(api, token):
    q = _q(api, token, action="draft", title="AHU supply", accountName="Pharma Co", lines=LINES)[1]["item"]
    _q(api, token, action="issue", id=q["id"])
    _q(api, token, action="accept", id=q["id"])
    return db.get_collection_item("sales_quotes", q["id"])


TERMS = dict(action="terms", advancePct=30, retentionPct=5, warrantyMonths=12,
             releaseRule=SC.REL_WARRANTY_END, recoveryRule=SC.REC_PRORATA)


# ── it can only come from an accepted offer ──────────────────────────────────────────────────────

def test_a_contract_is_built_from_an_accepted_quotation(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    st, r = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])
    assert st == 200, r
    assert r["item"]["value"] == 1_000_000_000
    assert r["item"]["quoteNo"] == q["quoteNo"]


def test_every_contract_line_points_back_at_the_quotation_line(api, tokens):
    """Per LINE, not per document — it is what makes a trace possible at all."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    assert all(l["src"]["coll"] == "sales_quotes" and l["src"]["id"] == q["id"] for l in c["lines"])


def test_an_unaccepted_quotation_cannot_become_a_contract(api, tokens):
    """Otherwise the contract cannot say which offer the customer actually agreed to."""
    q = _q(api, tokens["staff"], action="draft", title="X", lines=LINES)[1]["item"]
    _q(api, tokens["staff"], action="issue", id=q["id"])
    st, r = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])
    assert st == 400 and "ACCEPTED" in r["error"]


def test_one_quotation_makes_only_one_contract(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])
    st, r = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])
    assert st == 400 and "already exists" in r["error"]


# ── terms ────────────────────────────────────────────────────────────────────────────────────────

def test_setting_the_terms_returns_what_they_are_worth(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    st, r = _c(api, tokens["staff"], id=c["id"], **TERMS)
    assert st == 200, r
    assert r["advance"] == 300_000_000, "30% of the ₫1bn carried from the quotation"
    assert r["retentionCap"] == 50_000_000


def test_the_terms_answer_carries_the_vat_refusal(api, tokens):
    """The screen must be able to show the blocker at the point the terms are set, not later."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    r = _c(api, tokens["staff"], id=c["id"], **TERMS)[1]
    assert r["vat"]["ready"] is False


def test_a_signed_contract_cannot_have_its_terms_rewritten(api, tokens):
    """They are what the customer signed. A variation raises them; an edit rewrites history."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    _c(api, tokens["staff"], action="activate", id=c["id"])
    st, r = _c(api, tokens["staff"], id=c["id"], action="terms", advancePct=50)
    assert st == 400 and "variation" in r["error"]


# ── the in-flight load ───────────────────────────────────────────────────────────────────────────

def test_an_in_flight_contract_can_have_its_real_balances_loaded(api, tokens):
    """Without it, every job already running shows zero advance outstanding and zero retention held
    — figures that are structurally zero on an authoritative-looking screen."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    st, r = _c(api, tokens["staff"], action="opening", id=c["id"],
               certifiedToDate=400_000_000, advanceOutstanding=180_000_000, retentionHeld=20_000_000)
    assert st == 200, r
    assert r["item"]["retentionHeld"] == 20_000_000 and r["item"]["openingLoaded"] is True
    assert r["item"]["openingBy"]


def test_the_opening_load_is_audited(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], action="opening", id=c["id"], retentionHeld=1)
    assert any(x.get("action") == "Loaded contract opening balances" for x in db.list_collection("audit"))


def test_balances_cannot_be_loaded_after_activation(api, tokens):
    """After that they move only through certified claims. A back door here would let somebody
    type over what the claims computed."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    _c(api, tokens["staff"], action="activate", id=c["id"])
    st, r = _c(api, tokens["staff"], action="opening", id=c["id"], retentionHeld=99)
    assert st == 400 and "certified claims" in r["error"]


# ── activation ───────────────────────────────────────────────────────────────────────────────────

def test_activating_takes_a_contract_number_and_opens_the_advance(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    st, r = _c(api, tokens["staff"], action="activate", id=c["id"])
    assert st == 200, r
    assert r["item"]["contractNo"].startswith("SO-")
    assert r["item"]["advanceOutstanding"] == 300_000_000


def test_a_contract_with_an_advance_but_no_recovery_rule_cannot_be_activated(api, tokens):
    """The engine would refuse to compute a claim on it, so activating it would create a contract
    that can never be billed — a dead end discovered a month later."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], action="terms", advancePct=30)
    st, r = _c(api, tokens["staff"], action="activate", id=c["id"])
    assert st == 400 and "recovery rule" in r["error"]


# ── closing ──────────────────────────────────────────────────────────────────────────────────────

def test_a_contract_that_does_not_close_cleanly_is_blocked_and_says_why(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    _c(api, tokens["staff"], action="activate", id=c["id"])
    st, r = _c(api, tokens["staff"], action="close", id=c["id"])
    assert st == 200 and r.get("blocked") is True
    assert any("never recovered" in i for i in r["final"]["issues"])


def test_it_can_be_closed_once_the_outstanding_items_are_acknowledged(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    _c(api, tokens["staff"], action="activate", id=c["id"])
    st, r = _c(api, tokens["staff"], action="close", id=c["id"], acknowledge=True)
    assert st == 200 and r["item"]["status"] == S.CLOSED
    assert r["item"]["finalAccount"]["advanceOutstanding"] == 300_000_000


# ── the generic route stays shut ─────────────────────────────────────────────────────────────────

def test_the_collection_route_cannot_rewrite_the_balances(api, tokens):
    """A blind whole-document PATCH would reset the advance and retention to whatever the browser
    last saw — the balances every later claim is computed from."""
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    cur = db.get_collection_item("sales_contracts", c["id"])
    st, r = api("PATCH", "/api/coll/sales_contracts/" + c["id"], tokens["management"],
                dict(cur, retentionHeld=0, advanceOutstanding=0))
    assert st == 400 and "/api/sales/contract" in r["error"]


def test_you_cannot_touch_somebody_elses_contract(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    assert _c(api, tokens["other"], action="activate", id=c["id"])[0] == 403


def test_it_needs_a_session(api, tokens):
    assert _c(api, None, action="from_quote", quoteId="x")[0] == 401


# ── the contract's own status machine ────────────────────────────────────────────────────────────

def test_a_contract_goes_draft_to_active_to_closed_not_the_quotations_path(api, tokens):
    """A contract is drafted, signed into force and closed. There is no "issued to the customer for
    consideration" step and "accepted" is not a thing that happens to it — so it has its own table
    rather than being bent through the quotation's."""
    assert S.CONTRACT_TRANSITIONS[S.DRAFT] == (S.ACTIVE, S.CANCELLED)
    assert S.CONTRACT_TRANSITIONS[S.ACTIVE] == (S.CLOSED, S.CANCELLED)
    assert S.CONTRACT_TRANSITIONS[S.CLOSED] == ()


def test_a_contract_cannot_be_closed_before_it_is_active(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    st, r = _c(api, tokens["staff"], action="close", id=c["id"], acknowledge=True)
    assert st == 400 and "draft" in r["error"]


def test_a_closed_contract_is_final(api, tokens):
    q = _accepted_quote(api, tokens["staff"])
    c = _c(api, tokens["staff"], action="from_quote", quoteId=q["id"])[1]["item"]
    _c(api, tokens["staff"], id=c["id"], **TERMS)
    _c(api, tokens["staff"], action="activate", id=c["id"])
    _c(api, tokens["staff"], action="close", id=c["id"], acknowledge=True)
    st, r = _c(api, tokens["staff"], action="activate", id=c["id"])
    assert st == 400 and "final" in r["error"]
