"""The Daily Report's arithmetic, measured against the two reports the client already receives.

Every figure asserted here was read off one of these two files:

    DailyReport_Mega_Taikisha_09.01.2026.pdf   (10 pages)
    DailyReport_Mega_Newtecons_09.02.2026.pdf  (10 pages)

That is the point of the file. This module reproduces a report somebody is already reading every
morning, so the test that matters is not "does the code do what the code says" — it is "does the
number on the screen match the number on the page the client has in their hand". A test written
from the implementation would agree with a wrong implementation.
"""
import pytest

import daily_report as dr


# The masthead facts, identical on both files.
PROJECT = {"name": "Mega Lifesciences", "location": "Nhon Trach Industrial Park - Dong Nai",
           "investor": "Mega Lifesciences PCL",
           "consultant": "Newtecons JSC / Taikisha Vietnam Inc",
           "pmConsultant": "Humiley Vietnam Co., Ltd",
           "startDate": "2025-11-14", "endDate": "2027-04-28"}

# Taikisha's own column sets — page 2 of its file. Newtecons' are different, which is the whole
# reason the columns live on the contractor rather than in this module.
TAIKISHA = {
    "id": "C-TAI", "name": "Taikisha", "projectId": "P-MEGA",
    "mgmtRoles": ["Admin", "Cad Staff", "Project Manager Electrical", "Project Manager Mechanical",
                  "Safety man", "Site Manager", "Storage man", "Supervisor"],
    "workerTrades": ["Electrical Works", "Fire Fighting Works", "HVAC", "Other Works",
                     "Plumbing Works"],
    "categories": ["Electrical Works", "Fire Fighting Works", "HVAC Works", "Other Works",
                   "Plumbing Works", "Utility Works"],
}
NEWTECONS = {
    "id": "C-NEW", "name": "Newtecons", "projectId": "P-MEGA",
    "mgmtRoles": ["Design Coordination", "HSSE Supervisor", "Office Manger", "Project Manager",
                  "QAQC Supervisor", "Quantity Surveyor", "Secretary", "Site Manager",
                  "Supervisor Engineer"],
    "workerTrades": ["Finishing", "Infrastructure", "Steel structure", "Structure", "Surveying",
                     "Temporary electricity and water"],
    "categories": ["Architectural Finishing Works", "Civil Structure Works", "External Works"],
}

# Page 2 of the Taikisha file: 0+7+0+0+0+1+0+5 = 13 management, 17+10+43+0+21 = 91 workers.
TAI_0901 = {
    "contractorId": "C-TAI", "date": "2026-09-01",
    "weather": {"morning": "Sunny", "afternoon": "Sunny", "evening": "Sunny",
                "avgTemp": "30", "rainHours": "1"},
    "mgmt": {"Admin": 0, "Cad Staff": 7, "Project Manager Electrical": 0,
             "Project Manager Mechanical": 0, "Safety man": 0, "Site Manager": 1,
             "Storage man": 0, "Supervisor": 5},
    "workers": {"Electrical Works": 17, "Fire Fighting Works": 10, "HVAC": 43,
                "Other Works": 0, "Plumbing Works": 21},
}
# The seven bars under it: management 17,17,18,20,3,14,13 and workers 104,120,120,111,21,74,91.
TAI_BARS = [("2026-08-26", 17, 104), ("2026-08-27", 17, 120), ("2026-08-28", 18, 120),
            ("2026-08-29", 20, 111), ("2026-08-30", 3, 21), ("2026-08-31", 14, 74)]


def _history():
    """The six earlier days the Taikisha bar charts show, plus the day itself."""
    out = []
    for d, m, w in TAI_BARS:
        out.append({"contractorId": "C-TAI", "date": d,
                    "mgmt": {"Supervisor": m}, "workers": {"HVAC": w}})
    out.append(TAI_0901)
    return out


# ── the masthead ─────────────────────────────────────────────────────────────────────────────────
def test_total_construction_duration_matches_the_printed_report():
    """"Total Construction Duration (Days): 530" — page 1 of both files."""
    assert dr.total_duration_days("2025-11-14", "2027-04-28") == 530


def test_duration_to_date_matches_both_printed_reports():
    """"Construction Duration to Date (Days)" — 292 on the 1st, 293 on the 2nd.

    The two counts differ in convention (see the module docstring of daily_report). Both files are
    asserted because one alone could be matched by an off-by-one in either direction.
    """
    assert dr.elapsed_duration_days("2025-11-14", "2026-09-01") == 292
    assert dr.elapsed_duration_days("2025-11-14", "2026-09-02") == 293


def test_the_two_durations_really_are_counted_differently():
    """Guards the decision itself, not just the two numbers.

    Somebody tidying this "inconsistency" into one convention would move a headline figure on a
    document the client reads daily. If that is ever done deliberately, this test is where it gets
    argued — and it fails loudly rather than shifting a number in silence.
    """
    span_total = dr.total_duration_days("2026-01-01", "2026-01-31")
    span_elapsed = dr.elapsed_duration_days("2026-01-01", "2026-01-31")
    assert (span_total, span_elapsed) == (30, 31)


def test_a_missing_project_date_says_it_does_not_know():
    """None, not 0. A report printing "Total Construction Duration (Days): 0" over a project with
    no end date on it states something false with complete confidence."""
    assert dr.total_duration_days("2025-11-14", "") is None
    assert dr.elapsed_duration_days("", "2026-09-01") is None


def test_a_report_dated_before_the_start_does_not_go_negative():
    assert dr.elapsed_duration_days("2026-09-01", "2026-08-01") == 0


# ── headcount ────────────────────────────────────────────────────────────────────────────────────
def test_management_and_worker_totals_match_the_printed_tables():
    """13 and 91 — the two Total cells on page 2 of the Taikisha file."""
    assert dr.manpower_row(TAI_0901["mgmt"], TAIKISHA["mgmtRoles"])["total"] == 13
    assert dr.manpower_row(TAI_0901["workers"], TAIKISHA["workerTrades"])["total"] == 91


def test_the_newtecons_tables_have_different_columns_and_still_total_correctly():
    """Page 2 of the Newtecons file: 1+2+1+1+1+1+1+1+4 = 13, and 30+0+0+52+4+0 = 86."""
    rep = {"mgmt": {"Design Coordination": 1, "HSSE Supervisor": 2, "Office Manger": 1,
                    "Project Manager": 1, "QAQC Supervisor": 1, "Quantity Surveyor": 1,
                    "Secretary": 1, "Site Manager": 1, "Supervisor Engineer": 4},
           "workers": {"Finishing": 30, "Infrastructure": 0, "Steel structure": 0,
                       "Structure": 52, "Surveying": 4, "Temporary electricity and water": 0}}
    assert dr.manpower_row(rep["mgmt"], NEWTECONS["mgmtRoles"])["total"] == 13
    assert dr.manpower_row(rep["workers"], NEWTECONS["workerTrades"])["total"] == 86


def test_a_headcount_under_a_deleted_column_is_not_in_the_total_and_is_not_lost():
    """The failure this guards: somebody removes "Storage man" from the contractor's columns and
    the six storemen keep being added to a total printed under a table they do not appear in.

    They must leave the total (it has to equal the visible cells) AND be reported, because a
    number that silently vanishes is how the report starts disagreeing with the site.
    """
    row = dr.manpower_row({"Cad Staff": 7, "Storage man": 6},
                          ["Cad Staff"])                      # Storage man no longer a column
    assert row["total"] == 7
    assert row["orphanTotal"] == 6
    assert [o["col"] for o in row["orphans"]] == ["Storage man"]
    said = " ".join(w["msg"] for w in dr.warnings(
        PROJECT, {"mgmtRoles": ["Cad Staff"], "workerTrades": []},
        {"date": "2026-09-01", "mgmt": {"Cad Staff": 7, "Storage man": 6}}))
    assert "Storage man" in said and "6" in said


def test_a_cell_that_is_not_a_number_counts_as_nobody():
    assert dr.manpower_row({"Cad Staff": "tbc", "Supervisor": "5"}, ["Cad Staff", "Supervisor"])["total"] == 5


# ── the delta arrows ─────────────────────────────────────────────────────────────────────────────
def test_the_delta_arrows_match_the_printed_kpi_cards():
    """Page 1 of the Taikisha file: "13 (▼ 1)" and "91 (▲ 17)"."""
    h = _history()
    m = dr.manpower_delta(h, "C-TAI", "2026-09-01", "mgmt")
    w = dr.manpower_delta(h, "C-TAI", "2026-09-01", "workers")
    assert (m["n"], m["dir"], m["by"]) == (13, "down", 1)
    assert (w["n"], w["dir"], w["by"]) == (91, "up", 17)


def test_no_change_reads_as_flat_not_as_a_rise():
    """Page 1 of the Newtecons file prints "13 (- 0)" — no arrow."""
    h = [{"contractorId": "C", "date": "2026-09-01", "mgmt": {"a": 13}, "workers": {}},
         {"contractorId": "C", "date": "2026-09-02", "mgmt": {"a": 13}, "workers": {}}]
    assert dr.manpower_delta(h, "C", "2026-09-02", "mgmt")["dir"] == "flat"


def test_the_delta_compares_against_the_last_day_reported_not_yesterday():
    """A site that does not report on Sunday must not show Monday as a rise from nothing.

    This is the bug a naive `date - 1 day` lookup produces: no report yesterday, so `was` is 0, so
    every Monday prints a triumphant "(▲ 91)". The comparison walks back to the last day anybody
    counted heads, and says how far back it had to look.
    """
    h = [{"contractorId": "C", "date": "2026-08-28", "mgmt": {}, "workers": {"HVAC": 90}},
         {"contractorId": "C", "date": "2026-08-31", "mgmt": {}, "workers": {"HVAC": 91}}]
    d = dr.manpower_delta(h, "C", "2026-08-31", "workers")
    assert (d["dir"], d["by"], d["prevDate"], d["sinceDays"]) == ("up", 1, "2026-08-28", 3)


def test_the_very_first_report_claims_no_movement():
    h = [{"contractorId": "C", "date": "2026-09-01", "mgmt": {}, "workers": {"HVAC": 91}}]
    d = dr.manpower_delta(h, "C", "2026-09-01", "workers")
    assert (d["n"], d["dir"], d["by"]) == (91, "none", 0)


def test_another_contractors_headcount_never_reaches_this_card():
    """Both contractors report the same days on the same project. A delta that ignored the
    contractor would compare Taikisha's 91 against Newtecons' 86 and print a fall of five."""
    h = [{"contractorId": "C-TAI", "date": "2026-08-31", "mgmt": {}, "workers": {"HVAC": 74}},
         {"contractorId": "C-NEW", "date": "2026-08-31", "mgmt": {}, "workers": {"Structure": 93}},
         {"contractorId": "C-TAI", "date": "2026-09-01", "mgmt": {}, "workers": {"HVAC": 91}}]
    assert dr.manpower_delta(h, "C-TAI", "2026-09-01", "workers")["by"] == 17


# ── the seven-day bars ───────────────────────────────────────────────────────────────────────────
def test_the_seven_day_series_matches_the_printed_bar_charts():
    s = dr.manpower_series(_history(), "C-TAI", "2026-09-01")
    assert [x["date"] for x in s] == ["2026-08-26", "2026-08-27", "2026-08-28", "2026-08-29",
                                      "2026-08-30", "2026-08-31", "2026-09-01"]
    assert [x["mgmt"] for x in s] == [17, 17, 18, 20, 3, 14, 13]
    assert [x["workers"] for x in s] == [104, 120, 120, 111, 21, 74, 91]


def test_a_day_with_no_report_is_a_gap_not_a_zero():
    """"Nobody reported" and "nobody came" are different facts and must not draw the same bar."""
    h = [{"contractorId": "C", "date": "2026-09-01", "mgmt": {"a": 5}, "workers": {}}]
    s = dr.manpower_series(h, "C", "2026-09-02", days=2)
    assert [x["mgmt"] for x in s] == [5, None]
    assert [x["reported"] for x in s] == [True, False]


# ── grouped tables ───────────────────────────────────────────────────────────────────────────────
def test_work_progress_groups_in_the_contractors_own_category_order():
    rows = [{"category": "Plumbing Works", "item": "b"}, {"category": "Electrical Works", "item": "a"}]
    got = [g["category"] for g in dr.progress_rows(rows, TAIKISHA["categories"])]
    assert got == ["Electrical Works", "Plumbing Works"]


def test_a_category_nobody_configured_still_appears():
    """Renaming a category in SharePoint must not delete that day's work from the report."""
    rows = [{"category": "Facade Works", "item": "x"}, {"category": "Electrical Works", "item": "a"}]
    got = [g["category"] for g in dr.progress_rows(rows, TAIKISHA["categories"])]
    assert got == ["Electrical Works", "Facade Works"]


def test_zero_percent_and_unanswered_are_different_answers():
    """Page 4 of both files prints "0%" against items that did not move today. That is a real
    answer and must not render as the dash reserved for a question nobody filled in."""
    g = dr.progress_rows([{"category": "E", "item": "a", "daily": "0", "accum": "85"},
                          {"category": "E", "item": "b", "daily": "", "accum": ""}])[0]
    by_item = {r["item"]: r for r in g["rows"]}
    assert by_item["a"]["daily"] == 0
    assert by_item["b"]["daily"] is None


def test_all_four_document_groups_print_every_day():
    """Page 8 of both files: four headings, each with "None" under it. The empty line is the
    point — it separates "nothing was issued" from "this section was skipped"."""
    groups = dr.document_rows([])
    assert [g["group"] for g in groups] == list(dr.DOC_GROUPS)
    assert all(g["empty"] for g in groups)


def test_a_document_row_lands_under_the_group_it_names():
    groups = {g["group"]: g for g in dr.document_rows(
        [{"group": "7.3", "item": "Duct material submission", "docCode": "MS-014"}])}
    assert groups["7.3- Material Submission"]["rows"][0]["docCode"] == "MS-014"
    assert groups["7.1- Construction Shop Drawings"]["empty"]


# ── safety ───────────────────────────────────────────────────────────────────────────────────────
def test_the_shipped_safety_list_is_the_eleven_checks_on_the_printed_report():
    assert len(dr.SAFETY_DEFAULTS) == 11
    assert dr.safety_rows({}, None)[0]["item"] == "Barricade & Warning Sign Check"


def test_an_unanswered_safety_check_is_not_a_passed_one():
    """The most dangerous default in the whole module. Page 10 shows eleven green ticks, and
    defaulting the tick on would produce that page for a day nobody walked the site."""
    rows = dr.safety_rows({"Housekeeping Inspection": "Yes"}, None)
    by = {r["item"]: r["status"] for r in rows}
    assert by["Housekeeping Inspection"] == "yes"
    assert by["PPE Compliance Inspection"] == "unanswered"
    said = " ".join(w["msg"] for w in dr.warnings(
        PROJECT, TAIKISHA, {"date": "2026-09-01", "safety": {"Housekeeping Inspection": "Yes"}}))
    assert "safety check" in said and "not answered" in said


def test_a_safety_answer_for_a_check_not_on_the_list_still_prints():
    """The site did a confined-space check on the one day there was a confined space. The
    contractor's configured list has not caught up. Dropping the answer deletes a safety record
    because of a configuration lag — the same rule the orphan headcount follows: surface it."""
    rows = dr.safety_rows({"Confined Space Entry Check": "Yes"}, ["Housekeeping Inspection"])
    by = {r["item"]: r for r in rows}
    assert by["Confined Space Entry Check"]["status"] == "yes"
    assert by["Confined Space Entry Check"]["extra"] is True
    assert by["Housekeeping Inspection"]["extra"] is False


@pytest.mark.parametrize("given,want", [
    (True, "yes"), ("Yes", "yes"), ("có", "yes"), ("1", "yes"),
    (False, "no"), ("No", "no"), ("không", "no"),
    ("N/A", "na"), ("", "unanswered"), (None, "unanswered")])
def test_the_form_answers_the_site_actually_submits_are_understood(given, want):
    assert dr.safety_rows({"X": given}, ["X"])[0]["status"] == want


# ── the Gantt ────────────────────────────────────────────────────────────────────────────────────
def test_a_gantt_group_states_its_duration_and_does_not_invent_a_percentage():
    """Page 5 prints "34 days" beside a rolled-up category, never an averaged percentage.

    Averaging is the tempting bug: a category holding a 200-day run at 98% and a 3-day fixing at
    10% is not 54% complete, and claiming so on a client report is worse than saying nothing.
    """
    g = dr.gantt([{"category": "HVAC Works", "item": "a", "start": "2026-08-11",
                   "finish": "2026-09-13", "accum": "97"},
                  {"category": "HVAC Works", "item": "b", "start": "2026-08-25",
                   "finish": "2026-09-05", "accum": "10"}], ["HVAC Works"], "2026-09-01")
    grp = g["groups"][0]
    assert grp["days"] == 34                      # 11 Aug → 13 Sep inclusive
    assert "pct" not in grp
    assert [r["pct"] for r in grp["rows"]] == [97.0, 10.0]   # ordered by progress, as printed


def test_the_gantt_quarter_headings_span_the_work():
    q = dr.gantt([{"category": "E", "item": "a", "start": "2026-07-01", "finish": "2026-11-30"}],
                 None, "2026-09-01")["quarters"]
    assert [x["label"] for x in q] == ["Q3", "Q4"]


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
def test_photos_are_numbered_from_one_within_each_category():
    """Page 7 captions read "HVAC Works - Photo 01" … and restart per category."""
    got = dr.number_photos([{"category": "HVAC Works", "id": "b"},
                            {"category": "Plumbing Works", "id": "c"},
                            {"category": "HVAC Works", "id": "a"}],
                           ["HVAC Works", "Plumbing Works"])
    assert [p["caption"] for p in got] == [
        "HVAC Works - Photo 01", "HVAC Works - Photo 02", "Plumbing Works - Photo 01"]


def test_a_resync_cannot_produce_two_photo_threes():
    """The sequence is assigned here, never trusted from the form: a phone uploading out of order
    or a second sync of the same day would otherwise caption two frames "Photo 03"."""
    same = [{"category": "HVAC Works", "id": "x", "seq": 3},
            {"category": "HVAC Works", "id": "y", "seq": 3}]
    assert [p["seq"] for p in dr.number_photos(same)] == [1, 2]


# ── sorting ──────────────────────────────────────────────────────────────────────────────────────
def test_a_table_sorts_by_its_own_columns():
    rows = [{"item": "Excavator", "qty": "1"}, {"item": "Boom lift", "qty": "3"}]
    assert [r["item"] for r in dr.sort_rows("equipment", rows, "qty", "desc")] == \
        ["Boom lift", "Excavator"]


def test_a_sort_column_from_a_url_cannot_choose_the_expression_it_sorts_by():
    """The sort key arrives from a query string. Only named columns of the named table are
    honoured; anything else leaves the order alone rather than reaching for an attribute."""
    rows = [{"item": "b"}, {"item": "a"}]
    assert dr.sort_rows("equipment", rows, "__class__", "asc") == rows
    assert dr.sort_rows("nosuchtable", rows, "item", "asc") == rows


# ── the assembled model ──────────────────────────────────────────────────────────────────────────
def test_build_produces_every_section_the_report_prints():
    m = dr.build(PROJECT, TAIKISHA, TAI_0901, [], _history(), "2026-09-01")
    assert sorted(m["sections"]) == sorted(dr.SECTION_KEYS)
    assert m["project"]["totalDays"] == 530
    assert m["project"]["elapsedDays"] == 292
    assert m["sections"]["overview"]["workers"]["by"] == 17
    assert m["sections"]["manpower"]["mgmt"]["total"] == 13
    assert m["sections"]["manpower"]["weather"]["avgTemp"] == "30 °C"
    assert m["sections"]["manpower"]["weather"]["rainHours"] == "1 Hours"


def test_the_ten_sections_are_in_the_order_the_report_is_tabbed():
    assert [s["tab"] for s in dr.SECTIONS] == [
        "Overview", "Weather & Manpower", "Equipment-Materials", "Work Progress",
        "Progress Gantt", "Work Plan", "Daily Photos", "Document & Defect", "Inspection",
        "Safety & Recomm."]


# ── pagination ───────────────────────────────────────────────────────────────────────────────────
def test_a_short_report_is_exactly_ten_pages_like_the_printed_one():
    m = dr.build(PROJECT, TAIKISHA, TAI_0901, [], _history(), "2026-09-01")
    pages = dr.paginate(m)
    assert len(pages) == 10
    assert pages[0]["of"] == 10 and pages[-1]["page"] == 10


def test_a_long_table_continues_instead_of_being_cut():
    """The failure this replaces: a section that printed its first thirty rows of forty-seven and
    looked complete. Every row must be on a sheet somewhere, and the footer's "of" must know."""
    big = dict(TAI_0901, progress=[{"category": "Electrical Works", "item": "Item %02d" % i,
                                    "daily": "1", "accum": "5"} for i in range(47)])
    m = dr.build(PROJECT, TAIKISHA, big, [], [big], "2026-09-01")
    pages = dr.paginate(m)
    prog = [p for p in pages if p["section"] == "progress"]
    assert len(prog) == 2 and prog[0]["parts"] == 2
    covered = prog[-1]["rows"][1]
    assert covered == 48                       # 47 items plus the one category heading row
    assert all(p["of"] == len(pages) for p in pages)
    assert len(pages) == 11


def test_the_plans_own_page_numbers_are_internally_consistent():
    """The plan is the screen's estimate, not the printed count — the exporter measures and
    numbers the real sheets. Within the plan, every sheet must still agree on the total, or the
    preview says "about 10 pages" while listing eleven of them."""
    m = dr.build(PROJECT, TAIKISHA, TAI_0901, [], _history(), "2026-09-01")
    pages = dr.paginate(m)
    assert pages[0]["of"] == len(pages)
    assert [p["page"] for p in pages] == list(range(1, len(pages) + 1))


def test_the_body_box_fits_on_an_a4_sheet():
    x, y, w, h = dr.body_box()
    assert x > 0 and y > 0 and w > 0 and h > 0
    assert x + w <= dr.PAGE["w"] and y + h <= dr.PAGE["h"]


# ── what the report admits to ────────────────────────────────────────────────────────────────────
def test_progress_that_went_impossible_is_stated_on_the_report():
    said = " ".join(w["msg"] for w in dr.warnings(PROJECT, TAIKISHA, {
        "date": "2026-09-01",
        "progress": [{"item": "Install PPR pipe", "daily": "30", "accum": "20"},
                     {"item": "Install duct", "accum": "140"},
                     {"item": "Backfill", "start": "2026-09-10", "finish": "2026-09-01"}]}))
    assert "Install PPR pipe moved 30% today but stands at 20% overall" in said
    assert "Install duct is recorded at 140% complete" in said
    assert "Backfill finishes before it starts" in said


def test_a_report_dated_outside_the_programme_is_flagged_not_hidden():
    levels = {w["msg"] for w in dr.warnings(PROJECT, TAIKISHA, {"date": "2030-01-01"})}
    assert any("after the planned completion date" in m for m in levels)


def test_a_contractor_with_no_logo_is_told_once_where_to_set_it():
    said = " ".join(w["msg"] for w in dr.warnings(PROJECT, TAIKISHA, TAI_0901))
    assert "Report Setup" in said
    quiet = " ".join(w["msg"] for w in dr.warnings(
        PROJECT, dict(TAIKISHA, logo="data:image/png;base64,AAAA"), TAI_0901))
    assert "Report Setup" not in quiet


# ── filtering ────────────────────────────────────────────────────────────────────────────────────
def test_the_filter_bar_narrows_by_contractor_month_week_and_date():
    reports = [{"projectId": "P", "contractorId": "C-TAI", "date": "2026-09-01"},
               {"projectId": "P", "contractorId": "C-NEW", "date": "2026-09-01"},
               {"projectId": "P", "contractorId": "C-TAI", "date": "2026-08-11"}]
    assert len(dr.filter_reports(reports, contractor_id="C-TAI")) == 2
    assert len(dr.filter_reports(reports, month="2026-08")) == 1
    assert len(dr.filter_reports(reports, week=dr.week_of("2026-09-01"))) == 2
    assert len(dr.filter_reports(reports, on_date="2026-08-11")) == 1


def test_picking_a_date_overrides_a_month_left_set_from_last_week():
    """What the screen does: choosing a date shows that day, not that day intersected with a stale
    month filter — which would show an empty report and look like a missing submission."""
    reports = [{"contractorId": "C", "date": "2026-09-01"}]
    assert len(dr.filter_reports(reports, month="2026-08", on_date="2026-09-01")) == 1
