"""Mark-paid requires the bank payment slip, and attaches it during the authorized Paid e-signature.

A payment disbursement must carry proof of payment. The slip rides through /api/esign (the only path
that can transition a decided money record), so it's stored atomically with the Paid signature — and a
Paid attempt with no slip is rejected before any signature is appended (no orphan).
"""
import app
import db


def _approved_payment(api, tokens):
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": "PR-SLIP", "payee": "Vendor", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    pid = b["item"]["id"]
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    row["status"] = "Approved"; row["approvedBy"] = "Editor User"
    db.put_collection_item("payments", row)
    return pid


def test_mark_paid_without_slip_is_rejected(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)   # skip re-auth to drive the e-signature
    pid = _approved_payment(api, tokens)
    st, b = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payments", "id": pid, "meaning": "Paid — PR-SLIP", "setStatus": "Paid"})
    assert st == 400 and "bank payment slip" in (b.get("error") or "").lower(), b
    # And it must NOT have signed / flipped status (no orphan Paid signature).
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    assert row.get("status") == "Approved"
    assert not any((s.get("setStatus") or "").lower() == "paid" for s in (row.get("signatures") or []))


def test_mark_paid_attaches_the_bank_slip(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _approved_payment(api, tokens)
    slip = "data:application/pdf;base64,YmFuay1zbGlw"
    st, b = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payments", "id": pid, "meaning": "Paid — PR-SLIP", "setStatus": "Paid",
                 "attach": {"bankSlip": slip, "bankSlipName": "bank-slip.pdf"}})
    assert st == 200, b
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    assert row.get("status") == "Paid"
    assert row.get("bankSlip") == slip, "the bank slip must be stored on the paid payment"
    assert row.get("bankSlipName") == "bank-slip.pdf"
    assert row.get("paidBy")
    assert row.get("paidOn"), "the disbursement date must be stamped for the voucher date-trail"


def test_a_non_data_slip_is_rejected(api, tokens, monkeypatch):
    # A URL/script masquerading as a slip must not satisfy the requirement.
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _approved_payment(api, tokens)
    st, b = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payments", "id": pid, "meaning": "Paid — PR-SLIP", "setStatus": "Paid",
                 "attach": {"bankSlip": "https://evil.example/x", "bankSlipName": "x"}})
    assert st == 400, b
