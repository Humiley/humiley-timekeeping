"""Timekeeping nudges — working-day gating + who gets a check-in vs check-out reminder."""
import app


def test_tk_is_workday(base_url):
    import db
    from datetime import datetime, timedelta
    db.set_setting("portal_holidays", [])
    mon = datetime(2026, 1, 5)          # 2026-01-05 is a Monday
    assert app._tk_is_workday(mon.strftime("%Y-%m-%d")) is True
    assert app._tk_is_workday((mon + timedelta(days=5)).strftime("%Y-%m-%d")) is False   # Saturday
    db.set_setting("portal_holidays", [{"date": mon.strftime("%Y-%m-%d"), "name": "Holiday"}])
    assert app._tk_is_workday(mon.strftime("%Y-%m-%d")) is False                          # holiday
    db.set_setting("portal_holidays", [])


def test_tk_push_disabled_returns_zero(monkeypatch):
    monkeypatch.setattr(app, "_PUSH_OK", False)
    assert app._tk_push(["a@h.com"], "t", "b") == 0


def test_tk_nudges_targeting(monkeypatch, base_url):
    """check-in nudges the person with NO record; check-out nudges the person still clocked in;
       the person who clocked in AND out gets neither."""
    import db
    from datetime import datetime, timedelta
    today = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
    monkeypatch.setattr(app, "_tk_is_workday", lambda d: True)     # force a workday regardless of the real calendar
    monkeypatch.setattr(app.db, "list_leave", lambda **k: [])
    base = {"role": "staff", "level": "staff", "title": "Staff", "dept": "Ops", "status": "Active",
            "annualUsed": 0, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0, "managerEmail": ""}
    for eid, email in (("TKN1", "inout@h.com"), ("TKN2", "openp@h.com"), ("TKN3", "noshow@h.com")):
        try:
            db.create_employee(dict(base, id=eid, name=eid, email=email))
        except Exception:
            pass
    r1 = db.clock_in("TKN1", today, "08:00")
    if r1:
        db.clock_out(r1, "17:00")
    db.clock_in("TKN2", today, "08:05")     # open (no clock-out)

    calls = []
    monkeypatch.setattr(app, "_tk_push", lambda emails, title, body, url="/", tag="": calls.append((title, {str(e).lower() for e in emails})) or len(emails))
    app._tk_nudges("checkin", today)
    app._tk_nudges("checkout", today)
    ci = next((c[1] for c in calls if "Check-in" in c[0]), set())
    co = next((c[1] for c in calls if "Check-out" in c[0]), set())

    assert "noshow@h.com" in ci and "inout@h.com" not in ci and "openp@h.com" not in ci, ci
    assert "openp@h.com" in co and "inout@h.com" not in co and "noshow@h.com" not in co, co
