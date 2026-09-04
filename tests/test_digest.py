"""Weekly leadership & manager digest: rolls pending 3-level requests up by who must act next,
   groups submit-state items under the requester's manager, review-state items to leadership,
   flags overdue, and emails per manager + one company roll-up. Opt-in (off by default)."""
import app


def _clear(db):
    for coll in ("payments", "travel", "claims"):
        for d in list(db.list_collection(coll)):
            if d.get("id"):
                db.delete_collection_item(coll, d["id"])


def test_digest_gather_and_send(monkeypatch, base_url):
    import db
    from datetime import datetime, timedelta
    _clear(db)
    db.set_setting("portal_apprEmail", "1")
    db.set_setting("portal_digestEnabled", "1")
    db.set_setting("portal_digestLeadTo", "md@h.com")
    db.set_setting("portal_apprReminderDays", "2")
    old = (datetime.utcnow() - timedelta(days=6)).strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-A", "status": "Submitted", "submittedOn": old, "amount": 500000})
    db.put_collection_item("payments", {"empId": "E2", "reqNo": "PAY-B", "status": "Submitted", "submittedOn": today, "amount": 200000})
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-R", "status": "Reviewed", "submittedOn": old, "reviewedOn": old, "amount": 900000})
    emp = {"E1": {"email": "e1@h.com", "name": "E One", "managerEmail": "boss@h.com"},
           "E2": {"email": "e2@h.com", "name": "E Two", "managerEmail": "boss@h.com"}}
    monkeypatch.setattr(app.db, "get_employee", lambda i: emp.get(i))
    monkeypatch.setattr(app.db, "get_employee_by_email", lambda e: {"name": "The Boss", "email": e} if e == "boss@h.com" else None)
    monkeypatch.setattr(app.db, "list_leave", lambda **k: [])   # keep the test deterministic (ignore any demo leave)

    managers, leadership, counts = app._digest_gather()
    assert counts["await"] == 2 and counts["review"] == 1, counts
    assert counts["overdue"] == 2, "both 6-day-old items (submit + review) are overdue; the today one is not"
    assert counts["valuePending"] == 1600000.0
    assert set(managers.keys()) == {"boss@h.com"}
    assert len(managers["boss@h.com"]["rows"]) == 2 and managers["boss@h.com"]["name"] == "The Boss"
    assert len(leadership) == 1 and leadership[0]["ref"] == "PAY-R"
    assert any(r["overdue"] for r in managers["boss@h.com"]["rows"]) and leadership[0]["overdue"]

    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append((to[0], subject, html)) or True)
    n = app._digest_send()
    assert n == 2, "one manager email + one leadership email"
    tos = [t for t, _, _ in sent]
    assert "boss@h.com" in tos and "md@h.com" in tos
    boss_html = next(h for t, _, h in sent if t == "boss@h.com")
    # Split, so a failure names which half broke rather than "the and was false".
    assert "PAY-A" in boss_html, "the manager's own row is missing from their digest"
    assert "cid:humileylogo" in boss_html, "the digest lost the reverse brand mark"


def test_digest_off_switch(monkeypatch, base_url):
    import db
    db.set_setting("portal_digestEnabled", "0")
    calls = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda *a, **k: calls.append(1) or True)
    assert app._digest_send() == 0, "digest off (opt-in) sends nothing on the schedule path"
    assert not calls


def test_digest_preview_ignores_off_switch(monkeypatch, base_url):
    """The admin 'send me a test' preview must work even while the weekly schedule is off,
       so an admin can see the format before enabling it — but still respects Mail.Send on/off."""
    import db
    db.set_setting("portal_digestEnabled", "0")
    db.set_setting("portal_apprEmail", "1")
    monkeypatch.setattr(app.db, "list_leave", lambda **k: [])
    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append(to[0]) or True)
    n = app._digest_send(preview_to="admin@h.com")
    assert n == 1 and sent == ["admin@h.com"]

    db.set_setting("portal_apprEmail", "0")   # Mail.Send master switch off -> even preview sends nothing
    sent2 = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda *a, **k: sent2.append(1) or True)
    assert app._digest_send(preview_to="admin@h.com") == 0 and not sent2
    db.set_setting("portal_apprEmail", "1")
