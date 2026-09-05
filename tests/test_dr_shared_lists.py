# -*- coding: utf-8 -*-
"""One set of twelve SharePoint lists can serve every contractor on a project.

Report Setup asks for twelve list URLs per contractor, which reads as "build twelve lists per
contractor" — twelve for Taikisha, twelve for Newtecons, and so on. It is not: every row carries the
contractor it belongs to, `_matches` drops rows naming a different one, and no role is a required
column, so one shared header list can hold the union of everybody's roles. The panel now says this
out loud and offers a control to copy one contractor's links to the next.

That guidance is only safe while the two rules below hold. If a change ever let one contractor's
rows through into another's report, the advice in the panel would quietly become a way to publish
Taikisha's headcount on the report Newtecons sends the client.
"""
import dr_sharepoint as sp

DAY = "2026-09-01"
ROLES = ["Site Manager", "Supervisor"]
TRADES = ["HVAC", "Electrical Works"]


def _row(**kw):
    r = {"date": DAY}
    r.update(kw)
    return r


# ── the filter that makes a shared list safe ─────────────────────────────────────────────────────
def test_a_row_naming_another_contractor_is_excluded():
    assert sp._matches(_row(contractor="Newtecons"), "Taikisha", DAY) is False


def test_a_row_naming_this_contractor_is_kept():
    assert sp._matches(_row(contractor="Taikisha"), "Taikisha", DAY) is True


def test_a_row_with_no_contractor_column_is_kept():
    """The other supported shape: a list dedicated to one contractor, with no contractor column at
    all. A blank must NOT read as 'belongs to somebody else', or the most common single-contractor
    setup imports nothing and says nothing about it."""
    assert sp._matches(_row(), "Taikisha", DAY) is True


def test_the_name_is_matched_loosely_because_a_person_types_it():
    """The column is filled in on a form the portal does not control."""
    for written in ("taikisha", "  Taikisha  ", "TAIKISHA"):
        assert sp._matches(_row(contractor=written), "Taikisha", DAY) is True, \
            "%r did not match" % written


def test_the_day_still_has_to_match():
    """Both filters hold, or a shared list leaks yesterday's figures into today's report."""
    assert sp._matches(_row(contractor="Taikisha"), "Taikisha", "2026-08-31") is False


# ── what makes ONE header list able to serve contractors with different tables ───────────────────
def test_no_role_is_a_required_column():
    """If a role were required, a single shared header list could never satisfy two contractors
    whose tables differ — which is exactly what the panel now tells people to build."""
    assert sp.REQUIRED["header"] == ("date",), \
        "a shared header list stops being possible: %r" % (sp.REQUIRED["header"],)


def test_a_role_belonging_to_another_contractor_is_not_counted_as_this_ones():
    """A shared header list carries the union of everybody's roles. Quantity Surveyor is Newtecons'.
    On Taikisha's report it must not sit in the management table as though it were theirs."""
    rep = sp.split_counts(
        {"_counts": {"Site Manager": 1, "Supervisor": 5, "Quantity Surveyor": 4}}, ROLES, TRADES)
    assert rep["mgmt"] == {"Site Manager": 1, "Supervisor": 5}
    assert "Quantity Surveyor" not in rep["mgmt"]


def test_an_unrecognised_role_is_surfaced_rather_than_dropped():
    """It lands on the workers table, where daily_report.warnings names it as an orphan. Discarding
    it would remove people from a report the client reads, with no trace anywhere."""
    rep = sp.split_counts({"_counts": {"Quantity Surveyor": 4}}, ROLES, TRADES)
    assert rep["workers"].get("Quantity Surveyor") == 4, \
        "an unknown headcount vanished instead of being surfaced"


def test_a_contractors_own_trades_still_reach_the_workers_table():
    rep = sp.split_counts({"_counts": {"HVAC": 43, "Site Manager": 1}}, ROLES, TRADES)
    assert rep["workers"]["HVAC"] == 43
    assert rep["mgmt"]["Site Manager"] == 1
