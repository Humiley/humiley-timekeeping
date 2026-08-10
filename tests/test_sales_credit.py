"""The credit note — the destination three refusals in this codebase have been naming.

    sales_doc.apply:            "A negative claim is a credit note, not a claim."
    sales_contract.application: "A negative certification is a credit note, not a claim."
    sales_variation.effect:     "raise a credit note against the claim instead."

The tests that matter are about the thing a negative claim gets wrong: a progress claim moves four
balances at once, and undoing it by typing a minus sign moves only one of them.
"""
import pytest

import sales_credit as C
import sales_doc as S


def _app(**kw):
    """A certified claim: ₫200m certified, 30% advance recovered, 5% retention withheld."""
    return dict({"id": "sal-a1", "status": "certified", "certifiedThis": 200_000_000,
                 "advanceRecovered": 60_000_000, "retentionThis": 10_000_000,
                 "netPayable": 130_000_000, "creditedAmt": 0,
                 "claims": {"l1": 200_000_000}}, **kw)


def _contract(**kw):
    return dict({"id": "sal-c1", "value": 1_000_000_000, "certifiedToDate": 200_000_000,
                 "retentionHeld": 10_000_000, "advanceOutstanding": 240_000_000,
                 "lines": [S.new_line("l1", desc="Works", qty=1, unitPrice=1_000_000_000,
                                      certifiedAmt=200_000_000)]}, **kw)


# ── the reversal a negative claim gets wrong ────────────────────────────────────────────────────

def test_a_full_credit_reverses_every_balance_the_claim_moved():
    e = C.effect(_app(), 200_000_000)
    assert e["ok"] is True
    assert e["retentionReleased"] == 10_000_000
    assert e["advanceRestored"] == 60_000_000
    assert e["netCredit"] == 130_000_000, "exactly what the customer was asked to pay"


def test_a_half_credit_reverses_exactly_half_of_each():
    """Reversing the certified value while leaving retention and advance recovery alone is the
    shape that silently loses money: retention stays withheld on work that was credited back."""
    e = C.effect(_app(), 100_000_000)
    assert e["retentionReleased"] == 5_000_000
    assert e["advanceRestored"] == 30_000_000
    assert e["netCredit"] == 65_000_000


def test_the_statement_names_all_three_movements():
    s = C.effect(_app(), 100_000_000)["statement"]
    assert "retention released" in s and "advance recovery restored" in s
    assert "₫65,000,000 less" in s


def test_applying_it_moves_the_contract_the_other_way():
    out = C.apply_to(_contract(), _app(), 100_000_000)
    c = out["contract"]
    assert c["certifiedToDate"] == 100_000_000
    assert c["retentionHeld"] == 5_000_000
    assert c["advanceOutstanding"] == 270_000_000, "recovery restored onto the advance"


def test_the_line_gets_its_open_balance_back_so_the_work_can_be_re_certified():
    out = C.apply_to(_contract(), _app(), 100_000_000)
    assert out["contract"]["lines"][0]["certifiedAmt"] == 100_000_000


def test_the_claim_records_what_was_credited_off_it():
    out = C.apply_to(_contract(), _app(), 100_000_000)
    a = out["application"]
    assert a["creditedAmt"] == 100_000_000 and a["fullyCredited"] is False
    assert a["netPayable"] == 65_000_000


def test_crediting_it_in_full_marks_it_so():
    out = C.apply_to(_contract(), _app(), 200_000_000)
    assert out["application"]["fullyCredited"] is True
    assert out["application"]["netPayable"] == 0


def test_it_returns_new_dicts_rather_than_mutating():
    c, a = _contract(), _app()
    C.apply_to(c, a, 200_000_000)
    assert c["certifiedToDate"] == 200_000_000 and a["creditedAmt"] == 0


# ── what it refuses ─────────────────────────────────────────────────────────────────────────────

def test_it_cannot_credit_more_than_the_claim_certified():
    e = C.effect(_app(), 250_000_000)
    assert e["ok"] is False and "still creditable" in e["why"]


def test_a_second_credit_only_gets_what_is_left():
    e = C.effect(_app(creditedAmt=150_000_000), 60_000_000)
    assert e["ok"] is False
    assert C.effect(_app(creditedAmt=150_000_000), 50_000_000)["ok"] is True


def test_a_fully_credited_claim_says_so_rather_than_naming_a_zero_balance():
    e = C.effect(_app(creditedAmt=200_000_000), 1)
    assert e["ok"] is False and "already been credited in full" in e["why"]


def test_an_uncertified_claim_has_nothing_to_credit():
    e = C.effect(_app(status="draft"), 1_000)
    assert e["ok"] is False and "CERTIFIED" in e["why"]


def test_a_negative_credit_is_refused_and_says_why_that_is_backwards():
    e = C.effect(_app(), -1)
    assert e["ok"] is False and "already a reduction" in e["why"]


def test_apply_refuses_whatever_effect_refuses():
    out = C.apply_to(_contract(), _app(), 999_000_000)
    assert out["ok"] is False and "contract" not in out


def test_a_claim_that_certified_nothing_is_refused_FOR_THAT_REASON():
    """It has nothing left to credit either, so the check order decides which reason the user gets
    — and "already credited in full" would be a confident, wrong explanation of a claim that was
    never worth anything."""
    e = C.effect(_app(certifiedThis=0, creditedAmt=0), 1)
    assert e["ok"] is False
    assert "certified nothing" in e["why"], e["why"]


# ── the record ──────────────────────────────────────────────────────────────────────────────────

def test_every_reason_has_a_vietnamese_label():
    for r in C.REASONS:
        assert r["labelVn"], r["code"]


def test_applied_is_final():
    assert C.TRANSITIONS[C.APPLIED] == ()


def test_a_draft_cannot_be_applied_without_being_issued():
    assert C.APPLIED not in C.TRANSITIONS[C.DRAFT]


def test_it_does_not_claim_to_issue_the_tax_document():
    assert any("Decree 123/2020" in u["question"] for u in C.UNRESOLVED)
    assert "Nothing here issues one" in C.UNRESOLVED[0]["action"]
