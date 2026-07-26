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


def _run_send_synchronously(monkeypatch):
    """Make _graph_send_mail's fire-and-forget thread run inline so a test can assert its outcome."""
    class _Sync:
        def __init__(self, target=None, daemon=None, **k):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(app.threading, "Thread", _Sync)


def test_send_mail_selfheals_after_consent(monkeypatch):
    """A just-granted Mail.Send consent is NOT in the CACHED app token → Graph 403s. The sender must
       discard the stale token, mint a fresh one (force=True), and retry ONCE so it succeeds with no restart."""
    import io
    import urllib.error
    tok_calls, posts = [], []

    def fake_token(force=False):
        tok_calls.append(force)
        return "FRESH" if force else "STALE"
    monkeypatch.setattr(app, "_graph_app_token", fake_token)

    def fake_urlopen(req, timeout=None):
        auth = req.get_header("Authorization") or ""
        posts.append(auth)
        if "FRESH" in auth:
            return io.BytesIO(b"")                       # 202-equivalent; .read() works
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"error":{"code":"ErrorAccessDenied","message":"Access is denied."}}'))
    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    _run_send_synchronously(monkeypatch)

    app._APPR_EMAIL_HEALTH.update({"at": "", "ok": 0, "failed": 0, "lastError": ""})
    assert app._graph_send_mail("finance@humiley.com", ["a@h.com"], "Hi", "<p>hi</p>") is True

    assert tok_calls == [False, True], "cached token first, then FORCE a fresh one on 403"
    assert "STALE" in posts[0] and "FRESH" in posts[1], "the retry must use the refreshed token"
    assert app._APPR_EMAIL_HEALTH["ok"] == 1 and app._APPR_EMAIL_HEALTH["lastError"] == ""
    assert app._APPR_EMAIL_HEALTH["failed"] == 0


def test_send_mail_no_retry_on_non_auth_error(monkeypatch):
    """A non-auth failure (e.g. 500) must NOT force-refresh/retry — the self-heal is for consent (401/403) only."""
    import io
    import urllib.error
    forced = []
    monkeypatch.setattr(app, "_graph_app_token", lambda force=False: (forced.append(force) or "T"))

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {},
                                     io.BytesIO(b'{"error":{"code":"x","message":"boom"}}'))
    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    _run_send_synchronously(monkeypatch)

    app._APPR_EMAIL_HEALTH.update({"at": "", "ok": 0, "failed": 0, "lastError": ""})
    app._graph_send_mail("finance@humiley.com", ["a@h.com"], "Hi", "<p>hi</p>")
    assert forced == [False], "500 is not auth — no force-refresh, no retry"
    assert app._APPR_EMAIL_HEALTH["failed"] == 1 and app._APPR_EMAIL_HEALTH["ok"] == 0


def test_waiting_since_handles_leave_string_signatures_and_created_at(base_url):
    import json as _json
    rev = {"status": "reviewed", "created_at": "2026-06-01T09:00:00Z",
           "signatures": _json.dumps([{"setStatus": "Reviewed", "ts": "2026-06-05T10:00:00Z"}])}
    t = app._appr_waiting_since(rev, "review")           # must NOT crash on the JSON-string signatures
    assert t == app._appr_epoch("2026-06-05T10:00:00Z")  # uses the Reviewed-signature clock
    sub = {"status": "pending", "created_at": "2026-06-01T09:00:00Z", "startDate": "2026-07-20", "signatures": "[]"}
    assert app._appr_waiting_since(sub, "submit") == app._appr_epoch("2026-06-01T09:00:00Z"), "created_at, not startDate"


def _reset_reminders(db):
    from datetime import datetime, timedelta
    for coll in ("payments", "claims", "travel"):
        for d in list(db.list_collection(coll)):
            if d.get("id"):
                db.delete_collection_item(coll, d["id"])
    db.set_setting("_apprRemindedAt", "{}")
    db.set_setting("portal_apprEmail", "1")
    db.set_setting("portal_apprReminders", "1")
    db.set_setting("portal_apprReminderDays", "2")


def test_overdue_escalates_past_threshold(monkeypatch, base_url):
    """Once an overdue item passes portal_apprEscalateDays, the nudge is re-labelled 'Escalated' and
       CCs the escalation recipient (approvals never get stuck on one absent approver)."""
    import db
    from datetime import datetime, timedelta
    _reset_reminders(db)
    db.set_setting("portal_apprEscalateDays", "3")
    db.set_setting("portal_apprEscalateTo", "director@h.com")
    old = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-ESC", "status": "Submitted", "submittedOn": old, "amount": 500000})
    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append({"subject": subject, "cc": cc or []}) or True)
    monkeypatch.setattr(app.db, "get_employee", lambda i: {"email": "a@h.com", "name": "Alice", "managerEmail": "b@h.com"} if i else None)
    try:
        assert app._appr_reminders() >= 1
        esc = [s for s in sent if "Escalated ·" in s["subject"]]
        assert esc, "5-day overdue past the 3-day threshold must escalate, got: " + str([s["subject"] for s in sent])
        assert "director@h.com" in esc[0]["cc"], "escalation must CC the escalation recipient"
    finally:
        db.set_setting("portal_apprEscalateDays", "0")
        db.set_setting("portal_apprEscalateTo", "")


def test_below_escalate_threshold_only_reminds(monkeypatch, base_url):
    import db
    from datetime import datetime, timedelta
    _reset_reminders(db)
    db.set_setting("portal_apprEscalateDays", "10")   # higher than the item's age → no escalation yet
    db.set_setting("portal_apprEscalateTo", "director@h.com")
    old = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-REM", "status": "Submitted", "submittedOn": old, "amount": 100000})
    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append({"subject": subject, "cc": cc or []}) or True)
    monkeypatch.setattr(app.db, "get_employee", lambda i: {"email": "a@h.com", "name": "Alice", "managerEmail": "b@h.com"} if i else None)
    try:
        app._appr_reminders()
        assert sent and all("Reminder ·" in s["subject"] for s in sent), "below threshold it must remind, not escalate"
        assert all("director@h.com" not in s["cc"] for s in sent), "no escalation CC below the threshold"
    finally:
        db.set_setting("portal_apprEscalateDays", "0")
        db.set_setting("portal_apprEscalateTo", "")
