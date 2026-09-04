"""The minimum-wage check, end to end.

min_wage.py proves the arithmetic and the effective dating. This proves the parts only the server
can: that the region really is stored on the employee record and reaches the check, that the
company default covers a single-site company without editing every row, that the register is not
readable by everybody, and that the contract writer now REFUSES a below-minimum contract instead of
issuing it.
"""
import pytest

import db
import min_wage as mw


@pytest.fixture(autouse=True)
def _clean():
    # The WHOLE row, not the handful of fields this file means to touch. Restoring a subset is how
    # a fixture in this suite has broken unrelated tests before: _setup below rewrites name, dob,
    # address and more, and every later suite then sees a different employee than it seeded.
    before = {e["id"]: dict(e) for e in db.list_employees()}
    db.set_setting("portal_wageRegion", "")
    db.set_setting("portal_trainedUplift", False)
    yield
    db.set_setting("portal_wageRegion", "")
    db.set_setting("portal_trainedUplift", False)
    for eid, v in before.items():
        db.update_employee(eid, v)


def _pay(eid, salary, region=None, trained=None):
    v = {"salary": salary}
    if region is not None:
        v["wageRegion"] = region
    if trained is not None:
        v["trained"] = 1 if trained else 0
    db.update_employee(eid, v)


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

def test_it_lists_every_salary_so_it_is_management_and_above(api, tokens):
    assert api("GET", "/api/hr/minwage", tokens["staff"])[0] == 403
    assert api("GET", "/api/hr/minwage", tokens["mgr"])[0] == 403
    assert api("GET", "/api/hr/minwage", tokens["management"])[0] == 200


def test_it_needs_a_session(api, tokens):
    assert api("GET", "/api/hr/minwage", None)[0] == 401


# ── the region really is stored and really reaches the check ─────────────────────────────────────

def test_a_region_on_the_employee_record_survives_a_round_trip_and_is_used(api, tokens):
    """`wageRegion` had to be added to EMP_FIELDS and to the table. Without both, every save would
    have reported success and thrown it away — which is how `shirtSize` was lost before."""
    _pay("HML-STF", 4_000_000, region="I")
    assert db.get_employee("HML-STF").get("wageRegion") == "I"
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"][0]
    assert row["ok"] is False and row["shortfall"] == 1_310_000
    assert row["region"] == "I"


def test_the_same_wage_passes_in_region_four(api, tokens):
    _pay("HML-STF", 4_000_000, region="IV")
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert [x for x in r["rows"] if x["empId"] == "HML-STF"][0]["ok"] is True


def test_without_a_region_anywhere_nobody_is_checked_and_the_register_says_so(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"wageRegion": "", "salary": 4_000_000})
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert r["checked"] == 0 and r["below"] == 0
    assert r["unchecked"] == r["headcount"]
    assert "nothing is asserted about them either way" in r["statement"]
    assert "No company default wage region is set" in r["regionNote"]


def test_the_company_default_covers_a_single_site_company(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"wageRegion": "", "salary": 4_000_000})
    db.set_setting("portal_wageRegion", "I")
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert r["unchecked"] == 0 and r["below"] == r["headcount"]
    assert r["regionNote"] == "", "nothing to warn about once it is set"


def test_an_employees_own_region_beats_the_company_default(api, tokens):
    db.set_setting("portal_wageRegion", "I")
    _pay("HML-STF", 4_000_000, region="IV")
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert [x for x in r["rows"] if x["empId"] == "HML-STF"][0]["ok"] is True


# ── the effective dating survives the round trip ─────────────────────────────────────────────────

def test_a_2025_date_is_measured_against_the_2025_decree(api, tokens):
    """4,960,000 was lawful in Region I in 2025 and is not in 2026. A single overwritten constant
    would report a breach that never happened."""
    _pay("HML-STF", 4_960_000, region="I")
    _, old = api("GET", "/api/hr/minwage?asOf=2025-12-31", tokens["management"])
    _, new = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert [x for x in old["rows"] if x["empId"] == "HML-STF"][0]["ok"] is True
    assert [x for x in new["rows"] if x["empId"] == "HML-STF"][0]["ok"] is False


def test_the_register_publishes_the_schedule_so_a_figure_can_be_checked(api, tokens):
    _, r = api("GET", "/api/hr/minwage", tokens["management"])
    assert any("293/2025" in x["decree"] for x in r["schedule"])
    assert any("74/2024" in x["decree"] for x in r["schedule"])


# ── the 7% uplift is company policy, never assumed ───────────────────────────────────────────────

def test_the_uplift_is_off_until_the_company_turns_it_on(api, tokens):
    _pay("HML-STF", 5_310_000, region="I", trained=True)
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    assert [x for x in r["rows"] if x["empId"] == "HML-STF"][0]["ok"] is True
    assert r["trainedUpliftApplied"] is False


def test_with_it_on_a_trained_worker_at_the_bare_minimum_is_short(api, tokens):
    db.set_setting("portal_trainedUplift", True)
    _pay("HML-STF", 5_310_000, region="I", trained=True)
    _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    row = [x for x in r["rows"] if x["empId"] == "HML-STF"][0]
    assert row["ok"] is False and row["applies"] == 5_681_700
    assert r["trainedUpliftApplied"] is True


def test_the_register_always_carries_the_note_that_it_is_not_a_statutory_floor(api, tokens):
    _, r = api("GET", "/api/hr/minwage", tokens["management"])
    assert "not asserted here as a statutory floor" in r["trainedUpliftNote"]
    assert r["trainedUpliftNoteVn"]


# ── an inactive employee is not a finding ────────────────────────────────────────────────────────

def test_somebody_who_has_left_is_not_in_the_register(api, tokens):
    db.set_setting("portal_wageRegion", "I")
    _pay("HML-STF", 1_000_000, region="I")
    db.update_employee("HML-STF", {"status": "Inactive"})
    try:
        _, r = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
        assert not [x for x in r["rows"] if x["empId"] == "HML-STF"]
    finally:
        db.update_employee("HML-STF", {"status": "Active"})


# ── the contract writer refuses a below-minimum contract ─────────────────────────────────────────

CO = {
    "legalNameVn": "Công ty TNHH Kỹ thuật Humiley Việt Nam", "legalNameEn": "Humiley Vietnam",
    "regNo": "0316889472", "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Văn A", "repTitle": "Giám đốc",
}


def _terms(**kw):
    base = {"empId": "HML-STF", "jobTitle": "Kỹ sư Cơ điện", "workplace": "123 Nguyễn Huệ",
            "contractType": "definite", "startDate": "2026-01-01", "endDate": "2027-12-31",
            "wage": 9_000_000, "wageRegion": "I"}
    base.update(kw)
    return base


def _setup(api, tokens):
    assert api("POST", "/api/hr/company", tokens["admin"], CO)[0] == 200
    db.update_employee("HML-STF", {"name": "Nguyễn Đức Huy", "dob": "1995-04-12",
                                   "gender": "Male", "address": "45 Lê Lợi",
                                   "personalId": "079095001234", "title": "Kỹ sư Cơ điện",
                                   "salary": 9_000_000, "startDate": "2026-01-01",
                                   "contractExempt": ""})


def test_a_contract_below_the_regional_minimum_cannot_be_issued(api, tokens):
    """`_term_missing` tested only that the wage was above zero, so a contract stating ₫3,000,000 a
    month in Ho Chi Minh City was issuable, signable and invisible."""
    _setup(api, tokens)
    code, b = api("POST", "/api/hr/contract", tokens["management"], _terms(wage=3_000_000))
    assert code == 400, b
    assert any("below the statutory minimum" in m for m in b["blockers"]["term"])
    assert any("Art. 90(2)" in m for m in b["blockers"]["term"])


def test_the_refusal_names_the_decree_and_the_shortfall(api, tokens):
    _setup(api, tokens)
    _, b = api("POST", "/api/hr/contract", tokens["management"], _terms(wage=3_000_000))
    msg = [m for m in b["blockers"]["term"] if "below the statutory minimum" in m][0]
    assert "293/2025" in msg and "2,310,000" in msg


def test_a_lawful_wage_still_issues(api, tokens):
    _setup(api, tokens)
    assert api("POST", "/api/hr/contract", tokens["management"], _terms())[0] == 200


def test_a_contract_with_no_region_is_not_refused_on_a_check_nobody_could_make(api, tokens):
    """A wage nobody could measure must not be reported as one that failed. The gap belongs in the
    wage register, not as a blocker on a document somebody is trying to issue."""
    _setup(api, tokens)
    code, b = api("POST", "/api/hr/contract", tokens["management"],
                  _terms(wage=3_000_000, wageRegion=""))
    assert code == 200, b


def test_the_region_falls_back_to_the_employee_record_when_the_draft_omits_it(api, tokens):
    """The drafting form does not ask for a region — the workplace's region is a fact about the
    employee, and the contract writer should not need it typed again."""
    _setup(api, tokens)
    db.update_employee("HML-STF", {"wageRegion": "I"})
    code, b = api("POST", "/api/hr/contract", tokens["management"],
                  _terms(wage=3_000_000, wageRegion=""))
    assert code == 400, b
    assert any("Region I" in m for m in b["blockers"]["term"])


def test_and_then_to_the_company_default(api, tokens):
    """A single-site company sets it once rather than on thirty records."""
    _setup(api, tokens)
    db.update_employee("HML-STF", {"wageRegion": ""})
    db.set_setting("portal_wageRegion", "I")
    code, b = api("POST", "/api/hr/contract", tokens["management"],
                  _terms(wage=3_000_000, wageRegion=""))
    assert code == 400, b
    assert any("Region I" in m for m in b["blockers"]["term"])


def test_a_posting_to_another_region_can_still_be_stated_on_the_contract(api, tokens):
    """A site posting can be in a different region from the employee's home record."""
    _setup(api, tokens)
    db.update_employee("HML-STF", {"wageRegion": "I"})
    code, b = api("POST", "/api/hr/contract", tokens["management"],
                  _terms(wage=4_000_000, wageRegion="IV"))
    assert code == 200, b
