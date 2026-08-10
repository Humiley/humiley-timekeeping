"""The payment application — the only place a contract's balances move.

Everything else on the sell side describes intent. This changes what the customer owes, so the
tests that matter are the ones about money going wrong quietly: claiming past what is left,
certifying your own claim, and two claims certified at the same moment both spending the same
remaining balance.
"""
import threading

import pytest

import app
import db
import sales_contract as SC
import sales_doc as S


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()



@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    """Certifying, applying a variation and applying a credit note are all e-signatures now, so
    every test in this file drives /api/esign. The M365 re-auth is skipped here — the Part 11
    identity component has its own tests; these are about what the signature DOES."""
    monkeypatch.setattr(app, "DEMO_MODE", True)

def _post(api, token, path, **b):
    return api("POST", path, token, b)


def _live_contract(api, token, value=1_000_000_000, deposit=None, **terms):
    """A contract with its deposit already received, unless a test says otherwise.

    The deposit is a balance that moves when CASH moves, so a claim can only recover what actually
    arrived. These tests are about the claim arithmetic, so the money is banked up front; the test
    that cares about the other case passes deposit=0.
    """
    q = _post(api, token, "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co", lines=[{"desc": "Works", "qty": 1, "unitPrice": value}])[1]["item"]
    _post(api, token, "/api/sales/quote", action="issue", id=q["id"])
    _post(api, token, "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, token, "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    t = dict({"advancePct": 30, "retentionPct": 5, "warrantyMonths": 12,
              "recoveryRule": SC.REC_PRORATA, "releaseRule": SC.REL_WARRANTY_END}, **terms)
    _post(api, token, "/api/sales/contract", action="terms", id=c["id"], **t)
    _post(api, token, "/api/sales/contract", action="activate", id=c["id"])
    live = db.get_collection_item("sales_contracts", c["id"])
    want = SC.advance_amount(live) if deposit is None else deposit
    if want:
        _post(api, token, "/api/sales/receipt", kind="advance", contractId=c["id"], amount=want)
    return db.get_collection_item("sales_contracts", c["id"])


def _uid(c):
    return c["lines"][0]["uid"]



def _certify(api, token, aid, monkey=None):
    """Certifying is an e-signature now — the same act PMC's interim payment certificate has
    required for months. Tests drive it through /api/esign."""
    return api("POST", "/api/esign", token,
               {"coll": "sales_applications", "id": aid, "meaning": "Certified payment application",
                "setStatus": "certified"})

# ── the arithmetic a person signs ────────────────────────────────────────────────────────────────

def test_a_claim_shows_the_deductions_before_anybody_certifies_it(api, tokens):
    c = _live_contract(api, tokens["staff"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="2026-08", claims={_uid(c): 200_000_000})
    assert st == 200, r
    assert r["preview"]["advanceRecovered"] == 60_000_000
    assert r["preview"]["retentionThis"] == 10_000_000
    assert r["preview"]["netPayable"] == 130_000_000


def test_a_draft_moves_nothing_on_the_contract(api, tokens):
    c = _live_contract(api, tokens["staff"])
    _post(api, tokens["staff"], "/api/sales/application", action="draft",
          contractId=c["id"], claims={_uid(c): 200_000_000})
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["advanceOutstanding"] == 300_000_000, "untouched until certified"


def test_certifying_moves_the_balances_once(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 200_000_000})[1]["item"]
    st, r = _certify(api, tokens["management"], a["id"])
    assert st == 200, r
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["certifiedToDate"] == 200_000_000
    assert after["advanceOutstanding"] == 240_000_000
    assert after["retentionHeld"] == 10_000_000


def test_the_line_counter_moves_too_so_the_next_claim_starts_from_the_remainder(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 200_000_000})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    after = db.get_collection_item("sales_contracts", c["id"])
    assert S.open_amount(after["lines"][0], "certifiedAmt") == 800_000_000


# ── it must not overshoot ────────────────────────────────────────────────────────────────────────

def test_claiming_more_than_the_line_has_left_is_refused_with_the_shortfall(api, tokens):
    c = _live_contract(api, tokens["staff"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], claims={_uid(c): 1_200_000_000})
    assert st == 400 and "over by" in r["error"]


def test_a_second_claim_cannot_take_the_contract_past_its_value(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 900_000_000})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], claims={_uid(c): 200_000_000})
    assert st == 400, r


def test_a_claim_against_a_line_that_is_not_on_the_contract_is_refused(api, tokens):
    c = _live_contract(api, tokens["staff"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], claims={"nope": 1_000})
    assert st == 400 and "No line with this id" in r["error"]


def test_a_claim_can_only_be_raised_against_an_active_contract(api, tokens):
    c = _live_contract(api, tokens["staff"])
    _post(api, tokens["staff"], "/api/sales/contract", action="close", id=c["id"], acknowledge=True)
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], claims={_uid(c): 1_000})
    assert st == 400 and "ACTIVE" in r["error"]


# ── separation of duties ─────────────────────────────────────────────────────────────────────────

def test_you_cannot_certify_your_own_claim(api, tokens):
    """The buy side has enforced payer != approver for months. This is the same rule facing the
    other way: raising the claim and certifying it are two people."""
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 100_000_000})[1]["item"]
    st, r = _certify(api, tokens["staff"], a["id"])
    assert st == 403 and "somebody other than" in r["error"]


def test_a_certified_application_cannot_be_edited(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 100_000_000})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft", id=a["id"],
                  contractId=c["id"], claims={_uid(c): 999_000_000})
    assert st == 400 and "cannot be edited" in r["error"]


def test_certifying_twice_is_refused_so_the_balances_move_once(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 100_000_000})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    st, r = _certify(api, tokens["management"], a["id"])
    assert st == 400 and "already" in r["error"]
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 100_000_000


def test_certifying_is_audited(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 100_000_000})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    assert any(x.get("action") == "Certified payment application" for x in db.list_collection("audit"))


# ── concurrency: the one that costs money ────────────────────────────────────────────────────────

def test_two_claims_certified_at_once_cannot_both_spend_the_same_balance(api, tokens):
    """THE case this endpoint exists to survive. A read-then-write would let the second claim
    overwrite the first's deduction: both get certified, the contract records one, and the advance
    recovers half as fast as the money went out."""
    c = _live_contract(api, tokens["staff"])
    uid = _uid(c)
    apps = [_post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="p%d" % i, claims={uid: 400_000_000})[1]["item"]
            for i in range(2)]
    results, lock = [], threading.Lock()

    def go(a):
        r = _certify(api, tokens["management"], a["id"])
        with lock:
            results.append(r)

    ts = [threading.Thread(target=go, args=(a,)) for a in apps]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    after = db.get_collection_item("sales_contracts", c["id"])
    ok = [r for r in results if r[0] == 200]
    assert after["certifiedToDate"] == 400_000_000 * len(ok), \
        "the contract must record exactly what was certified, not less: %r" % after["certifiedToDate"]
    assert after["advanceOutstanding"] == 300_000_000 - 120_000_000 * len(ok)
    assert S.open_amount(after["lines"][0], "certifiedAmt") == 1_000_000_000 - 400_000_000 * len(ok)


def test_the_contract_never_ends_up_certifying_more_than_it_is_worth(api, tokens):
    """Six concurrent claims of 200m against a 1bn contract: at most five can be right."""
    c = _live_contract(api, tokens["staff"])
    uid = _uid(c)
    apps = [_post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="p%d" % i, claims={uid: 200_000_000})[1]["item"]
            for i in range(6)]
    lock = threading.Lock(); results = []

    def go(a):
        r = _certify(api, tokens["management"], a["id"])
        with lock:
            results.append(r)

    ts = [threading.Thread(target=go, args=(a,)) for a in apps]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["certifiedToDate"] <= 1_000_000_000, after["certifiedToDate"]
    assert after["certifiedToDate"] == 200_000_000 * len([r for r in results if r[0] == 200])


# ── it must not state a VAT figure ───────────────────────────────────────────────────────────────

def test_the_draft_answer_carries_the_vat_refusal(api, tokens):
    c = _live_contract(api, tokens["staff"])
    r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 100_000_000})[1]
    assert r["vat"]["ready"] is False
    assert "exclusive of VAT" in r["preview"]["taxNote"]


def test_the_generic_route_cannot_write_an_application(api, tokens):
    st, r = api("POST", "/api/coll/sales_applications", tokens["management"], {"period": "x"})
    assert st == 400 and "/api/sales/application" in r["error"]


def test_a_lost_compare_and_swap_is_retried_not_pushed_back_at_the_user(api, tokens):
    """Deterministic, because racing two threads and hoping they overlap proves nothing on a run
    where they do not. One CAS is forced to fail: with the retry the claim still lands, without it
    the user is told to re-submit a claim that was never wrong."""
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 300_000_000})[1]["item"]

    real = db.put_collection_item_if_rev
    calls = {"n": 0}

    def flaky(coll, item, expect_rev):
        if coll == "sales_contracts":
            calls["n"] += 1
            if calls["n"] == 1:
                return None                      # the row moved under us, exactly once
        return real(coll, item, expect_rev)

    db.put_collection_item_if_rev = flaky
    try:
        st, r = _certify(api, tokens["management"], a["id"])
    finally:
        db.put_collection_item_if_rev = real
    assert st == 200, r
    assert calls["n"] >= 2, "the write should have been attempted again"
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 300_000_000


def test_persistent_contention_gives_up_cleanly_and_certifies_nothing(api, tokens):
    """Five attempts is a retry, not a spin. When it truly cannot land, the contract must be
    untouched and the user told plainly — a half-applied claim is the worst outcome available."""
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], claims={_uid(c): 300_000_000})[1]["item"]
    real = db.put_collection_item_if_rev
    db.put_collection_item_if_rev = lambda coll, item, rev: None if coll == "sales_contracts" else real(coll, item, rev)
    try:
        st, r = _certify(api, tokens["management"], a["id"])
    finally:
        db.put_collection_item_if_rev = real
    assert st == 409 and "Nothing was certified" in r["error"]
    after = db.get_collection_item("sales_contracts", c["id"])
    # .get, because a contract that has never been claimed against carries no counter at all — an
    # absent balance and a zero balance are the same fact here, and asserting the key exists would
    # be testing the storage shape rather than the money.
    assert (after.get("certifiedToDate") or 0) == 0
    assert after["advanceOutstanding"] == 300_000_000
    assert db.get_collection_item("sales_applications", a["id"])["status"] == S.DRAFT


def test_the_contract_ceiling_binds_even_when_the_LINE_still_has_room(api, tokens):
    """The two guards catch different things. A bill of quantities can total more than the figure
    actually agreed — somebody sets the contract value to the negotiated sum — and then a line can
    have plenty left while the contract has none."""
    # The agreed contract is 400m even though the BOQ line is worth 1bn. The value has to be set
    # BEFORE activation — afterwards the terms are what the customer signed and are correctly
    # refused, which is how the first version of this test fooled itself.
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="BOQ job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"],
          value=400_000_000, advancePct=0, retentionPct=0)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    c = db.get_collection_item("sales_contracts", c["id"])
    assert c["value"] == 400_000_000 and S.open_amount(c["lines"][0], "certifiedAmt") == 1_000_000_000
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], claims={_uid(c): 600_000_000})
    assert st == 400, r
    assert "variation" in r["error"], r["error"]


# ── the deposit is a balance that moves when cash moves ─────────────────────────────────────────

def test_a_claim_recovers_nothing_until_the_deposit_has_actually_arrived(api, tokens):
    """Recovering a deposit that never came understates the claim — the customer is told less is
    payable because of money they never paid — and reports an advance owed back that the company is
    not holding. Two wrong numbers from one assumption."""
    c = _live_contract(api, tokens["staff"], deposit=0)
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="2026-08", claims={_uid(c): 200_000_000})
    assert st == 200, r
    assert r["preview"]["advanceRecovered"] == 0
    assert r["preview"]["netPayable"] == 190_000_000, "certified less retention only"


def test_the_deposit_arriving_makes_it_recoverable(api, tokens):
    c = _live_contract(api, tokens["staff"], deposit=0)
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", kind="advance",
                  contractId=c["id"], amount=300_000_000, reference="FT-DEP-1")
    assert st == 200, r
    assert r["advanceReceived"] == 300_000_000 and r["stillToArrive"] == 0
    _, d = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                 contractId=c["id"], period="2026-08", claims={_uid(c): 200_000_000})
    assert d["preview"]["advanceRecovered"] == 60_000_000


def test_a_part_deposit_only_makes_that_part_recoverable(api, tokens):
    """Staged deposits are the point of the whole change: 20% on signing, 10% on delivery. Until the
    second tranche lands, only the first is winding down."""
    c = _live_contract(api, tokens["staff"], deposit=0)
    _post(api, tokens["staff"], "/api/sales/receipt", kind="advance", contractId=c["id"],
          amount=200_000_000)
    _, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                 contractId=c["id"], period="2026-08", claims={_uid(c): 900_000_000})
    assert r["preview"]["advanceRecovered"] == 200_000_000, "capped by what actually arrived"


def test_certifying_is_refused_as_an_unsigned_action_and_says_where_to_sign(api, tokens):
    """It moves the contract's balances and tells a customer what to pay. It was the last
    consequential sell-side act still going through on a plain POST, while PMC's interim payment
    certificate — the same document on the project side — has been signed for months."""
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], period="2026-08", claims={_uid(c): 100_000_000})[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="certify", id=a["id"])
    assert st == 400
    assert "e-signature, not an action" in r["error"]
    assert db.get_collection_item("sales_applications", a["id"])["status"] == "draft"
    assert db.get_collection_item("sales_contracts", c["id"]).get("certifiedToDate", 0) == 0


def test_the_signature_records_who_certified_it(api, tokens):
    c = _live_contract(api, tokens["staff"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft",
              contractId=c["id"], period="2026-08", claims={_uid(c): 100_000_000})[1]["item"]
    assert _certify(api, tokens["management"], a["id"])[0] == 200
    row = db.get_collection_item("sales_applications", a["id"])
    assert row["status"] == "certified" and row["certifiedBy"]
    assert any((s.get("setStatus") or "") == "certified" for s in row.get("signatures") or [])


def test_a_claim_that_became_uncertifiable_between_draft_and_signature_is_refused(api, tokens):
    """Two claims drafted against the same open balance; the first is signed, so the second no
    longer fits. The signature must refuse rather than certify what is no longer there."""
    c = _live_contract(api, tokens["staff"])
    a1 = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
               period="2026-08", claims={_uid(c): 700_000_000})[1]["item"]
    a2 = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
               period="2026-09", claims={_uid(c): 700_000_000})[1]["item"]
    assert _certify(api, tokens["management"], a1["id"])[0] == 200
    st, r = _certify(api, tokens["management"], a2["id"])
    assert st == 400 and "over by" in r["error"], r
    assert db.get_collection_item("sales_applications", a2["id"])["status"] == "draft"
    assert db.get_collection_item("sales_contracts", c["id"])["certifiedToDate"] == 700_000_000
