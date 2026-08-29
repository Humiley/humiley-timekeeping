"""The supplier register over HTTP: who may see it, and what it refuses to guess.

The register exists for one control above all — noticing that a payment names a different bank
account from the one this supplier has been paid at before. What only this level can prove is that
the control reaches somebody: it is computed across every payment in the review, not left for a
person to check one at a time, because the payment nobody opened is the case the control is for.
"""
import pytest

import db


def _pay(pid="PAY-S-1", name="Acme Co", acc="0123 4567 8901", bank="Vietcombank",
         status="Paid", amount=1_000_000, **kw):
    return db.put_collection_item("payments", dict({
        "id": pid, "reqNo": pid, "status": status, "amount": amount,
        "payeeCompany": name, "payee": name, "bankAcc": acc, "bankName": bank,
        "bankHolder": name.upper(), "paidOn": "2026-12-05",
    }, **kw))


def _sup(sid="SUP-1", name="Acme Co", acc="0123 4567 8901", bank="Vietcombank", **kw):
    return db.put_collection_item("suppliers", dict({
        "id": sid, "name": name, "mst": "0123456789",
        "bankAcc": acc, "bankName": bank, "bankHolder": name.upper(),
    }, **kw))


@pytest.fixture(autouse=True)
def _clean():
    for coll, prefix in (("payments", "PAY-S"), ("suppliers", "SUP-")):
        for d in db.list_collection(coll):
            if str(d.get("id", "")).startswith(prefix):
                db.delete_collection_item(coll, d.get("id"))
    # Suppliers is a new collection; anything left by another file would change the counts here.
    for d in db.list_collection("suppliers"):
        db.delete_collection_item("suppliers", d.get("id"))
    yield


# --- who may look -----------------------------------------------------------------------------------

def test_staff_cannot_read_the_supplier_register(api, tokens):
    assert api("GET", "/api/suppliers/review", tokens["staff"])[0] == 403


def test_a_manager_is_not_enough(api, tokens):
    """It holds the bank accounts the company pays into. That is management-level information for
    the same reason the ledger is."""
    assert api("GET", "/api/suppliers/review", tokens["mgr"])[0] == 403


def test_management_may_read(api, tokens):
    s, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert s == 200 and r["ok"] is True


# --- the control ------------------------------------------------------------------------------------

def test_a_changed_bank_account_is_surfaced_in_the_review(api, tokens):
    """THE test. The payment nobody opened is exactly the case this exists for, so the change has to
    be found by the register rather than by somebody checking one payment at a time."""
    _sup()
    _pay(supplierId="SUP-1", acc="9999 8888 77", bank="Techcombank")

    s, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert s == 200
    assert len(r["bankChanges"]) == 1, r["bankChanges"]
    msg = r["bankChanges"][0]["message"]
    assert "THE BANK ACCOUNT HAS CHANGED" in msg
    assert "0123 4567 8901" in msg and "9999 8888 77" in msg
    assert "ringing a number you already had" in msg


def test_the_same_account_typed_differently_raises_nothing(api, tokens):
    """A warning that fires on every second payment is one nobody reads."""
    _sup()
    _pay(supplierId="SUP-1", acc="0123-4567-8901", bank="VIETCOMBANK")
    _, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert r["bankChanges"] == []


def test_one_payment_can_be_checked_on_its_own(api, tokens):
    _sup()
    _pay(supplierId="SUP-1", acc="9999", bank="Techcombank")
    s, r = api("GET", "/api/suppliers/bank-check?id=PAY-S-1", tokens["editor"])
    assert s == 200
    assert r["verdict"]["status"] == "changed"
    assert r["supplierName"] == "Acme Co"


def test_an_unlinked_payment_says_it_cannot_be_compared(api, tokens):
    """Not a silent pass — a silent pass reads as 'checked and fine'."""
    _pay()
    s, r = api("GET", "/api/suppliers/bank-check?id=PAY-S-1", tokens["editor"])
    assert s == 200 and r["verdict"]["status"] == "unknown"


def test_the_bank_check_never_blocks_anything(api, tokens):
    """It is a GET. The answer belongs to a person who can ring the supplier — a system that refused
    the payment would be worked around, and this fraud is defeated by a phone call, not a 403."""
    _sup()
    _pay(supplierId="SUP-1", acc="9999")
    assert api("GET", "/api/suppliers/bank-check?id=PAY-S-1", tokens["editor"])[0] == 200
    still = db.get_collection_item("payments", "PAY-S-1")
    assert still["status"] == "Paid", "the check changed the payment"


# --- linking is one decision at a time ------------------------------------------------------------------

def test_linking_a_payment_to_an_existing_supplier(api, tokens):
    _sup()
    _pay()
    s, r = api("POST", "/api/suppliers/link", tokens["management"],
               {"paymentId": "PAY-S-1", "supplierId": "SUP-1"})
    assert s == 200, r
    assert db.get_collection_item("payments", "PAY-S-1")["supplierId"] == "SUP-1"
    assert r["verdict"]["status"] == "matches"


def test_creating_the_supplier_a_payment_describes(api, tokens):
    _pay(name="Brand New Ltd", payeeMst="0123456789")
    s, r = api("POST", "/api/suppliers/link", tokens["management"], {"paymentId": "PAY-S-1"})
    assert s == 200, r
    sup = db.get_collection_item("suppliers", r["supplierId"])
    assert sup["name"] == "Brand New Ltd"
    assert sup["bankAcc"] == "0123 4567 8901"
    assert sup["createdFrom"] == "PAY-S-1"


def test_a_payment_with_no_payee_creates_nothing(api, tokens):
    _pay(name="")
    s, r = api("POST", "/api/suppliers/link", tokens["management"], {"paymentId": "PAY-S-1"})
    assert s == 400 and "names no payee" in r.get("error", "")
    assert db.list_collection("suppliers") == []


def test_a_bad_tax_code_refuses_the_create_rather_than_storing_it(api, tokens):
    """A supplier created with an identity nobody can verify is worse than no supplier: it looks
    like a master record and joins nothing reliably."""
    _pay(name="Dodgy Ltd", payeeMst="12345")
    s, r = api("POST", "/api/suppliers/link", tokens["management"], {"paymentId": "PAY-S-1"})
    assert s == 400 and "not a usable MST" in r.get("error", "")
    assert db.list_collection("suppliers") == []


def test_linking_to_a_supplier_that_does_not_exist_is_refused(api, tokens):
    _pay()
    s, _ = api("POST", "/api/suppliers/link", tokens["management"],
               {"paymentId": "PAY-S-1", "supplierId": "SUP-404"})
    assert s == 404


def test_staff_cannot_link(api, tokens):
    _sup(); _pay()
    assert api("POST", "/api/suppliers/link", tokens["staff"],
               {"paymentId": "PAY-S-1", "supplierId": "SUP-1"})[0] == 403


def test_linking_leaves_an_audit_entry(api, tokens):
    _sup(); _pay()
    before = len([a for a in db.list_collection("audit")
                  if a.get("action") == "Linked a payment to a supplier"])
    api("POST", "/api/suppliers/link", tokens["management"],
        {"paymentId": "PAY-S-1", "supplierId": "SUP-1"})
    after = [a for a in db.list_collection("audit")
             if a.get("action") == "Linked a payment to a supplier"]
    assert len(after) == before + 1


# --- the backfill proposes, it does not decide -------------------------------------------------------------

def test_the_review_proposes_a_link_for_an_unambiguous_name(api, tokens):
    _sup()
    _pay()
    _, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert r["backfill"]["counts"]["link"] == 1
    # …and has NOT applied it. Proposing and doing are different verbs.
    assert not db.get_collection_item("payments", "PAY-S-1").get("supplierId")


def test_an_ambiguous_name_is_proposed_to_nobody(api, tokens):
    _sup(sid="SUP-1")
    _sup(sid="SUP-2")
    _pay()
    _, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert r["backfill"]["counts"]["ambiguous"] == 1
    assert r["backfill"]["counts"]["link"] == 0


# --- the question that had no answer -------------------------------------------------------------------------

def test_spend_is_reported_and_says_when_it_is_incomplete(api, tokens):
    _sup()
    _pay(pid="PAY-S-1", supplierId="SUP-1", amount=3_000_000)
    _pay(pid="PAY-S-2", name="Nobody Ltd", amount=5_000_000)      # unlinked
    _, r = api("GET", "/api/suppliers/review", tokens["management"])

    assert r["spend"]["rows"][0]["total"] == 3_000_000
    assert r["spend"]["unlinkedPayments"] == 1
    assert r["spend"]["unlinkedTotal"] == 5_000_000
    assert r["spend"]["complete"] is False, "a partial total must not present itself as the answer"


def test_duplicates_in_the_register_are_reported(api, tokens):
    _sup(sid="SUP-1", name="Acme Co")
    _sup(sid="SUP-2", name="ACME CO., LTD")
    _, r = api("GET", "/api/suppliers/review", tokens["management"])
    assert r["duplicates"] and len(r["duplicates"][0]["suppliers"]) == 2
