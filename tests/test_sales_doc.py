"""The shared sell-side document spine — lines, the status machine, and the open balance.

The tests that earn their place here are the ones guarding the two decisions that cannot be
retrofitted: a line id that survives reordering, and an open balance that refuses to overshoot
instead of clamping. A clamp turns "you are claiming more than the contract is worth" into a number
that looks fine, which is the most expensive silent failure available on this side of the business.
"""
import pytest

import sales_doc as S


def _lines():
    return [S.new_line("l1", "Cleanroom AHU", qty=2, unitPrice=100_000_000),
            S.new_line("l2", "HEPA terminals", qty=24, unitPrice=4_500_000),
            S.new_line("h1", "SECTION A", kind=S.HEADING),
            S.new_line("l3", "Installation", qty=1, unitPrice=85_000_000, discPct=10)]


# ── what a line is worth ─────────────────────────────────────────────────────────────────────────

def test_a_line_is_qty_times_price_less_its_discount():
    assert S.line_amount(S.new_line("x", qty=2, unitPrice=100)) == 200
    assert S.line_amount(S.new_line("x", qty=2, unitPrice=100, discPct=10)) == 180


def test_a_heading_or_a_note_is_worth_nothing_whatever_is_typed_on_it():
    """A bill of quantities is not a flat list of priced rows. A heading that reached a total would
    be double-counting the section it introduces."""
    for kind in (S.HEADING, S.NOTE):
        assert S.line_amount(S.new_line("x", kind=kind, qty=5, unitPrice=1000)) == 0


def test_an_optional_line_is_priced_but_excluded_until_taken_up():
    assert S.line_amount(S.new_line("x", kind=S.OPTIONAL, qty=1, unitPrice=500)) == 0


def test_a_discount_cannot_go_below_zero_or_above_the_line():
    assert S.line_amount(S.new_line("x", qty=1, unitPrice=100, discPct=150)) == 0
    assert S.line_amount(S.new_line("x", qty=1, unitPrice=100, discPct=-50)) == 100


def test_rubbish_in_a_money_field_is_zero_not_a_crash_and_never_NaN():
    ln = S.new_line("x", qty="two", unitPrice=None)
    assert ln["qty"] == 0 and ln["unitPrice"] == 0
    assert S.line_amount(ln) == 0


def test_totals_count_only_the_lines_that_carry_value():
    t = S.totals(_lines())
    assert t["lines"] == 3, "the heading is not a line with a value"
    assert t["amount"] == 200_000_000 + 108_000_000 + 76_500_000


# ── the line id, which must survive the document being edited ────────────────────────────────────

def test_a_new_uid_never_reuses_a_deleted_one():
    """Reuse would silently attach the deleted line's history — its claims, its certificates — to
    whatever new line took its number."""
    lines = [S.new_line("l1"), S.new_line("l2"), S.new_line("l3")]
    del lines[1]
    assert S.next_uid(lines) == "l4"


def test_uids_are_not_positions():
    """Insert a heading at the top of a 300-line BOQ and every claim, certificate and invoice line
    would re-point by one row if history pointed at positions."""
    lines = _lines()
    lines.insert(0, S.new_line(S.next_uid(lines), "NEW HEADING", kind=S.HEADING))
    assert [l["uid"] for l in lines if l["uid"] == "l1"], "l1 is still l1"
    assert S.open_amount([l for l in lines if l["uid"] == "l1"][0]) == 200_000_000


# ── the open balance ─────────────────────────────────────────────────────────────────────────────

def test_nothing_claimed_means_the_whole_line_is_open():
    assert S.open_amount(_lines()[0]) == 200_000_000


def test_claiming_reduces_what_is_left():
    r = S.apply(_lines(), {"l1": 50_000_000})
    assert r["ok"] is True
    assert S.open_amount(r["lines"][0]) == 150_000_000


def test_claiming_more_than_is_open_refuses_and_says_by_how_much():
    """THE case this module exists for. A clamp here would show a clean total that is wrong."""
    r = S.apply(_lines(), {"l1": 250_000_000})
    assert r["ok"] is False
    p = r["problems"][0]
    assert p["over"] == 50_000_000
    assert "over by" in p["why"]


def test_an_overclaim_applies_NOTHING_not_just_the_lines_that_fit():
    """A half-posted payment application has a total on its PDF that no longer matches its lines,
    and somebody signs it."""
    orig = _lines()
    r = S.apply(orig, {"l1": 10_000_000, "l2": 999_999_999})
    assert r["ok"] is False
    assert S.open_amount(orig[0]) == 200_000_000, "the good line must not have moved either"


def test_two_claims_in_sequence_cannot_exceed_the_line_between_them():
    a = S.apply(_lines(), {"l1": 150_000_000})
    b = S.apply(a["lines"], {"l1": 60_000_000})
    assert b["ok"] is False and b["problems"][0]["available"] == 50_000_000


def test_claiming_the_exact_remainder_is_allowed():
    a = S.apply(_lines(), {"l1": 150_000_000})
    b = S.apply(a["lines"], {"l1": 50_000_000})
    assert b["ok"] is True
    assert S.open_amount(b["lines"][0]) == 0


def test_float_noise_does_not_block_a_legitimate_final_claim():
    lines = [S.new_line("l1", qty=3, unitPrice=33_333_333.33)]
    whole = S.line_amount(lines[0])
    a = S.apply(lines, {"l1": whole / 3})
    b = S.apply(a["lines"], {"l1": whole / 3})
    c = S.apply(b["lines"], {"l1": whole / 3})
    assert c["ok"] is True, c


def test_a_negative_claim_is_refused_as_a_credit_note():
    r = S.apply(_lines(), {"l1": -1_000})
    assert r["ok"] is False and "credit note" in r["problems"][0]["why"]


def test_a_heading_cannot_be_claimed():
    r = S.apply(_lines(), {"h1": 1_000})
    assert r["ok"] is False and "carries no value" in r["problems"][0]["why"]


def test_a_claim_against_a_line_that_is_not_there_is_named():
    r = S.apply(_lines(), {"nope": 1_000})
    assert r["ok"] is False and "No line with this id" in r["problems"][0]["why"]


def test_an_open_balance_is_never_negative():
    ln = S.new_line("l1", qty=1, unitPrice=100, billedAmt=150)
    assert S.open_amount(ln) == 0, "a negative would net off against another line and vanish"


def test_totals_report_progress_against_the_document():
    r = S.apply(_lines(), {"l1": 100_000_000})
    t = S.totals(r["lines"])
    assert t["applied"] == 100_000_000
    assert t["open"] == t["amount"] - 100_000_000
    assert 0 < t["pct"] < 100


# ── carrying lines into the next document ────────────────────────────────────────────────────────

def test_copying_carries_only_what_is_still_open():
    """The most common way a progress claim goes out for money that was already invoiced."""
    a = S.apply(_lines(), {"l1": 150_000_000})
    nxt = S.copy_to(a["lines"], "sales_orders", "SO-1")
    l1 = [l for l in nxt if l["src"]["uid"] == "l1"][0]
    assert l1["unitPrice"] == 50_000_000


def test_a_fully_claimed_line_is_not_carried_at_all():
    a = S.apply(_lines(), {"l1": 200_000_000})
    assert not [l for l in S.copy_to(a["lines"], "x", "1") if l["src"]["uid"] == "l1"]


def test_every_copied_line_points_back_at_where_it_came_from():
    """Per LINE, not per document — that is what makes a trace view possible at all."""
    nxt = S.copy_to(_lines(), "sales_quotes", "QT-2026-0001")
    assert all(l["src"]["coll"] == "sales_quotes" and l["src"]["id"] == "QT-2026-0001" for l in nxt)
    assert {l["src"]["uid"] for l in nxt} == {"l1", "l2", "l3"}


def test_a_partial_copy_takes_only_the_lines_asked_for():
    nxt = S.copy_to(_lines(), "x", "1", uids=["l2"])
    assert [l["src"]["uid"] for l in nxt] == ["l2"]


def test_headings_are_not_carried_as_claimable_lines():
    assert all(l["kind"] in S.VALUED for l in S.copy_to(_lines(), "x", "1"))


def test_the_trace_names_the_source_of_each_line():
    nxt = S.copy_to(_lines(), "sales_quotes", "QT-1")
    t = S.trace(nxt)
    assert t and all(x["from"]["id"] == "QT-1" for x in t)


# ── the status machine ───────────────────────────────────────────────────────────────────────────

def test_the_normal_path():
    assert S.can_transition(S.DRAFT, S.ISSUED)
    assert S.can_transition(S.ISSUED, S.ACCEPTED)
    assert S.can_transition(S.ACCEPTED, S.CLOSED)


def test_a_document_cannot_skip_being_issued():
    assert not S.can_transition(S.DRAFT, S.ACCEPTED)


def test_a_lost_document_is_final():
    r = S.transition({"status": S.LOST}, S.ISSUED)
    assert r["ok"] is False and "final" in r["why"]


def test_a_refusal_names_both_states_and_what_is_allowed():
    r = S.transition({"status": S.DRAFT}, S.ACCEPTED)
    assert "draft" in r["why"] and "accepted" in r["why"] and "issued" in r["why"]


def test_marking_something_lost_requires_a_reason():
    """Win rate is charted already and is undiagnosable without this. A company can lose for years
    without learning why."""
    assert S.transition({"status": S.ISSUED}, S.LOST)["ok"] is False
    assert S.transition({"status": S.ISSUED}, S.LOST, "price")["ok"] is True


def test_cancelling_needs_a_reason_too():
    assert S.transition({"status": S.DRAFT}, S.CANCELLED)["ok"] is False
    assert S.transition({"status": S.DRAFT}, S.CANCELLED, "duplicate")["ok"] is True


def test_a_document_already_in_that_state_says_so():
    assert S.transition({"status": S.ISSUED}, S.ISSUED)["ok"] is False


def test_only_a_draft_is_editable_in_place():
    """Once it has left the building it is evidence. A change after issue is a new revision."""
    assert S.EDITABLE == (S.DRAFT,)
    assert S.ISSUED not in S.EDITABLE


def test_a_missing_status_is_treated_as_draft_not_as_an_error():
    assert S.transition({}, S.ISSUED)["ok"] is True


@pytest.mark.parametrize("state", [S.LOST, S.SUPERSEDED, S.CANCELLED, S.CLOSED])
def test_terminal_states_go_nowhere(state):
    assert S.TRANSITIONS[state] == ()
    assert state in S.TERMINAL


def test_the_tolerance_absorbs_float_noise_and_nothing_a_person_would_notice():
    """TOL exists so a legitimate final claim is not blocked by binary rounding. It must not be wide
    enough to let a real overclaim through: at ₫1,000 over, on every line of a 300-line BOQ, a wide
    tolerance quietly gives away real money."""
    r = S.apply([S.new_line("l1", qty=1, unitPrice=1_000_000)], {"l1": 1_001_000})
    assert r["ok"] is False, "₫1,000 over must be refused"
    assert S.TOL < 1.0, "a tolerance of ₫%s is a licence to overclaim" % S.TOL
