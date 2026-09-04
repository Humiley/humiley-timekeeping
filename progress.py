# -*- coding: utf-8 -*-
"""What a schedule row has actually reported — the reading rules, in one place.

Progress on this platform is filed as DATED READINGS in a row's `log`: `{d, pct, by, at, qty?}`.
The Detail Schedule has always done it, and since the Master Schedule's Daily progress table so do
master activities. Three things now have to agree about what those readings mean — the frontend
(`_pdLog`/`_pdReadPct`/`_pdAcc` in templates/index.html), the Power BI feed, and the EOT reschedule
engine — and the way to make three implementations disagree is to write three of them.

These four functions were bi.py's, described there as "the rules, ported from the frontend". They
are here so that qsurvey.py can ask the same question without a third copy appearing; bi.py imports
them and its own module-level names are unchanged. If the frontend's rules change, this file and
`_pdLog`/`_pdReadPct`/`_pdAcc` must change together — the same standing obligation payroll_calc.py
carries against `_payComputed`.

The rules themselves:
  · a reading with a QUANTITY against a planned quantity is a measurement; one with only a
    percentage is an estimate — decided per READING, so a line that gained a quantity halfway
    through keeps the history it already had;
  · accumulated progress on a day is the latest reading ON OR BEFORE it, so back-dating a
    correction works and a reading dated in the future is not "now";
  · the log is user data and arrives malformed — undated entries are dropped, not trusted.
"""


def _pct(v):
    """0-100, integer. Anything unparseable is 0 rather than an exception."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def clean_log(item):
    """Readings oldest-first, ignoring anything undated. This is user data; it arrives malformed."""
    log = (item or {}).get("log")
    if not isinstance(log, list):
        return []
    good = [e for e in log if isinstance(e, dict) and e.get("d")]
    return sorted(good, key=lambda e: str(e.get("d")))


def qty_plan(item):
    """The scheduled quantity — 500 m of pipe, 240 m2 of ceiling. Zero means the line is judged."""
    try:
        q = float((item or {}).get("qtyPlan") or 0)
    except (TypeError, ValueError):
        return 0.0
    return q if q > 0 else 0.0


def read_pct(item, e):
    """One reading as a percentage. A reading carrying a QUANTITY is a measurement; one carrying only
    a percentage is an estimate. Decided per READING so a line that gained a quantity partway keeps
    the history it already had."""
    qp = qty_plan(item)
    q = (e or {}).get("qty")
    if qp > 0 and q not in (None, ""):
        try:
            return _pct(float(q) / qp * 100.0)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return _pct((e or {}).get("pct"))


def accumulated_at(item, day):
    """The latest reading on or before `day`. Zero before the first one."""
    v = 0
    for e in clean_log(item):
        if str(e.get("d")) <= day:
            v = read_pct(item, e)
        else:
            break
    return v


def latest_pct(item):
    """The last reading there is, whatever day it carries — "has the site reported this finished?"

    Deliberately NOT `accumulated_at(item, today)`, for two reasons.

    The first is about the answer. A reading dated in the future is a data-entry error, not a
    prediction, and the two possible readings of it are not symmetric: treating a reported 100 as
    done means an activity is LEFT ALONE, which is visible and harmless; treating it as unreported
    means the EOT engine rewrites the completion date of work somebody has already finished, which
    is silent and destroys the record. When a wrong answer is unavoidable, take the recoverable one.

    The second is about the test. A function that reads the clock has a verdict that changes with
    the date it runs on, and this repo has already had a test go red at 08:00 on a runner in another
    timezone for that reason. Nothing here needs today, so nothing here asks.
    """
    log = clean_log(item)
    return read_pct(item, log[-1]) if log else 0


def has_readings(item):
    """Whether anybody has reported against this row at all — the difference between 0% because
    the work has not started and 0% because nobody has ever been asked."""
    return bool(clean_log(item))


def last_reading_date(item):
    log = clean_log(item)
    return str(log[-1].get("d")) if log else ""


def master_ref(task):
    """How a detail line names the master activity it rolls up into: the WBS code where there is
    one, else the activity name. Mirrors `_pdTaskRef` in templates/index.html."""
    return str((task or {}).get("wbs") or (task or {}).get("name") or "").strip()
