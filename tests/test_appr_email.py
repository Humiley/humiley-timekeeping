"""Approval-lifecycle email: right sender (by department), right recipients, right subject per event.
   Decisions still happen in the portal — the email only notifies + deep-links (no one-click approve)."""
import app


def test_approval_email_sender_and_recipients(monkeypatch, base_url):
    captured = []
    monkeypatch.setattr(app, "_graph_send_mail",
                        lambda sender, to, subject, html, cc=None: captured.append(
                            {"sender": sender, "to": to, "cc": cc, "subject": subject, "html": html}) or True)
    monkeypatch.setattr(app.db, "get_setting", lambda k, d="": ("1" if k == "portal_apprEmail" else d))
    monkeypatch.setattr(app.db, "get_employee",
                        lambda i: {"email": "alice@humiley.com", "name": "Alice", "managerEmail": "bob@humiley.com"} if i else None)

    claim = {"empId": "E1", "reqNo": "CLM-001", "amount": 1500000, "status": "Submitted"}
    app._appr_notify("claims", claim, "submitted", "Alice")
    app._appr_notify("claims", claim, "approved", "Bob")
    leave = {"emp_id": "E1", "startDate": "2026-08-01", "endDate": "2026-08-03", "status": "Reviewed"}
    app._appr_notify("leave", leave, "reviewed", "Bob")

    sub, appr, rev = captured
    assert sub["sender"] == "finance@humiley.com"          # claims -> Finance
    assert "bob@humiley.com" in sub["to"]                  # submitted -> the manager reviews
    assert "needs review" in sub["subject"] and sub["subject"].startswith("[Humiley]")
    assert appr["sender"] == "finance@humiley.com"
    assert appr["to"] == ["alice@humiley.com"]             # approved -> the requester
    assert "approved" in appr["subject"]
    assert "1,500,000" in appr["html"]                     # amount rendered
    assert rev["sender"] == "hr@humiley.com"               # leave -> HR
    assert rev["to"] == ["hr@humiley.com"]                 # reviewed -> dept approvals inbox
    assert "alice@humiley.com" in (rev["cc"] or [])


def test_approval_email_off_switch(monkeypatch, base_url):
    calls = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda *a, **k: calls.append(1) or True)
    monkeypatch.setattr(app.db, "get_setting", lambda k, d="": ("0" if k == "portal_apprEmail" else d))
    app._appr_notify("claims", {"empId": "E1"}, "approved", "Bob")
    assert not calls, "portal_apprEmail=0 must send nothing"


def test_overdue_reminder_engine(monkeypatch, base_url):
    import db
    from datetime import datetime, timedelta
    for coll in ("payments", "claims", "travel"):
        for d in list(db.list_collection(coll)):
            if d.get("id"):
                db.delete_collection_item(coll, d["id"])
    db.set_setting("_apprRemindedAt", "{}")
    old = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-OLD", "status": "Submitted", "submittedOn": old, "amount": 500000})
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-NEW", "status": "Submitted", "submittedOn": today, "amount": 100000})
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-DONE", "status": "Approved", "submittedOn": old})
    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append(subject) or True)
    monkeypatch.setattr(app.db, "get_employee", lambda i: {"email": "a@h.com", "name": "Alice", "managerEmail": "b@h.com"} if i else None)

    n1 = app._appr_reminders()
    assert n1 >= 1, "the 5-day-old pending payment must be reminded"
    assert all("Reminder ·" in s for s in sent), sent
    assert any("Payment request" in s and "needs review" in s for s in sent)
    before = len(sent)
    assert app._appr_reminders() == 0, "dedup — a second sweep the same day sends nothing"
    assert len(sent) == before
