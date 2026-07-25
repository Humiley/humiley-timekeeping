"""Payroll / compensation visibility — Approver (management) level and above only.

A Contributor (manager) can approve team requests but must NOT see anyone's pay; the compensation fields
(salary/grade/bank/taxId) are stripped from other employees' records for below-Approver readers, while
leave balances stay visible so managers can still approve leave. The Payroll page + payruns/payadjust are
already gated to management level; this closes the employee-directory leak.
"""
import db


def _emp(api, who, token, eid):
    st, r = api("GET", "/api/employees", token)
    assert st == 200, r
    return next((e for e in r["employees"] if e.get("id") == eid), None)


def test_compensation_hidden_from_a_manager(api, tokens):
    db.update_employee("HML-OTH", {"salary": 42_000_000, "bank": "9990001", "grade": "G5",
                                   "taxId": "TX-1", "annualUsed": 3, "annualTotal": 12})
    m = _emp(api, "mgr", tokens["mgr"], "HML-OTH")
    assert m is not None
    for pay in ("salary", "bank", "grade", "taxId"):
        assert pay not in m, "a manager must not see %s of another employee" % pay
    # …but the manager still sees the roster + the leave balances they need to approve leave.
    assert m.get("name")
    assert m.get("annualTotal") == 12 and m.get("annualUsed") == 3


def test_compensation_visible_to_an_approver(api, tokens):
    db.update_employee("HML-OTH", {"salary": 42_000_000, "bank": "9990001"})
    mgmt = _emp(api, "management", tokens["management"], "HML-OTH")   # management == Approver level
    assert mgmt is not None and mgmt.get("salary") == 42_000_000 and mgmt.get("bank") == "9990001"


def test_staff_sees_directory_only_no_compensation(api, tokens):
    db.update_employee("HML-OTH", {"salary": 42_000_000})
    s = _emp(api, "staff", tokens["staff"], "HML-OTH")
    assert s is not None and "salary" not in s


def test_own_record_always_shows_full_compensation(api, tokens):
    # HML-STF viewing their OWN record still sees their own pay (self-service).
    db.update_employee("HML-STF", {"salary": 21_000_000})
    own = _emp(api, "staff", tokens["staff"], "HML-STF")
    assert own is not None and own.get("salary") == 21_000_000


def test_manager_edit_cannot_wipe_or_change_compensation(api, tokens):
    # The read-strip means a manager's Edit-Employee form loads a BLANK salary; saving the form would
    # PATCH salary='' — but _emp_update strips compensation from a below-Approver body, so the real
    # value is PRESERVED (no data loss). This pairs the read gate with the write gate.
    db.update_employee("HML-OTH", {"salary": 55_000_000, "bank": "1234", "grade": "G6"})
    st, _ = api("PATCH", "/api/employees/HML-OTH", tokens["mgr"],
                {"name": "Other Staff", "phone": "0900000000", "salary": "", "bank": "", "grade": ""})
    assert st == 200, "the benign profile edit should still succeed"
    row = db.get_employee("HML-OTH")
    assert row.get("salary") == 55_000_000, "a manager's save must NOT wipe salary"
    assert row.get("bank") == "1234" and row.get("grade") == "G6"
    assert row.get("phone") == "0900000000", "the non-compensation edit should apply"


def test_approver_edit_can_set_compensation(api, tokens):
    st, _ = api("PATCH", "/api/employees/HML-OTH", tokens["management"],
                {"name": "Other Staff", "salary": 60_000_000})
    assert st == 200
    assert db.get_employee("HML-OTH").get("salary") == 60_000_000, "an Approver may set compensation"
