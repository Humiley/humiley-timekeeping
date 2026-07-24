"""Invoice Tracking access-control (company policy: EDITOR + ADMIN only).

A Finance/Approver (management) account may run Payroll + Finance Control but must NOT reach
Invoice Tracking. Editor + Admin may. This pins that boundary across EVERY invtrack gate — read,
status/sync/import, and collection add — so a future refactor can't silently widen access.
"""
import pytest

# (token-key, expected-allowed) for the Invoice Tracking level boundary.
ROLES = [
    ("staff", False),
    ("mgr", False),
    ("management", False),   # Finance/Approver — explicitly excluded
    ("editor", True),
    ("admin", True),
]


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_read(api, tokens, who, allowed):
    st, _ = api("GET", "/api/coll/invtrack", tokens[who])
    if allowed:
        assert st == 200, "%s should be able to read Invoice Tracking" % who
    else:
        assert st == 403, "%s must NOT be able to read Invoice Tracking" % who


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_status(api, tokens, who, allowed):
    st, _ = api("GET", "/api/invtrack/status", tokens[who])
    assert st == (200 if allowed else 403), "%s status gate wrong" % who


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_write(api, tokens, who, allowed):
    st, _ = api("POST", "/api/coll/invtrack", tokens[who],
                {"invNo": "TEST-1", "amount": 100})
    # editor/admin get through the level gate (200); everyone else is 403.
    # (management is the case that matters most — it used to be allowed.)
    if allowed:
        assert st == 200, "%s should be able to add an Invoice Tracking record" % who
    else:
        assert st == 403, "%s must NOT be able to add an Invoice Tracking record" % who


def test_management_can_still_reach_payroll_and_finance(api, tokens):
    """The lockdown is Invoice-Tracking-specific: a Finance/Approver (management) account must
    KEEP its Payroll + Finance access — only Invoice Tracking is walled off."""
    st, _ = api("GET", "/api/coll/payruns", tokens["management"])
    assert st == 200, "management must retain Payroll (payruns) read access"


# --------------------------------------------------------------------------- captured-file serving
def test_invtrack_file_stored_served_and_gated(base_url, tokens):
    """A real invoice attachment captured from the mailbox is stored server-side and served by
    /api/invtrack/file/<id> — content-type correct, Invoice-Tracking-gated, no path traversal."""
    import app
    import urllib.request
    import urllib.error

    sf = app._invtrack_store_file(b"%PDF-1.4\n%demo invoice\n", "demo.pdf", "application/pdf")
    assert sf and sf["kind"] == "pdf" and sf["id"], "store helper must persist + return metadata"
    fid = sf["id"]

    def fetch(path, token):
        req = urllib.request.Request(base_url + path)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers.get("Content-Type"), r.headers.get("X-Content-Type-Options"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, None, None, b""

    # editor may open the file — correct content-type + nosniff, real bytes
    st, ct, nosniff, body = fetch("/api/invtrack/file/" + fid + ".pdf", tokens["editor"])
    assert st == 200 and ct == "application/pdf" and nosniff == "nosniff" and body.startswith(b"%PDF")
    # staff (below the Invoice Tracking level) is blocked
    st, _, _, _ = fetch("/api/invtrack/file/" + fid + ".pdf", tokens["staff"])
    assert st == 403
    # a non-existent / malformed id 404s (and can't traverse)
    st, _, _, _ = fetch("/api/invtrack/file/deadbeef.pdf", tokens["editor"])
    assert st == 404
    st, _, _, _ = fetch("/api/invtrack/file/..%2f..%2fapp.pdf", tokens["editor"])
    assert st in (400, 404)


# --------------------------------------------------------------- SharePoint archive configuration
@pytest.mark.parametrize("who", ["staff", "mgr", "management", "editor"])
def test_sptest_is_admin_only(api, tokens, who):
    """The connection test writes a probe file into the company's SharePoint and is the same
    privilege as setting the link — so EVERY non-admin, including an editor who may otherwise
    use Invoice Tracking, must be refused."""
    st, _ = api("POST", "/api/invtrack/sptest", tokens[who], {})
    assert st == 403, "%s must NOT be able to run the SharePoint connection test" % who


def test_sptest_admin_reports_stages_without_raising(api, tokens):
    """An admin always gets a staged diagnosis rather than an exception — with nothing configured
    it must stop cleanly at the 'config' stage instead of 500ing or hanging on a Graph call."""
    import app
    app.db.set_setting("portal_invtrackSpUrl", "")
    st, body = api("POST", "/api/invtrack/sptest", tokens["admin"], {})
    assert st == 200, "admin should reach the endpoint"
    assert body.get("ok") is False
    stages = body.get("stages") or []
    assert stages and stages[0]["key"] == "config" and stages[0]["ok"] is False
    assert "link" in stages[0]["detail"].lower(), "must tell the admin what to do"


def test_changing_the_folder_link_clears_the_sharepoint_caches(api, tokens):
    """Regression: a wrong link used to be negative-cached for 5 minutes (and the resolved
    site/drive cached indefinitely), so an admin who FIXED the link in Settings saw no effect
    until the container restarted. Saving a new link must reset every cache immediately."""
    import app
    app._INVTRACK_SP.update({"url": "https://old.example/sites/X", "site": "s", "drive": "d", "rel": "r"})
    app._INVTRACK_SP_FAIL.update({"url": "https://old.example/sites/X", "until": 9e9})
    app._INVTRACK_SP_DIRS.add("d|2026/07")

    st, _ = api("PATCH", "/api/portal", tokens["admin"],
                {"invtrackSpUrl": "https://humiley.sharepoint.com/sites/Finance/Shared Documents/Inv"})
    assert st == 200

    assert app._INVTRACK_SP["url"] is None, "resolved site/drive cache must be dropped"
    assert app._INVTRACK_SP_FAIL["url"] == "", "negative cache must be dropped"
    assert not app._INVTRACK_SP_DIRS, "ensured-folder cache must be dropped"
    app.db.set_setting("portal_invtrackSpUrl", "")   # leave the setting as we found it


def test_sp_upload_is_silent_and_free_when_not_configured():
    """With no folder configured the archive must make ZERO Graph calls and must not record a
    failure — otherwise the new health panel would show scary errors for every customer who
    simply hasn't enabled SharePoint."""
    import app
    app.db.set_setting("portal_invtrackSpUrl", "")
    before = dict(app._INVTRACK_SP_HEALTH)
    assert app._invtrack_sp_upload(b"data", "x.pdf", "application/pdf", "2026-07-24") is None
    assert dict(app._INVTRACK_SP_HEALTH) == before, "must not touch health when unconfigured"


def test_graph_err_text_scrubs_token_shaped_strings():
    """The error surfaced in the admin UI must never carry anything token-shaped."""
    import app
    secret = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6Ii1LSTNROW5OUjdiUm9meG1lWm9YcWJIWkdldyJ9"
    txt = app._graph_err_text(Exception("failed for " + secret))
    assert secret not in txt and "…" in txt
    assert len(txt) <= 320


# ------------------------------------------------------------------------ file serving is XSS-safe
def test_mailbox_xml_is_served_as_download_not_scriptable(base_url, tokens):
    """Regression (stored XSS): an XML attachment mailed to hd@humiley.com must NOT come back as an
    inline, scriptable application/xml document in the portal origin. It must download as opaque
    bytes with a sandbox CSP so a crafted XSLT/XHTML can't run JavaScript and steal the token."""
    import app, urllib.request, urllib.error
    evil = b'<?xml version="1.0"?><x>hi</x>'
    sf = app._invtrack_store_file(evil, "HDon.xml", "application/xml")
    assert sf and sf["kind"] == "xml"
    req = urllib.request.Request(base_url + "/api/invtrack/file/" + sf["id"] + ".xml",
                                 headers={"Authorization": "Bearer " + tokens["editor"]})
    with urllib.request.urlopen(req, timeout=10) as r:
        ctype = r.headers.get("Content-Type"); disp = r.headers.get("Content-Disposition")
        csp = r.headers.get("Content-Security-Policy")
    assert ctype == "application/octet-stream", "XML must not be served as a scriptable type"
    assert disp and disp.startswith("attachment"), "XML must download, not render inline"
    assert csp and "sandbox" in csp, "file response must be sandboxed"

    # a PDF may still open inline (it is not script-executable in the page origin)
    sfp = app._invtrack_store_file(b"%PDF-1.4\n", "x.pdf", "application/pdf")
    req = urllib.request.Request(base_url + "/api/invtrack/file/" + sfp["id"] + ".pdf",
                                 headers={"Authorization": "Bearer " + tokens["editor"]})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.headers.get("Content-Type") == "application/pdf"
        assert (r.headers.get("Content-Disposition") or "").startswith("inline")


# ------------------------------------------------------------- SharePoint file naming is collision-proof
def test_sp_leaf_is_content_addressed_and_path_safe():
    """Two invoices sharing the mailbox default name (HoaDon.pdf) must NOT map to the same SharePoint
    file, and a name with a path separator must never escape the Year/Month folder."""
    import app
    a = app._sp_safe_leaf("HoaDon.pdf", "a" * 32)
    b = app._sp_safe_leaf("HoaDon.pdf", "b" * 32)
    assert a != b, "same name + different content must not collide"
    assert a.endswith("HoaDon.pdf") and b.endswith("HoaDon.pdf")
    tricky = app._sp_safe_leaf("../../secret/evil.pdf", "c" * 32)
    assert "/" not in tricky and "\\" not in tricky and ".." not in tricky.split("-", 1)[-1].split(".")[0]


def test_sp_parse_folder_accepts_browser_view_url():
    """An admin who pastes the browser's library view URL (…/Forms/AllItems.aspx?id=…) must resolve to
    the same folder as the clean path form — not to a bogus 'Forms' folder."""
    import app
    host, site, rel = app._sp_parse_folder(
        "https://humiley.sharepoint.com/sites/Finance/Shared Documents/Invoices")
    host2, site2, rel2 = app._sp_parse_folder(
        "https://humiley.sharepoint.com/sites/Finance/Forms/AllItems.aspx"
        "?id=%2Fsites%2FFinance%2FShared%20Documents%2FInvoices&viewid=abc")
    assert (host, site, rel) == (host2, site2, rel2) == ("humiley.sharepoint.com", "/sites/Finance", "Invoices")


# ------------------------------------------------------------------- backfill is admin-only + bounded
@pytest.mark.parametrize("who", ["staff", "editor", "management"])
def test_spbackfill_is_admin_only(api, tokens, who):
    st, _ = api("POST", "/api/invtrack/spbackfill", tokens[who], {})
    assert st == 403, "%s must not run the SharePoint backfill" % who


def test_spbackfill_requires_configuration(api, tokens):
    import app
    app.db.set_setting("portal_invtrackSpUrl", "")
    st, body = api("POST", "/api/invtrack/spbackfill", tokens["admin"], {})
    assert st == 400, "backfill without a configured folder must be a clean 400, not a crash"


# --------------------------------------------------------------- GET /api/portal redacts integration URLs
def test_portal_get_redacts_integration_urls_for_staff(api, tokens):
    """A plain staff account must not be able to read the Teams webhook (a posting credential) or the
    Invoice-Tracking SharePoint path from GET /api/portal; admin still sees them."""
    import app
    app.db.set_setting("portal_teamsWebhook", "https://teams.example/hook/SECRET")
    app.db.set_setting("portal_invtrackSpUrl", "https://humiley.sharepoint.com/sites/Finance/Docs")
    app.db.set_setting("portal_financeSpUrl", "https://humiley.sharepoint.com/sites/Finance/Bills")

    st, staff = api("GET", "/api/portal", tokens["staff"])
    assert st == 200
    assert staff.get("teamsWebhook") == "", "staff must not see the Teams webhook"
    assert staff.get("invtrackSpUrl") == "", "staff must not see the Invoice-Tracking SharePoint path"
    assert staff.get("financeSpUrl"), "financeSpUrl stays readable — staff open bills with it"

    st, adm = api("GET", "/api/portal", tokens["admin"])
    assert adm.get("teamsWebhook") == "https://teams.example/hook/SECRET"
    assert adm.get("invtrackSpUrl") == "https://humiley.sharepoint.com/sites/Finance/Docs"
    # tidy up
    for k in ("portal_teamsWebhook", "portal_invtrackSpUrl", "portal_financeSpUrl"):
        app.db.set_setting(k, "")
