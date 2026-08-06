"""Who may publish a company document.

Gating this on an approval LEVEL was the wrong axis. It locked out the HR officer who actually writes
the policies — she is not an Approver and has no reason to be — while admitting a site manager who
holds the level and has no business committing the whole company to signing something.

So it is a NAMED duty, the same shape as the authorised-payer list: being named IS the grant. An
admin always qualifies, listed or not, so no configuration can lock the company out of its own
documents and an admin can step in when HR is away. With nobody named it falls back to the level
rule, so an install that never sets this keeps working.
"""
import app
import db


STAFF_EMAIL = "staff1@humiley.com"   # HML-STF, plain staff — no level, no approval rights
MGR_EMAIL = "mgr@humiley.com"


def _as_hr(email):
    db.set_setting("portal_hrAdmins", email)


def _doc_body(**kw):
    b = {"title": "Employee Handbook", "code": "HML-HR-900", "version": "1.0", "audience": "All",
         "file": "data:application/pdf;base64,JVBERi0xLjQK", "fileName": "handbook.pdf"}
    b.update(kw)
    return b


# ── being named is the grant ─────────────────────────────────────────────────────────────────────

def test_a_named_hr_person_can_publish_without_any_special_level(api, tokens):
    """The whole point: HR publishes policy without being made an Approver."""
    _as_hr(STAFF_EMAIL)
    try:
        st, b = api("POST", "/api/coll/hrdocs", tokens["staff"], _doc_body(code="HML-HR-901"))
        assert st == 200, b
        assert b["item"]["publishedBy"]
    finally:
        db.set_setting("portal_hrAdmins", "")


def test_being_named_also_allows_editing_and_archiving(api, tokens):
    _as_hr(STAFF_EMAIL)
    try:
        _, b = api("POST", "/api/coll/hrdocs", tokens["staff"], _doc_body(code="HML-HR-902"))
        d = b["item"]
        st, b2 = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["staff"], dict(d, owner="Tran Doan"))
        assert st == 200, b2
        st, b3 = api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["staff"], dict(d, archived=True))
        assert st == 200, b3
    finally:
        db.set_setting("portal_hrAdmins", "")


def test_somebody_not_named_is_refused_even_at_manager_level(api, tokens):
    """The list EXCLUDES as well as admits — that is what makes it a duty rather than a rank."""
    _as_hr("someone.else@humiley.com")
    try:
        st, b = api("POST", "/api/coll/hrdocs", tokens["mgr"], _doc_body(code="HML-HR-903"))
        assert st == 403, b
        assert "HR" in (b.get("error") or "")
    finally:
        db.set_setting("portal_hrAdmins", "")


def test_an_admin_can_always_publish_even_when_not_named(api, tokens):
    """No configuration may lock the company out of its own documents, and the admin is the person
    who steps in when HR is away — which is exactly why we are not demanding an Approver exist."""
    _as_hr("only.hr@humiley.com")
    try:
        st, b = api("POST", "/api/coll/hrdocs", tokens["admin"], _doc_body(code="HML-HR-904"))
        assert st == 200, b
    finally:
        db.set_setting("portal_hrAdmins", "")


# ── the unset default must not change behaviour ──────────────────────────────────────────────────

def test_with_nobody_named_it_falls_back_to_the_level_rule(api, tokens):
    db.set_setting("portal_hrAdmins", "")
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"], _doc_body(code="HML-HR-905"))
    assert st == 200, b
    st, _ = api("POST", "/api/coll/hrdocs", tokens["staff"], _doc_body(code="HML-HR-906"))
    assert st == 403, "staff must not publish company policy just because the list is empty"


def test_no_real_email_is_baked_into_the_default(api, tokens):
    """A shipped default would grant strangers HR on every other install — the payer list carries the
    same warning because the test suite once caught exactly that."""
    assert app._APPR_SETTING_DEFAULTS.get("hrAdmins", "") == ""


# ── the list is an authorization list, not public information ────────────────────────────────────

def test_only_an_admin_reads_the_hr_list_back(api, tokens):
    _as_hr(STAFF_EMAIL)
    try:
        _, a = api("GET", "/api/portal", tokens["admin"])
        assert STAFF_EMAIL in (a.get("hrAdmins") or "")
        _, s = api("GET", "/api/portal", tokens["staff"])
        assert (s.get("hrAdmins") or "") == "", "a non-admin must not read the HR allow-list"
    finally:
        db.set_setting("portal_hrAdmins", "")


def test_everyone_is_told_their_own_capability(api, tokens):
    """canPublishDocs is what the UI gates on, so it must agree with the write path exactly —
    otherwise the button appears for somebody the API then refuses."""
    _as_hr(STAFF_EMAIL)
    try:
        _, s = api("GET", "/api/portal", tokens["staff"])
        assert s.get("canPublishDocs") is True
        _, m = api("GET", "/api/portal", tokens["mgr"])
        assert m.get("canPublishDocs") is False
        _, a = api("GET", "/api/portal", tokens["admin"])
        assert a.get("canPublishDocs") is True
    finally:
        db.set_setting("portal_hrAdmins", "")


def test_a_non_admin_cannot_write_themselves_into_the_hr_list(api, tokens):
    """Otherwise the grant is self-service and means nothing."""
    db.set_setting("portal_hrAdmins", "")
    # PATCH is the real settings route — POST 404s, which would make this pass without proving anything.
    st, _ = api("PATCH", "/api/portal", tokens["mgr"], {"hrAdmins": MGR_EMAIL})
    assert (db.get_setting("portal_hrAdmins", "") or "") == "", "only an admin may set who is HR"
    st, _ = api("POST", "/api/coll/hrdocs", tokens["mgr"], _doc_body(code="HML-HR-907"))
    assert st == 403


def test_an_admin_can_set_who_is_hr_through_the_settings_route(api, tokens):
    db.set_setting("portal_hrAdmins", "")
    try:
        st, b = api("PATCH", "/api/portal", tokens["admin"], {"hrAdmins": STAFF_EMAIL})
        assert st == 200, b
        assert (db.get_setting("portal_hrAdmins", "") or "") == STAFF_EMAIL
        st, _ = api("POST", "/api/coll/hrdocs", tokens["staff"], _doc_body(code="HML-HR-908"))
        assert st == 200, "the person just named as HR must be able to publish"
    finally:
        db.set_setting("portal_hrAdmins", "")
