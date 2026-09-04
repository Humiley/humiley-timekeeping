"""The Daily Report's endpoints: the door, the sort, the photo stream and the sync.

daily_report.py's arithmetic is tested in test_daily_report.py and the SharePoint mapping in
test_dr_sharepoint.py. What is left — and what those two cannot see — is whether the HTTP layer
actually hands the assembled report out, whether it refuses the people it should, and whether a
photo that cannot be fetched says why instead of rendering a blank frame.
"""
import base64
import urllib.error
import urllib.request

import pytest

import app
import db


PROJECT = {"id": "P-MEGA", "name": "Mega Lifesciences",
           "location": "Nhon Trach Industrial Park - Dong Nai",
           "investor": "Mega Lifesciences PCL", "clientName": "MEGA",
           "consultant": "Newtecons JSC / Taikisha Vietnam Inc",
           "pmConsultant": "Humiley Vietnam Co., Ltd",
           "startDate": "2025-11-14", "endDate": "2027-04-28"}
CONTRACTOR = {"id": "C-TAI", "name": "Taikisha", "projectId": "P-MEGA",
              "logo": "data:image/png;base64,iVBORw0KGgo=",
              "mgmtRoles": ["Cad Staff", "Site Manager", "Supervisor"],
              "workerTrades": ["Electrical Works", "Fire Fighting Works", "HVAC",
                               "Other Works", "Plumbing Works"],
              "categories": ["Electrical Works", "HVAC Works", "Plumbing Works"]}
REPORT = {"id": "DR-C-TAI-2026-09-01", "projectId": "P-MEGA", "contractorId": "C-TAI",
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
YESTERDAY = {"id": "DR-C-TAI-2026-08-31", "projectId": "P-MEGA", "contractorId": "C-TAI",
             "date": "2026-08-31", "mgmt": {"Cad Staff": 7, "Site Manager": 2, "Supervisor": 5},
             "workers": {"HVAC": 74}}


@pytest.fixture(autouse=True)
def _seed(base_url):
    """A project, a contractor and two days — torn down after each test so one test's extra report
    cannot move another's delta arrow."""
    db.put_collection_item("dr_projects", dict(PROJECT))
    db.put_collection_item("dr_contractors", dict(CONTRACTOR))
    db.put_collection_item("dr_reports", dict(YESTERDAY))
    db.put_collection_item("dr_reports", dict(REPORT))
    yield
    for coll in ("dr_projects", "dr_contractors", "dr_reports", "dr_photos"):
        for row in list(db.list_collection(coll)):
            db.delete_collection_item(coll, row.get("id"))
    app.Handler._DR_PHOTO_CACHE.clear()


def _report(api, token, qs=""):
    st, b = api("GET", "/api/dr/report" + qs, token)
    assert st == 200, b
    return b


# ── the assembled report over the wire ───────────────────────────────────────────────────────────
def test_the_endpoint_hands_out_the_report_the_pdf_prints(api, tokens):
    b = _report(api, tokens["mgr"], "?projectId=P-MEGA&contractorId=C-TAI&date=2026-09-01")
    r = b["report"]
    assert r["project"]["totalDays"] == 530
    assert r["project"]["elapsedDays"] == 292
    assert r["contractor"]["name"] == "Taikisha"
    assert r["sections"]["manpower"]["mgmt"]["total"] == 13
    assert r["sections"]["manpower"]["workers"]["total"] == 91
    assert r["sections"]["overview"]["workers"]["by"] == 17
    assert r["sections"]["overview"]["mgmt"]["dir"] == "down"


def test_the_ten_page_plan_comes_back_with_the_report(api, tokens):
    """The screen tabs it and the PDF paginates it from the same list, so the two cannot disagree
    about how many pages the report has."""
    b = _report(api, tokens["mgr"], "?contractorId=C-TAI&date=2026-09-01")
    assert len(b["sections"]) == 10
    assert len(b["pages"]) == 10
    assert b["pages"][0]["of"] == 10


def test_arriving_with_nothing_selected_shows_the_newest_report(api, tokens):
    """A first-time visitor has no project, contractor or date. The useful answer is the latest
    report, not an empty page asking them to choose from a list they have not been shown."""
    b = _report(api, tokens["mgr"])
    assert b["report"]["date"] == "2026-09-01"
    assert b["reportId"] == "DR-C-TAI-2026-09-01"


def test_the_date_picker_is_built_from_days_that_exist(api, tokens):
    """A week offered in the filter that yields nothing is a filter people stop trusting."""
    b = _report(api, tokens["mgr"], "?contractorId=C-TAI")
    assert [d["date"] for d in b["dates"]] == ["2026-09-01", "2026-08-31"]
    assert b["dates"][0]["week"] == "W36" and b["dates"][0]["month"] == "2026-09"


def test_a_day_with_no_report_renders_the_masthead_rather_than_an_error(api, tokens):
    """A consultant opening a Sunday should see the project and an empty day, not a 404."""
    b = _report(api, tokens["mgr"], "?contractorId=C-TAI&date=2026-09-06")
    assert b["report"]["project"]["name"] == "Mega Lifesciences"
    assert b["report"]["sections"]["progress"]["groups"] == []


# ── who may see it ───────────────────────────────────────────────────────────────────────────────
def test_a_site_engineer_can_read_the_report_they_filled_in(api, tokens):
    """READ_MIN puts these at staff on purpose: the engineer who submits the SharePoint form has
    to be able to read back what they submitted, and the foreman yesterday's."""
    st, b = api("GET", "/api/dr/report?contractorId=C-TAI", tokens["staff"])
    assert st == 200, b
    assert b["report"]["sections"]["manpower"]["workers"]["total"] == 91


def test_an_account_with_the_app_switched_off_is_refused(api, tokens):
    """The app-key ternaries and this gate must agree — a family enforced on /api/coll and not on
    its own endpoints is an app that can be switched off for reading and still queried."""
    db.update_employee("HML-STF", {"appsDenied": "dr"})
    try:
        st, b = api("GET", "/api/dr/report?contractorId=C-TAI", tokens["staff"])
        assert st == 403
        assert "Daily Report" in str(b)
        st2, _ = api("GET", "/api/coll/dr_reports", tokens["staff"])
        assert st2 == 403, "the collection route must refuse the same account the endpoint does"
    finally:
        db.update_employee("HML-STF", {"appsDenied": ""})


def test_the_sync_and_the_setup_check_need_a_manager(api, tokens):
    for path in ("/api/dr/sync", "/api/dr/detect"):
        st, _ = api("POST", path, tokens["staff"], {"contractorId": "C-TAI", "date": "2026-09-01"})
        assert st == 403, path


def test_one_staff_account_cannot_delete_another_persons_report(api, tokens):
    """dr_ is in the delete-ownership guard. Without it any staff account could delete the site's
    signed record of a day — the same failure that let a signed AHU gate be deleted."""
    st, _ = api("DELETE", "/api/coll/dr_reports/DR-C-TAI-2026-09-01", tokens["staff"])
    assert st == 403
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")


def test_report_setup_is_not_writable_by_the_site(api, tokens):
    """A contractor row carries the SharePoint URLs and the logo. Staff fill reports in; they do
    not repoint where the reports are read from."""
    st, _ = api("POST", "/api/coll/dr_contractors", tokens["staff"],
                {"id": "C-EVIL", "name": "x", "lists": {"progress": "https://evil/"}})
    assert st == 403
    assert not db.get_collection_item("dr_contractors", "C-EVIL")


# ── sorting ──────────────────────────────────────────────────────────────────────────────────────
def test_a_table_reorders_on_request(api, tokens):
    b = _report(api, tokens["mgr"],
                "?contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=qty&dir=desc")
    got = [r["item"] for r in b["report"]["sections"]["equipment"]["equipment"]]
    assert got[0] == "Concrete Drill Battery"


def test_sorting_one_table_leaves_the_others_alone(api, tokens):
    """The person clicked a heading on Equipment. Nothing on Work Progress should move."""
    b = _report(api, tokens["mgr"],
                "?contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=item&dir=desc")
    prog = b["report"]["sections"]["progress"]["groups"][0]["rows"]
    assert [r["item"] for r in prog] == ["Install ACD pipe at - Zone 1 1FL",
                                         "Install PAc duct Zone 1 1FL"]


def test_a_nonsense_sort_in_a_bookmarked_link_still_shows_the_report(api, tokens):
    b = _report(api, tokens["mgr"],
                "?contractorId=C-TAI&date=2026-09-01&table=equipment&sortBy=__class__")
    assert len(b["report"]["sections"]["equipment"]["equipment"]) == 3


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
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


def test_an_uploaded_photo_streams_back_as_an_image(base_url, tokens):
    db.put_collection_item("dr_photos", {
        "id": "DRP-1", "contractorId": "C-TAI", "date": "2026-09-01", "kind": "daily",
        "category": "HVAC Works", "src": "upload",
        "dataUrl": "data:image/png;base64," + base64.b64encode(_PNG).decode()})
    st, body, hdr = _raw(base_url, "/api/dr/photo/DRP-1", tokens["mgr"])
    assert st == 200
    assert body == _PNG
    assert hdr["Content-Type"] == "image/png"


def test_photo_bytes_are_sandboxed_like_every_other_uploaded_file(base_url, tokens):
    """These come off a site engineer's phone by way of SharePoint. If an "image" turns out not to
    be one, it must not be able to script against the portal origin."""
    db.put_collection_item("dr_photos", {
        "id": "DRP-2", "contractorId": "C-TAI", "date": "2026-09-01", "src": "upload",
        "dataUrl": "data:image/png;base64," + base64.b64encode(_PNG).decode()})
    _st, _b, hdr = _raw(base_url, "/api/dr/photo/DRP-2", tokens["mgr"])
    assert "sandbox" in hdr.get("Content-Security-Policy", "")
    assert hdr.get("X-Content-Type-Options") == "nosniff"


def test_a_photo_that_cannot_be_fetched_says_why(base_url, tokens):
    """A broken frame with no explanation is the bug shape this whole module is written against.
    The reason travels in a header the photo pane reads and prints under the empty frame."""
    db.put_collection_item("dr_photos", {
        "id": "DRP-3", "contractorId": "C-TAI", "date": "2026-09-01", "src": "upload",
        "dataUrl": ""})
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
        db.put_collection_item("dr_photos", {
            "id": "DRP-P%d" % i, "contractorId": cid, "date": date, "kind": "daily",
            "category": "HVAC Works", "src": "upload", "dataUrl": "data:image/png;base64,AAAA"})
    b = _report(api, tokens["mgr"], "?contractorId=C-TAI&date=2026-09-01")
    photos = b["report"]["sections"]["photos"]["photos"]
    assert [p["id"] for p in photos] == ["DRP-P0"]
    assert photos[0]["caption"] == "HVAC Works - Photo 01"


# ── sync ─────────────────────────────────────────────────────────────────────────────────────────
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
    """Without this a three-day range writes three rows and the date picker offers days that look
    like days the site failed to report, rather than days nothing was submitted for."""
    assert app.Handler._dr_has_content({"weather": {}, "mgmt": {}, "workers": {}}, []) is False
    assert app.Handler._dr_has_content({"weather": {"morning": "Sunny"}}, []) is True
    assert app.Handler._dr_has_content({}, [{"id": "p"}]) is True
    assert app.Handler._dr_has_content({"progress": [{"item": "x"}]}, []) is True


def test_a_resync_replaces_that_days_rows_and_keeps_a_hand_upload(api, tokens):
    """Re-syncing a corrected form must not leave yesterday's rows underneath today's — and must
    not delete a photo somebody uploaded by hand in the portal, which is data loss, not a sync."""
    db.put_collection_item("dr_photos", {
        "id": "DRP-SP", "contractorId": "C-TAI", "date": "2026-09-01", "src": "sharepoint",
        "spKind": "share", "spUrl": "https://x/old.jpg"})
    db.put_collection_item("dr_photos", {
        "id": "DRP-MINE", "contractorId": "C-TAI", "date": "2026-09-01", "src": "upload",
        "dataUrl": "data:image/png;base64,AAAA"})
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
    """createdById is what the delete-ownership guard reads. A nightly sync run by a service
    account must not quietly make that account the owner of everybody's reports."""
    h = app.Handler
    h._dr_store(h, {"id": "HML-ADM", "name": "Admin User"}, CONTRACTOR,
                {"contractorId": "C-TAI", "date": "2026-09-01"}, [], "2026-09-01")
    first = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")
    assert first["createdById"] == "HML-MGR"       # from the seeded row, not overwritten
