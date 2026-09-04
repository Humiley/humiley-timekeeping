"""Headcount and turnover, end to end.

workforce.py proves the arithmetic. This proves what only the server can: that the history is read
from dated employee facts, that a record which cannot be placed in time is reported rather than
dropped, and that the window defaults to something useful instead of erroring.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _restore():
    before = {e["id"]: {"startDate": e.get("startDate"), "endDate": e.get("endDate"),
                        "status": e.get("status"), "dept": e.get("dept")}
              for e in db.list_employees()}
    yield
    for eid, v in before.items():
        db.update_employee(eid, v)


# Everyone the test does not name is parked in a long-finished employment: outside every window
# these tests look at, so they never touch a count — but still Active, because setting them Inactive
# also logs out the account the test is authenticating with (session_user turns away an Inactive
# employee immediately, which is exactly the Wave 2 behaviour, and it 401s the whole suite).
PARKED = {"startDate": "2000-01-01", "endDate": "2000-12-31", "status": "Active"}


def _only(spec):
    """Put every employee somewhere definite, so a count means what the test says it means.

    A NAMED person starts from a clean slate, not from PARKED — merging over it leaves the parked
    `endDate` of 2000-12-31 in place for anyone whose spec does not mention an end date, which
    quietly ends their employment twenty-six years before the window being tested.
    """
    for e in db.list_employees():
        if e["id"] in spec:
            db.update_employee(e["id"], dict({"startDate": None, "endDate": None,
                                              "status": "Active"}, **spec[e["id"]]))
        else:
            db.update_employee(e["id"], dict(PARKED))


def _get(api, tokens, q="", who="admin"):
    return api("GET", "/api/hr/workforce" + q, tokens[who])


def test_the_history_is_read_from_dated_facts_not_from_todays_roster(api, tokens):
    """The whole point: it can answer for a month that has already gone."""
    _only({"HML-STF": {"startDate": "2026-01-01", "status": "Active"},
           "HML-OTH": {"startDate": "2026-05-01", "status": "Active"}})
    st, b = _get(api, tokens, "?from=2026-01&to=2026-06")
    assert st == 200, b
    by = {r["ym"]: r for r in b["months"]}
    assert by["2026-01"]["closing"] == 1
    assert by["2026-05"]["closing"] == 2
    assert by["2026-05"]["joiners"] == 1


def test_the_month_to_month_chain_holds_on_real_records(api, tokens):
    _only({"HML-STF": {"startDate": "2026-01-01", "status": "Active"},
           "HML-OTH": {"startDate": "2026-03-01", "endDate": "2026-06-30", "status": "Inactive"},
           "HML-MGR": {"startDate": "2026-04-15", "status": "Active"}})
    _, b = _get(api, tokens, "?from=2026-01&to=2026-08")
    prev = None
    for r in b["months"]:
        assert r["balances"] is True, r
        if prev is not None:
            assert r["opening"] == prev, r["ym"]
        prev = r["carriedForward"]


def test_a_leaver_shows_in_the_month_they_left_with_their_name(api, tokens):
    _only({"HML-STF": {"startDate": "2020-01-01", "endDate": "2026-06-30", "status": "Inactive"}})
    _, b = _get(api, tokens, "?from=2026-06&to=2026-06")
    r = b["months"][0]
    assert r["leavers"] == 1
    assert "Staff One" in r["leaverNames"]


def test_turnover_comes_back_with_the_denominator_it_used(api, tokens):
    _only({"HML-STF": {"startDate": "2020-01-01", "status": "Active"},
           "HML-OTH": {"startDate": "2020-01-01", "status": "Active"},
           "HML-MGR": {"startDate": "2020-01-01", "endDate": "2026-06-30", "status": "Inactive"}})
    _, b = _get(api, tokens, "?from=2026-06&to=2026-06")
    assert b["leavers"] == 1
    assert b["turnoverPct"] > 0
    assert "average headcount" in b["turnoverBasis"]


def test_a_record_that_cannot_be_placed_in_time_is_reported_not_dropped(api, tokens):
    """A headcount history that silently excludes people is worse than one that admits what it could
    not read."""
    _only({"HML-STF": {"startDate": "2026-01-01", "status": "Active"},
           "HML-OTH": {"startDate": None, "status": "Active"}})
    _, b = _get(api, tokens, "?from=2026-01&to=2026-03")
    assert any(x["empId"] == "HML-OTH" for x in b["unusable"])
    assert "No start date" in [x["why"] for x in b["unusable"] if x["empId"] == "HML-OTH"][0]


def test_the_window_defaults_to_the_last_twelve_months(api, tokens):
    st, b = _get(api, tokens)
    assert st == 200
    assert len(b["months"]) == 12
    assert b["to"] >= b["from"]


def test_departments_come_back_for_the_current_headcount(api, tokens):
    _only({"HML-STF": {"startDate": "2020-01-01", "status": "Active", "dept": "Factory"},
           "HML-OTH": {"startDate": "2020-01-01", "status": "Active", "dept": "Factory"},
           "HML-MGR": {"startDate": "2020-01-01", "status": "Active", "dept": "Sales"}})
    _, b = _get(api, tokens, "?from=2026-08&to=2026-08")
    assert b["byDept"][0]["dept"] == "Factory" and b["byDept"][0]["headcount"] == 2


def test_a_backwards_window_is_refused_rather_than_returning_nothing_silently(api, tokens):
    st, b = _get(api, tokens, "?from=2026-09&to=2026-06")
    assert st == 400 and "starts after it ends" in (b.get("error") or "")


def test_a_window_that_is_not_a_month_is_refused_and_says_why(api, tokens):
    """Both guards return 400, so asserting only the status cannot tell them apart — a mutation run
    removed the format check entirely and the test still passed, because the ordering check caught
    the junk and blamed the ordering. The message has to name the real problem."""
    for bad in ("?from=banana&to=2026-06", "?from=2026-13&to=2026-14", "?from=2026-06&to=nope"):
        st, b = _get(api, tokens, bad)
        assert st == 400, bad
        assert "YYYY-MM" in (b.get("error") or ""), (bad, b)
        assert "starts after it ends" not in (b.get("error") or ""), bad


def test_a_manager_may_read_it_but_staff_may_not(api, tokens):
    """Headcount and turnover are management information, not personal data — a department manager
    has a legitimate use for them. An individual's start date is not exposed here; only counts and
    the names attached to a joining or leaving month."""
    assert _get(api, tokens, "?from=2026-08&to=2026-08", who="mgr")[0] == 200
    assert _get(api, tokens, "?from=2026-08&to=2026-08", who="staff")[0] == 403
