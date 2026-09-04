"""Three places where one movement was counted twice, and one that had no account to go to.

The shape is the same in each: two correct-looking calculations, each right on its own, applied to
the same fact. And in two of the three the CONTROL on the screen still reported success — the
statement balanced, the journal balanced — because both sides moved together. A check that cannot
distinguish "right" from "doubled" is not a check.
"""
import pytest

import app
import db
import payroll_journal
import sales_contract as SC
import sales_credit as CN


@pytest.fixture(autouse=True)
def _clean(base_url):
    # `base_url` initialises the throwaway DB. Several tests here exercise payroll_journal directly
    # and never touch the API, so without it this fixture ran against a database with no tables and
    # every one of them errored in setup — which pytest reports as an ERROR, not a failure, and a
    # mutation check reading only the exit code would have called that "caught".
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_receipts",
                  "sales_credits", "crm_companies", "payruns"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO','CN')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _post(api, t, path, **b):
    return api("POST", path, t, b)


# ═══ 1. the credit note the customer statement took off twice ═══════════════════════════════════

def _order(api, tokens, claim=500_000_000):
    """A live contract with one certified claim: 30% advance, 5% retention, pro-rata recovery."""
    acc = db.put_collection_item("crm_companies", {"name": "Pharma Co", "legalNameVn": "Cty CP",
                                                   "mst": "0312345678", "owner": "Staff One"})
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co", accountId=acc["id"],
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], advancePct=30,
          retentionPct=5, warrantyMonths=12, recoveryRule=SC.REC_PRORATA,
          releaseRule=SC.REL_WARRANTY_END)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    _post(api, tokens["staff"], "/api/sales/receipt", kind="advance", contractId=c["id"],
          amount=300_000_000, reference="FT-DEP")
    c = db.get_collection_item("sales_contracts", c["id"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-08", claims={c["lines"][0]["uid"]: claim})[1]["item"]
    api("POST", "/api/esign", tokens["management"],
        {"coll": "sales_applications", "id": a["id"], "meaning": "Certified",
         "setStatus": "certified"})
    return acc, db.get_collection_item("sales_applications", a["id"])


def _credit(api, tokens, appl, amount):
    cn = _post(api, tokens["staff"], "/api/sales/credit", action="draft",
               applicationId=appl["id"], amount=amount, reason=CN.REASON_CODES[0],
               note="Rework")[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    api("POST", "/api/esign", tokens["management"],
        {"coll": "sales_credits", "id": cn["id"], "meaning": "Applied", "setStatus": CN.APPLIED})
    return db.get_collection_item("sales_credits", cn["id"])


def _stmt(api, tokens, acc_id):
    st, r = api("GET", "/api/sales/statement?accountId=" + acc_id, tokens["staff"])
    assert st == 200, r
    return r


def test_an_applied_credit_comes_off_the_statement_once(api, tokens):
    """`apply_to` already reduced the claim's netPayable by netCredit, and the statement then added
    a credit ROW for the same netCredit. The document a customer signs to agree the debt said the
    company was owed the net credit LESS than it was."""
    acc, appl = _order(api, tokens)
    cn = _credit(api, tokens, appl, 100_000_000)
    net_credit = float(cn["netCredit"])
    assert net_credit > 0

    after = db.get_collection_item("sales_applications", appl["id"])
    r = _stmt(api, tokens, acc["id"])

    claim_rows = [x for x in r["rows"] if x["kind"] == "claim"]
    credit_rows = [x for x in r["rows"] if x["kind"] == "credit"]
    assert len(claim_rows) == 1 and len(credit_rows) == 1

    # the claim is shown AS CERTIFIED; the credit note is the one place the reduction happens
    assert round(claim_rows[0]["debit"] - credit_rows[0]["credit"], 2) == \
        round(float(after["netPayable"]), 2), \
        "claim minus credit must land on what the claim is actually still worth"
    assert round(credit_rows[0]["credit"], 2) == round(net_credit, 2)


def test_the_statement_and_the_receivables_screen_agree(api, tokens):
    """These are the two documents that are supposed to reconcile: one goes to the customer, one is
    read inside the company. They were out by exactly the net credit."""
    acc, appl = _order(api, tokens)
    _credit(api, tokens, appl, 100_000_000)

    r = _stmt(api, tokens, acc["id"])
    st, rec = api("GET", "/api/sales/receivables", tokens["management"])
    assert st == 200, rec

    outstanding = round(float((rec.get("trade") or {}).get("total") or 0), 2)
    trade = round(sum(x["debit"] - x["credit"] for x in r["rows"] if x["kind"] != "deposit"), 2)
    assert trade == outstanding, \
        "the statement's trade movement and the receivables outstanding are the same debt"


def test_a_statement_with_no_credit_note_is_unchanged(api, tokens):
    """The fix must not move the ordinary case. If this fails, claims are being inflated by
    something other than a credit."""
    acc, appl = _order(api, tokens)
    r = _stmt(api, tokens, acc["id"])
    claim = [x for x in r["rows"] if x["kind"] == "claim"][0]
    assert round(claim["debit"], 2) == round(float(appl["netPayable"]), 2)


def test_a_full_credit_leaves_the_claim_owing_nothing(api, tokens):
    """The boundary the reconstruction has to survive: netPayable floors at zero, so adding the
    credit back has to restore the whole certified figure, not a clipped one."""
    acc, appl = _order(api, tokens)
    cn = _credit(api, tokens, appl, float(appl["certifiedThis"]))
    r = _stmt(api, tokens, acc["id"])
    claim = [x for x in r["rows"] if x["kind"] == "claim"][0]
    credit = [x for x in r["rows"] if x["kind"] == "credit"][0]
    assert round(claim["debit"] - credit["credit"], 2) == 0.0
    assert round(claim["debit"], 2) == round(float(cn["netCredit"]), 2)


# ═══ 2. the pay run posted twice ════════════════════════════════════════════════════════════════

def _line(eid, name, gross=30_000_000, extra_ded=0.0):
    si_base = gross
    ee_si, ee_hi, ee_ui = si_base * .08, si_base * .015, si_base * .01
    er_si, er_hi, er_ui, er_tu = si_base * .175, si_base * .03, si_base * .01, si_base * .02
    pit = 1_000_000.0
    net = gross - (ee_si + ee_hi + ee_ui) - pit - extra_ded
    calc = {"grossPay": gross, "net": net, "eeBhxh": ee_si, "eeBhyt": ee_hi, "eeBhtn": ee_ui,
            "erBhxh": er_si, "erBhyt": er_hi, "erBhtn": er_ui, "erTu": er_tu,
            "erTotal": er_si + er_hi + er_ui + er_tu, "pit": pit, "unpaidDeduction": 0}
    if extra_ded:
        calc["extraDedTot"] = extra_ded
        calc["extraDeduct"] = [{"label": "Staff loan", "amt": extra_ded}]
    return {"empId": eid, "name": name, "dept": "Engineering", "calc": calc}


def _run(rid, period, lines, status="Finalised"):
    return db.put_collection_item("payruns", {"id": rid, "period": period, "status": status,
                                              "lines": lines})


def _journal(api, tokens, period):
    return api("GET", "/api/hr/payroll/journal?period=" + period.replace(" ", "%20"),
               tokens["management"])


def test_one_person_in_two_runs_for_a_month_is_refused(api, tokens):
    """Both sides double, so `balanced()` still returns True — the only control on the screen
    reports success on a journal that posts the month's salary, insurance and PIT twice."""
    _run("PR-A", "August 2026", [_line("HML-STF", "Staff One"), _line("HML-OTH", "Other Staff")])
    _run("PR-B", "August 2026", [_line("HML-STF", "Staff One")])

    st, r = _journal(api, tokens, "August 2026")
    assert st == 409, r
    assert "Staff One" in r["error"]
    assert "PR-A" in r["error"] and "PR-B" in r["error"], "name the runs, not just the person"


def test_the_control_that_could_not_catch_it_still_says_it_balanced(api, tokens):
    """Stated as a fact about the data, so nobody re-derives the refusal from `balanced()` later."""
    merged = {"lines": [_line("HML-STF", "Staff One"), _line("HML-STF", "Staff One")]}
    entries = payroll_journal.entries(merged)
    assert payroll_journal.balanced(entries) is True, \
        "a doubled run balances perfectly — that is exactly why the refusal has to be elsewhere"


def test_the_same_person_in_two_DIFFERENT_months_is_not_a_duplicate(api, tokens):
    """Everyone appears in January's run and February's. Scoping the scan per period is the whole
    difference between a guard and a blocked journal."""
    _run("PR-JAN", "January 2026", [_line("HML-STF", "Staff One")])
    _run("PR-FEB", "February 2026", [_line("HML-STF", "Staff One")])
    st, r = api("GET", "/api/hr/payroll/journal", tokens["management"])
    assert st == 200, r
    assert r["runs"] == 2


def test_one_run_per_period_posts_normally(api, tokens):
    _run("PR-ONE", "August 2026", [_line("HML-STF", "Staff One"), _line("HML-OTH", "Other Staff")])
    st, r = _journal(api, tokens, "August 2026")
    assert st == 200, r
    assert r["balanced"] is True and r["entries"]


def test_a_correction_run_for_a_DIFFERENT_person_is_fine(api, tokens):
    """The guard must catch the overlap, not the second run."""
    _run("PR-MAIN", "August 2026", [_line("HML-STF", "Staff One")])
    _run("PR-CORR", "August 2026", [_line("HML-OTH", "Other Staff")])
    assert _journal(api, tokens, "August 2026")[0] == 200


# ═══ 3. the deduction with nowhere to go ════════════════════════════════════════════════════════

def test_a_manual_deduction_balances():
    """`net` is already reduced by it, and nothing credited it — so every month containing a staff
    loan repayment, an advance recovery or a fine was out of balance by exactly that amount and
    could not be posted at all."""
    run = {"lines": [_line("HML-STF", "Staff One", extra_ded=5_000_000)]}
    e = payroll_journal.entries(run)
    t = payroll_journal.totals(e)
    assert payroll_journal.balanced(e), t
    assert round(t["debit"] - t["credit"], 2) == 0.0


def test_the_deduction_lands_in_a_named_account():
    run = {"lines": [_line("HML-STF", "Staff One", extra_ded=5_000_000)]}
    e = payroll_journal.entries(run)
    row = next((x for x in e if x["account"] == payroll_journal.ACC["deduction"]), None)
    assert row is not None, "a deduction posted nowhere is a deduction nobody can trace"
    assert row["credit"] == 5_000_000.0
    assert row["name"], "an account with no name is unreadable in an import file"


def test_a_deduction_may_name_its_own_account():
    """A loan repayment, an advance recovery and a fine do not settle in the same place, and which
    one is a company decision — like the expense mapping, not something to infer."""
    run = {"lines": [_line("HML-STF", "Staff One", extra_ded=0)]}
    run["lines"][0]["calc"]["extraDedTot"] = 3_000_000
    run["lines"][0]["calc"]["extraDeduct"] = [{"label": "Advance", "amt": 3_000_000, "acct": "141"}]
    run["lines"][0]["calc"]["net"] -= 3_000_000
    e = payroll_journal.entries(run)
    assert payroll_journal.balanced(e)
    assert any(x["account"] == "141" and x["credit"] == 3_000_000.0 for x in e)


def test_an_older_run_with_only_the_TOTAL_still_balances():
    """Runs frozen before the per-line detail was kept carry `extraDedTot` and no list. Dropping
    them would reproduce the original defect on exactly the historical months nobody can re-sign."""
    run = {"lines": [_line("HML-STF", "Staff One", extra_ded=2_000_000)]}
    del run["lines"][0]["calc"]["extraDeduct"]
    e = payroll_journal.entries(run)
    assert payroll_journal.balanced(e)


def test_a_run_with_no_deduction_gains_no_line():
    """The fix must not invent a zero-value account row in every month."""
    e = payroll_journal.entries({"lines": [_line("HML-STF", "Staff One")]})
    assert not any(x["account"] == payroll_journal.ACC["deduction"] for x in e)
    assert payroll_journal.balanced(e)


# ═══ 4. one payslip, one month ══════════════════════════════════════════════════════════════════

def test_working_days_come_back_for_somebody_with_no_overtime(api, tokens):
    """The divisor used to be computed only inside the overtime loop, so an employee who worked no
    overtime had none — and the payslip's unpaid-leave deduction fell back to a hardcoded Mon–Fri
    22 while the overtime on the same payslip was priced off the person's real schedule."""
    st, r = api("GET", "/api/hr/overtime?period=2026-08", tokens["management"])
    assert st == 200, r
    wd = r.get("workingDaysByEmp")
    assert isinstance(wd, dict) and wd, "the map must exist independently of the overtime rows"
    assert not r["rows"], "this fixture has no approved overtime — that is the point of the test"
    assert "HML-STF" in wd and 15 <= wd["HML-STF"] <= 31
