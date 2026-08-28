# -*- coding: utf-8 -*-
"""A setting has to survive the round trip: form → save → reload → form.

The trained-worker uplift decides whether every employee's minimum wage is checked against
Decree 293/2025 plus 7% (Art. 90 / the company's collective agreement). It broke in three
independent places at once, and each break was invisible:

  1. the browser sent a JSON boolean. _portal_update's loop begins `if not isinstance(v, str):
     continue`, so ticking the box saved NOTHING while the toast said "Saved";
  2. every reader did `bool(db.get_setting("portal_trainedUplift", False))`. get_setting already
     decodes, so a stored "0" comes back as a non-empty string — truthy — and the uplift would have
     been applied across the whole wage register with the switch OFF;
  3. the GET returned "0"/"1" and the form did `!!g(...)`, and `!!"0"` is true, so the box redrew
     ticked no matter what was stored.

Each of the three is a silent wrong answer rather than an error. Together they are why this is a
test about the round trip and not about any one function: only the whole loop can show it.

Handler._flag exists for (2) and says so in its own docstring. It was written and then not used.
"""
import app
import db


def _set(v):
    db.set_setting("portal_trainedUplift", v)


def _flag():
    return app.Handler._flag("portal_trainedUplift")


# ── (2) the reader ──────────────────────────────────────────────────────────────────────────────
def test_the_string_zero_is_off(base_url):
    """The whole of break 2. `bool("0")` is True."""
    _set("0")
    assert _flag() is False, 'a stored "0" turned the uplift ON'


def test_the_string_one_is_on(base_url):
    _set("1")
    assert _flag() is True


def test_a_stored_boolean_is_honoured_either_way(base_url):
    """Settings written before this field was a string still exist in the live database."""
    _set(False)
    assert _flag() is False
    _set(True)
    assert _flag() is True


def test_unset_is_off(base_url):
    """Off is the safe default: applying a 7% uplift nobody asked for would over-state every
    employee's floor and produce findings against people who are correctly paid."""
    db.set_setting("portal_trainedUplift", "")
    assert _flag() is False


def test_no_reader_uses_bool_on_the_raw_setting(base_url):
    """The bug, not its symptom. Any new call site written the obvious way brings it straight back,
    and nothing on screen would look wrong."""
    src = open(app.__file__, encoding="utf-8").read()
    assert 'bool(db.get_setting("portal_trainedUplift"' not in src, \
        'bool() on a decoded setting reads a stored "0" as true'
    # And the helper is actually reached — a test that only forbids the wrong spelling would pass
    # with every call site deleted.
    assert src.count('_flag("portal_trainedUplift")') >= 4, \
        "expected the three consumers plus the GET read-back to go through _flag"


# ── (1) the writer ──────────────────────────────────────────────────────────────────────────────
def test_the_settings_writer_ignores_anything_that_is_not_a_string(base_url):
    """Pinning the constraint the form has to satisfy. This is not a bug to fix — the string-only
    rule is what makes the "did this value change?" comparison below it safe — it is a rule the
    browser has to know about, and did not."""
    src = open(app.__file__, encoding="utf-8").read()
    assert "if not isinstance(v, str):\n                continue" in src, \
        "if this rule moved, the form's contract with it has to be re-checked"


def test_the_form_sends_a_string_and_reads_one_back(base_url):
    """Breaks 1 and 3, from the browser's side. Checked here because there is no other place both
    ends of this round trip are visible at once."""
    html = open("templates/index.html", encoding="utf-8").read()
    assert "trainedUplift: (document.getElementById('portal-trainedUplift') || {}).checked ? '1' : '0'" in html, \
        "a JSON boolean is dropped by _portal_update and the setting never moves"
    assert "String(g('trainedUplift', '0')) === '1'" in html, \
        '`!!g(...)` redraws the box ticked for the string "0"'


# ── the value the whole thing exists to decide ──────────────────────────────────────────────────
def test_the_wage_register_follows_the_switch(base_url):
    """End to end: the switch has to change the answer the register gives, or none of the above
    matters. min_wage.review is asked the same question twice with only this setting moved."""
    import min_wage
    emps = [{"id": "T1", "name": "Test", "status": "Active", "region": "I",
             "trained": True, "salary": 4_960_000}]
    off = min_wage.review(emps, "2026-08-24", default_region="I", apply_trained_uplift=False)
    on = min_wage.review(emps, "2026-08-24", default_region="I", apply_trained_uplift=True)
    assert off != on, ("the uplift flag changes nothing in min_wage.review, so the setting is "
                       "decorative whatever the plumbing does")
