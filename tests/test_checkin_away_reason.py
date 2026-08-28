# -*- coding: utf-8 -*-
"""A punch the app could see was NOT at the chosen site has to say why — enforced on the SERVER.

The check-in screen blocks the plain Check In in that case and offers a reason box instead, but a
client-side block is a courtesy, not a control: anything can POST to this endpoint. The rule lives
where the row is written.

The test is the STAMP — the same three-state label every screen reads — and the distinction it draws
is the point of the whole feature:

  'away from site'  the app knew they were somewhere else  -> a reason is REQUIRED
  'GPS unverified'  the app could not tell                 -> nothing is demanded of them

Demanding an explanation for an unconfirmed fix would put the burden on whoever has the worst phone,
which is not a finding about a person. Blocking the punch outright would be worse still: somebody who
worked would have no record of it, and unrecorded hours are the employer's exposure, not theirs.
"""
from datetime import datetime, timedelta

import db

EMP = "HML-MGT"          # the 'management' token's employee (tests/conftest.py)

AWAY = "HQ Tower (away from site)"
UNVER = "HQ Tower (GPS unverified)"
INZONE = "HQ Tower"


def _past_time(vn=None):
    """A check-in time that is in the past on the COMPANY clock, whatever hour the suite runs at.

    These tests used to send a hardcoded "08:00". The server stamps a punch with the VN day (UTC+7)
    and refuses one in the future, so between 00:00 and 08:00 Vietnam time every test in this file
    failed on "Check-in time can't be in the future" instead of on the thing it asserts. That window
    is the middle of the afternoon in UTC, so it took CI red on an unrelated PR to notice — and it
    was failing on main just the same, for everybody, for eight hours a day.

    The server's clock is the only one that matters here, so derive the time from it rather than
    from the runner's timezone.
    """
    vn = vn or (datetime.utcnow() + timedelta(hours=7))
    earlier = vn - timedelta(minutes=5)
    if earlier.date() != vn.date():
        # Just after midnight: five minutes ago was YESTERDAY, and the punch is recorded against
        # today's date — so yesterday's clock time would read as the future all over again.
        return "00:00"
    return earlier.strftime("%H:%M")


def test_the_time_this_file_sends_is_never_in_the_future_at_any_hour():
    """The helper above is the fix, so it gets a test of its own — swept across every minute of the
    day rather than trusted at whatever minute the suite happens to run.

    This is the assertion the old hardcoded "08:00" would have failed for 480 of these 1,440
    minutes, and passing it at 09:00 is exactly why nobody noticed.
    """
    day = datetime(2026, 8, 29)
    for minute in range(24 * 60):
        now = day + timedelta(minutes=minute)
        sent = _past_time(now)
        hh, mm = (int(x) for x in sent.split(":"))
        claimed = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # The server's own rule: refused when the claimed time is past the company clock, and it
        # always stamps the punch with TODAY's date, so the comparison is same-day.
        assert claimed <= now, (
            "at %s the helper offered %s, which the server would refuse as the future"
            % (now.strftime("%H:%M"), sent))


def _checkin(api, tok, **body):
    body.setdefault("time", _past_time())
    return api("POST", "/api/attendance/checkin", tok, body)


def _rows(emp_id):
    return db.list_attendance(emp_id=emp_id) or []


def _clear(emp_id):
    """There is no db.delete_attendance — attendance rows are removed directly. Checked, not assumed:
    inventing a helper is how a test ends up ERRORING in setup and being counted as passing."""
    conn = db.get_conn()
    conn.execute("DELETE FROM attendance WHERE emp_id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ── the reason is required, and its absence writes NOTHING ──────────────────────────────────────
def test_away_from_site_without_a_reason_is_refused(api, tokens):
    eid = EMP
    _clear(eid)
    try:
        st, r = _checkin(api, tokens["management"], loc=AWAY)
        assert st == 400, r
        assert "not at the site" in (r.get("error") or "").lower()
        assert _rows(eid) == [], "the punch was written anyway — the guard only pretended to refuse"
    finally:
        _clear(eid)


def test_a_blank_or_trivial_reason_is_not_a_reason(api, tokens):
    eid = EMP
    for junk in ("", "   ", "x", "ok"):
        _clear(eid)
        st, _ = _checkin(api, tokens["management"], loc=AWAY, awayReason=junk)
        assert st == 400, "%r was accepted as an explanation" % junk
    _clear(eid)


# ── with a reason it goes through, and the reason is STORED ─────────────────────────────────────
def test_a_reason_lets_the_punch_through_and_is_kept(api, tokens):
    eid = EMP
    _clear(eid)
    try:
        st, r = _checkin(api, tokens["management"], loc=AWAY,
                         awayReason="At the Mega Lifesciences gate, zone not registered yet")
        assert st == 200, r
        rows = _rows(eid)
        assert len(rows) == 1
        assert "Mega Lifesciences" in (rows[0].get("away_reason") or ""), \
            "the reason was demanded and then thrown away, which is worse than not asking"
    finally:
        _clear(eid)


# ── "we could not tell" is not a finding about a person ─────────────────────────────────────────
def test_gps_unverified_is_never_asked_to_explain_itself(api, tokens):
    eid = EMP
    _clear(eid)
    try:
        st, r = _checkin(api, tokens["management"], loc=UNVER)
        assert st == 200, "a poor GPS fix must not stop somebody recording the day they worked"
        assert len(_rows(eid)) == 1
    finally:
        _clear(eid)


def test_an_in_zone_punch_is_untouched(api, tokens):
    eid = EMP
    _clear(eid)
    try:
        st, _ = _checkin(api, tokens["management"], loc=INZONE)
        assert st == 200
        rows = _rows(eid)
        assert len(rows) == 1 and not rows[0].get("away_reason")
    finally:
        _clear(eid)


# ── the reason is free text from a phone, so treat it as hostile ────────────────────────────────
def test_the_reason_is_sanitised_and_bounded(api, tokens):
    eid = EMP
    _clear(eid)
    try:
        st, _ = _checkin(api, tokens["management"], loc=AWAY,
                         awayReason="<img src=x onerror=alert(1)> at the " + ("A" * 500))
        assert st == 200
        stored = _rows(eid)[0].get("away_reason") or ""
        assert "<" not in stored and ">" not in stored, "markup reached storage"
        assert len(stored) <= 300, "unbounded free text: %d chars" % len(stored)
    finally:
        _clear(eid)
