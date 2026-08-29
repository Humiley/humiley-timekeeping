"""A paid payment reaching the ledger, and the state it must be in first.

Only a PAID payment posts. An approved one is a commitment — the money has not left, and in this
portal the disbursement is a separate e-signature that refuses without a bank slip. Posting on
approval would put cash out of the bank in the accounts before it was out of the bank.

Periods here belong to this file alone: `_gl_payrun_batch` aggregates by period, and a foreign
document sitting in the same month changes the figures. See test_gl_statements_api.py, which failed
only in the full suite for exactly that reason.
"""
import pytest

import db


PERIOD = "2026-11"


def _payment(pid="PAY-GL-1", amount=500_000_000, category="Operating expense",
             status="Paid", when="2026-11-12", method="Bank transfer", **kw):
    return db.put_collection_item("payments", dict({
        "id": pid, "reqNo": pid, "status": status, "paidOn": when,
        "amount": amount, "category": category, "method": method,
        "payee": "Acme Co", "department": "Engineering",
        "bankSlip": "data:image/png;base64,x",
    }, **kw))


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM gl_entries")
    conn.execute("DELETE FROM gl_batches")
    conn.commit()
    conn.close()
    for d in db.list_collection("payments"):
        when = str(d.get("paidOn") or d.get("dueDate") or "")
        if str(d.get("id", "")).startswith("PAY-GL") or when[:7] == PERIOD:
            db.delete_collection_item("payments", d.get("id"))
    for p in db.list_collection(db.GL_PERIODS):
        db.delete_collection_item(db.GL_PERIODS, p.get("id"))
    db.set_setting("portal_purchaseAccounts", {})
    yield


# --- what may post -------------------------------------------------------------------------------

def test_a_paid_payment_posts_the_cost_and_the_cash(api, tokens):
    _payment()
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})
    assert s == 200, r
    assert r["period"] == PERIOD, "the payment landed in the month it was PAID"

    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    by = {row["account"]: row for row in sm["trialBalance"]["rows"]}
    assert by["642"]["debit"] == 500_000_000
    assert by["112"]["credit"] == 500_000_000
    assert sm["trialBalance"]["balanced"]


@pytest.mark.parametrize("status", ["Pending Approval", "Approved", "Rejected", "Cancelled"])
def test_only_a_paid_payment_posts(api, tokens, status):
    """An approved request is a commitment, not a cash movement."""
    _payment(status=status)
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})
    assert s == 409, status
    assert "the money has not left" in r.get("error", "")


def test_the_same_payment_cannot_post_twice(api, tokens):
    _payment()
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})[0] == 200
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})
    assert s == 409 and "already been posted" in r.get("error", "")

    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    by = {row["account"]: row for row in sm["trialBalance"]["rows"]}
    assert by["112"]["credit"] == 500_000_000, "the bank was debited twice"


def test_the_caller_cannot_choose_the_month(api, tokens):
    _payment(when="2026-11-12")
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1", "period": "2026-01"})
    assert s == 200 and r["period"] == "2026-11"


def test_a_payment_with_no_date_is_refused_rather_than_dated_today(api, tokens):
    _payment(when="")
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})
    assert s == 409 and "no month to file it in" in r.get("error", "")


def test_staff_cannot_post_a_payment(api, tokens):
    _payment()
    assert api("POST", "/api/gl/post", tokens["staff"],
               {"source": "purchase", "id": "PAY-GL-1"})[0] == 403


# --- the account map ------------------------------------------------------------------------------

def test_the_company_map_overrides_the_default(api, tokens):
    db.set_setting("portal_purchaseAccounts", {"Subcontractor": "632"})
    _payment(category="Subcontractor")
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})[0] == 200
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    accounts = {row["account"] for row in sm["trialBalance"]["rows"]}
    assert "632" in accounts and "627" not in accounts


def test_the_buy_side_map_does_not_leak_into_the_sell_side(api, tokens):
    """One shared dict would let an override for a payment category change what a claim credits.
    The two sides read different settings."""
    db.set_setting("portal_purchaseAccounts", {"Operating expense": "9999"})
    _payment()
    assert api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-1"})[0] == 200
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    accounts = {row["account"] for row in sm["trialBalance"]["rows"]}
    assert "9999" in accounts
    assert "511" not in accounts, "a sell-side account appeared from a buy-side override"


# --- what the month still owes ----------------------------------------------------------------------

def test_an_unposted_paid_payment_is_listed_with_its_caveats(api, tokens):
    _payment(category="Purchase — Goods")
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    row = next(p for p in sm["pending"] if p["source"] == "purchase")
    assert "PAY-GL-1" in row["label"]
    assert any("cost of sales will be understated" in w for w in row.get("warnings", [])), row

    api("POST", "/api/gl/post", tokens["management"], {"source": "purchase", "id": "PAY-GL-1"})
    _, after = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    assert after["pending"] == []


def test_an_unmapped_category_is_flagged_on_the_pending_row(api, tokens):
    _payment(category="Cryptocurrency")
    _, sm = api("GET", "/api/gl/summary?period=" + PERIOD, tokens["management"])
    row = next(p for p in sm["pending"] if p["source"] == "purchase")
    assert any("Cryptocurrency" in w for w in row.get("warnings", [])), row


def test_a_closed_month_refuses_a_payment_too(api, tokens):
    _payment()
    api("POST", "/api/gl/post", tokens["management"], {"source": "purchase", "id": "PAY-GL-1"})
    assert api("POST", "/api/gl/close", tokens["admin"], {"period": PERIOD})[0] == 200

    _payment(pid="PAY-GL-2")
    s, r = api("POST", "/api/gl/post", tokens["management"],
               {"source": "purchase", "id": "PAY-GL-2"})
    assert s == 409 and "is closed" in r.get("error", "")


# --- cash out reaches the statements -----------------------------------------------------------------

def test_the_payment_shows_as_expense_and_reduced_cash_on_the_statements(api, tokens):
    _payment()
    api("POST", "/api/gl/post", tokens["management"], {"source": "purchase", "id": "PAY-GL-1"})
    _, st = api("GET", "/api/gl/statements?period=" + PERIOD, tokens["management"])

    assert st["incomeStatement"]["period"]["expense"] == 500_000_000
    assets = {row["account"]: row["balance"] for row in st["balanceSheet"]["assets"]}
    assert assets["112"] == -500_000_000, "paying out of an empty ledger leaves the bank negative"
    assert st["balanceSheet"]["balanced"], "the sheet stopped balancing"
