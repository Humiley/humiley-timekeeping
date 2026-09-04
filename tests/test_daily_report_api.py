"""The Daily Report's endpoints, now that it lives inside the Project app.

`daily_report.py`'s arithmetic is tested in test_daily_report.py and the SharePoint mapping in
test_dr_sharepoint.py. What is left — and what those two cannot see — is whether the HTTP layer
hands the assembled report out, whether it refuses the people it should, and whether a photo that
cannot be fetched says why instead of rendering a blank frame.

The report is a tab in a project workspace, so every test here goes through a project: the project
comes from `pm_projects`, the report's own masthead extras from `dr_settings` keyed by that project
id, and every scope question is the one the rest of the PM module asks — "are you on this job?".
"""
import base64
import urllib.error
import urllib.request

import pytest

import app
import db


PID = "P-MEGA"
# The project as PMC holds it. The daily report reads its name, client and planned dates from here
# rather than keeping a second copy — see daily_report.merge_project.
PM_PROJECT = {"id": PID, "name": "Mega Lifesciences", "code": "MEGA-01",
              "client": "MEGA", "manager": "Dept Manager", "status": "Active",
              "startPlanned": "2025-11-14", "endPlanned": "2027-04-28"}
# What only this report needs.
SETTINGS = {"id": PID, "location": "Nhon Trach Industrial Park - Dong Nai",
            "investor": "Mega Lifesciences PCL",
            "consultant": "Newtecons JSC / Taikisha Vietnam Inc",
            "pmConsultant": "Humiley Vietnam Co., Ltd",
            "clientLogo": "data:image/png;base64,iVBORw0KGgo=",
            "spFolderUrl": ""}
CONTRACTOR = {"id": "C-TAI", "name": "Taikisha", "projectId": PID,
              "logo": "data:image/png;base64,iVBORw0KGgo=",
              "mgmtRoles": ["Cad Staff", "Site Manager", "Supervisor"],
              "workerTrades": ["Electrical Works", "Fire Fighting Works", "HVAC",
                               "Other Works", "Plumbing Works"],
              "categories": ["Electrical Works", "HVAC Works", "Plumbing Works"]}
REPORT = {"id": "DR-C-TAI-2026-09-01", "projectId": PID, "contractorId": "C-TAI",
          "date": "2026-09-01", "source": "sharepoint", "status": "submitted",
          "owner": "Dept Manager", "createdById": "HML-MGR",
          "weather": {"morning": "Sunny", "afternoon": "Sunny", "evening": "Sunny",
                      "avgTemp": "30", "rainHours": "1"},
          "mgmt": {"Cad Staff": 7, "Site Manager": 1, "Supervisor": 5},
          "workers": {"Electrical Works": 17, "Fire Fighting Works": 10, "HVAC": 43,
                      "Other Works": 0, "Plumbing Works": 21},
          "equipment": [{"item": "Excavator", "qty": "1", "unit": "pcs"},
                        {"item": "Concrete Drill Battery", "qty": "6", "unit": "pcs"},
                        {"item": "Plate compactor", "qty": "1", "unit": "pcs"}],
          "progress": [{"category": "HVAC Works", "item": "Install ACD pipe at - Zone 1 1FL",
                        "daily": "0", "accum": "84", "start": "2026-08-22", "finish": "2026-09-12"},
                       {"category": "HVAC Works", "item": "Install PAc duct Zone 1 1FL",
                        "daily": "8", "accum": "60", "start": "2026-08-25", "finish": "2026-09-14"}]}
YESTERDAY = {"id": "DR-C-TAI-2026-08-31", "projectId": PID, "contractorId": "C-TAI",
             "date": "2026-08-31", "mgmt": {"Cad Staff": 7, "Site Manager": 2, "Supervisor": 5},
             "workers": {"HVAC": 74}}


@pytest.fixture(autouse=True)
def _seed(base_url):
    """One project, one contractor and two days — torn down after each test so one test's extra
    report cannot move another's delta arrow. Staff One is put on the project Team, because that is
    what makes a project visible below manager level and the site engineer IS on the job."""
    db.put_collection_item("pm_projects", dict(PM_PROJECT))
    db.put_collection_item("dr_settings", dict(SETTINGS))
    db.put_collection_item("dr_contractors", dict(CONTRACTOR))
    db.put_collection_item("dr_reports", dict(YESTERDAY))
    db.put_collection_item("dr_reports", dict(REPORT))
    db.put_collection_item("pm_resources", {"id": "R-STF", "projectId": PID,
                                            "empId": "HML-STF", "name": "Staff One",
                                            "role": "Site Engineer"})
    yield
    for coll in ("dr_settings", "dr_contractors", "dr_reports", "dr_photos"):
        for row in list(db.list_collection(coll)):
            db.delete_collection_item(coll, row.get("id"))
    db.delete_collection_item("pm_projects", PID)
    db.delete_collection_item("pm_resources", "R-STF")
    app.Handler._DR_PHOTO_CACHE.clear()


def _report(api, token, qs=""):
    st, b = api("GET", "/api/dr/report?projectId=" + PID + qs, token)
    assert st == 200, b
    return b


# ── the project is the PM project ────────────────────────────────────────────────────────────────
def test_the_masthead_is_built_from_the_pm_project_plus_the_report_settings(api, tokens):
    """The name, client and dates come from pm_projects; the investor and consultants from
    dr_settings. Two registers holding the same start date is two registers that will one day
    disagree about it, on a document the client reads."""
    r = _report(api, tokens["mgr"], "&contractorId=C-TAI&date=2026-09-01")["report"]
    p = r["project"]
    assert p["name"] == "Mega Lifesciences"          # pm_projects.name
    assert p["clientName"] == "MEGA"                 # pm_projects.client
    assert p["startDate"] == "2025-11-14"            # pm_projects.startPlanned
    assert p["endDate"] == "2027-04-28"              # pm_projects.endPlanned
    assert p["investor"] == "Mega Lifesciences PCL"  # dr_settings
    assert p["pmConsultant"] == "Humiley Vietnam Co., Ltd"
    assert p["totalDays"] == 530 and p["elapsedDays"] == 292


def test_renaming_the_project_in_pmc_renames_it_on_the_report(api, tokens):
    """The one behaviour that proves there is no second copy."""
    db.put_collection_item("pm_projects", dict(PM_PROJECT, name="Mega Lifesciences Phase 2"))
    r = _report(api, tokens["mgr"], "&contractorId=C-TAI")["report"]
    assert r["project"]["name"] == "Mega Lifesciences Phase 2"


def test_the_report_refuses_to_render_without_a_project(api, tokens):
    """It is a tab inside a project workspace. There is no portfolio-wide daily report, and one
    that silently picked a project would show somebody another job's site data."""
    st, b = api("GET", "/api/dr/report", tokens["mgr"])
    assert st == 400
    assert "project" in str(b.get("error")).lower()


# ── the assembled report over the wire ───────────────────────────────────────────────────────────
def test_the_endpoint_hands_out_the_report_the_pdf_prints(api, tokens):
    r = _report(api, tokens["mgr"], "&contractorId=C-TAI&date=2026-09-01")["report"]
    assert r["contractor"]["name"] == "Taikisha"
    assert r["sections"]["manpower"]["mgmt"]["total"] == 13
    assert r["sections"]["manpower"]["workers"]["total"] == 91
    assert r["sections"]["overview"]["workers"]["by"] == 17
    assert r["sections"]["overview"]["mgmt"]["dir"] == "down"


def test_the_ten_page_plan_comes_back_with_the_report(api, tokens):
    b = _report(api, tokens["mgr"], "&contractorId=C-TAI&date=2026-09-01")
    assert len(b["sections"]) == 10
    assert len(b["pages"]) == 10
    assert b["pages"][0]["of"] == 10


def test_arriving_with_no_contractor_or_date_shows_the_newest_report(api, tokens):
    b = _report(api, tokens["mgr"])
    assert b["report"]["date"] == "2026-09-01"
    assert b["reportId"] == "DR-C-TAI-2026-09-01"


def test_the_date_picker_is_built_from_days_that_exist(api, tokens):
    b = _report(api, tokens["mgr"], "&contractorId=C-TAI")
    assert [d["date"] for d in b["dates"]] == ["2026-09-01", "2026-08-31"]
    assert b["dates"][0]["week"] == "W36" and b["dates"][0]["month"] == "2026-09"


def test_a_day_with_no_report_renders_the_masthead_rather_than_an_error(api, tokens):
    b = _report(api, tokens["mgr"], "&contractorId=C-TAI&date=2026-09-06")
    assert b["report"]["project"]["name"] == "Mega Lifesciences"
    assert b["report"]["sections"]["progress"]["groups"] == []


# ── who may see it ──────────────────────────────────────────────────────────────────────────────
def test_a_site_engineer_on_the_project_can_read_the_report_they_filled_in(api, tokens):
    """READ_MIN puts these at staff on purpose: the engineer who submits the SharePoint form has to
    be able to read back what they submitted, and the foreman yesterday's."""
    st, b = api("GET", "/api/dr/report?projectId=" + PID + "&contractorId=C-TAI", tokens["staff"])
    assert st == 200, b
    assert b["report"]["sections"]["manpower"]["workers"]["total"] == 91


def test_a_staff_account_on_another_job_is_refused(api, tokens):
    """The same project scope the rest of the PM module reads with. Without it the daily report
    would be the one PM screen that served a job you are not on — and site photos and headcounts
    are exactly the sort of thing a client would object to being shared across projects."""
    st, b = api("GET", "/api/dr/report?projectId=" + PID + "&contractorId=C-TAI", tokens["other"])
    assert st == 403
    assert "not one of yours" in str(b.get("error"))


def test_the_projects_app_switch_governs_it(api, tokens):
    """It is part of the Project app, so Projects is the switch. An app gate that gated half an app
    would leave somebody who cannot open the portfolio reading every project's daily report."""
    db.update_employee("HML-MGR", {"appsDenied": "pm"})
    try:
        st, b = api("GET", "/api/dr/report?projectId=" + PID, tokens["mgr"])
        assert st == 403
        assert "Projects" in str(b)
        st2, _ = api("GET", "/api/coll/dr_reports", tokens["mgr"])
        assert st2 == 403, "the collection route must refuse the same account the endpoint does"
    finally:
        db.update_employee("HML-MGR", {"appsDenied": ""})


def test_the_sync_and_the_setup_check_need_a_project_you_are_on(api, tokens):
    for path in ("/api/dr/sync", "/api/dr/detect"):
        st, _ = api("POST", path, tokens["other"],
                    {"contractorId": "C-TAI", "date": "2026-09-01"})
        assert st == 403, path


def test_a_contractor_from_another_project_cannot_be_driven_from_this_one(api, tokens):
    """Without this check, a caller entitled to project A could pass project B's contractorId and
    sync B's SharePoint lists, folders and report rows from inside a workspace they may open."""
    db.put_collection_item("dr_contractors", {"id": "C-OTHER", "name": "Elsewhere",
                                              "projectId": "P-OTHER"})
    try:
        st, b = api("POST", "/api/dr/sync", tokens["mgr"],
                    {"contractorId": "C-OTHER", "projectId": PID, "date": "2026-09-01"})
        assert st == 400
        assert "different project" in str(b.get("error"))
    finally:
        db.delete_collection_item("dr_contractors", "C-OTHER")


def test_a_contractor_with_no_project_is_refused_rather_than_synced_into_nowhere(api, tokens):
    db.put_collection_item("dr_contractors", {"id": "C-ORPHAN", "name": "Orphan"})
    try:
        st, b = api("POST", "/api/dr/sync", tokens["admin"], {"contractorId": "C-ORPHAN"})
        assert st == 400
        assert "not attached to a project" in str(b.get("error"))
    finally:
        db.delete_collection_item("dr_contractors", "C-ORPHAN")


# ── writes are scoped by project, not by author ─────────────────────────────────────────────────
def test_a_report_cannot_be_deleted_from_another_job(api, tokens):
    st, _ = api("DELETE", "/api/coll/dr_reports/DR-C-TAI-2026-09-01", tokens["other"])
    assert st == 403
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")


def test_the_engineer_on_the_job_can_delete_a_duplicate_they_did_not_create(api, tokens):
    """The point of scoping by project rather than by author. The row was created by whoever ran
    the sync (HML-MGR); the engineer who produced the day's report is on the Team and has to be
    able to remove a duplicate — under creator-ownership they could not, and the person who pressed
    Sync could delete every report on the job."""
    db.put_collection_item("dr_reports", dict(REPORT, id="DR-DUP", createdById="HML-MGR",
                                              owner="Dept Manager"))
    st, b = api("DELETE", "/api/coll/dr_reports/DR-DUP", tokens["staff"])
    assert st == 200, b
    assert not db.get_collection_item("dr_reports", "DR-DUP")


def test_a_report_cannot_be_written_into_a_project_you_are_not_on(api, tokens):
    st, _ = api("POST", "/api/coll/dr_reports", tokens["other"],
                {"id": "DR-EVIL", "projectId": PID, "contractorId": "C-TAI", "date": "2026-09-09"})
    assert st == 403
    assert not db.get_collection_item("dr_reports", "DR-EVIL")


def test_a_report_cannot_be_moved_between_projects(api, tokens):
    """projectId is what every scope here is decided on, so a PATCH that rewrites it rewrites who
    may see and touch the row."""
    st, b = api("PATCH", "/api/coll/dr_reports/DR-C-TAI-2026-09-01", tokens["staff"],
                dict(REPORT, projectId="P-OTHER"))
    assert st == 403, b
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")["projectId"] == PID


def test_report_setup_is_scoped_to_the_project_too(api, tokens):
    st, _ = api("POST", "/api/coll/dr_contractors", tokens["other"],
                {"id": "C-EVIL", "name": "x", "projectId": PID,
                 "lists": {"progress": "https://evil/"}})
    assert st == 403
    assert not db.get_collection_item("dr_contractors", "C-EVIL")


# ── sorting ─────────────────────────────────────────────────────────────────────────────────────
def test_a_table_reorders_on_request(api, tokens):
    b = _report(api, tokens["mgr"],
                "&contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=qty&dir=desc")
    got = [r["item"] for r in b["report"]["sections"]["equipment"]["equipment"]]
    assert got[0] == "Concrete Drill Battery"


def test_sorting_one_table_leaves_the_others_alone(api, tokens):
    b = _report(api, tokens["mgr"],
                "&contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=item&dir=desc")
    prog = b["report"]["sections"]["progress"]["groups"][0]["rows"]
    assert [r["item"] for r in prog] == ["Install ACD pipe at - Zone 1 1FL",
                                         "Install PAc duct Zone 1 1FL"]


def test_a_nonsense_sort_in_a_bookmarked_link_still_shows_the_report(api, tokens):
    b = _report(api, tokens["mgr"],
                "&contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=__class__")
    assert len(b["report"]["sections"]["equipment"]["equipment"]) == 3


# ── photos ──────────────────────────────────────────────────────────────────────────────────────
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _raw(base_url, path, token):
    req = urllib.request.Request(base_url + path)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def _photo(pid_, **kw):
    row = {"id": pid_, "contractorId": "C-TAI", "projectId": PID, "date": "2026-09-01",
           "kind": "daily", "category": "HVAC Works", "src": "upload",
           "dataUrl": "data:image/png;base64," + base64.b64encode(_PNG).decode()}
    row.update(kw)
    return row


def test_an_uploaded_photo_streams_back_as_an_image(base_url, tokens):
    db.put_collection_item("dr_photos", _photo("DRP-1"))
    st, body, hdr = _raw(base_url, "/api/dr/photo/DRP-1", tokens["mgr"])
    assert st == 200
    assert body == _PNG
    assert hdr["Content-Type"] == "image/png"


def test_photo_bytes_are_sandboxed_like_every_other_uploaded_file(base_url, tokens):
    """These come off a site engineer's phone by way of SharePoint. If an "image" turns out not to
    be one, it must not be able to script against the portal origin."""
    db.put_collection_item("dr_photos", _photo("DRP-2"))
    _st, _b, hdr = _raw(base_url, "/api/dr/photo/DRP-2", tokens["mgr"])
    assert "sandbox" in hdr.get("Content-Security-Policy", "")
    assert hdr.get("X-Content-Type-Options") == "nosniff"


def test_a_photo_that_cannot_be_fetched_says_why(base_url, tokens):
    """A broken frame with no explanation is the bug shape this whole module is written against.
    The reason travels in a header the photo pane reads and prints under the empty frame."""
    db.put_collection_item("dr_photos", _photo("DRP-3", dataUrl=""))
    st, _b, hdr = _raw(base_url, "/api/dr/photo/DRP-3", tokens["mgr"])
    assert st == 404
    assert "no image" in hdr.get("X-DR-Photo-Error", "").lower()


def test_a_photo_id_cannot_walk_out_of_the_collection(base_url, tokens):
    for bad in ("../../etc/passwd", "..%2F..%2Fapp.py", "a" * 200):
        st, _b, _h = _raw(base_url, "/api/dr/photo/" + bad, tokens["mgr"])
        assert st == 404, bad


def test_the_report_lists_the_photos_of_that_day_and_that_contractor_only(api, tokens):
    for i, (cid, date) in enumerate([("C-TAI", "2026-09-01"), ("C-TAI", "2026-08-31"),
                                     ("C-NEW", "2026-09-01")]):
        db.put_collection_item("dr_photos", _photo("DRP-P%d" % i, contractorId=cid, date=date))
    b = _report(api, tokens["mgr"], "&contractorId=C-TAI&date=2026-09-01")
    photos = b["report"]["sections"]["photos"]["photos"]
    assert [p["id"] for p in photos] == ["DRP-P0"]
    assert photos[0]["caption"] == "HVAC Works - Photo 01"


# ── sync ────────────────────────────────────────────────────────────────────────────────────────
def test_a_sync_without_microsoft_365_configured_says_so_instead_of_failing_obscurely(api, tokens):
    if (app.M365.get("clientSecret") or "").strip():
        pytest.skip("this server has a real M365 secret configured")
    st, b = api("POST", "/api/dr/sync", tokens["mgr"],
                {"contractorId": "C-TAI", "date": "2026-09-01"})
    assert st == 400
    assert "Microsoft 365" in str(b.get("error"))


def test_a_sync_for_an_unknown_contractor_is_refused(api, tokens):
    st, b = api("POST", "/api/dr/sync", tokens["mgr"], {"contractorId": "nope"})
    assert st == 400
    assert "contractor" in str(b.get("error")).lower()


@pytest.mark.parametrize("body,ok", [
    ({"date": "2026-09-01"}, True),
    ({"from": "2026-09-01", "to": "2026-09-03"}, True),
    ({"from": "2026-09-03", "to": "2026-09-01"}, False),        # backwards
    ({"from": "2026-01-01", "to": "2026-12-31"}, False),        # a year in one request
    ({}, False)])
def test_the_sync_window_is_bounded(body, ok):
    """A range sync walks every date in the window against every configured list. A year-wide
    request is not a sync, it is an outage — and it would write 365 empty report rows."""
    got = app.Handler._dr_sync_dates(body)
    assert bool(got) is ok
    if ok:
        assert len(got) <= 31


def test_an_empty_day_is_not_written_as_a_blank_report():
    assert app.Handler._dr_has_content({"weather": {}, "mgmt": {}, "workers": {}}, []) is False
    assert app.Handler._dr_has_content({"weather": {"morning": "Sunny"}}, []) is True
    assert app.Handler._dr_has_content({}, [{"id": "p"}]) is True
    assert app.Handler._dr_has_content({"progress": [{"item": "x"}]}, []) is True


def test_a_resync_replaces_that_days_rows_and_keeps_a_hand_upload(api, tokens):
    """Re-syncing a corrected form must not leave yesterday's rows underneath today's — and must
    not delete a photo somebody uploaded by hand in the portal, which is data loss, not a sync."""
    db.put_collection_item("dr_photos", _photo("DRP-SP", src="sharepoint", spKind="share",
                                               spUrl="https://x/old.jpg", dataUrl=""))
    db.put_collection_item("dr_photos", _photo("DRP-MINE"))
    h = app.Handler
    u = {"id": "HML-MGR", "name": "Dept Manager"}
    out = h._dr_store(h, u, CONTRACTOR,
                      {"contractorId": "C-TAI", "date": "2026-09-01", "progress": []},
                      [{"contractorId": "C-TAI", "date": "2026-09-01", "src": "sharepoint",
                        "spKind": "share", "spUrl": "https://x/new.jpg"}],
                      "2026-09-01")
    left = {p["id"]: p for p in db.list_collection("dr_photos")}
    assert "DRP-SP" not in left, "the previous sync's photo should have been replaced"
    assert "DRP-MINE" in left, "a hand upload must survive a re-sync"
    assert out["replacedPhotos"] == 1
    assert left["DRP-C-TAI-2026-09-01-001"]["spUrl"] == "https://x/new.jpg"


def test_a_resync_by_someone_else_does_not_transfer_ownership_of_the_record():
    """createdById is the audit trail of who filed the day. A nightly sync run by a service account
    must not quietly rewrite every report to say it authored them."""
    h = app.Handler
    h._dr_store(h, {"id": "HML-ADM", "name": "Admin User"}, CONTRACTOR,
                {"contractorId": "C-TAI", "date": "2026-09-01"}, [], "2026-09-01")
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")["createdById"] == "HML-MGR"


# ── the project's SharePoint folder ─────────────────────────────────────────────────────────────
def test_a_project_with_no_folder_configured_contributes_no_photos_and_no_noise():
    """Not an error. Plenty of projects run the first week on the lists alone."""
    h = app.Handler
    assert h._dr_folder(h, dict(CONTRACTOR)) is None
    assert h._dr_folder_photos(h, None, CONTRACTOR, "2026-09-01") == ([], None)


def test_the_category_of_a_folder_photo_is_read_from_its_file_name():
    """A folder cannot carry a column, so the file name is the only place a category can come
    from — and a name matching nothing still appears on the report rather than being dropped."""
    h = app.Handler
    assert h._dr_category_from_name("HVAC Works - 03.jpg", CONTRACTOR) == "HVAC Works"
    assert h._dr_category_from_name("hvacworks_1.HEIC", CONTRACTOR) == "HVAC Works"
    assert h._dr_category_from_name("IMG_4821.jpg", CONTRACTOR) == "Electrical Works"  # first
    assert h._dr_category_from_name("IMG_4821.jpg", {"categories": []}) == ""
