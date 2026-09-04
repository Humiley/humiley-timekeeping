"""Labour contracts — Article 20 of the Labour Code 2019.

The consequences here happen by operation of law rather than by anybody's decision, which is exactly
why they need to be computed rather than remembered: a fixed term that expires unnoticed has already
become an indefinite one, and a third fixed term is unlawful whether or not anybody meant it.
"""
import contracts as C


def _c(start, end=None, type_=None, **kw):
    return dict({"startDate": start, "endDate": end,
                 "type": type_ or (C.INDEFINITE if end is None else C.DEFINITE)}, **kw)


# ── Art. 20(1)(b): the 36-month ceiling ──────────────────────────────────────────────────────────

def test_a_year_is_twelve_months():
    assert C.term_months("2026-01-01", "2026-12-31") == 12


def test_three_years_is_exactly_thirty_six_months_and_is_lawful():
    assert C.term_months("2026-01-01", "2028-12-31") == 36
    assert C.exceeds_max_term("2026-01-01", "2028-12-31") is False


def test_a_day_over_three_years_exceeds_the_ceiling():
    """Off by one here is the difference between a lawful contract and an unenforceable term."""
    assert C.exceeds_max_term("2026-01-01", "2029-01-01") is True


def test_a_backwards_term_is_zero_months_not_negative():
    assert C.term_months("2026-12-31", "2026-01-01") == 0


# ── where a contract stands today ────────────────────────────────────────────────────────────────

def test_an_indefinite_contract_never_expires():
    assert C.status(_c("2020-01-01"), "2030-01-01") == "indefinite"
    assert C.days_left(_c("2020-01-01"), "2030-01-01") is None


def test_a_contract_with_time_left_is_active():
    assert C.status(_c("2026-01-01", "2026-12-31"), "2026-06-01") == "active"


def test_a_contract_inside_the_warning_window_is_expiring():
    assert C.status(_c("2026-01-01", "2026-12-31"), "2026-11-20") == "expiring"


def test_the_last_day_of_the_contract_is_still_inside_it():
    """An end date is the last day covered, not the first day after."""
    assert C.status(_c("2026-01-01", "2026-12-31"), "2026-12-31") in ("active", "expiring")
    assert C.days_left(_c("2026-01-01", "2026-12-31"), "2026-12-31") == 0


def test_the_day_after_expiry_starts_the_thirty_day_window():
    """Art. 20(2)(a): the old terms continue while a replacement is being signed."""
    assert C.status(_c("2026-01-01", "2026-12-31"), "2027-01-01") == "grace"


def test_thirty_days_after_expiry_is_still_inside_the_window():
    assert C.status(_c("2026-01-01", "2026-12-31"), "2027-01-30") == "grace"


def test_thirty_one_days_after_expiry_the_contract_has_already_changed():
    """Art. 20(2)(b). Nobody decides this and nobody signs it — it has simply happened, and the
    only question left is whether the company knows."""
    assert C.status(_c("2026-01-01", "2026-12-31"), "2027-01-31") == "lapsed"


def test_the_date_it_became_indefinite_is_computable():
    assert str(C.becomes_indefinite_on(_c("2026-01-01", "2026-12-31"))) == "2027-01-31"


def test_a_fixed_term_with_no_end_date_is_flagged_rather_than_assumed():
    assert C.status({"type": C.DEFINITE, "endDate": ""}, "2026-06-01") == "unknown"


def test_the_warning_window_is_a_business_choice_and_can_be_set_per_contract():
    c = _c("2026-01-01", "2026-12-31", warnDays=90)
    assert C.status(c, "2026-10-05") == "expiring"


# ── Art. 20(2)(c): a fixed term may be renewed once ──────────────────────────────────────────────

def test_a_first_fixed_term_may_be_followed_by_another():
    assert C.next_contract_must_be_indefinite([_c("2024-01-01", "2024-12-31")]) is False


def test_after_two_fixed_terms_the_next_must_be_indefinite():
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2025-12-31")]
    assert C.next_contract_must_be_indefinite(hist) is True


def test_somebody_already_on_an_indefinite_contract_does_not_go_back_to_fixed_terms():
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01")]
    assert C.next_contract_must_be_indefinite(hist) is True


def test_the_narrow_exceptions_may_keep_renewing():
    """Art. 20(2)(c) carves out an elderly employee, a foreign worker, a hired director of a
    state-capital enterprise and a full-time union officer."""
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2025-12-31")]
    assert C.next_contract_must_be_indefinite(hist, exempt="elderly") is False
    assert C.next_contract_must_be_indefinite(hist, exempt="foreign") is False


def test_an_exemption_nobody_recognises_is_not_an_exemption():
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2025-12-31")]
    assert C.next_contract_must_be_indefinite(hist, exempt="because-we-said-so") is True


def test_no_contracts_at_all_does_not_require_an_indefinite_one():
    assert C.next_contract_must_be_indefinite([]) is False


# ── which contract is in force ───────────────────────────────────────────────────────────────────

def test_the_current_contract_is_the_one_running_today():
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2026-12-31")]
    assert C.current(hist, "2026-06-01")["startDate"] == "2025-01-01"


def test_a_contract_that_has_not_started_yet_is_not_in_force():
    hist = [_c("2025-01-01", "2026-12-31"), _c("2027-01-01", "2028-12-31")]
    assert C.current(hist, "2026-06-01")["startDate"] == "2025-01-01"


def test_an_expired_contract_is_still_returned_because_it_is_the_thing_needing_an_answer():
    """Returning nothing would hide the person whose contract ran out — the exact case the register
    exists to surface."""
    hist = [_c("2024-01-01", "2024-12-31")]
    assert C.current(hist, "2026-06-01")["endDate"] == "2024-12-31"


def test_no_history_means_no_current_contract():
    assert C.current([], "2026-06-01") is None


# ── the review that lands on somebody's desk ─────────────────────────────────────────────────────

def test_an_employee_with_no_contract_at_all_is_the_first_finding():
    r = C.review([], "2026-06-01")
    assert r["status"] == "none"
    assert [i["kind"] for i in r["issues"]] == ["missing"]


def test_a_healthy_indefinite_contract_raises_nothing():
    r = C.review([_c("2020-01-01")], "2026-06-01")
    assert r["status"] == "indefinite" and r["issues"] == []


def test_an_expiring_contract_says_how_long_is_left_and_what_to_do():
    r = C.review([_c("2026-01-01", "2026-12-31")], "2026-11-20")
    kinds = [i["kind"] for i in r["issues"]]
    assert kinds == ["expiring"]
    assert "30 days" in r["issues"][0]["message"]


def test_a_lapsed_contract_says_it_has_ALREADY_become_indefinite():
    """The distinction that matters: not "should be renewed" but "this already changed, and your
    record is now wrong about what kind of contract this person is on"."""
    r = C.review([_c("2026-01-01", "2026-06-30")], "2026-09-01")
    msg = " ".join(i["message"] for i in r["issues"])
    assert "ALREADY an indefinite-term contract" in msg


def test_a_third_fixed_term_is_called_out_before_it_is_signed():
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2026-12-31")]
    r = C.review(hist, "2026-11-25")
    kinds = [i["kind"] for i in r["issues"]]
    assert "must_be_indefinite" in kinds
    assert r["definiteCount"] == 2 and r["mustBeIndefinite"] is True


def test_the_renewal_warning_only_appears_when_a_renewal_is_actually_due():
    """Somebody two years into their second fixed term does not need telling today."""
    hist = [_c("2024-01-01", "2024-12-31"), _c("2025-01-01", "2027-12-31")]
    r = C.review(hist, "2026-01-01")
    assert "must_be_indefinite" not in [i["kind"] for i in r["issues"]]


def test_an_over_long_fixed_term_is_a_finding_on_its_own():
    r = C.review([_c("2026-01-01", "2030-12-31")], "2026-06-01")
    kinds = [i["kind"] for i in r["issues"]]
    assert "term_too_long" in kinds


def test_an_indefinite_contract_is_never_accused_of_running_too_long():
    r = C.review([_c("2010-01-01", None, C.INDEFINITE)], "2026-06-01")
    assert r["issues"] == []
