# -*- coding: utf-8 -*-
"""A headcount that could not be read is stated, not silently counted as something else.

`_num` turns "tbc" into 0 and -4 into -4, and its docstring said both were "reported by warnings()
rather than silently priced". They were not — `warnings()` covered orphans, percentages, dates,
safety, photos and the logo, and nothing else. So a SharePoint column reading "tbc" became zero
people on a document the client reads every morning, which is the exact failure the module says it
exists to prevent.

The site FORM cannot produce either: the server refuses a non-number and anything outside
0..100000 before it is stored. The SYNC can, because that column is typed by whoever built the
SharePoint list and merely read by us. Both feed the same report, which is why the check belongs on
the report rather than on the form.
"""
import daily_report as dr

CON = {"mgmtRoles": ["Site Manager", "Supervisor"], "workerTrades": ["HVAC"],
       "safetyChecklist": ["X"], "logo": "data:image/png;base64,x"}
PRJ = {"startDate": "2025-11-14", "endDate": "2027-04-28"}


def _warn(rep):
    return [w["msg"] for w in dr.warnings(PRJ, CON, rep, photos=[{"id": 1}])]


def test_text_where_a_number_belongs_is_named():
    msgs = _warn({"date": "2026-09-01", "mgmt": {"Site Manager": "tbc"}})
    hit = [m for m in msgs if "Site Manager" in m and "not a number" in m]
    assert hit, "a headcount of 'tbc' became zero without a word: %s" % msgs
    assert "counted as 0" in hit[0], "the reader is not told what it became: %r" % hit[0]


def test_a_negative_headcount_is_named():
    msgs = _warn({"date": "2026-09-01", "mgmt": {"Supervisor": -4}})
    hit = [m for m in msgs if "Supervisor" in m and "below zero" in m]
    assert hit, "a negative headcount printed with no warning: %s" % msgs


def test_the_raw_value_is_quoted_so_it_can_be_found_in_sharepoint():
    """"Not a number" sends somebody to a list of forty rows. The value they are looking for sends
    them to the cell."""
    msgs = _warn({"date": "2026-09-01", "workers": {"HVAC": "approx 12"}})
    assert any("approx 12" in m for m in msgs), "the offending value is not quoted: %s" % msgs


def test_a_good_headcount_says_nothing():
    """The warning list is read. One that cries wolf on every report is one nobody reads."""
    msgs = _warn({"date": "2026-09-01", "mgmt": {"Site Manager": 3, "Supervisor": 5},
                  "workers": {"HVAC": 40}})
    assert not [m for m in msgs if "not a number" in m or "below zero" in m], msgs


def test_zero_and_blank_are_not_complaints():
    """Zero is a real answer — nobody on site today. Blank is a section not filled in, which the
    safety and photo warnings already cover; complaining twice would train people to skim."""
    msgs = _warn({"date": "2026-09-01", "mgmt": {"Site Manager": 0, "Supervisor": ""}})
    assert not [m for m in msgs if "not a number" in m or "below zero" in m], msgs


def test_an_unreadable_value_under_an_UNKNOWN_column_is_still_named():
    """It is both an orphan and unreadable. The orphan warning says people are missing from the
    total; this one says the figure itself cannot be trusted. Losing the second because of the first
    is how a bad cell hides behind a lesser complaint."""
    msgs = _warn({"date": "2026-09-01", "mgmt": {"Quantity Surveyor": "two"}})
    assert any("Quantity Surveyor" in m and "not a number" in m for m in msgs), msgs


def test_the_helper_reports_in_column_order_then_orphans():
    got = dr.unreadable_counts({"Supervisor": "x", "Site Manager": "y", "Zzz": "w"},
                               ["Site Manager", "Supervisor"])
    assert [c for c, _r, _w in got] == ["Site Manager", "Supervisor", "Zzz"], got
