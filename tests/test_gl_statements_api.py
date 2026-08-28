"""The statements over HTTP: who may read them, and what they are computed over.

The rules are tested without a database in test_gl_statements.py. What only this level can prove is
that the endpoint feeds them the CUMULATIVE rows rather than one period's — the difference between a
balance sheet and a month's movement wearing its title.
"""
import pytest

import db


# Periods no other test file touches. THIS FILE FAILED ONLY IN THE FULL SUITE: test_gl_api.py leaves
# a finalised pay run for 2026-05 with the same employee behind it, so posting payroll for that month
# merged both runs, tripped the duplicate-people guard and returned 409. In isolation all ten tests
# passed — which is exactly how an order-dependent test file reports success about nothing.
MAY, JUNE = "2026-09", "2026-10"


def _payrun(period=MAY, run_id="PR-ST-1"):
    return db.put_collection_item("payruns", {
        "id": run_id, "period": period, "status": "Finalised",
        "lines": [{"empId": "HML-STF", "name": "Staff One", "dept": "Engineering",
                   "calc": {"grossPay": 100_000_000, "net": 89_500_000, "unpaidDeduction": 0,
                            "eeBhxh": 8_000_000, "erBhxh": 17_500_000,
                            "eeBhyt": 1_500_000, "erBhyt": 3_000_000,
                            "eeBhtn": 1_000_000, "erBhtn": 1_000_000,
                            "erTu": 2_000_000, "pit": 0,
                            "erTotal": 23_500_000, "extraDedTot": 0, "extraDeduct": []}}],
    })


def _claim(cid="PA-ST-1", certified=2_000_000_000, vat=200_000_000, when="2026-10-20T10:00:00Z"):
    return db.put_collection_item("sales_applications", {
        "id": cid, "appNo": cid, "status": "certified", "certifiedAt": when,
        "certifiedThis": certified, "vatAmount": vat, "retentionThis": 0,
        "advanceRecovered": 0, "netPayable": certified, "vatSet": True,
    })


@pytest.fixture(autouse=True)
def _clean():
    """Leave nothing behind AND tolerate nothing left behind.

    Cleaning by id prefix was not enough: `_gl_payrun_batch` merges EVERY finalised run for a period,
    so one foreign run in the same month changes the figures — or, when it names the same employee,
    is refused outright by the duplicate-people guard. So this clears anything at all sitting in the
    two periods this file uses, whoever created it.
    """
    conn = db.get_conn()
    conn.execute("DELETE FROM gl_entries")
    conn.execute("DELETE FROM gl_batches")
    conn.commit()
    conn.close()
    for r in db.list_collection("payruns"):
        if str(r.get("period") or "").strip() in (MAY, JUNE):
            db.delete_collection_item("payruns", r.get("id"))
    for coll in ("sales_applications", "sales_receipts", "sales_credits"):
        for d in db.list_collection(coll):
            when = str(d.get("certifiedAt") or d.get("receivedOn") or d.get("issuedOn") or "")
            if str(d.get("id", "")).startswith("PA-ST") or when[:7] in (MAY, JUNE):
                db.delete_collection_item(coll, d.get("id"))
    for p in db.list_collection(db.GL_PERIODS):
        db.delete_collection_item(db.GL_PERIODS, p.get("id"))
    db.set_setting("portal_fiscalYearStartMonth", 1)
    yield


# --- access ---------------------------------------------------------------------------------------

def test_staff_cannot_read_the_financial_statements(api, tokens):
    assert api("GET", "/api/gl/statements?period=" + JUNE, tokens["staff"])[0] == 403


def test_a_manager_is_not_enough(api, tokens):
    assert api("GET", "/api/gl/statements?period=" + JUNE, tokens["mgr"])[0] == 403


def test_management_may_read(api, tokens):
    s, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
    assert s == 200 and r["balanceSheet"]["balanced"] is True


# --- what they are computed over --------------------------------------------------------------------

def test_the_balance_sheet_carries_earlier_months_liabilities(api, tokens):
    """May's unpaid salary is still owed in June. A sheet that showed only June's movement would
    say the company owes nothing — which is the exact error this endpoint exists to avoid."""
    _payrun()
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "payrun", "period": MAY})[0] == 200
    _claim()
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "invoice", "id": "PA-ST-1"})[0] == 200

    s, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
    assert s == 200
    liab = {row["account"]: row["balance"] for row in r["balanceSheet"]["liabilities"]}
    assert liab["334"] == 89_500_000, "May's payable is missing from June's balance sheet"
    assets = {row["account"]: row["balance"] for row in r["balanceSheet"]["assets"]}
    assert assets["131"] == 2_200_000_000
    assert r["balanceSheet"]["balanced"]


def test_the_income_statement_separates_the_month_from_the_year(api, tokens):
    _payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": MAY})
    _claim()
    api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-ST-1"})

    _, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
    inc = r["incomeStatement"]
    assert inc["period"]["expense"] == 0, "May's payroll cost leaked into June"
    assert inc["yearToDate"]["expense"] == 123_500_000
    assert inc["period"]["income"] == 2_000_000_000


def test_asking_for_may_gives_mays_position_not_junes(api, tokens):
    _payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": MAY})
    _claim()
    api("POST", "/api/gl/post", tokens["management"], {"source": "invoice", "id": "PA-ST-1"})

    _, r = api("GET", "/api/gl/statements?period=" + MAY, tokens["management"])
    assets = {row["account"]: row["balance"] for row in r["balanceSheet"]["assets"]}
    assert "131" not in assets, "June's receivable appeared on May's balance sheet"
    assert r["balanceSheet"]["equityTotal"] == -123_500_000
    assert r["balanceSheet"]["balanced"]


# --- the fiscal year is a company fact ----------------------------------------------------------------

def test_the_fiscal_year_comes_from_the_setting_and_defaults_to_the_calendar(api, tokens):
    _, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
    assert r["fiscalYearStartMonth"] == 1
    assert r["fiscalYearStart"] == "2026-01"

    db.set_setting("portal_fiscalYearStartMonth", 4)
    _, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
    assert r["fiscalYearStartMonth"] == 4
    assert r["fiscalYearStart"] == "2026-04"


def test_a_nonsense_fiscal_month_falls_back_rather_than_producing_a_nonsense_year(api, tokens):
    """`get_setting` can return anything a settings screen wrote. A month of 0 or 13 would put the
    fiscal year start in a month that does not exist, and every year-to-date figure downstream of it
    would be quietly wrong."""
    for bad in (0, 13, -1, "banana"):
        db.set_setting("portal_fiscalYearStartMonth", bad)
        _, r = api("GET", "/api/gl/statements?period=" + JUNE, tokens["management"])
        assert r["fiscalYearStartMonth"] == 1, bad
        assert r["fiscalYearStart"] == "2026-01", bad


# --- edges ---------------------------------------------------------------------------------------------

def test_an_empty_ledger_gives_an_empty_sheet_that_balances(api, tokens):
    _, r = api("GET", "/api/gl/statements?period=2026-01", tokens["management"])
    bs = r["balanceSheet"]
    assert bs["assetsTotal"] == 0 and bs["fundedTotal"] == 0 and bs["balanced"]


def test_a_bad_period_is_refused(api, tokens):
    assert api("GET", "/api/gl/statements?period=2026-13", tokens["management"])[0] == 400
