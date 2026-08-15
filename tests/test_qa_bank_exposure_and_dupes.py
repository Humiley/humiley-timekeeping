"""Two findings from the 2026-08-15 QA audit, both about money leaving the company.

Neither was caught by the existing suite: test_payroll_access.py asserts only the four LEGACY
sensitive field names, so the structured bank columns added later drifted out of every guard, and
nothing anywhere exercised a period holding two finalised pay runs.
"""
import json

import pytest

import app
import db


BANK = {"bankName": "Vietcombank", "bankAcc": "0071000123456",
        "bankHolder": "NGUYEN VAN A", "bankBranch": "Tan Binh"}


@pytest.fixture(autouse=True)
def _bank_on_other():
    """Give a colleague real salary-transfer details, then take them away again."""
    # BOTH, so the bank-file tests below are not stopped by the (correct) pre-existing refusal to
    # emit a file while any payee is missing an account number.
    before = {e: dict(db.get_employee(e) or {}) for e in ("HML-OTH", "HML-STF")}
    db.update_employee("HML-OTH", dict(BANK, salary=25000000))
    db.update_employee("HML-STF", dict(BANK, bankAcc="0071000999888", bankHolder="STAFF ONE", salary=18000000))
    yield
    for e, b in before.items():
        db.update_employee(e, {k: b.get(k) or "" for k in BANK})


# ── the salary account is not everybody's business ───────────────────────────────────────────────

@pytest.mark.parametrize("who", ["staff", "mgr"])
def test_a_colleagues_salary_account_is_not_readable(api, tokens, who):
    """This is the exact data a payroll diversion needs — bank_transfer builds the file from bankAcc
    — and the first field a Decree 13 purpose-limitation audit asks about. The WRITE gate already
    refused it below management; only the read gate was missing."""
    st, b = api("GET", "/api/employees", tokens[who])
    assert st == 200
    row = next(e for e in b["employees"] if e["id"] == "HML-OTH")
    for f in BANK:
        assert f not in row, "%s leaked %s to %s" % ("/api/employees", f, who)
    assert "salary" not in row          # the field that was already guarded, still guarded


def test_management_still_sees_it_because_it_runs_payroll(api, tokens):
    st, b = api("GET", "/api/employees", tokens["management"])
    assert st == 200
    row = next(e for e in b["employees"] if e["id"] == "HML-OTH")
    assert row.get("bankAcc") == BANK["bankAcc"]


def test_you_can_always_see_your_own(api, tokens):
    """Scoping must not hide a person's own account from them."""
    st, b = api("GET", "/api/employees", tokens["staff"])
    me = next(e for e in b["employees"] if e["id"] == "HML-STF")
    assert me.get("bankAcc") == "0071000999888"   # set by the fixture


# ── a combined bank file must never pay one person twice ─────────────────────────────────────────

def _finalised_run(rid, period, lines):
    db.put_collection_item("payruns", {
        "id": rid, "period": period, "status": "Finalised", "lines": lines,
        "finalisedBy": "Admin User", "finalisedOn": "2026-08-31"})


@pytest.fixture
def _clean_runs():
    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def test_two_finalised_runs_holding_the_same_person_are_refused(api, tokens, _clean_runs):
    """A company roll-out plus an individual/correction run for the same month is a SUPPORTED state —
    the UI offers "a pay run already exists, create another?". Flattening both emits one row per
    line with no key on empId, so the person is paid twice and the batch total is inflated by their
    net. The control trailer sums the same inflated list, so a manual reconciliation agrees with
    itself and the error survives to the bank."""
    line = {"empId": "HML-OTH", "name": "Other Staff", "net": 25000000}
    _finalised_run("pr-company", "2026-08", [line, {"empId": "HML-STF", "name": "Staff One", "net": 18000000}])
    _finalised_run("pr-individual", "2026-08", [dict(line)])

    st, b = api("GET", "/api/hr/payroll/bankfile?period=2026-08", tokens["admin"])
    assert st == 400, "a file that pays somebody twice must be refused, not generated"
    err = b.get("error", "")
    assert "twice" in err
    assert "Other Staff" in err, "the refusal has to name who, or nobody can act on it"
    assert "pr-company" in err and "pr-individual" in err


def test_one_finalised_run_still_exports_normally(api, tokens, _clean_runs):
    """The guard must not block the ordinary month — a check that refuses everything is not a check."""
    _finalised_run("pr-only", "2026-08", [
        {"empId": "HML-OTH", "name": "Other Staff", "net": 25000000},
        {"empId": "HML-STF", "name": "Staff One", "net": 18000000}])
    st, b = api("GET", "/api/hr/payroll/bankfile?period=2026-08", tokens["admin"])
    assert st == 200, b
    assert b["count"] >= 1


def test_two_runs_with_different_people_are_fine(api, tokens, _clean_runs):
    """Splitting a month across two runs is legitimate as long as nobody is in both."""
    _finalised_run("pr-a", "2026-08", [{"empId": "HML-OTH", "name": "Other Staff", "net": 25000000}])
    _finalised_run("pr-b", "2026-08", [{"empId": "HML-STF", "name": "Staff One", "net": 18000000}])
    st, b = api("GET", "/api/hr/payroll/bankfile?period=2026-08", tokens["admin"])
    assert st == 200, b


def test_a_line_with_no_empId_does_not_trip_the_guard(api, tokens, _clean_runs):
    """Blank ids must not collapse into one another and look like a duplicate."""
    _finalised_run("pr-x", "2026-08", [{"name": "No Id A", "net": 1}, {"name": "No Id B", "net": 2}])
    st, b = api("GET", "/api/hr/payroll/bankfile?period=2026-08", tokens["admin"])
    # These lines are refused for a DIFFERENT, pre-existing and correct reason (no account number).
    # What matters here is that two blank ids were not collapsed into one another and reported as
    # the same person being paid twice.
    assert "twice" not in str(b), b
