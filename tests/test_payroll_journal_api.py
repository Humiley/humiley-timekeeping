"""The payroll journal endpoint.

payroll_journal.py proves the entries balance. This proves what only the server can answer: that a
DRAFT run never reaches a ledger, that the department mapping comes from settings, and that an
unbalanced journal is never handed over quietly.
"""
import pytest

import db
import payroll_calc as pc


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_payrollAccounts", {})
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_payrollAccounts", {})


def _run(api, tokens, period="August 2026", status="Finalised", dept="Engineering",
         gross=20_000_000, emp="HML-STF"):
    c = pc.compute(gross=gross, working_days=22)
    db.update_employee(emp, {"salary": gross})
    st, b = api("POST", "/api/coll/payruns", tokens["admin"], {
        "period": period, "scope": "company",
        "lines": [{"empId": emp, "name": "Staff One", "dept": dept, "contractGross": gross,
                   "gross": c["grossPay"], "net": c["net"], "pit": c["pit"], "calc": c}]})
    assert st == 200, b
    db.put_collection_item("payruns", dict(b["item"], status=status))
    return c


def _by(entries, code):
    return next((l for l in entries if l["account"] == code), None)


# ── only a signed run reaches a ledger ───────────────────────────────────────────────────────────

def test_a_finalised_run_produces_balanced_entries(api, tokens):
    c = _run(api, tokens)
    st, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert st == 200, b
    assert b["balanced"] is True
    assert b["totals"]["debit"] == b["totals"]["credit"]
    assert _by(b["entries"], "334")["credit"] == c["net"]


def test_a_draft_run_is_not_a_journal(api, tokens):
    """A proposal does not belong in a ledger. Every run is created Pending Approval."""
    _run(api, tokens, status="Pending Approval")
    _, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert b["runs"] == 0 and b["entries"] == []


def test_a_period_with_no_finalised_run_says_so_rather_than_returning_nothing(api, tokens):
    _, b = api("GET", "/api/hr/payroll/journal?period=March%202019", tokens["admin"])
    assert b["entries"] == [] and "No finalised pay run" in (b.get("note") or "")


def test_asking_without_a_period_covers_every_finalised_run(api, tokens):
    _run(api, tokens, period="July 2026")
    _run(api, tokens, period="August 2026")
    _, b = api("GET", "/api/hr/payroll/journal", tokens["admin"])
    assert b["runs"] == 2 and b["balanced"] is True


# ── the department mapping is a company decision ─────────────────────────────────────────────────

def test_the_expense_account_mapping_comes_from_settings(api, tokens):
    """Site labour belongs in 622, office salary in 642. Which is which is not something to infer
    from a department name."""
    db.set_setting("portal_payrollAccounts", {"Factory": "622"})
    _run(api, tokens, dept="Factory")
    _, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert _by(b["entries"], "622") is not None
    assert _by(b["entries"], "642") is None


def test_an_unmapped_department_still_appears_on_the_default_account(api, tokens):
    db.set_setting("portal_payrollAccounts", {"Factory": "622"})
    _run(api, tokens, dept="Operation")
    _, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert _by(b["entries"], "642") is not None
    assert b["balanced"] is True


def test_a_corrupt_account_setting_does_not_break_the_journal(api, tokens):
    db.set_setting("portal_payrollAccounts", "not a mapping")
    _run(api, tokens)
    st, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert st == 200 and b["balanced"] is True


# ── what the accountant receives ─────────────────────────────────────────────────────────────────

def test_the_csv_comes_with_it(api, tokens):
    _run(api, tokens)
    _, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert b["csv"].startswith("Period,Account")
    assert "TOTAL" in b["csv"]


def test_the_basis_is_stated(api, tokens):
    _run(api, tokens)
    _, b = api("GET", "/api/hr/payroll/journal?period=August%202026", tokens["admin"])
    assert "Circular 200" in b["basis"]


# ── who may see it ───────────────────────────────────────────────────────────────────────────────

def test_a_manager_cannot_read_the_payroll_journal(api, tokens):
    st, _ = api("GET", "/api/hr/payroll/journal", tokens["mgr"])
    assert st == 403


def test_management_can(api, tokens):
    st, _ = api("GET", "/api/hr/payroll/journal", tokens["management"])
    assert st == 200
