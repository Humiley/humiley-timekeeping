"""The four statutory classifications and the bank details, from the edit form to the database.

These fields decide real money and real law — the annual-leave base (Art. 113(1)), the health-check
cadence (OSH Law Art. 21), whether safety training is required at all (Decree 44/2016 Art. 24),
whether somebody may be kept on fixed terms indefinitely (Art. 20(2)(c)), and where their salary is
sent. They existed in the database and in the law modules for a day with nothing on any screen that
could write them, so every employee read as normal-conditions office staff.

The tests that matter here are the round-trips: a value entered has to come back, and a value the
law module cannot interpret must not be stored as though it could.
"""
import pytest

import contracts
import db

FIELDS = {
    "workConditions": "heavy",
    "oshGroup": "3",
    "disabled": 1,
    "contractExempt": "elderly",
    "bankName": "Techcombank",
    "bankAcc": "19012345678901",
    "bankHolder": "LE VAN MINH",
    "bankBranch": "Tan Binh",
}


@pytest.fixture(autouse=True)
def _restore():
    before = {e["id"]: {k: e.get(k) for k in FIELDS} for e in db.list_employees()}
    yield
    for eid, v in before.items():
        db.update_employee(eid, v)


def test_every_statutory_field_survives_the_round_trip(api, tokens):
    """The regression this file exists for: the fields were on no screen at all, so nothing wrote
    them. A field that cannot be set is a field that is always at its default."""
    st, b = api("PATCH", "/api/employees/HML-STF", tokens["admin"], dict(FIELDS))
    assert st == 200, b
    got = db.get_employee("HML-STF")
    for k, v in FIELDS.items():
        assert str(got.get(k)) == str(v), "%s did not round-trip: %r" % (k, got.get(k))


def test_the_renewal_exemption_records_which_case_applies_not_merely_that_one_does(api, tokens):
    """contracts.py tests this value for membership in RENEWAL_EXEMPT — it is the Art. 20(2)(c) case,
    not a yes/no. A checkbox sending 1 would never match, so the exemption would silently never
    apply; and because the column is TEXT, a stored "0" is truthy at any read site that treats it as
    a flag. Both failure modes are closed by validating against the law module's own tuple."""
    for good in contracts.RENEWAL_EXEMPT:
        api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"contractExempt": good})
        assert db.get_employee("HML-STF")["contractExempt"] == good


def test_a_value_the_law_module_cannot_interpret_is_not_stored_as_if_it_could(api, tokens):
    for junk in ("1", "0", "true", "yes", "exempt", "banana"):
        api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"contractExempt": junk})
        assert db.get_employee("HML-STF")["contractExempt"] == "", \
            "%r is not an Art. 20(2)(c) case and must not read as exempt" % junk


def test_clearing_the_exemption_really_clears_it(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"contractExempt": "elderly"})
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"contractExempt": ""})
    assert not db.get_employee("HML-STF")["contractExempt"]


def test_the_classifications_reach_the_law_modules_and_change_the_answer(api, tokens):
    """Proof that setting them is not merely cosmetic: hazardous work raises the statutory annual
    leave from 12 days to 14."""
    db.update_employee("HML-STF", {"startDate": "2023-01-01", "annualTotal": 12,
                                   "workConditions": ""})
    _, plain = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"workConditions": "heavy"})
    _, heavy = api("GET", "/api/hr/leave-entitlement?year=2026", tokens["admin"])
    req = lambda b: [r for r in b["rows"] if r["empId"] == "HML-STF"][0]["required"]
    assert req(plain) == 12 and req(heavy) == 14


def test_a_line_manager_still_cannot_set_any_of_them(api, tokens):
    """They are legal classifications the company makes and a bank destination for somebody's pay —
    not fields a line manager edits."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"workConditions": "", "bankAcc": ""})
    api("PATCH", "/api/employees/HML-STF", tokens["mgr"],
        {"workConditions": "especially_heavy", "bankAcc": "99999999", "oshGroup": "3"})
    got = db.get_employee("HML-STF")
    assert not got.get("workConditions") and not got.get("bankAcc") and not got.get("oshGroup")


# ── work schedule: the field the rest-day overtime rate depends on ───────────────────────────────

def test_the_work_schedule_round_trips(api, tokens):
    """`schedule` holds the NAME of a pattern and decides rest days — and therefore whether a given
    day's overtime is paid at 150% or the 200% rest-day rate. The only input that ever wrote it was
    inside a modal that was never in the DOM, so it was blank for everyone and the whole company
    read as Mon–Fri office. Fixing _rest_weekdays_for was necessary and not sufficient: nothing
    could put a value in front of it."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"schedule": "Factory Shift A"})
    assert db.get_employee("HML-STF")["schedule"] == "Factory Shift A"
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"schedule": ""})
    assert not db.get_employee("HML-STF")["schedule"]


def test_the_schedule_actually_changes_which_days_are_rest_days(api, tokens):
    """Proof it is not cosmetic: a Mon–Sat pattern makes Saturday a WORKING day, so Saturday
    overtime is normal-rate rather than the 200% rest-day rate."""
    import app as _app
    scheds = [{"name": "Factory Shift A", "days": "Mon-Sat"}]
    assert _app._rest_weekdays_for({"schedule": "Factory Shift A"}, scheds) == (6,), "Sunday only"
    assert _app._rest_weekdays_for({"schedule": ""}, scheds) == (5, 6), "blank falls back to Sat+Sun"
    assert _app._rest_weekdays_for({"schedule": "Nope"}, scheds) == (5, 6), "an unknown name too"


# ── the settings message has to name the screen the field is actually on ─────────────────────────

def test_the_hr_folder_error_points_at_the_screen_that_holds_the_field(api, tokens):
    """The old wording sent people to "Company Portal settings" — a screen that has not held this
    field for some time. It now lives under Access & Permissions → System Integrations, three feet
    above the button that raised the error, which made the message read as a bug in the button."""
    db.set_setting("portal_hrSpUrl", "")
    st, b = api("POST", "/api/hr/employee-folders", tokens["admin"], {})
    assert st == 400
    msg = b.get("error") or ""
    assert "System Integrations" in msg and "Save" in msg
    assert "Company Portal settings" not in msg


def test_a_saved_hr_folder_gets_past_the_check(api, tokens, monkeypatch):
    """Proof the guard is about the SETTING being absent and nothing else: with a value saved, the
    request gets past it and on to the upload. SharePoint is stubbed — a test must never reach out
    to Microsoft, and without the stub this one hangs on network timeouts once per employee."""
    import app as _app
    calls = []
    monkeypatch.setattr(_app, "_hrsp_put", lambda *a, **k: calls.append(a) or {"ok": True})
    db.set_setting("portal_hrSpUrl", "https://x.sharepoint.com/sites/HR/Shared%20Documents")
    try:
        st, b = api("POST", "/api/hr/employee-folders", tokens["admin"], {})
        assert st == 200, b
        assert b["created"] > 0 and calls, "it reached the upload rather than stopping at the check"
    finally:
        db.set_setting("portal_hrSpUrl", "")
