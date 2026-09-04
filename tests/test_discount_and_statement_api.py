"""The last two controls: a discount somebody has to authorise, and the statement a customer signs.

Both were on my own "not built" list. The discount threshold is the only control on the sell side
that guards MARGIN rather than money already committed — everything else checks what a contract
says, this checks what a salesperson gives away to win it. The statement is the document a customer
reconciles against before releasing a payment run, and it was being assembled by hand from four
screens.
"""
import pytest

import app
import db
import sales_contract as SC
import sales_credit as CN


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_receipts",
                  "sales_credits", "crm_companies"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO','CN')")
        conn.execute("DELETE FROM settings WHERE key = ?", ("portal_sales_quoteDiscountMax",))
        conn.commit(); conn.close()
    wipe(); yield; wipe()


@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _cap(api, tokens, pct):
    return _post(api, tokens["management"], "/api/sales/vat-settings", quoteDiscountMax=pct)


def _quote(api, tokens, lines):
    return _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
                 accountName="Pharma Co", lines=lines)[1]["item"]


LINES_5 = [{"desc": "AHU", "qty": 1, "unitPrice": 100_000_000, "discPct": 5}]
LINES_25 = [{"desc": "AHU", "qty": 1, "unitPrice": 100_000_000, "discPct": 25}]


# ── the threshold ───────────────────────────────────────────────────────────────────────────────

def test_with_no_threshold_recorded_any_discount_issues(api, tokens):
    """A limit this code invented would be a policy nobody agreed to."""
    q = _quote(api, tokens, LINES_25)
    st, r = _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    assert st == 200, r


def test_an_unset_threshold_SAYS_it_is_unset_rather_than_looking_like_a_pass(api, tokens):
    """"Any discount may be issued" and "the number you typed is not a number" are different
    problems with different fixes, and both would otherwise read as a silent green light."""
    q = _quote(api, tokens, LINES_25)
    _, r = _post(api, tokens["staff"], "/api/sales/quote", action="discount", id=q["id"])
    assert r["ok"] is True and r["capped"] is False
    assert "No discount threshold is set" in r["why"]


def test_a_discount_under_the_threshold_issues(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_5)
    assert _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])[0] == 200


def test_a_discount_over_the_threshold_is_refused_and_says_by_how_much(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    st, r = _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    assert st == 403
    assert "25%" in r["error"] and "threshold of 15%" in r["error"]
    assert db.get_collection_item("sales_quotes", q["id"])["status"] == "draft"


def test_an_approver_can_approve_it_and_then_it_issues(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    st, r = _post(api, tokens["management"], "/api/sales/quote", action="approve_discount",
                  id=q["id"], note="Strategic account")
    assert st == 200 and r["approvedPct"] == 25
    assert _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])[0] == 200


def test_approving_is_a_management_act(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    assert _post(api, tokens["staff"], "/api/sales/quote", action="approve_discount",
                 id=q["id"])[0] == 403


def test_the_approval_is_pinned_to_the_PERCENTAGE_not_a_flag(api, tokens):
    """Approve 15% then edit to 40% and a boolean would sail straight through. This is the only way
    the control fails in practice."""
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    _post(api, tokens["management"], "/api/sales/quote", action="approve_discount", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="draft", id=q["id"],
          lines=[{"desc": "AHU", "qty": 1, "unitPrice": 100_000_000, "discPct": 40}])
    st, r = _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    assert st == 403
    assert "discounted further since" in r["error"]


def test_discounting_LESS_than_was_approved_still_issues(api, tokens):
    """The approval is a ceiling, not a contract."""
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    _post(api, tokens["management"], "/api/sales/quote", action="approve_discount", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="draft", id=q["id"],
          lines=[{"desc": "AHU", "qty": 1, "unitPrice": 100_000_000, "discPct": 20}])
    assert _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])[0] == 200


def test_one_deep_line_inside_a_big_total_is_caught(api, tokens):
    """A weighted average smooths exactly this away: ₫1bn at 2% and ₫20m at 60% averages under the
    threshold while somebody just gave away 60% of a line."""
    _cap(api, tokens, 15)
    q = _quote(api, tokens, [{"desc": "Main", "qty": 1, "unitPrice": 1_000_000_000, "discPct": 2},
                             {"desc": "Extras", "qty": 1, "unitPrice": 20_000_000, "discPct": 60}])
    st, r = _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    assert st == 403 and "steepest line 60%" in r["error"]


def test_the_discount_can_be_inspected_before_anybody_tries_to_issue(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    st, r = _post(api, tokens["staff"], "/api/sales/quote", action="discount", id=q["id"])
    assert st == 200 and r["ok"] is False and r["discount"]["given"] == 25_000_000


def test_a_discount_cannot_be_approved_after_the_customer_has_the_price(api, tokens):
    q = _quote(api, tokens, LINES_25)
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    st, r = _post(api, tokens["management"], "/api/sales/quote", action="approve_discount", id=q["id"])
    assert st == 400 and "already has the price" in r["error"]


def test_a_threshold_that_is_not_a_percentage_is_refused(api, tokens):
    assert _cap(api, tokens, "loads")[0] == 400
    assert _cap(api, tokens, 140)[0] == 400


def test_approving_is_audited(api, tokens):
    _cap(api, tokens, 15)
    q = _quote(api, tokens, LINES_25)
    _post(api, tokens["management"], "/api/sales/quote", action="approve_discount", id=q["id"])
    assert any(x.get("action") == "Approved quotation discount" for x in db.list_collection("audit"))


# ── the customer statement ──────────────────────────────────────────────────────────────────────

def _order(api, tokens, claim=200_000_000):
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
        {"coll": "sales_applications", "id": a["id"], "meaning": "Certified", "setStatus": "certified"})
    return acc, db.get_collection_item("sales_contracts", c["id"]), \
        db.get_collection_item("sales_applications", a["id"])


def _stmt(api, token, acc_id):
    return api("GET", "/api/sales/statement?accountId=" + acc_id, token)


def test_the_statement_is_a_ledger_not_a_total(api, tokens):
    """A statement that shows only a balance is one nobody can dispute — which sounds good until
    the customer disputes it anyway and there is nothing to point at."""
    acc, c, a = _order(api, tokens)
    st, r = _stmt(api, tokens["staff"], acc["id"])
    assert st == 200, r
    kinds = [x["kind"] for x in r["rows"]]
    assert "deposit" in kinds and "claim" in kinds
    assert all("balance" in x and "on" in x and "ref" in x for x in r["rows"])


def test_the_running_balance_is_what_the_movements_come_to(api, tokens):
    acc, c, a = _order(api, tokens)
    _, r = _stmt(api, tokens["staff"], acc["id"])
    assert r["rows"][-1]["balance"] == r["closingBalance"]
    assert r["closingBalance"] == round(
        sum(x["debit"] - x["credit"] for x in r["rows"]), 2)


def test_a_receipt_reduces_what_is_owed(api, tokens):
    acc, c, a = _order(api, tokens)
    before = _stmt(api, tokens["staff"], acc["id"])[1]["closingBalance"]
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]}, reference="FT-1")
    after = _stmt(api, tokens["staff"], acc["id"])[1]["closingBalance"]
    assert round(before - after, 2) == a["netPayable"]


def test_an_applied_credit_note_appears_and_reduces_the_balance(api, tokens):
    acc, c, a = _order(api, tokens)
    before = _stmt(api, tokens["staff"], acc["id"])[1]["closingBalance"]
    cn = _post(api, tokens["staff"], "/api/sales/credit", action="draft", applicationId=a["id"],
               amount=100_000_000, reason="rejected_work")[1]["item"]
    _post(api, tokens["staff"], "/api/sales/credit", action="issue", id=cn["id"])
    api("POST", "/api/esign", tokens["management"],
        {"coll": "sales_credits", "id": cn["id"], "meaning": "Applied", "setStatus": CN.APPLIED})
    _, r = _stmt(api, tokens["staff"], acc["id"])
    assert "credit" in [x["kind"] for x in r["rows"]]
    assert r["closingBalance"] < before


def test_retention_and_the_advance_are_shown_apart_from_the_balance(api, tokens):
    """So the figure can be agreed without arguing about them — the same rule the receivables
    screen holds, restated where a customer will read it."""
    acc, c, a = _order(api, tokens)
    _, r = _stmt(api, tokens["staff"], acc["id"])
    assert r["retentionHeldByCustomer"] == 10_000_000
    assert r["advanceOwedBack"] > 0
    assert "NOT part of this balance" in r["whyNotOneNumber"]


def test_it_carries_the_customer_legal_identity(api, tokens):
    acc, c, a = _order(api, tokens)
    _, r = _stmt(api, tokens["staff"], acc["id"])
    assert r["mst"] == "0312345678" and r["legalNameVn"] == "Cty CP"


def test_an_unknown_customer_is_a_404_not_an_empty_statement(api, tokens):
    """An empty statement reads as "you owe nothing", which is a very different message."""
    assert api("GET", "/api/sales/statement?accountId=crm-nope", tokens["staff"])[0] == 404


def test_it_asks_which_customer(api, tokens):
    assert api("GET", "/api/sales/statement", tokens["staff"])[0] == 400


def test_a_staff_user_gets_no_rows_for_somebody_elses_customer(api, tokens):
    acc, c, a = _order(api, tokens)
    st, r = _stmt(api, tokens["other"], acc["id"])
    assert st == 200 and r["rows"] == [] and r["closingBalance"] == 0


def test_it_needs_a_session(api, tokens):
    assert api("GET", "/api/sales/statement?accountId=x", None)[0] == 401


def test_a_claim_nobody_has_certified_never_reaches_the_customer_statement(api, tokens):
    """You do not send a customer a bill for work that has not been signed off — and a draft claim
    on a statement is exactly that, with a number next to it."""
    acc, c, a = _order(api, tokens)
    before = _stmt(api, tokens["staff"], acc["id"])[1]
    _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
          period="2026-09", claims={c["lines"][0]["uid"]: 300_000_000})
    after = _stmt(api, tokens["staff"], acc["id"])[1]
    assert len(after["rows"]) == len(before["rows"])
    assert after["closingBalance"] == before["closingBalance"]


def test_no_row_restates_its_own_figure_in_another_format(api, tokens):
    """The claim carries a stored `statement` written when it was certified — raw floats, and stale
    the moment formatting changes. Putting it on the statement would print "277225000.00" beside a
    column reading ₫277,225,000, on the one document that goes outside the company."""
    acc, c, a = _order(api, tokens)
    _, r = _stmt(api, tokens["staff"], acc["id"])
    for x in r["rows"]:
        assert "certified, less" not in (x["note"] or ""), x
        assert ".00" not in (x["note"] or ""), x
