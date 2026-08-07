"""The salary payment file endpoint.

bank_transfer.py proves the file's contents. This proves the two refusals that protect real money:
never a partial file, and never a second one by accident.
"""
import pytest

import db
import payroll_calc as pc


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"bankAcc": e.get("bankAcc"), "bankName": e.get("bankName"),
                        "bankHolder": e.get("bankHolder"), "salary": e.get("salary")}
              for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_bankTemplate", None)
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_bankTemplate", None)
    for eid, v in before.items():
        db.update_employee(eid, v)


def _bank(eid="HML-STF", acc="19012345678901", name="Techcombank"):
    db.update_employee(eid, {"bankAcc": acc, "bankName": name})


def _run(api, tokens, period="August 2026", emps=("HML-STF",), status="Finalised"):
    lines = []
    for e in emps:
        c = pc.compute(gross=20_000_000, working_days=22)
        db.update_employee(e, {"salary": 20_000_000})
        lines.append({"empId": e, "name": "Staff", "dept": "Engineering",
                      "contractGross": 20_000_000, "gross": c["grossPay"], "net": c["net"],
                      "pit": c["pit"], "calc": c})
    st, b = api("POST", "/api/coll/payruns", tokens["admin"],
                {"period": period, "scope": "company", "lines": lines})
    assert st == 200, b
    db.put_collection_item("payruns", dict(b["item"], status=status))
    return b["item"]["id"]


# ── only from a signed run ───────────────────────────────────────────────────────────────────────

def test_a_signed_run_with_complete_bank_details_produces_a_file(api, tokens):
    _bank()
    _run(api, tokens)
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert st == 200, b
    assert b["count"] == 1 and b["total"] > 0
    assert b["csv"].split("\n")[0].startswith('"STT"')
    assert "TOTAL" in b["csv"]


def test_a_draft_run_produces_nothing(api, tokens):
    """A payment file is built from what a Director signed, never from a proposal."""
    _bank()
    _run(api, tokens, status="Pending Approval")
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert st == 400 and "signed" in (b.get("error") or "")


def test_a_period_with_no_run_at_all_is_refused(api, tokens):
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "March 2019"})
    assert st == 400


def test_asking_with_no_period_is_refused_rather_than_guessed(api, tokens):
    st, _ = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {})
    assert st == 400


# ── never a partial file ─────────────────────────────────────────────────────────────────────────

def test_one_employee_without_bank_details_blocks_the_whole_file(api, tokens):
    """The refusal this endpoint exists for. A file missing one row uploads cleanly and looks
    correct, and the person finds out when their salary does not arrive."""
    _bank("HML-STF")
    db.update_employee("HML-OTH", {"bankAcc": "", "bankName": ""})
    _run(api, tokens, emps=("HML-STF", "HML-OTH"))
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert st == 400, b
    assert "csv" not in b
    assert len(b["blocked"]) == 1
    assert "Other Staff" in (b.get("error") or "")


def test_the_preview_says_who_is_blocking_it_before_anybody_asks_for_the_file(api, tokens):
    db.update_employee("HML-STF", {"bankAcc": "", "bankName": ""})
    _run(api, tokens)
    st, b = api("GET", "/api/hr/payroll/bankfile?period=August%202026", tokens["admin"])
    assert st == 400
    assert b["blocked"][0]["why"]


def test_the_preview_of_a_healthy_run_shows_rows_without_producing_the_file(api, tokens):
    _bank()
    _run(api, tokens)
    st, b = api("GET", "/api/hr/payroll/bankfile?period=August%202026", tokens["admin"])
    assert st == 200
    assert b["count"] == 1 and b["preview"]
    assert "csv" not in b, "a GET must not be a way to produce the file"


# ── never a second file by accident ──────────────────────────────────────────────────────────────

def test_a_second_file_needs_an_explicit_confirmation(api, tokens):
    """Producing it twice is how a month gets paid twice."""
    _bank()
    _run(api, tokens)
    api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert st == 409
    assert b["needsConfirm"] is True and "twice" in (b.get("error") or "")
    assert "csv" not in b


def test_a_confirmed_regeneration_is_allowed_and_recorded_as_one(api, tokens):
    _bank()
    _run(api, tokens)
    api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    st, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"],
                {"period": "August 2026", "regenerate": True})
    assert st == 200 and "csv" in b
    # ANY matching row, not the last: db.list_collection is ORDER BY id, and ids are random uuids,
    # so "the newest" is not where indexing puts it. A test that assumes otherwise passes only while
    # there happens to be one row.
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Salary payment file produced"]
    assert any("REGENERATED" in a["detail"] for a in trail), \
        "the second file must be recorded as a regeneration"


def test_producing_the_file_is_stamped_on_the_run(api, tokens):
    _bank()
    rid = _run(api, tokens)
    api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    run = db.get_collection_item("payruns", rid)
    assert run["bankFileAt"] and run["bankFileBy"] == "Admin User"
    assert run["bankFileCount"] == 1


def test_producing_the_file_is_written_to_the_audit_chain(api, tokens):
    _bank()
    _run(api, tokens)
    api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Salary payment file produced"]
    assert any("1 employee" in a["detail"] for a in trail)


# ── the column layout is a setting ───────────────────────────────────────────────────────────────

def test_the_bank_template_can_be_configured_without_a_release(api, tokens):
    """Every Vietnamese bank publishes its own layout. Changing bank is a setting, not a deploy."""
    _bank()
    _run(api, tokens)
    db.set_setting("portal_bankTemplate", [{"key": "account", "header": "Beneficiary A/C"},
                                           {"key": "amount", "header": "Amount"}])
    _, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert b["csv"].split("\n")[0] == '"Beneficiary A/C","Amount"'


def test_a_half_configured_template_falls_back_to_the_shipped_one(api, tokens):
    """Better the default layout than a file with blank columns the bank silently accepts."""
    _bank()
    _run(api, tokens)
    db.set_setting("portal_bankTemplate", "nonsense")
    _, b = api("POST", "/api/hr/payroll/bankfile", tokens["admin"], {"period": "August 2026"})
    assert b["csv"].split("\n")[0].startswith('"STT"')


# ── who may do it ────────────────────────────────────────────────────────────────────────────────

def test_a_manager_cannot_produce_a_salary_payment_file(api, tokens):
    st, _ = api("POST", "/api/hr/payroll/bankfile", tokens["mgr"], {"period": "August 2026"})
    assert st == 403


def test_staff_cannot_even_preview_it(api, tokens):
    st, _ = api("GET", "/api/hr/payroll/bankfile?period=August%202026", tokens["staff"])
    assert st == 403
