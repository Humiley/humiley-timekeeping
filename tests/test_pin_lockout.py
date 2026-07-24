"""E-sign PIN brute-force lockout (db.verify_pin) — a security control that gates signing.

verify_pin returns (ok, reason). After PIN_LOCK_THRESHOLD (5) consecutive wrong PINs the account is
locked for PIN_LOCK_SECONDS, and even the CORRECT PIN is refused with reason 'locked' until it expires.
A correct PIN before the threshold resets the fail counter. (Depends on `base_url` only to init the DB.)
"""
import db


def test_no_pin_is_reported_not_accepted(base_url):
    ok, reason = db.verify_pin("HML-EDT", "1234")   # this employee never enrolled a PIN
    assert ok is False and reason == "no_pin", reason


def test_correct_pin_verifies(base_url):
    db.set_pin("HML-MGR", "2468")
    ok, reason = db.verify_pin("HML-MGR", "2468")
    assert ok is True, reason


def test_five_wrong_pins_lock_the_account(base_url):
    db.set_pin("HML-STF", "1357")
    assert db.verify_pin("HML-STF", "1357")[0] is True          # baseline: correct works, resets counter
    for i in range(db.PIN_LOCK_THRESHOLD):
        assert db.verify_pin("HML-STF", "0000")[0] is False, i  # 5 wrong attempts
    # Now locked: even the CORRECT pin is refused with 'locked'.
    ok, reason = db.verify_pin("HML-STF", "1357")
    assert ok is False and reason == "locked", reason


def test_a_correct_pin_resets_the_fail_counter_before_lockout(base_url):
    db.set_pin("HML-OTH", "9753")
    for _ in range(db.PIN_LOCK_THRESHOLD - 1):     # 4 wrong (one short of the threshold)
        db.verify_pin("HML-OTH", "0000")
    assert db.verify_pin("HML-OTH", "9753")[0] is True   # correct -> resets counter
    # Four MORE wrong attempts must NOT lock (counter was reset), and the correct pin still works.
    for _ in range(db.PIN_LOCK_THRESHOLD - 1):
        db.verify_pin("HML-OTH", "0000")
    ok, reason = db.verify_pin("HML-OTH", "9753")
    assert ok is True, reason
