# -*- coding: utf-8 -*-
"""/api/portal reads its settings in one query, and reads them the same way it used to.

It read 35 settings one at a time — 35 SELECTs and 35 connection hand-outs for a 1.5 KB response —
and it is awaited before the login overlay comes down, so all 35 sat between a user pressing sign-in
and seeing the app.

WHAT THIS COUNTS, AND WHY IT IS NOT MILLISECONDS: a regression in this repo once stayed green in CI
because 4 seconds fits inside a 10 second timeout on an idle runner. Reads scale with the data and
with the code; wall-clock scales with whatever else the box is doing. So the budget below is a count.

The saving is the easy half. The half that can go wrong quietly is AGREEMENT: get_setting returns its
`default` only when the key is ABSENT, so a setting stored as "" or 0 or false must still come back as
"" or 0 or false. Reach for `dict.get(k, d)` carelessly and every falsy stored value silently becomes
the default instead — which for `payerSeparation` would turn a disbursement separation-of-duties rule
back ON, and for `trainedUplift` would change a wage calculation.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_db():
    """Snapshot and restore every `portal_*` setting around each test in this file.

    These are COMPANY-level settings in ONE shared test database — the conftest already carries the
    same fixture for `portal_vat_*` after a test that rewrote the tax treatment made a receivables
    test report the wrong money with nothing wrong in the code it was testing. This file writes
    payerSeparation, trainedUplift and a webhook, so it has to clean up after itself the same way.

    Restores by VALUE where a key existed and DELETES where it did not, because setting a key back to
    None is not the same as it being absent — which is the very distinction these tests are about.
    """
    db.init_db()
    conn = db.get_conn()
    before = {k: v for k, v in conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'portal%'").fetchall()}
    conn.close()
    yield
    conn = db.get_conn()
    now = {k for (k,) in conn.execute("SELECT key FROM settings WHERE key LIKE 'portal%'").fetchall()}
    for k in now - set(before):
        conn.execute("DELETE FROM settings WHERE key = ?", (k,))
    for k, v in before.items():
        conn.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------------------------
# db.get_settings_prefix
# --------------------------------------------------------------------------------------------

def test_prefix_read_agrees_with_get_setting_including_falsy_values():
    """Every key, same value, whichever way it is read."""
    cases = {
        "portal_str": "hello",
        "portal_empty": "",          # falsy, and NOT the same as absent
        "portal_zero_str": "0",
        "portal_zero_num": 0,
        "portal_false": False,
        "portal_null": None,
        "portal_list": [{"key": "a"}],
        "portal_obj": {"x": 1},
    }
    for k, v in cases.items():
        db.set_setting(k, v)

    batch = db.get_settings_prefix("portal_")
    for k, v in cases.items():
        assert k in batch, "%s went missing from the batch read" % k
        assert batch[k] == db.get_setting(k), "%s disagrees between batch and per-key read" % k
        assert batch[k] == v


def test_absent_key_is_absent_rather_than_present_and_null():
    """The distinction the whole `or default` idiom in _portal_get rests on."""
    db.set_setting("portal_present", "")
    batch = db.get_settings_prefix("portal_")
    assert "portal_present" in batch and batch["portal_present"] == ""
    assert "portal_never_set" not in batch


def test_underscore_is_escaped_so_a_foreign_key_cannot_leak_in():
    """`_` is a LIKE wildcard, and the prefix this exists to serve is literally `portal_`.

    Unescaped, `portal_%` also matches `portalXevil`. That is not a crash — it is a caller quietly
    receiving a setting that is not theirs.
    """
    db.set_setting("portal_mine", "mine")
    db.set_setting("portalXevil", "not mine")
    db.set_setting("other", "not mine either")
    batch = db.get_settings_prefix("portal_")
    assert "portal_mine" in batch
    assert "portalXevil" not in batch
    assert "other" not in batch


def test_a_corrupt_row_does_not_take_its_neighbours_down():
    """One unparseable value must not deny every screen that reads the keys beside it."""
    db.set_setting("portal_good", "fine")
    conn = db.get_conn()
    conn.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 ("portal_broken", "{not json"))
    conn.commit()
    conn.close()
    batch = db.get_settings_prefix("portal_")
    assert batch.get("portal_good") == "fine"
    assert "portal_broken" not in batch


# --------------------------------------------------------------------------------------------
# the flag rule, now shared
# --------------------------------------------------------------------------------------------

def test_flag_and_flagval_apply_the_same_rule():
    """_flag reads then judges; _flagval judges a value the caller already holds. One rule.

    The rule itself exists because `bool(get_setting(...))` reads a stored "0" as TRUE — get_setting
    decodes, so "0" arrives as a non-empty string. Splitting the function must not lose that.
    """
    import app
    for stored in ("0", "1", "", "true", "false", "no", "on", 0, 1, True, False, None):
        db.set_setting("portal_probe", stored)
        assert app.Handler._flag("portal_probe") == app.Handler._flagval(stored), stored
    db.set_setting("portal_probe", "0")
    assert app.Handler._flag("portal_probe") is False, 'a stored "0" must read as OFF'


# --------------------------------------------------------------------------------------------
# the endpoint
# --------------------------------------------------------------------------------------------

def _run_portal_get(level="admin"):
    """Call _portal_get and return (response, number of SELECTs it issued)."""
    import app
    counts = {"selects": 0}
    real_row, real_rows = db._row, db._rows

    def row(*a, **k):
        counts["selects"] += 1
        return real_row(*a, **k)

    def rows(*a, **k):
        counts["selects"] += 1
        return real_rows(*a, **k)

    db._row, db._rows = row, rows
    try:
        class Fake(app.Handler):
            def __init__(self):
                pass

        h = Fake()
        h._caller_level = lambda u: level
        cap = {}
        h._json = lambda obj, status=200: cap.setdefault("out", obj)
        h._portal_get({"id": "u1", "email": "a@b.c", "level": level})
        return cap["out"], counts["selects"]
    finally:
        db._row, db._rows = real_row, real_rows


SELECT_BUDGET = 6


def test_the_select_count_does_not_grow_with_the_number_of_settings():
    """The PROPERTY, not a threshold: one query serves the whole namespace, however big it gets.

    A bare `assert selects <= 6` looked fine and could not fail — the shared test database holds only
    a handful of portal_ keys, so even a deliberate one-key-at-a-time implementation stayed under the
    budget. The mutation run caught it. Measure the SLOPE instead: add 40 settings and the count must
    not move, which is false for any per-key read regardless of how many keys happen to exist.
    """
    _, before = _run_portal_get()
    for i in range(40):
        db.set_setting("portal_filler%02d" % i, "x")
    _, after = _run_portal_get()
    assert after == before, (
        "40 more settings cost %d more SELECTs (%d -> %d). A prefix read is one statement whatever "
        "the namespace holds; anything that grows here is reading them one at a time."
        % (after - before, before, after)
    )
    assert after <= SELECT_BUDGET, (
        "/api/portal issued %d SELECTs for its whole response; it used to issue 35" % after
    )


def test_a_setting_stored_falsy_still_comes_back_falsy():
    """`_ps` must return `default` only when the key is ABSENT, never when the value is falsy.

    The first version of this test used "0", and "0" is a TRUTHY Python string — so `x or default`
    returns it either way and the test could not tell a correct implementation from a broken one.
    The mutation run caught that. These keys are chosen because they DISCRIMINATE:

      · announcements is read with no trailing `or`, so a stored [] must survive as [] and not
        become None — an empty list is "the owner cleared the announcements", not "unset";
      · payerSeparation and trainedUplift keep the "0" cases too, because those are the settings
        whose meaning actually matters: silently defaulting payerSeparation back to "1" re-imposes a
        disbursement separation-of-duties rule an owner deliberately turned off.
    """
    db.set_setting("portal_announcements", [])
    db.set_setting("portal_payerSeparation", "0")
    db.set_setting("portal_trainedUplift", "0")
    out, _ = _run_portal_get()
    assert out["announcements"] == [], (
        "a stored empty list came back as %r — falsy is not the same as absent" % out["announcements"]
    )
    assert out["payerSeparation"] == "0", "an OFF switch came back ON"
    assert out["trainedUplift"] == "0", "an OFF switch came back ON"


def test_the_response_is_the_same_as_reading_every_key_singly():
    """The batch read must produce byte-for-byte what the per-key reads produced.

    Rather than pin a snapshot of expected output — which would need editing every time a setting is
    added, and would tell us nothing about the keys nobody thought to list — this re-runs the endpoint
    with get_settings_prefix REPLACED by a per-key implementation built on get_setting, i.e. the old
    behaviour, and compares. Any key where batching changed the answer shows up here.
    """
    db.set_setting("portal_announcements", [{"t": "hi"}])
    db.set_setting("portal_apprSenderHr", "")
    db.set_setting("portal_digestDay", "3")
    db.set_setting("portal_payerSeparation", "0")
    db.set_setting("portal_wageRegion", "II")

    batched, _ = _run_portal_get()

    real_prefix = db.get_settings_prefix

    def one_at_a_time(prefix):
        keys = [r["key"] for r in db._rows("SELECT key FROM settings")]
        out = {}
        for k in keys:
            if k.startswith(prefix):
                out[k] = db.get_setting(k)
        return out

    db.get_settings_prefix = one_at_a_time
    try:
        singly, _ = _run_portal_get()
    finally:
        db.get_settings_prefix = real_prefix

    assert json.dumps(batched, sort_keys=True) == json.dumps(singly, sort_keys=True)


@pytest.mark.parametrize("level", ["staff", "manager", "admin"])
def test_entitlement_still_decides_what_is_sent(level):
    """Batching reads EVERY portal_ key into memory, including ones a caller may not see.

    That is fine as long as the response is still filtered — but it is exactly the kind of change
    where a secret leaks by accident, so assert the filter directly rather than trusting it.
    """
    db.set_setting("portal_teamsWebhook", "https://example.invalid/hook")
    db.set_setting("portal_speakupHandlers", "someone@humiley.com")
    out, _ = _run_portal_get(level=level)
    if level == "staff":
        assert out.get("teamsWebhook") == "", "a posting credential reached a staff account"
    else:
        assert out.get("teamsWebhook") == "https://example.invalid/hook"
    if level == "admin":
        assert out.get("speakupHandlers") == "someone@humiley.com"
    else:
        assert "speakupHandlers" not in out, "the speak-up handler list is an authorization list"
