"""Statutory returns, end to end.

statutory.py proves the arithmetic. This proves the one rule only the server can enforce: a return
is built from a SIGNED pay run and from nothing else. An unsigned month produces no return at all,
because a provisional figure that somebody files is worse than a missing one.
"""
import pytest

import db
import payroll_calc as pc
import statutory as st


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"salary": e.get("salary")} for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_siRegion", None)
    db.set_setting("portal_baseSalary", None)
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'payruns'")
    conn.commit()
    conn.close()
    db.set_setting("portal_siRegion", None)
    db.set_setting("portal_baseSalary", None)
    for eid, v in before.items():
        db.update_employee(eid, v)


# The contribution base is P1 + P2, which payroll_calc sets at 75% of gross — so a gross of
# 80,000,000 gives a base of 60,000,000: above the BHXH/BHYT cap of 46,800,000 and below the Region I
# BHTN cap of 99,200,000, which is exactly the band where the two caps disagree. The first version of
# these tests used a 60,000,000 gross and produced a 45,000,000 base, under both caps and therefore
# no variance at all — the test was asserting against a scenario it had not actually created.
GROSS_ABOVE_SI_CAP = 80_000_000


def _run(api, tokens, gross=20_000_000, period="August 2026", status="Finalised", eid="HML-STF"):
    c = pc.compute(gross=gross, working_days=22)
    db.update_employee(eid, {"salary": gross})
    st_, b = api("POST", "/api/coll/payruns", tokens["admin"],
                 {"period": period, "scope": "company",
                  "lines": [{"empId": eid, "name": "Staff One", "dept": "Engineering",
                             "contractGross": gross, "gross": c["grossPay"], "net": c["net"],
                             "pit": c["pit"], "calc": c}]})
    assert st_ == 200, b
    db.put_collection_item("payruns", dict(b["item"], status=status))
    return b["item"]["id"]


def _get(api, tokens, period="2026-08", who="admin"):
    return api("GET", "/api/hr/statutory?period=" + period, tokens[who])


# ── only from a signed run ───────────────────────────────────────────────────────────────────────

def test_a_signed_month_produces_the_schedule(api, tokens):
    _run(api, tokens)
    code, b = _get(api, tokens)
    assert code == 200, b
    assert b["contributions"]["rows"] and b["pit"]["people"] >= 1
    assert b["contributions"]["totals"]["employee"] > 0


def test_an_unsigned_month_produces_no_return_at_all(api, tokens):
    """A provisional figure somebody files is worse than a missing one."""
    _run(api, tokens, status="Pending Approval")
    code, b = _get(api, tokens)
    assert code == 400 and "signed" in (b.get("error") or "")


def test_a_month_with_no_run_is_refused(api, tokens):
    code, b = _get(api, tokens, period="2019-03")
    assert code == 400 and "no signed pay run" in (b.get("error") or "").lower()


def test_a_month_that_is_not_a_month_is_refused(api, tokens):
    assert api("GET", "/api/hr/statutory", tokens["admin"])[0] == 400
    assert api("GET", "/api/hr/statutory?period=banana", tokens["admin"])[0] == 400


# ── the cap variance ─────────────────────────────────────────────────────────────────────────────

def test_a_high_earner_surfaces_the_unemployment_cap_variance(api, tokens):
    """BHXH/BHYT cap at 20x the base salary; BHTN caps at 20x the REGIONAL minimum wage. The portal
    applies the lower figure to all three, so BHTN has been under-withheld above 46,800,000."""
    _run(api, tokens, gross=GROSS_ABOVE_SI_CAP)
    _, b = _get(api, tokens)
    c = b["contributions"]
    assert c["variance"] > 0
    assert c["affected"] and c["affected"][0]["empId"] == "HML-STF"
    row = c["rows"][0]
    assert row["baseSiHi"] == 46_800_000 and row["baseUi"] > 46_800_000


def test_an_ordinary_salary_shows_no_variance(api, tokens):
    _run(api, tokens, gross=20_000_000)
    _, b = _get(api, tokens)
    assert b["contributions"]["variance"] == 0 and b["contributions"]["affected"] == []


def test_what_was_withheld_is_reported_untouched_by_the_variance(api, tokens):
    """The figure has already gone to the authority. The return says what was paid AND what the caps
    imply; it does not rewrite history."""
    _run(api, tokens, gross=GROSS_ABOVE_SI_CAP)
    _, b = _get(api, tokens)
    row = b["contributions"]["rows"][0]
    assert row["withheld"]["eeBhtn"] == 468_000, "1% of the capped base, as actually withheld"
    assert row["required"]["eeBhtn"] == 600_000


def test_the_region_is_a_setting_not_a_literal(api, tokens):
    _run(api, tokens, gross=80_000_000)
    _, reg1 = _get(api, tokens)
    db.set_setting("portal_siRegion", "IV")
    _, reg4 = _get(api, tokens)
    assert reg1["contributions"]["capUi"] == 99_200_000
    assert reg4["contributions"]["capUi"] == 69_000_000
    assert reg4["contributions"]["region"] == "IV"


def test_a_decree_revision_to_the_base_salary_is_a_setting_too(api, tokens):
    _run(api, tokens)
    db.set_setting("portal_baseSalary", "3000000")
    _, b = _get(api, tokens)
    assert b["contributions"]["capSiHi"] == 60_000_000


def test_the_legal_basis_travels_with_the_numbers(api, tokens):
    _run(api, tokens)
    _, b = _get(api, tokens)
    assert "BHXH and BHYT" in b["contributions"]["capBasis"]


# ── labour usage report ──────────────────────────────────────────────────────────────────────────

def test_the_labour_return_counts_at_the_reporting_date(api, tokens):
    code, b = api("GET", "/api/hr/labour-report?asOf=2026-06-01", tokens["admin"])
    assert code == 200
    assert b["asOf"] == "2026-06-01"
    assert b["total"] == b["male"] + b["female"]
    assert "Art. 4" in b["basis"] and "5 June" in b["basis"]


def test_a_reporting_date_that_is_not_a_date_is_refused(api, tokens):
    assert api("GET", "/api/hr/labour-report?asOf=banana", tokens["admin"])[0] == 400


# ── who may read them ────────────────────────────────────────────────────────────────────────────

def test_below_editor_cannot_read_the_filed_figures(api, tokens):
    _run(api, tokens)
    assert _get(api, tokens, who="mgr")[0] == 403
    assert _get(api, tokens, who="staff")[0] == 403
    assert _get(api, tokens, who="management")[0] == 403, "management is below editor here"


def test_an_editor_can(api, tokens):
    _run(api, tokens)
    assert _get(api, tokens, who="editor")[0] == 200


def test_a_manager_cannot_pull_the_labour_return(api, tokens):
    assert api("GET", "/api/hr/labour-report", tokens["mgr"])[0] == 403
