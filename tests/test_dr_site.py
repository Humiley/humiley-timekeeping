"""The contractor's own form: the public endpoints, and everything they must refuse.

`test_dr_access.py` proves the policy — the lockout arithmetic, the signed cookie. This file proves
the DOORS built on it: that a link alone writes nothing, that one contractor's confirmed device
cannot file another's report, that the site can only write the fields the report prints, and that a
sign-in code which could not be emailed is never reported as sent.

Every route here is reachable by anybody on the internet who has the link, so the tests are written
from that side: not "does it work" but "what can somebody holding the link still not do".
"""
import base64
import json
import urllib.error
import urllib.request

import pytest

import app
import db
import dr_access


PID = "P-MEGA"
TOKEN = "tok" + "A" * 30
OTHER_TOKEN = "tok" + "B" * 30
SITE_EMAIL = "site@taikisha.example"

CONTRACTOR = {"id": "C-TAI", "name": "Taikisha", "projectId": PID, "token": TOKEN,
              "emails": SITE_EMAIL + ", pm@taikisha.example",
              "mgmtRoles": ["Cad Staff", "Site Manager"],
              "workerTrades": ["HVAC", "Plumbing Works"],
              "categories": ["HVAC Works", "Plumbing Works"]}
OTHER = {"id": "C-NEW", "name": "Newtecons", "projectId": PID, "token": OTHER_TOKEN,
         "emails": "other@newtecons.example", "mgmtRoles": [], "workerTrades": [],
         "categories": ["Civil Structure Works"]}


@pytest.fixture(autouse=True)
def _seed(base_url):
    db.put_collection_item("pm_projects", {"id": PID, "name": "Mega Lifesciences",
                                           "manager": "Dept Manager"})
    db.put_collection_item("dr_contractors", dict(CONTRACTOR))
    db.put_collection_item("dr_contractors", dict(OTHER))
    yield
    for coll in ("dr_contractors", "dr_reports", "dr_photos", "dr_access"):
        for row in list(db.list_collection(coll)):
            db.delete_collection_item(coll, row.get("id"))
    db.delete_collection_item("pm_projects", PID)


def _call(base_url, method, path, body=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", dr_access.COOKIE + "=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}"), dict(e.headers)
        except Exception:
            return e.code, {}, dict(e.headers)


def _cookie_for(contractor_id=CONTRACTOR["id"], email=SITE_EMAIL):
    """A confirmed device, minted the way the server does. Sign-in itself needs email, which is not
    available in a test server — the endpoints under test are the ones AFTER confirmation."""
    return dr_access.sign_session(app.Handler._dr_secret(app.Handler), contractor_id, email)


# ── the page ─────────────────────────────────────────────────────────────────────────────────────
def test_the_form_page_is_served_for_a_well_formed_link(base_url):
    req = urllib.request.Request(base_url + "/dr/" + TOKEN)
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read().decode()
    assert r.status == 200
    assert "/api/dr/site/day" in body, "the page did not come back"
    assert "no-store" in (r.headers.get("Cache-Control") or "")


def test_an_unknown_token_looks_exactly_like_a_real_one(base_url):
    """A 404 for an unknown token and a form for a real one is an oracle: try tokens, see which
    render. Both render; every ACTION behind the page fails the same way."""
    real = urllib.request.urlopen(base_url + "/dr/" + TOKEN, timeout=10).read()
    fake = urllib.request.urlopen(base_url + "/dr/" + "tok" + "Z" * 30, timeout=10).read()
    assert real == fake


def test_a_malformed_token_is_refused_without_touching_the_database(base_url):
    for bad in ("../../etc/passwd", "short", "a" * 200):
        req = urllib.request.Request(base_url + "/dr/" + bad)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read().decode()
                assert "not a valid link" in body.lower(), bad
        except urllib.error.HTTPError as e:
            assert e.code in (400, 404), bad


# ── the link alone does nothing ──────────────────────────────────────────────────────────────────
def test_the_link_alone_cannot_read_the_day(base_url):
    st, b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN)
    assert st == 401
    assert "sign in" in str(b.get("error")).lower()


def test_the_link_alone_cannot_write(base_url):
    st, _b, _h = _call(base_url, "POST", "/api/dr/site/save",
                       {"token": TOKEN, "date": "2026-09-01", "field": "equipment",
                        "value": [{"item": "Excavator"}]})
    assert st == 401
    assert not db.list_collection("dr_reports")


def test_the_link_alone_cannot_upload_a_photo(base_url):
    st, _b, _h = _call(base_url, "POST", "/api/dr/site/photo",
                       {"token": TOKEN, "date": "2026-09-01",
                        "dataUrl": "data:image/png;base64,iVBORw0KGgo="})
    assert st == 401
    assert not db.list_collection("dr_photos")


# ── one contractor's device cannot file another's report ─────────────────────────────────────────
def test_a_confirmed_device_is_bound_to_its_own_contractor(base_url):
    """The cookie says WHO you are; the link says WHICH form. Both have to agree, or a contractor's
    own confirmed phone could file its competitor's report simply by opening their link."""
    cookie = _cookie_for(CONTRACTOR["id"], SITE_EMAIL)
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + OTHER_TOKEN, cookie=cookie)
    assert st == 401
    st2, _b2, _h2 = _call(base_url, "POST", "/api/dr/site/save",
                          {"token": OTHER_TOKEN, "date": "2026-09-01", "field": "equipment",
                           "value": [{"item": "x"}]}, cookie=cookie)
    assert st2 == 401
    assert not db.list_collection("dr_reports")


def test_the_binding_holds_even_when_one_address_is_on_both_contractors_lists(base_url):
    """The case the test above does NOT cover, and the realistic one.

    With different addresses per contractor, the email allow-list refuses a cross-contractor cookie
    on its own — so removing the contractor check entirely left every test green. Verified by
    injecting exactly that regression. A shared address (a Humiley coordinator, a site@ alias used
    by both) removes that accidental defence and leaves only the binding, which is what this
    asserts.
    """
    shared = "coordinator@humiley.com"
    db.put_collection_item("dr_contractors", dict(CONTRACTOR, emails=SITE_EMAIL + ", " + shared))
    db.put_collection_item("dr_contractors", dict(OTHER, emails="other@newtecons.example, " + shared))
    cookie = _cookie_for(CONTRACTOR["id"], shared)
    # It works on its OWN form ...
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=cookie)
    assert st == 200, "the shared address must still work on its own contractor's form"
    # ... and not on the other's, even though the address is authorised for both.
    st2, _b2, _h2 = _call(base_url, "GET", "/api/dr/site/day?token=" + OTHER_TOKEN, cookie=cookie)
    assert st2 == 401, "a cookie for one contractor opened another's form"
    st3, _b3, _h3 = _call(base_url, "POST", "/api/dr/site/save",
                          {"token": OTHER_TOKEN, "date": "2026-09-01", "field": "equipment",
                           "value": [{"item": "x"}]}, cookie=cookie)
    assert st3 == 401, "a cookie for one contractor filed another's report"
    assert not db.list_collection("dr_reports")


def test_an_address_removed_from_the_list_stops_working_immediately(base_url):
    """The cookie is good for thirty days, so removal has to be checked on every request rather
    than only at sign-in — otherwise somebody who left the site keeps filing for a month."""
    cookie = _cookie_for()
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=cookie)
    assert st == 200
    db.put_collection_item("dr_contractors", dict(CONTRACTOR, emails="someone.else@x.example"))
    st2, _b2, _h2 = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=cookie)
    assert st2 == 401


def test_a_forged_cookie_is_refused(base_url):
    for junk in ("x", "x.y", "", "a" * 300):
        st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=junk)
        assert st == 401, junk


# ── what a signed-in site may see ────────────────────────────────────────────────────────────────
def test_the_day_returns_this_contractors_own_setup_and_nothing_else(base_url):
    st, b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=_cookie_for())
    assert st == 200, b
    assert b["contractor"]["name"] == "Taikisha"
    assert b["setup"]["mgmtRoles"] == CONTRACTOR["mgmtRoles"]
    assert b["setup"]["categories"] == CONTRACTOR["categories"]
    assert len(b["setup"]["safetyChecks"]) == 11        # the shipped default
    blob = json.dumps(b)
    assert "Newtecons" not in blob, "another contractor leaked into the response"

    # The project's NAME, client and location are now here on purpose: the form carries the same
    # masthead the printed report does, so somebody filing can see which project they are filing
    # for. That is not a leak — the contractor is standing on the site, works for that client, and
    # the report they produce prints all three at the top.
    #
    # What must NOT be here is the rest of the project record. The earlier version of this test said
    # "no project data at all", which was true when the payload had none and became wrong the moment
    # the masthead was asked for; a blanket assertion like that either blocks a legitimate change or
    # gets deleted wholesale when it fires. So it is now a list of the fields that would actually be
    # somebody else's business.
    assert b["project"]["name"] == "Mega Lifesciences"
    for field in ("manager", "budget", "startPlanned", "endPlanned", "percentComplete",
                  "phase", "code", "owner", "createdById", "status"):
        assert field not in b["project"], \
            "%s is not the site's business and is now in the payload" % field
    assert set(b["project"]) == {"name", "client", "location", "investor", "hasLogo"}, \
        "the masthead grew fields nobody reviewed: %s" % sorted(b["project"])
    assert "Dept Manager" not in blob, "the project manager's name reached the site"


# ── what a signed-in site may write ──────────────────────────────────────────────────────────────
def _save(base_url, field, value, date="2026-09-01"):
    return _call(base_url, "POST", "/api/dr/site/save",
                 {"token": TOKEN, "date": date, "field": field, "value": value},
                 cookie=_cookie_for())


def test_a_section_saves_and_reads_back(base_url):
    st, b, _h = _save(base_url, "equipment",
                      [{"item": "Excavator", "qty": "1", "unit": "pcs", "notes": ""}])
    assert st == 200 and b["count"] == 1
    row = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")
    assert row["equipment"][0]["item"] == "Excavator"
    assert row["source"] == "site" and row["contractorId"] == "C-TAI"
    assert row["projectId"] == PID, "the row must land on the contractor's own project"


def test_only_the_fields_the_report_prints_can_be_written(base_url):
    """The request body names the field. Without a whitelist a crafted request could set id,
    projectId or source and move the row onto another project."""
    for field in ("id", "projectId", "source", "contractorId", "status", "__proto__"):
        st, b, _h = _save(base_url, field, "x")
        assert st == 400, field
        assert "not part of the daily report" in str(b.get("error"))


def test_a_row_is_rebuilt_from_the_whitelist_not_filtered(base_url):
    """A filter keeps whatever it did not think to remove. Extra keys must simply not survive."""
    _save(base_url, "equipment", [{"item": "Excavator", "evil": "<script>", "projectId": "P-OTHER"}])
    row = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")
    assert set(row["equipment"][0]) == {"item", "qty", "unit", "notes"}
    assert row["projectId"] == PID


def test_a_headcount_must_be_a_number_and_a_sensible_one(base_url):
    st, b, _h = _save(base_url, "mgmt", {"Cad Staff": "lots"})
    assert st == 400 and "must be a number" in str(b.get("error"))
    st2, b2, _h2 = _save(base_url, "mgmt", {"Cad Staff": -3})
    assert st2 == 400 and "sensible" in str(b2.get("error"))
    st3, _b3, _h3 = _save(base_url, "mgmt", {"Cad Staff": 7})
    assert st3 == 200
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")["mgmt"] == {"Cad Staff": 7}


def test_a_headcount_for_a_role_this_contractor_does_not_have_is_dropped(base_url):
    """The roles come from the contractor's setup, and the total printed under table 2.1 is the sum
    of the columns on it — so a count under a name that is not a column must not be stored as if it
    were one."""
    _save(base_url, "mgmt", {"Cad Staff": 7, "Chief Astronaut": 4})
    assert db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")["mgmt"] == {"Cad Staff": 7}


def test_a_report_cannot_be_filed_for_a_future_date(base_url):
    """Not arithmetic pedantry: a report dated ahead sits at the top of the date list and reads as
    the latest day on site."""
    st, b, _h = _save(base_url, "equipment", [{"item": "x"}], date="2099-01-01")
    assert st == 400 and "future" in str(b.get("error"))


def test_a_day_with_no_date_is_refused(base_url):
    st, b, _h = _save(base_url, "equipment", [{"item": "x"}], date="")
    assert st == 400


def test_a_wall_of_rows_is_refused(base_url):
    st, b, _h = _save(base_url, "equipment", [{"item": "x"}] * 500)
    assert st == 400 and "rows" in str(b.get("error"))


def test_a_very_long_field_is_capped_rather_than_stored(base_url):
    _save(base_url, "equipment", [{"item": "A" * 50_000}])
    row = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")
    assert len(row["equipment"][0]["item"]) <= app.Handler.DR_SITE_MAX_TEXT


def test_an_unanswered_safety_check_is_simply_absent(base_url):
    """It must not be stored as anything — daily_report renders an absent check as NOT ANSWERED,
    and a stored blank could be mistaken for an answer later."""
    _save(base_url, "safety", {"Housekeeping Inspection": {"status": "Yes"},
                               "PPE Compliance Inspection": {"status": ""}})
    saved = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")["safety"]
    assert list(saved) == ["Housekeeping Inspection"]


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_a_photo_is_stored_against_the_day_and_the_contractor(base_url):
    st, b, _h = _call(base_url, "POST", "/api/dr/site/photo",
                      {"token": TOKEN, "date": "2026-09-01", "category": "HVAC Works",
                       "name": "a.png", "dataUrl": _PNG}, cookie=_cookie_for())
    assert st == 200, b
    row = db.get_collection_item("dr_photos", b["id"])
    assert row["contractorId"] == "C-TAI" and row["date"] == "2026-09-01"
    assert row["category"] == "HVAC Works"
    assert b["stored"] == "portal"      # no SharePoint folder configured in the test


def test_a_photo_category_this_contractor_does_not_have_falls_back(base_url):
    st, b, _h = _call(base_url, "POST", "/api/dr/site/photo",
                      {"token": TOKEN, "date": "2026-09-01", "category": "Nuclear Works",
                       "dataUrl": _PNG}, cookie=_cookie_for())
    assert st == 200
    assert db.get_collection_item("dr_photos", b["id"])["category"] == "HVAC Works"


def test_only_an_image_is_accepted(base_url):
    for bad in ("data:text/html;base64,PHNjcmlwdD4=",
                "data:application/pdf;base64,JVBERi0=",
                "https://example.com/a.jpg", "", "not a data url"):
        st, _b, _h = _call(base_url, "POST", "/api/dr/site/photo",
                           {"token": TOKEN, "date": "2026-09-01", "dataUrl": bad},
                           cookie=_cookie_for())
        assert st == 400, bad
    assert not db.list_collection("dr_photos")


def test_a_photo_larger_than_the_cap_is_refused(base_url):
    big = "data:image/png;base64," + base64.b64encode(b"\0" * (13 * 1024 * 1024)).decode()
    st, b, _h = _call(base_url, "POST", "/api/dr/site/photo",
                      {"token": TOKEN, "date": "2026-09-01", "dataUrl": big},
                      cookie=_cookie_for())
    assert st == 400 and "12 MB" in str(b.get("error"))


# ── the sign-in flow's failure modes ─────────────────────────────────────────────────────────────
def test_asking_for_a_code_never_says_whether_the_address_is_known(base_url):
    """Same answer for an authorised address and an unknown one. With no mail configured the
    authorised one reports a send failure — which is also the same for both, by construction."""
    st1, b1, _h = _call(base_url, "POST", "/api/dr/site/code",
                        {"token": TOKEN, "email": "nobody@nowhere.example"})
    assert st1 == 200
    assert b1["message"] == dr_access.SENT_MESSAGE
    st2, b2, _h2 = _call(base_url, "POST", "/api/dr/site/code",
                         {"token": "tok" + "Q" * 30, "email": SITE_EMAIL})
    assert st2 == 200 and b2["message"] == dr_access.SENT_MESSAGE


def test_a_code_that_could_not_be_emailed_is_never_reported_as_sent(base_url):
    """The credential IS the email. Saying "on its way" when nothing left the server leaves
    somebody watching an inbox — the false-green the digest health rows were fixed for."""
    if (app.M365.get("clientSecret") or "").strip():
        pytest.skip("this server can actually send mail")
    st, b, _h = _call(base_url, "POST", "/api/dr/site/code",
                      {"token": TOKEN, "email": SITE_EMAIL})
    assert st == 502
    assert b["ok"] is False
    assert "could not be sent" in b["message"]
    # and nothing was recorded, so the throttle does not count a mail that never went
    assert not db.list_collection("dr_access")


def test_verifying_without_a_code_says_ask_for_one(base_url):
    st, b, _h = _call(base_url, "POST", "/api/dr/site/verify",
                      {"token": TOKEN, "email": SITE_EMAIL, "code": "123456"})
    assert st == 400
    assert "expired" in str(b.get("error")).lower()


def test_signing_out_clears_the_cookie(base_url):
    st, _b, h = _call(base_url, "POST", "/api/dr/site/signout", {}, cookie=_cookie_for())
    assert st == 200
    assert "Max-Age=0" in (h.get("Set-Cookie") or "")


def test_the_cookie_is_httponly_and_samesite(base_url):
    """It is the credential for a public form. A script must not be able to read it, and it must
    not ride along on a cross-site POST."""
    _st, _b, h = _call(base_url, "POST", "/api/dr/site/signout", {}, cookie=_cookie_for())
    sc = h.get("Set-Cookie") or ""
    assert "HttpOnly" in sc and "SameSite=Lax" in sc


# ── a sync must not overwrite what the site typed ────────────────────────────────────────────────
def test_a_sharepoint_sync_does_not_overwrite_a_day_the_site_filed(base_url):
    """Both routes can be live during a changeover. A sync that ran afterwards would replace a
    report somebody typed with whatever the lists held — silently, and unrecoverably."""
    _save(base_url, "equipment", [{"item": "Excavator", "qty": "1"}])
    h = app.Handler
    out = h._dr_store(h, {"id": "HML-MGR", "name": "Dept Manager"}, CONTRACTOR,
                      {"contractorId": "C-TAI", "date": "2026-09-01", "equipment": []},
                      [], "2026-09-01")
    assert out.get("skipped")
    row = db.get_collection_item("dr_reports", "DR-C-TAI-2026-09-01")
    assert row["equipment"][0]["item"] == "Excavator", "the site's typed report was overwritten"


# ── signing a device out ─────────────────────────────────────────────────────────────────────────
# These are here rather than in test_dr_access.py because the defect they pin was not in the
# arithmetic. `_dr_revoke_ep` deleted the contractor's `dr_access` rows and reported "N confirmed
# device(s) cut" — but a `dr_access` row is the pending code, the send throttle and the lockout
# counter for ONE ADDRESS. It is not a session. The session is a self-contained signed cookie the
# server never stored, so deleting those rows signed nobody out: a phone kept working for the
# remaining thirty days behind a button that said otherwise, and the whole suite stayed green
# because nothing asked what happened to a cookie afterwards.
def _cookie_for_current(contractor_id=CONTRACTOR["id"], email=SITE_EMAIL):
    """A cookie minted from the contractor's CURRENT generation — what a fresh code gives you."""
    con = db.get_collection_item("dr_contractors", contractor_id) or {}
    return dr_access.sign_session(app.Handler._dr_secret(app.Handler), contractor_id, email,
                                  dr_access.session_epoch(con))


def test_signing_everyone_out_stops_a_cookie_that_was_working(base_url, api, tokens):
    c = _cookie_for()
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=c)
    assert st == 200, "the cookie did not work to begin with — this test proves nothing"

    st, b = api("POST", "/api/dr/revoke", tokens["mgr"],
                {"contractorId": CONTRACTOR["id"], "projectId": PID})
    assert st == 200, b

    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=c)
    assert st == 401, "the device is still signed in after Sign everyone out"


def test_signing_everyone_out_leaves_the_link_working(base_url, api, tokens):
    """The other half of the promise, and what makes this a different control from re-issuing the
    link: the crew that remains signs in again with a code, off the same bookmark."""
    before = db.get_collection_item("dr_contractors", CONTRACTOR["id"])["token"]
    api("POST", "/api/dr/revoke", tokens["mgr"],
        {"contractorId": CONTRACTOR["id"], "projectId": PID})
    after = db.get_collection_item("dr_contractors", CONTRACTOR["id"])["token"]
    assert after == before, "the link changed when only the devices should have"

    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN,
                       cookie=_cookie_for_current())
    assert st == 200, "a device signing in again after the sign-out is refused"


def test_a_new_link_signs_everyone_out_as_well(base_url, api, tokens):
    """Re-issuing is the stronger control and must not be weaker in any direction: a leaked link is
    a leaked link, and a device already signed in through it does not get to stay."""
    c = _cookie_for()
    st, b = api("POST", "/api/dr/revoke", tokens["mgr"],
                {"contractorId": CONTRACTOR["id"], "projectId": PID, "newLink": True})
    assert st == 200, b
    new_token = db.get_collection_item("dr_contractors", CONTRACTOR["id"])["token"]
    assert new_token != TOKEN

    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + TOKEN, cookie=c)
    assert st == 401, "the old link still resolves"
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + new_token, cookie=c)
    assert st == 401, "the old cookie still works on the new link"


def test_one_contractors_sign_out_does_not_touch_another(base_url, api, tokens):
    """The generation is per contractor. If it were global — or if the loop matched on the wrong
    field — pressing the button for one site would sign out every other site on the portal, which is
    the kind of blast radius nobody would connect to the button they pressed."""
    other = _cookie_for(OTHER["id"], "other@newtecons.example")
    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + OTHER_TOKEN, cookie=other)
    assert st == 200

    api("POST", "/api/dr/revoke", tokens["mgr"],
        {"contractorId": CONTRACTOR["id"], "projectId": PID})

    st, _b, _h = _call(base_url, "GET", "/api/dr/site/day?token=" + OTHER_TOKEN, cookie=other)
    assert st == 200, "signing Taikisha out also signed Newtecons out"


# ── who the code is sent FROM ────────────────────────────────────────────────────────────────────
# `_dr_mail_sender` used to fall back through `portal_apprEmail`, which is the "Approval emails"
# CHECKBOX and stores "1"/"0". Both are non-empty strings and therefore truthy, so on any server
# where `portal_apprSenderProc` was unset the sender became literally "1": Graph was asked to send
# as a mailbox named 1, `TK_ADMIN_EMAIL` was unreachable, and `_dr_send_code`'s "no sender address
# configured" guard could never fire, so the site saw an opaque Graph error instead of the true
# cause. Nothing caught it because every test and every live server had the setting populated.
def test_the_sender_is_never_the_approval_emails_checkbox(base_url):
    """The checkbox is stored under portal_apprEmail as "1"/"0". Neither may ever reach Graph as an
    address — and "0" is the dangerous one, because it is falsy to a reader's eye and truthy to
    Python."""
    prev_proc = db.get_setting("portal_apprSenderProc", "")
    prev_flag = db.get_setting("portal_apprEmail", "")
    try:
        for flag in ("1", "0"):
            db.set_setting("portal_apprSenderProc", "")
            db.set_setting("portal_apprEmail", flag)
            got = app.Handler._dr_mail_sender(app.Handler)
            assert got not in ("1", "0"), "the checkbox reached Graph as a sender: %r" % got
            assert "@" in got, "the sender is not an address: %r" % got
    finally:
        db.set_setting("portal_apprSenderProc", prev_proc)
        db.set_setting("portal_apprEmail", prev_flag)


def test_the_configured_sender_still_wins(base_url):
    """The fix must not quietly pin everyone to the default."""
    prev = db.get_setting("portal_apprSenderProc", "")
    try:
        db.set_setting("portal_apprSenderProc", "  site@humiley.com  ")
        assert app.Handler._dr_mail_sender(app.Handler) == "site@humiley.com"
    finally:
        db.set_setting("portal_apprSenderProc", prev)
