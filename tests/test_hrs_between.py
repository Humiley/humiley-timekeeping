"""db._hrs_between — the one function that decides how long somebody worked.

It is called from three places (db.clock_out, db.generate_attendance, and the amendment path at
app.py:5354/5363), so it has to be right on its own rather than only behind the check-out endpoint's
guards.

The defect these lock down: the +24h wrap was applied only when the time-of-day subtraction came out
NEGATIVE. That is correct for a same-day punch and correct for a genuine night shift (20:00 -> 04:00
subtracts to -960), but wrong for every overnight case where the second time is LATER than the
first — a forgotten check-out noticed the next afternoon. 08:00 -> 17:00 across a night is 33 hours,
and it was reported as nine.
"""
import db


# ── same day ─────────────────────────────────────────────────────────────────────────────────────

def test_an_ordinary_day():
    assert db._hrs_between("08:00", "17:00") == "9h 00m"


def test_minutes_are_kept_and_zero_padded():
    assert db._hrs_between("08:15", "17:05") == "8h 50m"
    assert db._hrs_between("08:00", "08:05") == "0h 05m"


def test_a_same_day_checkout_before_the_checkin_is_refused_not_wrapped():
    """Without overnight=True this is not a night shift, it is a bad record — and silently adding
    24 hours to it would invent a day."""
    assert db._hrs_between("17:00", "08:00") == ""


# ── across midnight ──────────────────────────────────────────────────────────────────────────────

def test_a_genuine_night_shift():
    assert db._hrs_between("20:00", "04:00", overnight=True) == "8h 00m"
    assert db._hrs_between("22:00", "06:00", overnight=True) == "8h 00m"
    assert db._hrs_between("18:00", "00:30", overnight=True) == "6h 30m"


def test_an_overnight_span_is_wrapped_whatever_the_sign():
    """THE FIX. The wrap used to depend on the subtraction being negative, so a forgotten check-out
    closed the next AFTERNOON reported as a short day instead of the impossible one it is. The
    check-out endpoint refuses anything over 16h — but it can only refuse what it is told."""
    assert db._hrs_between("08:00", "17:00", overnight=True) == "33h 00m"
    assert db._hrs_between("08:00", "08:20", overnight=True) == "24h 20m"


def test_exactly_twenty_four_hours_is_twenty_four_not_zero():
    assert db._hrs_between("08:00", "08:00", overnight=True) == "24h 00m"


def test_it_never_reports_more_than_one_wrap():
    """A record can only be one night old on this path; two wraps would be arithmetic nobody meant."""
    for a, b in (("00:00", "23:59"), ("08:00", "07:59")):
        h = int(db._hrs_between(a, b, overnight=True).split("h")[0])
        assert h < 48, (a, b, h)


# ── rubbish in ───────────────────────────────────────────────────────────────────────────────────

def test_unparseable_times_give_an_empty_string_not_a_number():
    """An empty string is rendered as a dash. A zero would read as a day somebody worked nothing."""
    for a, b in (("", "17:00"), ("08:00", ""), ("oops", "17:00"), (None, "17:00"), ("08:00", None)):
        assert db._hrs_between(a, b) == "", (a, b)
