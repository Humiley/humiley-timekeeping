"""The finance voucher/dossier shows the full date trail — requested / approved / paid.

Each date is stamped on the record when its 21 CFR Part 11 e-signature is applied: reviewedOn on
review, approvedOn on approval (mirroring the pre-existing paidOn on disbursement). The consolidated
payment dossier reads these back; older records without them fall back to the signature timestamps in
the UI. This test drives the real /api/esign chain (submit -> review -> approve -> pay).
"""
import app
import db


def _submit_payment(api, tokens):
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": "PR-DATE", "payee": "Vendor", "amount": 1000, "empId": "HML-STF",
                 "attachment": "data:application/pdf;base64,QQ==", "status": "Submitted"})
    assert st == 200, b
    return b["item"]["id"]


def _row(pid):
    return next(x for x in db.list_collection("payments") if x.get("id") == pid)


def test_approve_and_pay_stamp_the_date_trail(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)   # skip re-auth so the e-signatures can be driven
    pid = _submit_payment(api, tokens)

    # Review by the requester's DIRECT manager -> reviewedOn stamped.
    st, b = api("POST", "/api/esign", tokens["mgr"],
                {"coll": "payments", "id": pid, "meaning": "Reviewed — PR-DATE", "setStatus": "Reviewed"})
    assert st == 200, b
    assert _row(pid).get("reviewedOn"), "review must stamp reviewedOn"

    # Approve by a DIFFERENT person at editor level -> approvedBy + approvedOn stamped.
    st, b = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payments", "id": pid, "meaning": "Approved — PR-DATE", "setStatus": "Approved"})
    assert st == 200, b
    row = _row(pid)
    assert row.get("status") == "Approved"
    assert row.get("approvedBy") and row.get("approvedOn"), "approval must stamp approvedBy + approvedOn"

    # Pay (editor, with the required bank slip) -> paidBy + paidOn stamped.
    st, b = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payments", "id": pid, "meaning": "Paid — PR-DATE", "setStatus": "Paid",
                 "attach": {"bankSlip": "data:application/pdf;base64,YmFuaw==", "bankSlipName": "slip.pdf"}})
    assert st == 200, b
    row = _row(pid)
    assert row.get("status") == "Paid"
    assert row.get("paidBy") and row.get("paidOn"), "disbursement must stamp paidBy + paidOn"
