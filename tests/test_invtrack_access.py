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
