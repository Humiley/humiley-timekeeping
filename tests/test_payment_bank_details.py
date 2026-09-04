"""Beneficiary company + bank details on a payment request, and the one email that carries them.

Two things are pinned here, both reported from production:

1. **Finance lost approved payments.** The Finance register built its period date from `dueDate` only.
   `dueDate` is optional, and the period predicate is fail-closed (a blank date is DROPPED, not kept),
   so any payment submitted without a due date vanished from Finance the moment a period was selected
   — approved ones included. The frontend now reads `p.ts || p.dueDate`. Guarded here by asserting the
   fallback is present in the shipped bundle, since `_finItems` is browser-side.

2. **One approval produced two emails.** The frontend sent its own "HUMILEY · Finance" mail on top of
   the backend's branded template. The backend template is now the only sender, and it carries the
   same beneficiary block the requester filled in, so the decision mail matches the request form.
"""
import os
import re

import app

BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "index.html")


def _bundle():
    with open(BUNDLE, encoding="utf-8") as fh:
        return fh.read()


def _rows(html):
    """Pull the (label, value) pairs out of a rendered _appr_email_html table."""
    return re.findall(r"width:150px;vertical-align:top'>([^<]+)</td><td[^>]*>([^<]*)</td>", html)


def _capture(monkeypatch):
    box = []
    monkeypatch.setattr(app, "_graph_send_mail",
                        lambda sender, to, subject, html, cc=None: box.append(
                            {"to": to, "cc": cc, "subject": subject, "html": html}) or True)
    monkeypatch.setattr(app.db, "get_setting", lambda k, d="": ("1" if k == "portal_apprEmail" else d))
    monkeypatch.setattr(app.db, "get_employee",
                        lambda i: {"email": "b@humiley.com", "name": "Le Van B",
                                   "managerEmail": "tony.nguyen@humiley.com"} if i else None)
    return box


PAYMENT = {
    "empId": "HML-002", "reqNo": "PAY-1", "amount": 12_000_000, "status": "Approved",
    "payeeCompany": "ACME Company Ltd", "payeeMst": "0312345678", "bankName": "Vietcombank",
    "bankAcc": "007100123456", "bankHolder": "ACME COMPANY LTD", "bankBranch": "HCM District 1",
}


def test_approval_email_carries_the_beneficiary_block(monkeypatch):
    box = _capture(monkeypatch)
    app._appr_notify("payments", PAYMENT, "approved", "Tony Nguyen")
    assert len(box) == 1, "exactly one email per decision — the frontend must not send a second"
    labels = dict(_rows(box[0]["html"]))
    for k, v in (("Company", "ACME Company Ltd"), ("Tax code (MST)", "0312345678"),
                 ("Bank", "Vietcombank"), ("Account number", "007100123456"),
                 ("Account holder", "ACME COMPANY LTD"), ("Branch", "HCM District 1")):
        assert labels.get(k) == v, "approval mail is missing %s — it must match the request form" % k


def test_blank_bank_fields_print_no_empty_rows(monkeypatch):
    """A petty-cash request has no bank details; the mail must not show six blank lines."""
    box = _capture(monkeypatch)
    app._appr_notify("payments", {"empId": "E", "reqNo": "CASH-1", "amount": 50_000,
                                  "status": "Approved"}, "approved", "Tony")
    labels = [k for k, _ in _rows(box[0]["html"])]
    for k in ("Company", "Bank", "Account number", "Account holder", "Branch"):
        assert k not in labels, "%s printed with no value" % k


def test_bank_block_is_payments_only(monkeypatch):
    """Claims/travel/leave have no beneficiary bank — the block must not leak into their mail."""
    box = _capture(monkeypatch)
    app._appr_notify("claims", dict(PAYMENT, reqNo="CLM-1"), "approved", "Tony")
    assert "Account number" not in [k for k, _ in _rows(box[0]["html"])]


def test_finance_period_date_falls_back_to_the_submit_date():
    """`date: p.ts || p.dueDate` — dueDate alone made no-due-date payments vanish from Finance."""
    src = _bundle()
    assert "date: p.ts || p.dueDate" in src, \
        "Finance period date must fall back to the submit date; dueDate alone drops payments"


def test_refresh_button_bypasses_the_collection_cache():
    """Refresh inside the 45s tkLoadColl cache window was a no-op — exactly when it gets pressed."""
    src = _bundle()
    assert "tkRenderFinance(true)" in src, "the Finance Refresh button must force a reload"
    assert "async function tkRenderFinance(force)" in src


def test_frontend_sends_no_second_decision_email():
    """tkFinFlowMail + the leave/claim decision handlers must not call tkMailRequester any more."""
    src = _bundle()
    fin = src[src.index("async function tkFinFlowMail("):]
    fin = fin[:fin.index("\n}\n") + 3]
    assert "tkMailRequester(" not in fin, "tkFinFlowMail must not send — the backend owns decision mail"
    assert "_pushNotify(" in fin, "the requester should still get the in-app/OS push"
    assert "'Your leave request was rejected'" not in src, "plain-text leave decision mail is a duplicate"


def test_slogan_is_current_everywhere():
    for path in ("app.py", BUNDLE):
        p = path if os.path.isabs(path) else os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), path)
        with open(p, encoding="utf-8") as fh:
            body = fh.read()
        assert "Move Air" not in body, "%s still carries the retired slogan" % path
