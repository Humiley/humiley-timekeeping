# -*- coding: utf-8 -*-
"""Why a Detail Schedule could not be cleaned up: "You can only delete your own records."

Every `pm_*` row below the project is PROJECT data — a schedule activity, a detail line, a risk, an
RFI. The delete guard judged them with the rule written for claims and travel, on a definition of
"own" that could not work for them:

    owner_id = existing.get("empId") or existing.get("createdById")
    owner_nm = existing.get("owner") or existing.get("name")

For a `pm_detail` row there is no empId, and `name` is the name of the WORK ("Cốp pha sàn"), so the
fallback compared a task name to a person's name and always decided no. A 400-line programme
imported by one engineer was undeletable by everyone else, the project manager included.

It was also incoherent with the write path: `_coll_update` has no ownership guard for `pm_*` at all,
so those same people could already blank the row's name, its dates and its progress. Being able to
destroy a record's contents but not the record is an obstacle, not a protection.

The rule now: you may delete a project's records if the project is one of YOURS — you manage it or
you are on its Team — which is exactly the test `_pm_visible_projects` already applies to READING
them. That is a deliberate widening, so both halves are pinned below: the people who gained the
ability, and the people who must not have.
"""
import app
import db
import pytest


@pytest.fixture
def proj():
    p = db.put_collection_item("pm_projects", {"name": "ZZ Delete Scope", "manager": "Tran Van Minh"})
    yield p
    for coll in ("pm_detail", "pm_tasks", "pm_resources"):
        for r in db.list_collection(coll):
            if r.get("projectId") == p["id"]:
                try:
                    db.delete_collection_item(coll, r["id"])
                except Exception:
                    pass
    try:
        db.delete_collection_item("pm_projects", p["id"])
    except Exception:
        pass


def _row(pid, **kw):
    r = {"projectId": pid, "name": "Cốp pha sàn", "createdById": "SOMEBODY-ELSE",
         "createdBy": "Nguyen Van An"}
    r.update(kw)
    return db.put_collection_item("pm_detail", r)


class _H(app.Handler):
    """The guard under test, without a socket. _coll_delete only needs the request user and the
    stored record, and returning the tuple its _err/_json produce is enough to read the verdict."""
    def __init__(self):
        pass

    def _json(self, obj, status=200):
        return ("json", status, obj)

    def _err(self, msg, status=400):
        return ("err", status, msg)


def _delete_as(user, iid, coll="pm_detail"):
    return _H()._coll_delete(user, coll, iid)


STAFF = {"id": "U-STAFF", "name": "Le Thi Hoa", "role": "staff", "level": "viewer"}
PM = {"id": "U-PM", "name": "Tran Van Minh", "role": "staff", "level": "viewer"}
TEAMMATE = {"id": "U-TEAM", "name": "Pham Quoc Bao", "role": "staff", "level": "viewer"}
BOSS = {"id": "U-BOSS", "name": "Do Van Hung", "role": "manager", "level": "manager"}


# ── the people who gained the ability ───────────────────────────────────────────────────────────
def test_the_project_manager_can_delete_a_line_somebody_else_imported(base_url, proj):
    """The whole finding. Before this the answer was 403 for every row of a 400-line import."""
    r = _row(proj["id"])
    kind, status, msg = _delete_as(PM, r["id"])
    assert kind != "err", "the project's own manager was refused: %s" % (msg,)
    assert db.get_collection_item("pm_detail", r["id"]) is None


def test_a_team_member_can_too(base_url, proj):
    db.put_collection_item("pm_resources", {"projectId": proj["id"], "empId": TEAMMATE["id"],
                                            "name": TEAMMATE["name"]})
    r = _row(proj["id"])
    kind, status, msg = _delete_as(TEAMMATE, r["id"])
    assert kind != "err", "somebody on the project Team was refused: %s" % (msg,)


def test_manager_level_can_delete_across_the_portfolio(base_url, proj):
    """Manager level and above READ the whole portfolio (_pm_visible_projects returns None for
    them), so refusing them the delete would be a rule that contradicts the one beside it."""
    r = _row(proj["id"])
    kind, status, msg = _delete_as(BOSS, r["id"])
    assert kind != "err", msg


def test_the_creator_still_can(base_url, proj):
    """Not a regression: whoever imported the rows keeps what they had — but only because they are
    on the project, not because they typed it."""
    db.put_collection_item("pm_resources", {"projectId": proj["id"], "empId": "U-IMPORTER",
                                            "name": "Nguyen Van An"})
    r = _row(proj["id"], createdById="U-IMPORTER")
    kind, status, msg = _delete_as({"id": "U-IMPORTER", "name": "Nguyen Van An",
                                    "role": "staff", "level": "viewer"}, r["id"])
    assert kind != "err", msg


# ── the people who must NOT have ────────────────────────────────────────────────────────────────
def test_somebody_not_on_the_project_is_still_refused(base_url, proj):
    """The half that makes this a scope change rather than an opening. Widening 'creator' to
    'anyone' would have been the easy fix and the wrong one."""
    r = _row(proj["id"])
    kind, status, msg = _delete_as(STAFF, r["id"])
    assert kind == "err" and status == 403, "a stranger to the project deleted its data"
    assert "project" in msg.lower(), "the refusal should say WHY, so it can be acted on: %r" % msg
    assert db.get_collection_item("pm_detail", r["id"]) is not None


def test_the_creator_is_refused_once_they_are_off_the_project(base_url, proj):
    """Creator identity is no longer the test in EITHER direction. Somebody who left the team does
    not keep a private key to the rows they once typed."""
    r = _row(proj["id"], createdById=STAFF["id"], createdBy=STAFF["name"])
    kind, status, msg = _delete_as(STAFF, r["id"])
    assert kind == "err" and status == 403, \
        "the old rule would have allowed this purely because they created it"


def test_a_pm_row_with_no_project_is_refused(base_url):
    """An orphan cannot be matched against any project, so there is no basis to allow it. Failing
    open here would make `projectId: ""` a universal key."""
    r = db.put_collection_item("pm_detail", {"name": "Orphan"})
    try:
        kind, status, msg = _delete_as(STAFF, r["id"])
        assert kind == "err" and status == 403
    finally:
        try:
            db.delete_collection_item("pm_detail", r["id"])
        except Exception:
            pass


# ── nothing above this guard was weakened ───────────────────────────────────────────────────────
def test_a_signed_variation_order_is_still_undeletable(base_url, proj):
    """pm_changes and pm_procurement_payments are contract evidence. Their refusal sits ABOVE the
    ownership block, so widening the ownership block must not reach them — including for the
    project manager, who is exactly the person who would want to."""
    c = db.put_collection_item("pm_changes", {"projectId": proj["id"], "title": "ZZ VO",
                                              "signatures": [{"name": "X", "meaning": "Approved"}]})
    try:
        kind, status, msg = _delete_as(PM, c["id"], coll="pm_changes")
        assert kind == "err" and status == 403 and "signed" in msg.lower(), \
            "a signed variation order became deletable: %s" % (msg,)
    finally:
        try:
            db.delete_collection_item("pm_changes", c["id"])
        except Exception:
            pass


def test_a_project_holding_records_is_still_undeletable(base_url, proj):
    """pm_projects deliberately keeps the OLD rule and its own children check — deleting the project
    is a different act from tidying its schedule."""
    _row(proj["id"])
    kind, status, msg = _delete_as(BOSS, proj["id"], coll="pm_projects")
    assert kind == "err" and status == 409, \
        "deleting a live project should still refuse while it holds records: %s" % (msg,)


def test_the_audit_trail_is_still_undeletable(base_url):
    kind, status, msg = _delete_as(BOSS, "anything", coll="audit")
    assert kind == "err" and status == 403


# ── and the rule is actually the visibility one, not a copy of it ───────────────────────────────
def test_the_guard_reuses_pm_visible_projects(base_url):
    """Two independent definitions of "is this project mine" would drift, and the pair that drifts
    silently is read-allowed / delete-refused — a screen full of rows with a button that 403s, which
    is precisely the bug this replaced."""
    src = open(app.__file__, encoding="utf-8").read()
    lines = src.splitlines()
    start = next(n for n, l in enumerate(lines) if l.strip().startswith("def _coll_delete("))
    # _coll_delete is the LAST method in the class, so "up to the next `    def `" finds nothing and
    # slicing to EOF would run over hundreds of lines of module-level code — the mistake that once
    # made an unrelated test convict correct code. End at the first line that leaves the method's
    # indentation instead, and say how long the body was so the assertions below are visibly about
    # the method and not about the file.
    end = next((n for n in range(start + 1, len(lines))
                if lines[n].strip() and not lines[n].startswith("        ")), len(lines))
    body = "\n".join(lines[start:end])
    # The method is ~180 lines. The bound is a runaway check, not a line-count assertion: it catches
    # a slice that grabbed one line or ran to EOF, without failing every time somebody adds a guard.
    n = len(body.splitlines())
    assert body.rstrip().endswith('return self._json({"ok": True})'), \
        "the slice does not end at the method's last statement (%d lines) — fix it before trusting it" % n
    assert 80 < n < 400, "extracted %d lines for _coll_delete — the slice is wrong" % n
    assert "_pm_visible_projects(u)" in body, \
        "the delete scope must be the same function the read scope uses"
    assert 'name.startswith("pm_") and name != "pm_projects"' in body
