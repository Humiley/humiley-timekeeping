"""Deleting a project must not strip a live job of its evidence.

_coll_delete removed the pm_projects row and nothing else: every pm_* child keyed on projectId
simply stopped being reachable. One confirm dialog stood between a project manager and a job's
signed variation orders and certified interim payment certificates — the artefacts a client or an
arbitrator asks for. hrdocs already refuses on this reasoning; projects did not.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("pm_projects", "pm_changes", "pm_tasks", "pm_procurement_payments"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _project(pid="pj-1"):
    db.put_collection_item("pm_projects", {"id": pid, "name": "Cleanroom Fit-out", "status": "Active"})
    return pid


def test_a_project_with_children_is_refused_not_emptied(api, tokens):
    pid = _project()
    db.put_collection_item("pm_tasks", {"id": "t1", "projectId": pid, "title": "Ducting"})
    st, b = api("DELETE", "/api/coll/pm_projects/" + pid, tokens["admin"])
    assert st == 409, b
    assert "Closed or Archived" in b.get("error", "")
    assert db.get_collection_item("pm_projects", pid), "the project must still be there"
    assert db.get_collection_item("pm_tasks", "t1"), "and so must its child"


def test_the_refusal_names_signed_evidence_specifically(api, tokens):
    """A signed variation is contract evidence, not working data — the message has to say so, or the
    person deciding cannot tell a scratch project from a job with certified money in it."""
    pid = _project()
    db.put_collection_item("pm_changes", {"id": "vo1", "projectId": pid, "title": "VO-01",
                                          "signatures": [{"by": "Nguyen Duc Huy"}]})
    db.put_collection_item("pm_procurement_payments", {"id": "ipc1", "projectId": pid,
                                                       "certifiedBy": "Nguyen Duc Huy"})
    st, b = api("DELETE", "/api/coll/pm_projects/" + pid, tokens["admin"])
    assert st == 409
    err = b.get("error", "")
    assert "signature or certification" in err, err
    assert db.get_collection_item("pm_changes", "vo1")
    assert db.get_collection_item("pm_procurement_payments", "ipc1")


def test_an_empty_project_can_still_be_deleted(api, tokens):
    """A guard that refuses everything is not a guard — a mistyped project with nothing under it
    must still be removable."""
    pid = _project("pj-empty")
    st, _ = api("DELETE", "/api/coll/pm_projects/" + pid, tokens["admin"])
    assert st == 200
    assert not db.get_collection_item("pm_projects", pid)


def test_another_projects_children_do_not_block_this_one(api, tokens):
    """Scoping: the count must be keyed on projectId, not on the collection being non-empty."""
    keep = _project("pj-keep")
    db.put_collection_item("pm_tasks", {"id": "t9", "projectId": keep, "title": "Elsewhere"})
    gone = _project("pj-gone")
    st, b = api("DELETE", "/api/coll/pm_projects/" + gone, tokens["admin"])
    assert st == 200, b
    assert db.get_collection_item("pm_tasks", "t9"), "the other project's work is untouched"
