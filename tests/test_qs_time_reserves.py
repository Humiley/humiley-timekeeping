"""Extension of time (PMBOK §6.6), reserve analysis (§11.7) and budget by trade (§7.3).

Each of the three has one distinction that decides whether the number means anything:

  * CLAIMED time is not GRANTED time. Only the client granting an extension moves the completion
    date; until then the contractor is liable for the original one while building work that cannot
    be finished by it. Treating a claim as a grant reports a late job as on time.
  * CONTINGENCY and MANAGEMENT RESERVE are not interchangeable. Contingency is inside the baseline
    and covers identified risks; management reserve is outside it, covers what nobody identified,
    and is released by the sponsor. Drawing it down for a known risk reports a project covered with
    money it was never authorised to spend.
  * MARGIN and BUDGET VARIANCE answer different questions. A trade can be comfortably profitable and
    well over the budget the job was priced to.
"""
import pytest

import qsurvey as qs


# ── extension of time ────────────────────────────────────────────────────────────────────────────

def _v(**kw):
    return dict({"id": "v1", "voNo": "VO-001", "title": "Upgrade Zone 2",
                 "status": qs.V_AGREED, "agreedValue": 100_000_000, "agreedOn": "2026-05-01",
                 "instructedOn": "2026-04-01", "timeImpactDays": 30}, **kw)


def _eot(**kw):
    return qs.extension_of_time(dict({
        "contractCompletion": "2026-11-30", "forecastCompletion": "2026-12-20",
        "variations": [_v()], "changes": [], "cutoff": "2026-05-31"}, **kw))


def test_a_claim_for_time_is_not_an_extension_of_time():
    """THE distinction. 30 days claimed and nothing granted leaves the contract date exactly where
    it was, and the job liable for it."""
    r = _eot()
    assert r["claimedDays"] == 30
    assert r["grantedDays"] == 0
    assert r["outstandingDays"] == 30
    assert r["revisedCompletion"] == "2026-11-30", "an ungranted claim moved the completion date"
    assert any(w["code"] == "time_claimed_not_granted" for w in r["warnings"])


def test_a_granted_extension_moves_the_completion_date():
    r = _eot(variations=[_v(eotGrantedDays=21, eotGrantedOn="2026-05-10", eotRef="EOT-002")])
    assert r["grantedDays"] == 21
    assert r["revisedCompletion"] == "2026-12-21"
    assert r["outstandingDays"] == 9


def test_delay_is_measured_against_the_revised_date_and_the_original_is_shown_too():
    """The difference between the two is precisely what the granted extension is worth, so both
    are reported rather than one replacing the other."""
    r = _eot(variations=[_v(eotGrantedDays=21, eotGrantedOn="2026-05-10")])
    assert r["delayVsOriginalDays"] == 20      # 30 Nov -> 20 Dec
    assert r["delayDays"] == 0                 # 21 Dec revised, forecast 20 Dec: not late
    assert r["ldExposure"] is None


def test_a_job_forecast_past_the_revised_date_is_late_by_that_much():
    r = _eot(forecastCompletion="2027-01-15",
             variations=[_v(eotGrantedDays=21, eotGrantedOn="2026-05-10")])
    assert r["revisedCompletion"] == "2026-12-21"
    assert r["delayDays"] == 25
    assert any(w["code"] == "forecast_past_the_revised_completion" for w in r["warnings"])


def test_finishing_early_is_not_negative_delay():
    """A negative delay reads as credit and there is no such thing. Early is not late."""
    r = _eot(forecastCompletion="2026-10-01")
    assert r["delayDays"] == 0
    assert r["delayVsOriginalDays"] == 0


def test_a_grant_recorded_after_the_cutoff_has_not_happened_yet():
    r = _eot(variations=[_v(eotGrantedDays=21, eotGrantedOn="2026-07-01")])
    assert r["grantedDays"] == 0


def test_time_on_a_variation_nobody_instructed_is_not_claimed():
    """An idea somebody had carries no time either — the same rule as the money side."""
    r = _eot(variations=[_v(status=qs.V_IDENTIFIED, instructedOn="")])
    assert r["claimedDays"] == 0


def test_an_approved_change_request_can_grant_time_without_a_variation():
    r = _eot(variations=[], changes=[{"id": "c", "crNo": "CR-1", "decision": "Approved",
                                      "eotGrantedDays": 14, "eotGrantedOn": "2026-05-02"}])
    assert r["grantedDays"] == 14
    assert r["revisedCompletion"] == "2026-12-14"


def test_a_pending_change_request_grants_nothing():
    r = _eot(variations=[], changes=[{"id": "c", "decision": "Pending", "eotGrantedDays": 14,
                                      "eotGrantedOn": "2026-05-02"}])
    assert r["grantedDays"] == 0


def test_liquidated_damages_are_computed_only_when_the_contract_states_a_rate():
    """Days late times a stated rate is arithmetic. Inventing the rate would put a number on a
    legal position nobody agreed."""
    late = {"forecastCompletion": "2026-12-30"}       # 30 days past 30 Nov
    assert _eot(**late)["ldExposure"] is None
    assert any(w["code"] == "no_ld_rate" for w in _eot(**late)["warnings"])
    r = _eot(ldPerDay=12_000_000, **late)
    assert r["delayDays"] == 30
    assert r["ldExposure"] == 360_000_000


def test_liquidated_damages_stop_at_the_contract_cap():
    r = _eot(forecastCompletion="2027-06-30", ldPerDay=12_000_000, ldCap=500_000_000)
    assert r["ldExposure"] == 500_000_000
    assert any(w["code"] == "ld_at_the_cap" for w in r["warnings"])


def test_no_completion_date_means_no_delay_rather_than_zero_delay():
    """"No programme" and "on time" are different facts, and a 0 here would report a project with
    no dates as finishing exactly on the day."""
    r = _eot(contractCompletion="", forecastCompletion="")
    assert r["delayDays"] is None and r["revisedCompletion"] is None
    assert any(w["code"] == "no_contract_completion" for w in r["warnings"])


def test_an_unparseable_date_does_not_become_a_number():
    r = _eot(contractCompletion="not a date")
    assert r["revisedCompletion"] is None
    assert r["delayDays"] is None


# ── reserve analysis ─────────────────────────────────────────────────────────────────────────────

def _res(**kw):
    return qs.reserves(dict({"contingencyReserve": 800_000_000, "managementReserve": 400_000_000,
                             "provisions": 200_000_000, "variationShortfall": 100_000_000,
                             "openThreatEmv": 300_000_000, "openThreatCount": 4}, **kw))


def test_contingency_is_drawn_by_provisions_and_by_variations_agreed_below_cost():
    r = _res()
    assert r["drawn"] == 300_000_000
    assert r["remaining"] == 500_000_000
    assert r["drawnPct"] == 37.5


def test_the_reserve_question_is_whether_what_is_left_covers_what_is_still_open():
    r = _res()
    assert r["adequate"] is True
    assert r["shortfallAgainstRisk"] == 0


def test_contingency_below_the_open_risk_is_raised_with_the_shortfall():
    r = _res(openThreatEmv=900_000_000)
    assert r["adequate"] is False
    assert r["shortfallAgainstRisk"] == 400_000_000
    w = [x for x in r["warnings"] if x["code"] == "contingency_below_open_risk"]
    assert w and "4 open threat" in w[0]["msg"]


def test_contingency_drawn_past_zero_is_reported_as_exhausted():
    r = _res(provisions=900_000_000)
    assert r["remaining"] < 0
    assert any(w["code"] == "contingency_exhausted" for w in r["warnings"])


def test_management_reserve_is_never_drawn_down_by_a_known_risk():
    """It covers what nobody identified and is released by the sponsor. Spending it here would
    report the project covered with money it was not authorised to spend."""
    r = _res()
    assert r["managementReserve"] == 400_000_000
    assert r["drawn"] == 300_000_000, "management reserve leaked into the drawdown"
    assert r["remaining"] == 500_000_000
    assert any(w["code"] == "management_reserve_is_not_for_this" for w in r["warnings"])
    assert "released by the sponsor" in r["note"]


def test_no_contingency_at_all_says_the_risks_come_out_of_the_margin():
    r = _res(contingencyReserve=0)
    assert r["remaining"] is None or r["remaining"] <= 0
    assert any(w["code"] == "no_contingency" for w in r["warnings"])


# ── budget by trade ──────────────────────────────────────────────────────────────────────────────

def _cvr(**kw):
    return qs.cvr(dict({
        "valueToDate": 1_000_000_000, "costToDate": 700_000_000,
        "valueByTrade": {qs.HVAC: 600_000_000, qs.CLEANROOM: 400_000_000},
        "costByTrade": {qs.HVAC: 450_000_000, qs.CLEANROOM: 250_000_000},
        "budgetByTrade": {qs.HVAC: 400_000_000, qs.CLEANROOM: 300_000_000}}, **kw))


def test_a_trade_can_be_profitable_and_over_its_budget_at_the_same_time():
    """The two questions margin and budget variance answer. HVAC earns ₫600m for ₫450m — 25% margin
    — and was priced to spend ₫400m. Only one of those numbers is in a project total."""
    t = {x["code"]: x for x in _cvr()["trades"]}
    assert t[qs.HVAC]["marginPct"] == 25.0
    assert t[qs.HVAC]["budget"] == 400_000_000
    assert t[qs.HVAC]["budgetVariance"] == -50_000_000
    assert t[qs.HVAC]["overBudget"] is True
    assert t[qs.CLEANROOM]["overBudget"] is False


def test_being_over_budget_is_raised_by_name():
    w = [x for x in _cvr()["warnings"] if x["code"] == "trade_over_its_budget"]
    assert w and "HVAC" in w[0]["msg"]


def test_a_trade_with_no_budget_has_None_variance_not_a_confident_zero():
    """"No plan to measure against" and "exactly on plan" are different facts."""
    t = {x["code"]: x for x in _cvr(budgetByTrade={qs.HVAC: 400_000_000})["trades"]}
    assert t[qs.CLEANROOM]["budget"] is None
    assert t[qs.CLEANROOM]["budgetVariance"] is None
    assert t[qs.CLEANROOM]["overBudget"] is False


def test_a_trade_spending_with_no_budget_line_is_raised():
    r = _cvr(budgetByTrade={qs.HVAC: 400_000_000})
    w = [x for x in r["warnings"] if x["code"] == "trade_spending_with_no_budget"]
    assert w and "Cleanroom" in w[0]["msg"]


def test_a_budget_with_no_cost_or_value_still_appears_as_a_trade():
    """A trade that is budgeted and has not started is part of the plan, and dropping it would make
    the budget column silently not add up to the project's."""
    r = _cvr(budgetByTrade={qs.HVAC: 400_000_000, qs.CLEANROOM: 300_000_000, qs.FIRE: 90_000_000})
    assert qs.FIRE in {x["code"] for x in r["trades"]}
