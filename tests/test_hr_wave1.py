"""Wave 1 of the HR remediation — the things that were legally or operationally wrong.

Each test here corresponds to a finding from the 13-domain HR audit of 6 August 2026. They are not
feature tests; they are the guardrails that stop each defect coming back, because every one of them
failed silently and with a success message.
"""
import json

import pytest

import app
import db


@pytest.fixture(autouse=True)
def _restore_other_staff():
    """These tests reassign HML-OTH's manager to exercise the direct-report rule. Leaving it moved
    contaminates every later test that asserts on review scope — put it back."""
    yield
    db.update_employee("HML-OTH", {"managerEmail": "admin@humiley.com"})


# ── an employee change leaves a trace ────────────────────────────────────────────────────────────

def _audit_for(target_id):
    return [a for a in db.list_collection("audit") if a.get("target") == "employees/" + target_id]


def test_a_salary_change_is_written_to_the_audit_trail(api, tokens):
    """A ₫50,000 payroll override was HMAC-chained; a salary rise wrote nothing at all."""
    # Set a known baseline directly (db writes no audit row), so this asserts a real CHANGE rather
    # than depending on whatever another test file happened to leave the salary at. Without it, a
    # test elsewhere that sets 31,000,000 makes this a no-op edit — correctly writing no audit row,
    # and failing here for a reason that has nothing to do with the audit trail.
    db.update_employee("HML-STF", {"salary": 21_000_000})
    before = len(_audit_for("HML-STF"))
    st, b = api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 31_000_000})
    assert st == 200, b
    rows = _audit_for("HML-STF")
    assert len(rows) > before, "changing a salary must leave an audit row"
    assert any(r["action"] == "Employee record changed" for r in rows)


def test_the_audit_trail_never_records_the_salary_ITSELF(api, tokens):
    """Otherwise the audit log quietly becomes a second, unprotected compensation database."""
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"salary": 47_777_777})
    detail = " ".join(r.get("detail") or "" for r in _audit_for("HML-STF"))
    assert "47777777" not in detail and "47,777,777" not in detail
    assert "salary changed" in detail


def test_a_promotion_and_a_transfer_are_recorded_with_their_values(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"title": "Senior Engineer", "dept": "Factory"})
    detail = " ".join(r.get("detail") or "" for r in _audit_for("HML-STF"))
    assert "Senior Engineer" in detail and "Factory" in detail


def test_an_unchanged_field_does_not_create_noise(api, tokens):
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"title": "Held Steady"})
    n = len(_audit_for("HML-STF"))
    api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"title": "Held Steady"})
    assert len(_audit_for("HML-STF")) == n, "re-saving the same value must not log a change"


# ── public holidays are not annual leave ─────────────────────────────────────────────────────────

def test_leave_days_cannot_exceed_the_working_days_in_the_range(api, tokens):
    """Labour Code Art. 112. The browser now excludes weekends and public holidays; this is the same
    rule where it cannot be edited."""
    # The PRODUCTION shape: _portal_update stores a list, and db.set_setting json-encodes it once.
    # Storing json.dumps(...) here instead wrote a JSON *string*, which the old json.loads-on-a-list
    # bug happened to accept — so this test certified a code path production could never take.
    db.set_setting("portal_holidays", [{"date": "2026-09-02", "name": "National Day"}])
    try:
        # Mon 31 Aug – Fri 4 Sep is 5 calendar days, but 2 Sep is a public holiday → 4 working days.
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-08-31", "endDate": "2026-09-04",
            "days": 5, "reason": "test"})
        assert st == 400, b
        assert "public holidays" in (b.get("error") or "").lower()
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-08-31", "endDate": "2026-09-04",
            "days": 4, "reason": "test"})
        assert st == 200, b
    finally:
        db.set_setting("portal_holidays", [])


def test_weekends_are_still_excluded_when_no_holidays_are_configured(api, tokens):
    db.set_setting("portal_holidays", [])
    # Fri 4 Sep – Mon 7 Sep = 4 calendar days, 2 working days.
    st, b = api("POST", "/api/leave", tokens["staff"], {
        "type": "Annual", "startDate": "2026-09-04", "endDate": "2026-09-07", "days": 4, "reason": "t"})
    assert st == 400, b


# ── evidence is not deletable, and deletion keeps the record ─────────────────────────────────────

def test_a_completed_exit_cannot_be_deleted(api, tokens):
    st, b = api("POST", "/api/coll/exits", tokens["admin"],
                {"name": "Leaver", "empId": "HML-OTH", "status": "Completed", "settlement": 12_000_000})
    assert st == 200, b
    st, b2 = api("DELETE", "/api/coll/exits/" + b["item"]["id"], tokens["admin"])
    assert st == 403, b2
    assert "final settlement" in (b2.get("error") or "").lower()
    assert db.get_collection_item("exits", b["item"]["id"])


def test_deleting_an_hr_record_snapshots_it_into_the_audit_chain(api, tokens):
    """The trail used to prove only that a deletion happened — useless in the argument it exists for."""
    st, b = api("POST", "/api/coll/pip", tokens["admin"],
                {"name": "Someone", "empId": "HML-OTH", "reason": "missed targets", "status": "Open"})
    assert st == 200, b
    pid = b["item"]["id"]
    api("DELETE", "/api/coll/pip/" + pid, tokens["admin"])
    row = [a for a in db.list_collection("audit") if a.get("target") == "pip/" + pid]
    assert row, "no audit row for the deletion"
    assert "missed targets" in (row[-1].get("detail") or ""), \
        "the deleted record itself must be preserved, not just the fact of deletion"


# ── the two silent data-destroyers ───────────────────────────────────────────────────────────────

def test_a_manager_saving_progress_cannot_orphan_an_enrolment(api, tokens):
    """It used to blind-replace the whole document: 200 OK, success toast, empId gone."""
    st, b = api("POST", "/api/coll/enrollments", tokens["admin"],
                {"empId": "HML-STF", "name": "Staff One", "course": "Working at Height", "progress": 0})
    assert st == 200, b
    eid = b["item"]["id"]
    st, b2 = api("PATCH", "/api/coll/enrollments/" + eid, tokens["mgr"], {"progress": 60})
    assert st == 200, b2
    row = db.get_collection_item("enrollments", eid)
    assert row["empId"] == "HML-STF" and row["name"] == "Staff One" and row["course"] == "Working at Height"
    assert row["progress"] == 60


def test_the_uniform_size_actually_persists(api, tokens):
    """Collected on the form, accepted by the importer, shown on the profile — and discarded on save,
    because it was in neither EMP_FIELDS nor the migration list. PPE is issued by size."""
    st, _ = api("PATCH", "/api/employees/HML-STF", tokens["admin"], {"shirtSize": "XL"})
    assert st == 200
    assert db.get_employee("HML-STF").get("shirtSize") == "XL"


# ── who may see what ─────────────────────────────────────────────────────────────────────────────

def _roster(api, token):
    _, b = api("GET", "/api/employees", token)
    return {e["id"]: e for e in b["employees"]}


def test_a_manager_reads_identity_pii_only_for_their_own_reports(api, tokens):
    """Decree 13 purpose limitation. Needing one person's next-of-kin is not a reason to hold everyone's."""
    db.update_employee("HML-OTH", {"managerEmail": "", "personalId": "0790001", "address": "12 Nguyen Trai"})
    r = _roster(api, tokens["mgr"])
    assert "personalId" not in r["HML-OTH"], "a manager must not read the CCCD of someone they do not manage"
    assert "address" not in r["HML-OTH"]
    db.update_employee("HML-OTH", {"managerEmail": "mgr@humiley.com"})
    r = _roster(api, tokens["mgr"])
    assert r["HML-OTH"].get("personalId") == "0790001", "…but must read it for their own report"


def test_a_manager_still_sees_leave_balances_for_everyone_they_approve(api, tokens):
    """Scoping this away broke leave approval — the reason the split is by field, not by person."""
    db.update_employee("HML-OTH", {"managerEmail": "", "annualTotal": 12, "annualUsed": 3})
    r = _roster(api, tokens["mgr"])
    assert r["HML-OTH"].get("annualTotal") == 12 and r["HML-OTH"].get("annualUsed") == 3


def test_compensation_stays_invisible_to_a_manager_even_for_their_own_report(api, tokens):
    db.update_employee("HML-OTH", {"managerEmail": "mgr@humiley.com", "salary": 40_000_000, "grade": "G5"})
    r = _roster(api, tokens["mgr"])
    for f in ("salary", "grade", "bank", "taxId"):
        assert f not in r["HML-OTH"], "%s must never reach a manager" % f


def test_the_benefits_catalogue_is_readable_by_staff(api, tokens):
    """It is a per-grade policy table, not personal data. Sitting in SELF_OWNED meant the staff filter
    matched nothing and every employee's Benefits card was permanently empty."""
    assert "benefits" not in app.Handler.SELF_OWNED
    api("POST", "/api/coll/benefits", tokens["admin"], {"grade": "G3", "lunch": 730000})
    st, b = api("GET", "/api/coll/benefits", tokens["staff"])
    assert st == 200, b
    assert b["items"], "staff must be able to read the benefits catalogue"
