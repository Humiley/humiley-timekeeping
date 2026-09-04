"""How a contractor gets into its own form — and every way it must not.

This is the security boundary of the daily report: a permanent link that goes out by email to a
company with no accounts in the tenant. The link is public by construction — it will be forwarded,
screenshotted and pasted into a group chat — so the tests that matter are the ones about what a
person holding the link still CANNOT do.

`_coll_approve_via_link` in app.py records what happens when that is got wrong: a token in an email
was treated as a credential, and a leaked one let a requester approve their own claim. This module
exists so the daily report does not repeat it, and this file is what holds that true.

Time is passed in everywhere rather than read from the clock, so expiry and lockout are tested by
moving time rather than by sleeping — a test that waited fifteen real minutes would be deleted by
the first person in a hurry.
"""
import pytest

import dr_access as acc


CON = {"id": "C-TAI", "name": "Taikisha",
       "emails": "site@taikisha.example, pm@taikisha.example"}
T0 = 1_800_000_000.0     # a fixed "now"; every test moves relative to it


# ── the link is not a credential ─────────────────────────────────────────────────────────────────
def test_the_token_is_long_enough_that_it_cannot_be_guessed():
    t = acc.new_token()
    assert acc.valid_token(t)
    assert len(t) >= 32                       # 24 random bytes, base64url, unpadded
    assert len({acc.new_token() for _ in range(200)}) == 200


def test_a_token_survives_an_email_client_and_a_url_bar():
    """No padding, no '+' or '/', nothing an email client wraps or a URL escapes — a link that
    arrives broken is a link the site cannot use and nobody can explain."""
    for _ in range(50):
        t = acc.new_token()
        assert acc.valid_token(t)
        assert "=" not in t and "+" not in t and "/" not in t


@pytest.mark.parametrize("bad", ["", "short", "has spaces", "../../etc/passwd",
                                 "a" * 65, "tok+en/x=", None])
def test_a_malformed_token_is_refused_before_anything_looks_it_up(bad):
    assert not acc.valid_token(bad)


def test_the_form_url_is_built_without_a_double_slash():
    assert acc.form_url("https://portal.humiley.com/", "abc") == "https://portal.humiley.com/dr/abc"
    assert acc.form_url("https://portal.humiley.com", "abc") == "https://portal.humiley.com/dr/abc"


# ── who may ask for a code ───────────────────────────────────────────────────────────────────────
def test_only_addresses_on_the_contractors_list_are_authorised():
    assert acc.email_allowed(CON, "site@taikisha.example")
    assert acc.email_allowed(CON, "  SITE@Taikisha.Example ")     # case and space are not identity
    assert not acc.email_allowed(CON, "someone@else.example")
    assert not acc.email_allowed(CON, "")


def test_the_same_address_twice_is_one_address():
    """Otherwise one person holds two independent lockout counters and the attempt limit is worth
    half of what it claims."""
    got = acc.parse_emails("a@x.com, A@X.COM\n a@x.com ; b@y.com")
    assert got == ["a@x.com", "b@y.com"]


def test_rubbish_never_reaches_the_allow_list():
    assert acc.parse_emails("not-an-email, @x.com, a@b, c@d.co") == ["c@d.co"]


def test_the_answer_never_says_whether_the_address_is_authorised():
    """The one sentence returned either way. A different answer for an unknown address turns the
    form into a way of discovering who the site staff are — a list worth having if you want to
    phish somebody into filing a false report."""
    assert "If that address is on this contractor's list" in acc.SENT_MESSAGE
    assert "not" not in acc.SENT_MESSAGE.lower().split("if that address")[0]


# ── the code itself ──────────────────────────────────────────────────────────────────────────────
def test_a_code_is_six_digits_and_keeps_its_leading_zeros():
    seen = {acc.new_code() for _ in range(400)}
    assert all(len(c) == 6 and c.isdigit() for c in seen)
    assert len(seen) > 300, "codes are repeating far more than chance allows"


def test_the_code_is_never_stored_in_the_clear():
    a = acc.issue_code({}, "123456", now=T0)
    blob = repr(a)
    assert "123456" not in blob
    assert a["codeHash"] and a["codeSalt"] and a["codeRounds"] >= 100_000


def test_two_issues_of_the_same_code_do_not_share_a_hash():
    """A per-issue salt. Without it, equal hashes across contractors would say "these two are the
    same code" to anybody who read the table."""
    a = acc.issue_code({}, "123456", now=T0)
    b = acc.issue_code({}, "123456", now=T0)
    assert a["codeHash"] != b["codeHash"]
    assert a["codeSalt"] != b["codeSalt"]


def test_the_right_code_is_accepted_once_and_then_is_gone():
    """Single use. Otherwise a forwarded confirmation email re-authorises a device weeks later."""
    a = acc.issue_code({}, "123456", now=T0)
    ok, why, a2 = acc.check_code(a, "123456", now=T0 + 30)
    assert ok and why == ""
    assert "codeHash" not in a2 and a2["confirmedAt"] == T0 + 30
    ok2, why2, _ = acc.check_code(a2, "123456", now=T0 + 40)
    assert not ok2 and why2 == "none"


def test_a_code_expires_after_fifteen_minutes():
    a = acc.issue_code({}, "123456", now=T0)
    ok, _w, _a = acc.check_code(a, "123456", now=T0 + acc.CODE_TTL - 1)
    assert ok
    a = acc.issue_code({}, "123456", now=T0)
    ok2, why, _a2 = acc.check_code(a, "123456", now=T0 + acc.CODE_TTL + 1)
    assert not ok2 and why == "expired"


def test_asking_for_a_new_code_kills_the_old_one():
    """Two live codes would double the guessing surface for no benefit."""
    a = acc.issue_code({}, "111111", now=T0)
    b = acc.issue_code(a, "222222", now=T0 + 10)
    assert not acc.check_code(b, "111111", now=T0 + 20)[0]
    assert acc.check_code(b, "222222", now=T0 + 20)[0]


# ── the lockout, which is what makes six digits safe ─────────────────────────────────────────────
def test_five_wrong_codes_locks_the_address():
    a = acc.issue_code({}, "123456", now=T0)
    for i in range(acc.CODE_MAX_ATTEMPTS - 1):
        ok, why, a = acc.check_code(a, "000000", now=T0 + i)
        assert not ok and why == "wrong"
        assert acc.attempts_left(a) == acc.CODE_MAX_ATTEMPTS - (i + 1)
    ok, why, a = acc.check_code(a, "000000", now=T0 + 9)
    assert not ok and why == "wrong"
    assert acc.locked_for(a, T0 + 9) > 0
    # and the right code does not work while locked
    ok2, why2, _ = acc.check_code(a, "123456", now=T0 + 10)
    assert not ok2 and why2 == "locked"


def test_the_lockout_also_destroys_the_code():
    """Otherwise waiting out the lockout resumes guessing against the SAME code, and the limit
    becomes five attempts per fifteen minutes forever rather than five attempts per code."""
    a = acc.issue_code({}, "123456", now=T0)
    for i in range(acc.CODE_MAX_ATTEMPTS):
        _ok, _w, a = acc.check_code(a, "000000", now=T0 + i)
    assert "codeHash" not in a
    ok, why, _ = acc.check_code(a, "123456", now=T0 + acc.CODE_LOCKOUT + 10)
    assert not ok and why == "none", "the old code must not still be live after the lockout"


def test_a_lockout_ends_by_itself():
    """The clock runs from the LAST failed attempt, not from the first — so the window is derived
    here rather than assumed. (The first version of this test assumed the first, and was three
    seconds short: it is the code that is right about when a lockout should start.)"""
    a = acc.issue_code({}, "123456", now=T0)
    last = T0
    for i in range(acc.CODE_MAX_ATTEMPTS):
        last = T0 + i
        _ok, _w, a = acc.check_code(a, "000000", now=last)
    assert acc.locked_for(a, last + acc.CODE_LOCKOUT - 1) > 0
    assert acc.locked_for(a, last + acc.CODE_LOCKOUT + 1) == 0
    b = acc.issue_code(a, "654321", now=last + acc.CODE_LOCKOUT + 2)
    ok, _w, _b = acc.check_code(b, "654321", now=last + acc.CODE_LOCKOUT + 3)
    assert ok, "after the lockout a fresh code must work"


def test_the_guess_odds_are_what_the_policy_claims():
    """Stated as a test so a future change to either number has to face the arithmetic: five
    attempts against a six-digit space is 1 in 200,000 per lockout window."""
    space = 10 ** acc.CODE_DIGITS
    assert space / acc.CODE_MAX_ATTEMPTS == 200_000


# ── the send throttle, which protects the mailbox ────────────────────────────────────────────────
def test_three_codes_then_wait():
    a = {}
    for i in range(acc.CODE_MAX_SENDS):
        ok, wait = acc.send_allowed(a, now=T0 + i)
        assert ok and wait == 0
        a = acc.issue_code(a, acc.new_code(), now=T0 + i)
    ok, wait = acc.send_allowed(a, now=T0 + 5)
    assert not ok and wait > 0


def test_the_window_rolls_rather_than_resetting_on_a_boundary():
    """Three requests a minute apart must not become six by waiting for a boundary to pass."""
    a = {}
    for i in range(acc.CODE_MAX_SENDS):
        a = acc.issue_code(a, acc.new_code(), now=T0 + i * 60)
    assert not acc.send_allowed(a, now=T0 + 180)[0]
    # once the OLDEST send falls out of the window, one more is allowed — and only one
    just_after = T0 + acc.CODE_SEND_WINDOW + 1
    assert acc.send_allowed(a, now=just_after)[0]


def test_the_send_history_cannot_grow_without_bound():
    a = {}
    for i in range(500):
        a = acc.record_send(a, now=T0 + i * 1000)
    assert len(a["sends"]) <= acc.CODE_MAX_SENDS * 2


# ── the remembered device ────────────────────────────────────────────────────────────────────────
def _secret():
    return acc.derive_secret("a-server-pepper-value")


def test_a_confirmed_device_is_remembered_and_says_who_it_is():
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "Site@Taikisha.example", now=T0)
    got = acc.verify_session(s, c, now=T0 + 60)
    assert got["contractorId"] == "C-TAI"
    assert got["email"] == "site@taikisha.example"      # normalised, so it matches the allow-list
    assert not got["renew"]


def test_a_session_expires():
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "a@b.co", now=T0)
    assert acc.verify_session(s, c, now=T0 + acc.SESSION_TTL - 10)
    assert acc.verify_session(s, c, now=T0 + acc.SESSION_TTL + 1) is None


def test_a_session_in_daily_use_is_renewed_before_it_lapses():
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "a@b.co", now=T0)
    near = T0 + acc.SESSION_TTL - acc.SESSION_SLIDE + 60
    assert acc.verify_session(s, c, now=near)["renew"] is True


def test_a_tampered_cookie_is_refused():
    """Every field of it: the contractor, the address, the expiry. All three are inside the MAC, so
    editing any of them invalidates the whole thing."""
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "a@b.co", now=T0)
    raw, _dot, mac = c.partition(".")
    import base64
    body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    for edited in (body.replace("C-TAI", "C-NEW"),
                   body.replace("a@b.co", "boss@humiley.com"),
                   body.rsplit("|", 1)[0] + "|" + str(int(T0 + 10 ** 9))):
        forged = base64.urlsafe_b64encode(edited.encode()).decode().rstrip("=") + "." + mac
        assert acc.verify_session(s, forged, now=T0 + 60) is None


def test_the_whole_signature_is_compared_not_a_prefix_of_it():
    """A cookie whose MAC is correct except for its last character must be refused.

    This exists because the tamper test above does NOT catch a weakened comparison. Verified by
    injecting the regression: replacing `hmac.compare_digest(mac, want_b)` with a four-character
    prefix check left every other test in this file green, because editing the BODY changes the
    whole MAC and a prefix check rejects that too. Only a MAC that agrees on its prefix and differs
    later can tell the two implementations apart — so that is what this constructs.
    """
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "a@b.co", now=T0)
    raw, _dot, mac = c.partition(".")
    assert acc.verify_session(s, c, now=T0 + 1), "the unmodified cookie must be valid"
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    for pos in (len(mac) - 1, len(mac) // 2, 4):
        other = next(ch for ch in alphabet if ch != mac[pos])
        bent = mac[:pos] + other + mac[pos + 1:]
        assert acc.verify_session(s, raw + "." + bent, now=T0 + 1) is None, (
            "a signature differing only at position %d was accepted — the comparison is not "
            "looking at the whole of it" % pos)


def test_a_truncated_signature_is_refused():
    """`startswith` is the other easy mistake: a short MAC is a prefix of the right one."""
    s = _secret()
    c = acc.sign_session(s, "C-TAI", "a@b.co", now=T0)
    raw, _dot, mac = c.partition(".")
    for n in (1, 4, 8, len(mac) - 1):
        assert acc.verify_session(s, raw + "." + mac[:n], now=T0 + 1) is None, (
            "a %d-character signature was accepted" % n)


def test_a_cookie_signed_with_another_secret_is_refused():
    a = acc.derive_secret("pepper-one")
    b = acc.derive_secret("pepper-two")
    c = acc.sign_session(a, "C-TAI", "x@y.co", now=T0)
    assert acc.verify_session(b, c, now=T0 + 1) is None


@pytest.mark.parametrize("junk", ["", ".", "x", "x.y", "....", None, "a" * 500])
def test_rubbish_in_the_cookie_never_raises(junk):
    """It arrives from a browser, so it is attacker-controlled. An exception here is a 500 on a
    public endpoint, which is a denial of service anybody can trigger."""
    assert acc.verify_session(_secret(), junk, now=T0) is None


def test_the_signing_key_is_derived_not_reused():
    """So a daily-report cookie can never be replayed against anything else the same pepper signs."""
    pepper = "a-server-pepper-value"
    assert acc.derive_secret(pepper) != pepper.encode("utf-8")
    assert acc.derive_secret(pepper) == acc.derive_secret(pepper)
    assert acc.derive_secret("other") != acc.derive_secret(pepper)


def test_signing_without_a_secret_refuses_rather_than_signing_with_nothing():
    """An empty pepper would produce a valid-looking cookie anybody could forge."""
    for empty in ("", None):
        with pytest.raises(ValueError):
            acc.derive_secret(empty)


# ── what the person is told ──────────────────────────────────────────────────────────────────────
def test_an_expired_code_and_a_code_that_never_existed_read_the_same():
    """Telling them apart tells an attacker whether an address has a code outstanding."""
    assert acc.code_failure_message("expired") == acc.code_failure_message("none")


def test_a_lockout_says_roughly_how_long():
    msg = acc.code_failure_message("locked", wait_s=8 * 60)
    assert "8 minute" in msg
    assert "1 minute" in acc.code_failure_message("locked", wait_s=20)
