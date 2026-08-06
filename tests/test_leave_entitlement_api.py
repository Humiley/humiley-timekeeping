"""Annual leave entitlement, end to end: what the law requires against what is on record.

leave_entitlement.py proves the arithmetic. This proves the part only the server can answer — that
the comparison never quietly reduces an entitlement somebody was actually given, that it is scoped
like the rest of HR, and that raising one leaves a trail.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _restore():
    before = {e["id"]: {"startDate": e.get("startDate"), "annualTotal": e.get("annualTotal"),
                        "workConditions": e.get("workConditions"), "endDate": e.get("endDate"),
                        "status": e.get("status")}
              for e in db.list_employees()}
    yield
    for eid, vals in before.items():
        db.update_employee(eid, vals)


def _rows(b):
    return {r["empId"]: r for r in b["rows"]}


# ── what the law requires ────────────────────────────────────────────────────────────────────────

def test_the_statutory_figure_is_reported_beside_what_is_on_record(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "annualTotal": 12})
    st, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    assert st == 200, b
    r = _rows(b)["HML-STF"]
    assert r["required"] == 12 and r["onRecord"] == 12 and r["shortfall"] == 0


def test_five_years_service_makes_a_twelve_day_record_a_day_short(api, tokens):
    """Art. 114. The quiet one: nothing in the portal has ever noticed the anniversary."""
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    _, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["required"] == 13 and r["shortfall"] == 1
    assert r["seniority"] == 1


def test_a_mid_year_hire_is_prorated_not_given_the_full_year(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2026-07-01", "annualTotal": 12})
    _, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["required"] == 6 and r["prorated"] is True and r["months"] == 6
    assert r["shortfall"] == 0, "12 on record is more than the 6 required — not a finding"


def test_hazardous_work_raises_the_requirement(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "annualTotal": 12,
                                   "workConditions": "heavy"})
    _, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    assert _rows(b)["HML-STF"]["required"] == 14


def test_the_working_out_comes_back_because_hr_gets_asked_why(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    _, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["why"] == "full year" and r["base"] == 12


def test_the_shortest_records_are_listed_first(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2016-01-01", "annualTotal": 12})   # 2 short
    db.update_employee("HML-OTH", {"startDate": "2021-01-01", "annualTotal": 12})   # 1 short
    _, b = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    ordered = [r["empId"] for r in b["rows"] if r["shortfall"]]
    assert ordered[:2] == ["HML-STF", "HML-OTH"]


def test_a_junk_year_falls_back_rather_than_erroring(api, tokens):
    st, b = api("GET", "/api/hr/leave-entitlement?year=banana", tokens["admin"])
    assert st == 200 and 2000 <= b["year"] <= 2100


def test_staff_cannot_read_the_company_wide_entitlement_review(api, tokens):
    st, _ = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["staff"])
    assert st == 403


# ── raising a record to the minimum ──────────────────────────────────────────────────────────────

def test_applying_raises_only_the_records_that_are_short(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    db.update_employee("HML-OTH", {"startDate": "2023-01-01", "annualTotal": 12})
    st, b = api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
    assert st == 200, b
    changed = {c["empId"] for c in b["changed"]}
    assert "HML-STF" in changed and "HML-OTH" not in changed
    assert db.get_employee("HML-STF")["annualTotal"] == 13


def test_applying_never_reduces_an_entitlement_somebody_was_actually_given(api, tokens):
    """A company that agreed 18 days agreed 18 days. A compliance tool that normalises that down to
    the statutory 12 is not fixing a problem, it is taking six days off somebody."""
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "annualTotal": 18})
    api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
    assert db.get_employee("HML-STF")["annualTotal"] == 18


def test_applying_can_be_limited_to_named_employees(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    db.update_employee("HML-OTH", {"startDate": "2021-03-01", "annualTotal": 12})
    api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"],
        {"year": 2026, "empIds": ["HML-STF"]})
    assert db.get_employee("HML-STF")["annualTotal"] == 13
    assert db.get_employee("HML-OTH")["annualTotal"] == 12


def test_every_raise_is_written_to_the_audit_trail(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
    trail = [a for a in db.list_collection("audit")
             if a.get("target") == "employee/HML-STF"
             and "statutory minimum" in (a.get("action") or "")]
    assert trail, "changing somebody's leave entitlement must leave a record"
    assert "13" in trail[-1]["detail"]


def test_applying_is_idempotent(api, tokens):
    db.update_employee("HML-STF", {"startDate": "2021-03-01", "annualTotal": 12})
    api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
    _, b = api("POST", "/api/hr/leave-entitlement/apply", tokens["admin"], {"year": 2026})
    assert b["count"] == 0


def test_a_manager_can_review_but_not_change_entitlements(api, tokens):
    st, _ = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["mgr"])
    assert st == 200
    st, _ = api("POST", "/api/hr/leave-entitlement/apply", tokens["mgr"], {"year": 2026})
    assert st == 403
