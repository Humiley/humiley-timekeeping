# -*- coding: utf-8 -*-
"""The four gates on the only endpoint in this codebase that deletes employees in bulk.

Each test asserts that something did NOT happen. A removal that works is one line; a removal that
refuses everything it should refuse is the reason this endpoint is allowed to exist at all.
"""
import db
import demo_data
import seed_data

PHRASE = "REMOVE SAMPLE DATA"


def _preview(api, tok):
    return api("GET", "/api/admin/demo-data", tok)


def _remove(api, tok, **body):
    return api("POST", "/api/admin/demo-data/remove", tok, body)


# ── who may even look ────────────────────────────────────────────────────────────────────────────
def test_a_manager_cannot_see_the_plan(api, tokens):
    assert _preview(api, tokens["mgr"])[0] == 403


def test_management_cannot_either(api, tokens):
    assert _preview(api, tokens["management"])[0] == 403


def test_an_admin_can(api, tokens):
    st, r = _preview(api, tokens["admin"])
    assert st == 200 and "plan" in r
    assert r["confirmPhrase"] == PHRASE
    assert "Nothing has been changed" in r["note"]


# ── the preview changes nothing ─────────────────────────────────────────────────────────────────
def test_the_preview_is_read_only(api, tokens):
    before = len(db.list_employees())
    _preview(api, tokens["admin"])
    _preview(api, tokens["admin"])
    assert len(db.list_employees()) == before


# ── the gates ───────────────────────────────────────────────────────────────────────────────────
def test_a_manager_cannot_remove(api, tokens):
    before = len(db.list_employees())
    st, _ = _remove(api, tokens["mgr"], confirm=PHRASE, backupConfirmed=True)
    assert st == 403
    assert len(db.list_employees()) == before


def test_no_phrase_no_removal(api, tokens):
    before = len(db.list_employees())
    st, r = _remove(api, tokens["admin"], backupConfirmed=True)
    assert st == 400 and "Nothing has been changed" in r["error"]
    assert len(db.list_employees()) == before


def test_the_wrong_phrase_is_refused(api, tokens):
    before = len(db.list_employees())
    for wrong in ("remove sample data", "REMOVE SAMPLE DATA ", "yes", "DELETE"):
        st, _ = _remove(api, tokens["admin"], confirm=wrong, backupConfirmed=True)
        assert st == 400, "%r must not be accepted" % wrong
    assert len(db.list_employees()) == before


def test_without_a_backup_acknowledgement_nothing_happens(api, tokens):
    before = len(db.list_employees())
    st, r = _remove(api, tokens["admin"], confirm=PHRASE)
    assert st == 400 and "backup" in r["error"].lower()
    assert len(db.list_employees()) == before


# ── the caller cannot choose what is deleted ────────────────────────────────────────────────────
def test_the_request_body_cannot_name_rows_to_delete(api, tokens):
    """The plan is re-computed server-side at the moment of deletion. A caller who passes ids, or a
    doctored plan, changes nothing — otherwise this endpoint is a delete-any-employee endpoint with
    a confirmation phrase in front of it."""
    real = db.create_employee({"id": "HML-KEEP", "name": "Real Person",
                               "email": "real.person@humiley.com", "role": "staff", "level": "staff"})
    try:
        st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True,
                        ids=["HML-KEEP"], employees=[{"id": "HML-KEEP"}],
                        plan={"employees": {"demo": [{"id": "HML-KEEP"}]}, "anything": True})
        assert st == 200, r
        assert db.get_employee("HML-KEEP") is not None, \
            "a real employee named in the REQUEST was deleted — the plan is not being re-computed"
    finally:
        if db.get_employee("HML-KEEP"):
            db.delete_employee("HML-KEEP")


def test_a_database_with_no_sample_removes_nothing(api, tokens):
    """The fixture org is HML-* — none of it is the shipped sample — so a full-strength call with
    every gate satisfied must still be a no-op."""
    before = sorted(e["id"] for e in db.list_employees())
    st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert st == 200, r
    assert r["removed"]["employees"] == 0
    assert sorted(e["id"] for e in db.list_employees()) == before


# ── what the plan says about the shipped sample ─────────────────────────────────────────────────
def test_the_protected_administrator_is_never_in_the_plan(api, tokens):
    """EMP001 in the shipped seed carries huy.nguyen@humiley.com, a real super-admin address."""
    e = dict(seed_data.EMPLOYEES[0])
    assert e["email"] == "huy.nguyen@humiley.com"
    p = demo_data.plan([e], [], lambda _i: 5, lambda _i: 1)
    assert p["totals"]["employees"] == 0
    assert p["totals"]["attendance"] == 0, "its attendance must not be counted either"


def test_the_hr_sample_caveat_reaches_the_screen(api, tokens):
    st, r = _preview(api, tokens["admin"])
    assert st == 200
    assert any("belong to REAL people" in n for n in r["plan"]["notes"]), \
        "the thing this cannot identify has to be on the screen somebody decides from"
