# -*- coding: utf-8 -*-
"""A PATCH that says nothing about the site's reported progress must not delete it.

PATCH on /api/coll is a blind whole-document REPLACE — db.put_collection_item does
`ON CONFLICT(coll,id) DO UPDATE SET data = excluded.data` — so a key the body leaves out is erased
just as surely as one it changes. Three collections already carry a hand-written guard against
exactly this, each added after the same accident: contracts (the signed PDF), candidates (the CV),
hrdocs (the attachment). Every one of those comments describes a list read that blanked a field and
a round trip that then destroyed it.

`log` had no such guard. It is the most valuable field in the Projects module — the site's reported
progress, one entry per day, and the thing every percentage on the Schedule is computed from — and
the field immediately beside it, `qtyPlanLog`, WAS already protected. That asymmetry defended the
audit trail of a scheduled quantity while leaving the measurements themselves exposed.

Why it matters beyond tidiness: every mutating client path builds its PATCH body by spreading a
whole cached row (`Object.assign({}, r, {...})`, or `{...ex, ...data}` in the generic edit form).
So the moment anything causes the cached row to be missing `log` — a slimmer list read, a partial
load, a hand-written integration — the next save of ANY field on that line deletes the history.
Renaming a unit of measure would erase months of reported progress, with a 200 and a success toast.

That is also why this had to land BEFORE any work that makes the list read lighter. It is the
precondition, not a nicety.

ABSENT, not falsy: deleting the only reading on a line legitimately leaves `log: []`, and that must
be honoured rather than treated as "nothing supplied" — otherwise a deletion silently fails and the
reading the user just removed comes back.
"""
import db
import pytest


@pytest.fixture
def line():
    """A detail line carrying real reported progress, the way the site would have left it."""
    proj = db.put_collection_item("pm_projects", {"name": "ZZ Past", "manager": "Admin User"})
    row = db.put_collection_item("pm_detail", {
        "projectId": proj["id"], "name": "Riser A", "category": "HVAC", "unit": "m",
        "qtyPlan": 500,
        "log": [{"d": "2026-08-01", "qty": 100, "pct": 20},
                {"d": "2026-08-02", "qty": 200, "pct": 40},
                {"d": "2026-08-03", "qty": 320, "pct": 64}]})
    yield proj, row
    for coll, rid in (("pm_detail", row["id"]), ("pm_projects", proj["id"])):
        try:
            db.delete_collection_item(coll, rid)
        except Exception:
            pass


def _stored(rid):
    return db.get_collection_item("pm_detail", rid) or {}


def test_a_body_that_omits_the_log_leaves_it_untouched(api, tokens, line):
    """The whole defect in one assertion."""
    _proj, row = line
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A (renamed)",
                 "category": "HVAC", "unit": "m", "qtyPlan": 500})
    assert st == 200
    after = _stored(row["id"])
    assert after.get("name") == "Riser A (renamed)", "the edit itself must still apply"
    assert len(after.get("log") or []) == 3, (
        "the PATCH said nothing about the log, so the three readings must still be there. "
        "got %r — this is months of site progress deleted by renaming a line." % (after.get("log"),))


def test_renaming_the_unit_does_not_delete_the_history(api, tokens, line):
    """pdCellSave's non-quantity branch never rebuilds the log; it only carries what it was given."""
    _proj, row = line
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A", "unit": "lm"})
    assert st == 200
    after = _stored(row["id"])
    assert after.get("unit") == "lm"
    assert len(after.get("log") or []) == 3, (
        "changing a unit of measure is the least-expected way to lose progress and the hardest to "
        "connect back to a cause")


def test_an_explicit_log_is_still_obeyed(api, tokens, line):
    """The guard must not become a wall: filing today's reading has to work."""
    _proj, row = line
    newlog = [{"d": "2026-08-01", "qty": 100, "pct": 20},
              {"d": "2026-08-02", "qty": 200, "pct": 40},
              {"d": "2026-08-03", "qty": 320, "pct": 64},
              {"d": "2026-08-04", "qty": 400, "pct": 80}]
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A", "log": newlog})
    assert st == 200
    after = _stored(row["id"])
    assert len(after.get("log") or []) == 4, "the day's reading must reach the record"
    assert after["log"][-1]["qty"] == 400


def test_an_explicitly_emptied_log_is_obeyed_too(api, tokens, line):
    """ABSENT, not falsy — the distinction this guard turns on.

    Removing the only reading on a line leaves []. A truthiness test would read that as 'nothing
    supplied', restore the old log, and the reading the user just deleted would reappear on the next
    render with no error — a deletion that silently does not happen.
    """
    _proj, row = line
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A", "log": []})
    assert st == 200
    assert (_stored(row["id"]).get("log") or []) == [], (
        "an empty list is a statement, not a silence")


def test_omitting_the_scheduled_quantity_does_not_read_as_a_change_to_zero(api, tokens, line):
    """Found by these very tests failing with 400 before qtyPlan joined the keep-if-unsaid set.

    The guard below this one compares the body's qtyPlan against the stored one to decide whether
    somebody is moving a scheduled quantity that progress has already been reported against. An
    ABSENT qtyPlan read as 0.0 there, so a PATCH that never mentioned it looked like a change from
    500 to nothing — and the two outcomes were both wrong in different directions:

      · on a line WITH readings the whole edit was refused, 400, "say why the scheduled quantity is
        changing", about a quantity nobody had touched;
      · on a line WITHOUT readings it sailed straight through and the quantity was erased.
    """
    _proj, row = line
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A", "unit": "m"})
    assert st == 200, "a rename must not be refused on account of a field it never mentioned"
    assert _stored(row["id"]).get("qtyPlan") == 500


def test_a_line_with_no_readings_does_not_silently_lose_its_quantity(api, tokens):
    """The other half of the same bug — this one had no error to make it visible."""
    proj = db.put_collection_item("pm_projects", {"name": "ZZ Unmeasured", "manager": "Admin User"})
    row = db.put_collection_item("pm_detail", {
        "projectId": proj["id"], "name": "Not started yet", "qtyPlan": 500, "unit": "m", "log": []})
    try:
        st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                    {"projectId": proj["id"], "name": "Not started yet", "unit": "lm"})
        assert st == 200
        assert _stored(row["id"]).get("qtyPlan") == 500, (
            "with no readings the change-of-quantity guard does not fire, so the omission went "
            "straight through and 500 m of planned work became nothing — no error, no audit row, "
            "and every percentage measured against it now divides by zero")
    finally:
        for coll, rid in (("pm_detail", row["id"]), ("pm_projects", proj["id"])):
            try:
                db.delete_collection_item(coll, rid)
            except Exception:
                pass


def test_the_quantity_audit_trail_is_still_protected(api, tokens, line):
    """The guard that already existed must survive the one added beside it."""
    _proj, row = line
    db.put_collection_item("pm_detail", dict(_stored(row["id"]), qtyPlanLog=[
        {"from": 400, "to": 500, "reason": "issued for construction", "by": "PM", "at": "2026-07-01"}]))
    st, _ = api("PATCH", "/api/coll/pm_detail/" + row["id"], tokens["admin"],
                {"projectId": row["projectId"], "name": "Riser A", "qtyPlan": 500})
    assert st == 200
    assert len(_stored(row["id"]).get("qtyPlanLog") or []) == 1


class TestMasterActivities:
    """pm_tasks carries statements about the past too, and the same PATCH shape reaches them."""

    @pytest.fixture
    def task(self):
        proj = db.put_collection_item("pm_projects", {"name": "ZZ PastT", "manager": "Admin User"})
        t = db.put_collection_item("pm_tasks", {
            "projectId": proj["id"], "wbs": "1.1", "name": "Mobilisation",
            "status": "In progress", "baselineFinish": "2026-09-30",
            "signatures": [{"by": "Director", "at": "2026-07-01", "reason": "baseline agreed"}]})
        yield proj, t
        for coll, rid in (("pm_tasks", t["id"]), ("pm_projects", proj["id"])):
            try:
                db.delete_collection_item(coll, rid)
            except Exception:
                pass

    def test_dragging_a_card_cannot_unsign_an_activity(self, api, tokens, task):
        """_pmKanDrop PATCHes the whole task to change one status field."""
        proj, t = task
        st, _ = api("PATCH", "/api/coll/pm_tasks/" + t["id"], tokens["admin"],
                    {"projectId": proj["id"], "wbs": "1.1", "name": "Mobilisation",
                     "status": "Done"})
        assert st == 200
        after = db.get_collection_item("pm_tasks", t["id"]) or {}
        assert after.get("status") == "Done", "the move itself must still apply"
        assert len(after.get("signatures") or []) == 1, (
            "a signature is a statement about what somebody agreed; a status change must not "
            "withdraw it")
        assert after.get("baselineFinish") == "2026-09-30", (
            "the baseline is what variance is measured against — losing it makes every schedule "
            "index silently meaningless rather than visibly wrong")

    def test_an_explicit_change_is_still_allowed(self, api, tokens, task):
        proj, t = task
        st, _ = api("PATCH", "/api/coll/pm_tasks/" + t["id"], tokens["admin"],
                    {"projectId": proj["id"], "wbs": "1.1", "name": "Mobilisation",
                     "baselineFinish": "2026-10-15", "signatures": []})
        assert st == 200
        after = db.get_collection_item("pm_tasks", t["id"]) or {}
        assert after.get("baselineFinish") == "2026-10-15"
        assert (after.get("signatures") or []) == []
