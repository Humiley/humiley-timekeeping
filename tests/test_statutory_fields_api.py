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
