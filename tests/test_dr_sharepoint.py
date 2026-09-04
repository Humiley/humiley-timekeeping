"""Reading the Daily Report out of SharePoint, with a fake Graph.

Every function under test takes its HTTP getter as an argument, so the whole path — parse a pasted
URL, resolve the list, match the columns, map the rows, assemble the day — runs here with no
network and no tenant. That is deliberate: the bugs in an integration like this are almost never in
the HTTP, they are in the mapping, and a test that needs a tenant to run is a test nobody runs.

The shapes below are what Graph really returns: `fields` keyed by INTERNAL column names
(`Daily_x0020_Progress`), a separate `columns` collection carrying the display names, and paging
through `@odata.nextLink`.
"""
import pytest

import dr_sharepoint as sp


SITE = "humiley.sharepoint.com"
SITE_ID = "humiley.sharepoint.com,aaaa,bbbb"


def graph(lists=None, columns=None, items=None):
    """A fake Graph. `lists` is [{id,name,displayName}], `columns` is {listId: [...]},
    `items` is {listId: [fields dicts]} — paged two at a time so the paging code is exercised
    rather than merely present."""
    lists = lists or []
    columns = columns or {}
    items = items or {}
    calls = []

    def get(url):
        calls.append(url)
        if url.endswith(":" + "/sites/Mega") or url.endswith(":/sites/Mega"):
            return {"id": SITE_ID}
        if "/lists?" in url:
            return {"value": lists}
        for l in lists:
            if url.endswith("/lists/" + l["id"]):
                return l
            if "/lists/" + l["id"] + "/columns" in url:
                return {"value": columns.get(l["id"], [])}
            if "/lists/" + l["id"] + "/items" in url:
                rows = items.get(l["id"], [])
                page = int((url.split("page=")[1].split("&")[0]) if "page=" in url else 0)
                chunk = rows[page * 2:page * 2 + 2]
                out = {"value": [{"id": str(page * 2 + i + 1), "fields": f}
                                 for i, f in enumerate(chunk)]}
                if len(rows) > (page + 1) * 2:
                    out["@odata.nextLink"] = url.split("&page=")[0] + "&page=%d" % (page + 1)
                return out
        raise AssertionError("fake graph got an unexpected URL: " + url)

    get.calls = calls
    return get


def cols(*pairs):
    return [{"name": n, "title": t} for n, t in pairs]


# ── URLs ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,hint", [
    ("https://humiley.sharepoint.com/sites/Mega/Lists/Daily Work Progress/AllItems.aspx",
     "Daily Work Progress"),
    ("https://humiley.sharepoint.com/sites/Mega/Lists/DailyWorkProgress", "DailyWorkProgress"),
    ("https://humiley.sharepoint.com/sites/Mega/Lists/Daily%20Work%20Progress/AllItems.aspx?viewid=x",
     "Daily Work Progress"),
    ("https://humiley.sharepoint.com/sites/Mega/_layouts/15/listedit.aspx?List=%7B7f1c-2%7D", "7f1c-2"),
])
def test_every_link_an_admin_actually_copies_is_understood(url, hint):
    host, site, got = sp.parse_list_url(url)
    assert (host, site) == (SITE, "/sites/Mega")
    assert got == hint


def test_a_link_that_names_no_list_says_what_to_paste_instead():
    with pytest.raises(ValueError) as e:
        sp.parse_list_url("https://humiley.sharepoint.com/sites/Mega")
    assert "address bar" in str(e.value) or "Lists" in str(e.value)


def test_a_link_to_the_wrong_thing_entirely_is_refused():
    with pytest.raises(ValueError):
        sp.parse_list_url("not a url at all")


# ── resolving ────────────────────────────────────────────────────────────────────────────────────
def test_a_list_is_found_by_its_display_name():
    g = graph(lists=[{"id": "L1", "name": "DailyWorkProgress", "displayName": "Daily Work Progress"}])
    ref = sp.resolve_list(g, "https://humiley.sharepoint.com/sites/Mega/Lists/Daily Work Progress")
    assert ref["list"] == "L1" and ref["listName"] == "Daily Work Progress"


def test_a_list_renamed_after_the_form_was_built_is_still_found_by_its_internal_name():
    """SharePoint freezes the internal name at creation. Matching only on the display name breaks
    the day somebody tidies a title, which is a silent, total loss of that section."""
    g = graph(lists=[{"id": "L1", "name": "DailyWorkProgress", "displayName": "Progress (2026)"}])
    ref = sp.resolve_list(g, "https://humiley.sharepoint.com/sites/Mega/Lists/DailyWorkProgress")
    assert ref["list"] == "L1"


def test_a_missing_list_names_the_lists_that_do_exist():
    """The useful error is not "not found" — it is "not found, and here is what is on the site"."""
    g = graph(lists=[{"id": "L1", "name": "Other", "displayName": "Other List"}])
    with pytest.raises(ValueError) as e:
        sp.resolve_list(g, "https://humiley.sharepoint.com/sites/Mega/Lists/Daily Work Progress")
    assert "Other List" in str(e.value)


# ── column matching ──────────────────────────────────────────────────────────────────────────────
def test_the_real_column_headings_from_the_printed_report_are_matched():
    """The exact headings on page 4: Category, Report Items, Daily Progress (%), Accumulated
    Progress (%), Start Date, Finish Date — plus ReportDate and Contractor."""
    c = cols(("ReportDate", "ReportDate"), ("Contractor", "Contractor"),
             ("Category", "Category"), ("Title", "Report Items"),
             ("Daily_x0020_Progress", "Daily Progress (%)"),
             ("Accum_x0020_Progress", "Accumulated Progress (%)"),
             ("StartDate", "Start Date"), ("FinishDate", "Finish Date"))
    m = sp.automap("progress", c)
    assert m["missing"] == []
    assert m["map"]["item"] == "Title"
    assert m["map"]["daily"] == "Daily_x0020_Progress"
    assert m["map"]["accum"] == "Accum_x0020_Progress"
    assert m["map"]["finish"] == "FinishDate"


def test_the_daily_and_accumulated_percentages_do_not_collide():
    """Both titles contain "Progress". Matching most-specific-first, and claiming a column once,
    is what stops "Daily Progress (%)" being read into the accumulated cell — a swap that would
    print a plausible, entirely wrong report."""
    c = cols(("ReportDate", "ReportDate"), ("Title", "Report Items"),
             ("A", "Accumulated Progress (%)"), ("D", "Daily Progress (%)"))
    m = sp.automap("progress", c)
    assert m["map"]["daily"] == "D" and m["map"]["accum"] == "A"


def test_a_missing_essential_column_is_reported_not_guessed():
    c = cols(("ReportDate", "ReportDate"), ("Category", "Category"))
    m = sp.automap("progress", c)
    assert "item" in m["missing"]


def test_the_columns_nothing_claimed_are_listed_so_a_mismatch_can_be_diagnosed():
    """"We could not find Report Items" is half an answer. "…and your list has Work Description,
    Zone and Foreman on it" is the whole one."""
    c = cols(("ReportDate", "ReportDate"), ("WorkDesc", "Work Description"), ("Zone", "Zone"))
    m = sp.automap("progress", c)
    assert "Work Description" in m["unused"] and "Zone" in m["unused"]


def test_headcount_columns_come_from_the_contractors_own_role_list():
    """Taikisha counts Cad Staff; Newtecons counts Quantity Surveyors. Neither is in this module,
    and adding a role must not need a code change."""
    c = cols(("ReportDate", "ReportDate"), ("CadStaff", "Cad Staff"),
             ("Supervisor", "Supervisor"), ("HVAC", "HVAC"))
    m = sp.automap("header", c, roles=["Cad Staff", "Supervisor"], trades=["HVAC"])
    assert m["roles"] == {"Cad Staff": "CadStaff", "Supervisor": "Supervisor", "HVAC": "HVAC"}


def test_an_admins_correction_beats_the_automatic_match_and_survives_re_detection():
    auto = {"map": {"item": "Title"}, "missing": [], "roles": {}, "unused": []}
    merged = sp.merge_map(auto, {"map": {"item": "WorkDesc"}})
    assert merged["map"]["item"] == "WorkDesc"


@pytest.mark.parametrize("a,b", [
    ("Daily Progress (%)", "daily_progress_%"), ("ReportDate", "Report Date"),
    ("Report_x0020_Items", "Report Items")])
def test_column_names_match_however_sharepoint_spelled_them(a, b):
    assert sp.norm(a) == sp.norm(b)


# ── mapping a row ────────────────────────────────────────────────────────────────────────────────
def test_a_row_maps_onto_the_shape_the_report_prints():
    m = {"map": {"date": "ReportDate", "contractor": "Contractor", "category": "Category",
                 "item": "Title", "daily": "D", "accum": "A", "start": "S", "finish": "F"}}
    row = sp.map_row("progress", {
        "ReportDate": "2026-09-01T00:00:00Z", "Contractor": "Taikisha",
        "Category": "HVAC Works", "Title": "Install ACD pipe at - Zone 1 1FL",
        "D": "0", "A": "84", "S": "2026-08-22", "F": "2026-09-12"}, m)
    assert row["date"] == "2026-09-01"
    assert row["item"] == "Install ACD pipe at - Zone 1 1FL"
    assert (row["daily"], row["accum"]) == ("0", "84")
    assert (row["start"], row["finish"]) == ("2026-08-22", "2026-09-12")


def test_an_unmapped_field_comes_back_blank_and_is_never_invented():
    row = sp.map_row("progress", {"Title": "x"}, {"map": {"item": "Title"}})
    assert row["category"] == "" and row["daily"] == ""


def test_a_lookup_or_person_column_renders_as_the_label_a_human_reads():
    """Graph returns these as objects. Left raw, the table cell prints "{'LookupValue': …}"."""
    row = sp.map_row("progress", {"C": {"LookupValue": "HVAC Works", "LookupId": 3}},
                     {"map": {"category": "C"}})
    assert row["category"] == "HVAC Works"


def test_the_us_date_a_forms_question_emits_is_read_correctly():
    """An en-US tenant hands back "9/1/2026". Refusing it empties the whole day for a reason
    nobody looking at the report could see."""
    row = sp.map_row("progress", {"D": "9/1/2026"}, {"map": {"date": "D"}})
    assert row["date"] == "2026-09-01"


# ── paging ───────────────────────────────────────────────────────────────────────────────────────
def test_every_page_of_a_long_list_is_read():
    """Five rows over three pages. Reading only the first page loses site work silently — the
    report simply shows fewer items than were submitted."""
    g = graph(lists=[{"id": "L1", "name": "P", "displayName": "P"}],
              items={"L1": [{"Title": "row %d" % i} for i in range(5)]})
    got = sp.fetch_items(g, SITE_ID, "L1")
    assert [r["Title"] for r in got] == ["row 0", "row 1", "row 2", "row 3", "row 4"]


def test_a_date_range_is_filtered_at_the_server_when_the_date_column_is_known():
    g = graph(lists=[{"id": "L1", "name": "P", "displayName": "P"}], items={"L1": []})
    sp.fetch_items(g, SITE_ID, "L1", date_field="ReportDate", since="2026-09-01", until="2026-09-01")
    assert any("filter" in u and "ReportDate" in u for u in g.calls)


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
def test_a_forms_upload_answer_is_parsed_rather_than_stored_as_a_url():
    """A file-upload question returns a JSON array. Stored whole it becomes an image src of
    "[{"name":…}]" — a broken frame with no explanation, which is exactly the bug shape to avoid."""
    ref = sp.photo_ref({"P": '[{"name":"IMG_1.jpg","link":"https://x.sharepoint.com/a/IMG_1.jpg"}]'},
                       {"photo": "P"})
    assert ref["kind"] == "share"
    assert ref["url"] == "https://x.sharepoint.com/a/IMG_1.jpg"
    assert ref["name"] == "IMG_1.jpg"


def test_a_hyperlink_column_is_understood():
    ref = sp.photo_ref({"P": {"Url": "https://x.sharepoint.com/a/b.jpg", "Description": "b.jpg"}},
                       {"photo": "P"})
    assert ref["kind"] == "share" and ref["name"] == "b.jpg"


def test_a_photo_row_with_no_file_says_so_instead_of_producing_a_broken_frame():
    assert sp.photo_ref({"P": ""}, {"photo": "P"})["kind"] == "none"
    assert sp.photo_ref({}, {})["kind"] == "none"


def test_a_share_url_is_encoded_the_way_graph_documents():
    assert sp.share_id("https://x/a.jpg").startswith("u!")
    assert "=" not in sp.share_id("https://x/a.jpg")


def test_only_images_come_back_from_a_photo_folder():
    """A folder also holding a method statement PDF must not put it in the photo grid."""
    def g(url):
        return {"value": [
            {"id": "1", "name": "a.jpg", "file": {"mimeType": "image/jpeg"}},
            {"id": "2", "name": "ms.pdf", "file": {"mimeType": "application/pdf"}},
            {"id": "3", "name": "b.HEIC", "file": {"mimeType": "image/heic"}}]}
    got = sp.folder_photos(g, "D1", "Daily Photos/2026-09-01")
    assert [p["name"] for p in got] == ["a.jpg", "b.HEIC"]


# ── the project's own folder ─────────────────────────────────────────────────────────────────────
def test_a_days_files_are_filed_under_contractor_month_and_day():
    """The shape somebody looking for "Taikisha, 1 September" actually browses. A single flat
    folder with a year of site photos in it is a folder nobody opens twice."""
    assert sp.folder_for("Taikisha", "2026-09-01") == "Daily Report/Taikisha/2026-09/2026-09-01"


def test_a_contractor_name_with_a_slash_in_it_does_not_create_two_folders():
    """"Newtecons JSC / Taikisha" would otherwise nest, and SharePoint rejects the rest outright."""
    got = sp.folder_for("Newtecons JSC / Taikisha", "2026-09-02")
    assert got == "Daily Report/Newtecons JSC Taikisha/2026-09/2026-09-02"
    assert got.count("/") == 3


def test_a_date_that_cannot_be_read_yields_no_path_at_all():
    """Rather than a folder called None, which is how a year of photos ends up somewhere nobody
    thinks to look."""
    assert sp.folder_for("Taikisha", "") == ""
    assert sp.folder_for("Taikisha", "not a date") == ""


def test_a_contractor_with_no_name_still_files_somewhere_findable():
    assert sp.folder_for("", "2026-09-01").startswith("Daily Report/Unassigned/")


def test_the_paperclip_route_is_explained_rather_than_silently_empty():
    """Graph cannot read list attachments at any consent level. Saying so, with the two
    arrangements that do work, beats a photo section that is permanently and inexplicably blank."""
    msg = sp.attachment_help()
    assert "document library" in msg and "UPLOADS" in msg


# ── assembly ─────────────────────────────────────────────────────────────────────────────────────
CONTRACTOR = {"id": "C-TAI", "name": "Taikisha", "projectId": "P-MEGA",
              "mgmtRoles": ["Cad Staff", "Site Manager", "Supervisor"],
              "workerTrades": ["Electrical Works", "HVAC", "Plumbing Works"]}


def _pulled():
    return {
        "header": [{"date": "2026-09-01", "contractor": "Taikisha", "weatherMorning": "Sunny",
                    "weatherAfternoon": "Sunny", "weatherEvening": "Sunny", "avgTemp": "30",
                    "rainHours": "1", "notes": "", "_spItemId": "9",
                    "counts": {"Cad Staff": 7, "Site Manager": 1, "Supervisor": 5,
                               "Electrical Works": 17, "HVAC": 43, "Plumbing Works": 21}}],
        "progress": [{"date": "2026-09-01", "contractor": "Taikisha", "category": "HVAC Works",
                      "item": "Install ACD pipe at - Zone 1 1FL", "daily": "0", "accum": "84",
                      "start": "2026-08-22", "finish": "2026-09-12"}],
        "photos": [{"date": "2026-09-01", "contractor": "Taikisha", "category": "HVAC Works",
                    "caption": "", "kind": "daily", "takenAt": "",
                    "ref": {"kind": "share", "url": "https://x/1.jpg", "driveId": "",
                            "itemId": "", "name": "1.jpg"}}],
    }


def test_a_days_lists_assemble_into_one_report_and_its_photos():
    rep, photos, notes = sp.assemble(_pulled(), CONTRACTOR, "2026-09-01")
    rep = sp.split_counts(rep, CONTRACTOR["mgmtRoles"], CONTRACTOR["workerTrades"])
    assert rep["date"] == "2026-09-01" and rep["source"] == "sharepoint"
    assert rep["weather"]["morning"] == "Sunny"
    assert sum(rep["mgmt"].values()) == 13
    assert sum(rep["workers"].values()) == 81
    assert rep["progress"][0]["accum"] == "84"
    assert len(photos) == 1 and photos[0]["spUrl"] == "https://x/1.jpg"


def test_a_headcount_column_matching_neither_list_is_kept_and_surfaced():
    """Not dropped. daily_report.warnings then names it in print; discarding it would remove
    people from the report with no trace at all."""
    pulled = _pulled()
    pulled["header"][0]["counts"]["Scaffolders"] = 4
    rep = sp.split_counts(sp.assemble(pulled, CONTRACTOR, "2026-09-01")[0],
                          CONTRACTOR["mgmtRoles"], CONTRACTOR["workerTrades"])
    assert rep["workers"]["Scaffolders"] == 4
    assert "Scaffolders" not in rep["mgmt"]


def test_another_contractors_rows_are_left_alone_and_counted():
    pulled = _pulled()
    pulled["progress"].append({"date": "2026-09-01", "contractor": "Newtecons",
                               "category": "Civil Structure Works", "item": "Block Q"})
    rep, _photos, notes = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    assert len(rep["progress"]) == 1
    assert any("another contractor" in n["msg"] for n in notes)


def test_a_list_dedicated_to_one_contractor_needs_no_contractor_column():
    """The most common single-contractor setup. A blank contractor cell excluding the row would
    import nothing at all, and the report would look like a day nobody worked."""
    pulled = {"progress": [{"date": "2026-09-01", "contractor": "", "item": "x"}]}
    rep, _p, _n = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    assert len(rep["progress"]) == 1


def test_a_row_with_no_readable_date_is_skipped_and_the_skip_is_stated():
    """Nine dropped rows out of forty must not look like a quiet day."""
    pulled = {"progress": [{"date": "", "contractor": "Taikisha", "item": "x"},
                           {"date": "2026-09-01", "contractor": "Taikisha", "item": "y"}]}
    rep, _p, notes = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    assert [r["item"] for r in rep["progress"]] == ["y"]
    assert any("no readable date" in n["msg"] and n["level"] == "warn" for n in notes)


def test_two_header_submissions_for_one_day_take_the_later_one_and_say_so():
    """A correction is a real thing. Resolving it silently is how a headcount changes with no
    explanation and gets argued about at the site meeting."""
    pulled = _pulled()
    pulled["header"].append(dict(pulled["header"][0], avgTemp="33", _spItemId="10"))
    rep, _p, notes = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    assert rep["weather"]["avgTemp"] == "33"
    assert any("header rows" in n["msg"] for n in notes)


def test_a_day_with_no_header_row_says_the_weather_is_unknown():
    rep, _p, notes = sp.assemble({"progress": []}, CONTRACTOR, "2026-09-01")
    assert any("No header row" in n["msg"] for n in notes)


def test_the_safety_list_becomes_the_answers_the_report_reads():
    pulled = {"safety": [{"date": "2026-09-01", "contractor": "Taikisha",
                          "item": "PPE Compliance Inspection", "status": "Yes", "notes": ""}]}
    rep, _p, _n = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    assert rep["safety"]["PPE Compliance Inspection"]["status"] == "Yes"


def test_every_list_kind_the_report_needs_has_a_field_spec_and_a_required_set():
    """A kind added to LIST_KINDS with no spec would configure in Report Setup, resolve, map
    nothing, and import blank rows forever. Cheap to state; the omission is silent."""
    for kind in sp.LIST_KINDS:
        assert kind in sp.FIELD_SPECS, kind
        assert kind in sp.REQUIRED, kind
        assert "date" in sp.REQUIRED[kind], kind


def test_every_list_kind_reaches_the_printed_report():
    """The seam between the two modules, tested end to end rather than by naming.

    dr_sharepoint decides which report FIELD each list writes into and daily_report decides which
    field each printed SECTION reads from. Nothing connects those two decisions but a string, and a
    string that stops matching fails in the worst possible way: the sync reports success, the row
    is stored, and the section prints empty. So a uniquely-identifiable row is pushed through every
    list and then looked for in the assembled model — if it is not somewhere in there, that list
    imports into a field nothing prints.
    """
    import json

    import daily_report

    pulled, expect = {}, {}
    for i, kind in enumerate(sp.LIST_KINDS):
        if kind in ("header", "photos"):
            continue                                  # both are asserted directly, above
        token = "SENTINEL%02d" % i
        row = {"date": "2026-09-01", "contractor": "Taikisha", "category": "HVAC Works"}
        for field in sp.FIELD_SPECS[kind]:
            row[field] = token
        pulled[kind] = [row]
        expect[kind] = token
    rep, _photos, _notes = sp.assemble(pulled, CONTRACTOR, "2026-09-01")
    model = daily_report.build({}, CONTRACTOR, rep, [], [rep], "2026-09-01")
    printed = json.dumps(model["sections"], default=str)
    missing = sorted(k for k, token in expect.items() if token not in printed)
    assert not missing, (
        "these SharePoint lists import into a field no section of the report reads, so their rows "
        "would be stored and never printed: %s" % ", ".join(missing))
