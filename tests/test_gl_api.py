"""The ledger over HTTP: who may post, what may post twice, and what a closed month refuses.

The rules module is exhaustively tested without a database (test_gl_rules.py). What can only be
tested here is everything that depends on WHO is asking and WHAT ALREADY HAPPENED — and that is
where a ledger's real failures live. A wrong debit is an error somebody spots. A pay run posted
twice balances perfectly and is invisible.
"""
import pytest

import db
import gl


PERIOD = "2026-05"


def _finalise_payrun(period=PERIOD, run_id="PR-TEST-1", net=89_500_000, emp="HML-STF",
                     who="Staff One"):
    """A signed pay run, in the shape payroll_journal reads: a frozen `calc` per line.

    `net` is gross − employee deductions − PIT. Get that wrong and the RUN itself does not balance,
    which the ledger refuses — as it did when this fixture first said 80,000,000 and was out by
    exactly the employee's own 10.5m of insurance. The fixture was wrong; the refusal was right.
    """
    return db.put_collection_item("payruns", {
        "id": run_id, "period": period, "status": "Finalised",
        "lines": [{"empId": emp, "name": who, "dept": "Engineering",
                   "calc": {"grossPay": 100_000_000, "net": net, "unpaidDeduction": 0,
                            "eeBhxh": 8_000_000, "erBhxh": 17_500_000,
                            "eeBhyt": 1_500_000, "erBhyt": 3_000_000,
                            "eeBhtn": 1_000_000, "erBhtn": 1_000_000,
                            "erTu": 2_000_000, "pit": 0,
                            "erTotal": 23_500_000, "extraDedTot": 0, "extraDeduct": []}}],
    })


@pytest.fixture(autouse=True)
def _clean_ledger():
    """Each test starts with an empty ledger and no closed months, so nothing here depends on the
    order the tests happen to run in."""
    conn = db.get_conn()
    conn.execute("DELETE FROM gl_entries")
    conn.execute("DELETE FROM gl_batches")
    conn.commit()
    conn.close()
    for p in db.list_collection(db.GL_PERIODS):
        db.delete_collection_item(db.GL_PERIODS, p.get("id"))
    for r in db.list_collection("payruns"):
        if str(r.get("id", "")).startswith("PR-TEST"):
            db.delete_collection_item("payruns", r.get("id"))
    yield


# --- who may look, who may post -------------------------------------------------------------------

def test_staff_cannot_read_the_ledger(api, tokens):
    s, _ = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["staff"])
    assert s == 403


def test_a_manager_is_not_enough_to_read_the_company_books(api, tokens):
    """Manager-level runs a department. The ledger is the whole company's position, so it sits at
    management — the same line payruns and the payroll journal already draw."""
    s, _ = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["mgr"])
    assert s == 403


def test_management_may_read(api, tokens):
    s, r = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert s == 200 and r["trialBalance"]["balanced"] is True
    assert r["period"] == PERIOD


def test_staff_cannot_post(api, tokens):
    _finalise_payrun()
    s, _ = api("POST", "/api/gl/post", tokens["staff"],
               {"source": "payrun", "period": PERIOD})
    assert s == 403


# --- posting ----------------------------------------------------------------------------------------

def test_a_finalised_pay_run_posts_and_balances(api, tokens):
    _finalise_payrun()
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "payrun", "period": PERIOD})
    assert s == 200, r
    assert r["debit"] == r["credit"] > 0

    s, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    tb = sm["trialBalance"]
    assert tb["balanced"] and tb["debit"] == tb["credit"] == r["debit"]
    assert sm["entryCount"] == r["lines"]
    # The expense side is a 6xx account and the liabilities are 3xx — the entries landed in real
    # places, not merely in balanced ones.
    kinds = {row["class"] for row in tb["rows"]}
    assert gl.EXPENSE in kinds and gl.LIABILITY in kinds


def test_the_same_pay_run_cannot_post_twice(api, tokens):
    """The defect this whole guard exists for. Posting twice doubles salary, insurance and PIT — and
    BOTH sides double, so the ledger still balances and no report says a word."""
    _finalise_payrun()
    s1, _ = api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    assert s1 == 200
    s2, r2 = api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    assert s2 == 409
    assert "already been posted" in r2.get("error", "")

    s, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert len([b for b in sm["batches"] if b["kind"] == "post"]) == 1


def test_a_draft_pay_run_does_not_post(api, tokens):
    db.put_collection_item("payruns", {"id": "PR-TEST-D", "period": PERIOD, "status": "Draft",
                                       "lines": [{"calc": {"grossPay": 1, "net": 1}}]})
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    assert s == 409 and "no finalised pay run" in r.get("error", "").lower()


def test_a_source_the_ledger_cannot_price_is_refused_and_says_so(api, tokens):
    """Payroll, claims, receipts, credit notes and paid payments post. A MANUAL journal does not —
    it would let a caller write arbitrary entries, which is the one thing the "built from the source
    document" rule exists to prevent. The refusal names the source rather than failing vaguely."""
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "manual", "period": PERIOD})
    assert s == 400
    assert "manual" in r.get("error", ""), r
    assert "not one of them" in r.get("error", "")


def test_a_sell_side_document_must_name_WHICH_document(api, tokens):
    """There are many claims in a month and each carries its own date, so a claim posts by id. A
    period would not identify one — and letting the caller pass a period would let them choose which
    month a document lands in, which is the one thing the date is there to decide."""
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "invoice", "period": PERIOD})
    assert s == 400
    assert "by id" in r.get("error", "")


def test_the_entries_come_from_the_pay_run_not_from_the_request(api, tokens):
    """A ledger that posts what a client sends is one anybody with a session can write anything
    into. The body names the document; it does not get to say what the document contains."""
    _finalise_payrun()
    s, r = api("POST", "/api/gl/post", tokens["management"], {
        "source": "payrun", "period": PERIOD,
        "lines": [{"account": "111", "debit": 999_999_999},
                  {"account": "411", "credit": 999_999_999}],
    })
    assert s == 200
    accounts = {row["account"] for row in
                api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])[1]
                ["trialBalance"]["rows"]}
    assert "411" not in accounts, "the request body reached the ledger"


# --- what has NOT posted --------------------------------------------------------------------------

def test_the_summary_names_what_the_month_still_owes_the_ledger(api, tokens):
    """A trial balance is correct about the entries it has and silent about the ones nobody posted,
    so "the books are complete" is the one claim it cannot make."""
    _finalise_payrun()
    s, before = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert [p["source"] for p in before["pending"]] == ["payrun"]

    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    s, after = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert after["pending"] == []


# --- reversal ----------------------------------------------------------------------------------------

def test_a_batch_is_corrected_by_reversal_and_the_pair_nets_to_nothing(api, tokens):
    _finalise_payrun()
    _, posted = api("POST", "/api/gl/post", tokens["management"],
                    {"source": "payrun", "period": PERIOD})
    s, r = api("POST", "/api/gl/reverse", tokens["management"],
               {"batch": posted["batch"], "reason": "posted against the wrong month"})
    assert s == 200, r

    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert sm["trialBalance"]["balanced"]
    assert all(row["balance"] == 0 for row in sm["trialBalance"]["rows"])
    # Both remain visible. The mistake and its correction are the record.
    assert len(sm["batches"]) == 2


def test_a_reversal_needs_a_reason(api, tokens):
    _finalise_payrun()
    _, posted = api("POST", "/api/gl/post", tokens["management"],
                    {"source": "payrun", "period": PERIOD})
    s, r = api("POST", "/api/gl/reverse", tokens["management"], {"batch": posted["batch"]})
    assert s == 400 and "reason" in r.get("error", "").lower()


def test_a_reversal_cannot_itself_be_reversed(api, tokens):
    _finalise_payrun()
    _, posted = api("POST", "/api/gl/post", tokens["management"],
                    {"source": "payrun", "period": PERIOD})
    _, rev = api("POST", "/api/gl/reverse", tokens["management"],
                 {"batch": posted["batch"], "reason": "wrong month"})
    s, r = api("POST", "/api/gl/reverse", tokens["management"],
               {"batch": rev["batch"], "reason": "changed my mind"})
    assert s == 409 and "re-post the original" in r.get("error", "")


# --- closing -------------------------------------------------------------------------------------------

def test_closing_is_a_director_act(api, tokens):
    s, _ = api("POST", "/api/gl/close", tokens["management"], {"period": PERIOD})
    assert s == 403


def test_the_person_who_posted_may_not_be_the_one_who_closes(api, tokens):
    """Segregation of duties — the control an auditor asks about first, and the same
    preparer-is-not-signer rule the pay run already follows."""
    _finalise_payrun()
    # The admin posts it themselves…
    s, _ = api("POST", "/api/gl/post", tokens["admin"], {"source": "payrun", "period": PERIOD})
    assert s == 200
    # …and is then refused the close.
    s, r = api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})
    assert s == 409
    assert "cannot also be the one who closes it" in r.get("error", "")


def test_a_period_closes_when_somebody_else_posted_it(api, tokens):
    _finalise_payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    s, r = api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})
    assert s == 200, r
    assert r["closedBy"]


def test_a_closed_period_refuses_further_posting(api, tokens):
    _finalise_payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    _, rev = api("POST", "/api/gl/reverse", tokens["management"],
                 {"batch": api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])[1]
                  ["batches"][0]["id"], "reason": "test"})
    api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})

    # A second pay run for the same month, finalised after the close — a DIFFERENT person, so this
    # is a legitimate document rather than one the duplicate-people guard would refuse first. What
    # is under test is the closed period, and a test that trips an earlier guard proves nothing
    # about the guard it was aimed at.
    _finalise_payrun(run_id="PR-TEST-2", emp="HML-OTH", who="Other Staff")
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    assert s == 409
    assert "is closed" in r.get("error", "")
    assert "has not been moved into an open one" in r.get("error", ""), \
        "the refusal does not explain that the entry was NOT silently re-dated"


def test_a_closed_period_cannot_be_edited_through_the_generic_collection_api(api, tokens):
    """The register is the only thing standing between a closed month and somebody quietly changing
    it, so the generic API must not be a way round the close endpoint's checks."""
    _finalise_payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})

    s, r = api("PATCH", "/api/coll/gl_periods/" + PERIOD, tokens["admin"], {"status": "open"})
    assert s == 409
    assert "through the ledger" in r.get("error", "")
    s, _ = api("DELETE", "/api/coll/gl_periods/" + PERIOD, tokens["admin"])
    assert s == 409
    assert db.gl_is_closed(PERIOD), "the period came open anyway"


def test_re_opening_is_possible_deliberately_and_leaves_a_reason(api, tokens):
    """A close that could never be undone would be undone by editing the database directly, and
    that is the version nobody can see afterwards."""
    _finalise_payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})

    s, _ = api("POST", "/api/gl/reopen", tokens["admin"], {"period": PERIOD})
    assert s == 400, "re-opened with no reason"
    s, r = api("POST", "/api/gl/reopen", tokens["admin"],
               {"period": PERIOD, "reason": "a late invoice belongs in this month"})
    assert s == 200 and not db.gl_is_closed(PERIOD)

    # Re-opened, so the period lock is gone — but the pay run already posted, and the idempotency
    # guard is a separate rule that survives the re-open. Both refusals matter and they are not the
    # same refusal.
    s, r = api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    assert s == 409 and "already been posted" in r.get("error", ""), r
    assert "is closed" not in r.get("error", ""), "the period lock outlived the re-open"


# --- the account enquiry ---------------------------------------------------------------------------------

def test_one_account_can_be_read_on_its_own(api, tokens):
    _finalise_payrun()
    api("POST", "/api/gl/post", tokens["management"], {"source": "payrun", "period": PERIOD})
    s, r = api("GET", "/api/gl/entries?period=%s&account=334" % PERIOD, tokens["management"])
    assert s == 200
    assert r["count"] >= 1
    assert all(row["account"] == "334" for row in r["rows"])
    # Every row can be traced back to the document it came from.
    assert all(row["source"] == "payrun" and row["source_id"] for row in r["rows"])
