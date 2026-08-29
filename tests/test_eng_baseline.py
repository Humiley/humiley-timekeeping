"""The plan a slipping programme cannot quietly rewrite.

Before this, "are we on schedule?" was answered from the LIVE plannedIssue dates. The planned
percentage, the SPI and the overdue count all read the same field an engineer edits when a drawing
slips — so moving one date made the deliverable stop being overdue, put SPI back to 1.00, cleared
the Needs-attention line, and left nothing behind saying the plan had moved. No bad intent is
required: updating a date to something realistic is the job. The measure that exists to detect
slippage was erased by the act of absorbing it.

A baseline is a photograph of the planned dates at a moment somebody stands behind. Three
properties matter more than the feature.

It is SERVER-WRITTEN. A plan a browser can write is a plan the person being measured can choose,
and then the schedule says whatever is convenient.

It is IMMUTABLE, and it is not deletable. Deleting an inconvenient baseline and taking a fresh one
is editing it in two steps. Baselines accumulate; the newest governs; the older ones are the record
of how many times the plan was re-cut, which is the number a design manager actually needs.

And taking one NEVER blocks the gate. The baseline is a by-product of a signed decision. If
capturing it fails, the decision still stands — a signature that could be lost to a bookkeeping
step would be a worse bug than having no baseline at all.
"""
import pytest

import app


@pytest.fixture(autouse=True)
def _demo_esign(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _mk(api, token, coll, body):
    st, b = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, b
    return b["item"]


def _sign(api, token, coll, iid, status, meaning="test"):
    return api("POST", "/api/esign", token,
               {"coll": coll, "id": iid, "meaning": meaning, "setStatus": status})


def _baselines(api, token, pid):
    st, b = api("GET", "/api/coll/eng_baselines", token)
    assert st == 200, b
    return sorted([x for x in b["items"] if x.get("projectId") == pid],
                  key=lambda x: x.get("seq") or 0)


@pytest.fixture
def commission(api, tokens):
    return _mk(api, tokens["admin"], "eng_projects", {
        "name": "Baseline commission", "code": "BSL26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})


def _deliv(api, tokens, commission, no, planned, **kw):
    body = {"projectId": commission["id"], "docNo": no, "title": "Doc " + no,
            "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
            "plannedIssue": planned, "weight": "10", "preparedBy": "Alice Engineer",
            "approver": "Staff One"}
    body.update(kw)
    return _mk(api, tokens["staff"], "eng_deliverables", body)


# ── taken by the server, at the moment the plan is agreed ───────────────────────

def test_passing_a_gate_takes_a_baseline(api, tokens, commission):
    """The gate is the only anchor a baseline needs: it is already a signed decision by somebody
    with authority, so nobody has to remember an extra step."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-001", "2026-09-30")
    _deliv(api, tokens, commission, "BSL26-EL-DWG-002", "2026-10-15")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, b

    rows = _baselines(api, tokens["staff"], commission["id"])
    assert len(rows) == 1, "the gate did not take a baseline"
    bl = rows[0]
    assert bl["count"] == 2 and bl["dated"] == 2
    assert bl["gateId"] == g["id"], "the baseline records which gate it came from"
    assert bl["takenBy"] == "Staff One", "and who signed it"
    assert {x["docNo"] for x in bl["lines"]} == {"BSL26-EL-DWG-001", "BSL26-EL-DWG-002"}
    assert {x["plannedIssue"] for x in bl["lines"]} == {"2026-09-30", "2026-10-15"}


def test_a_held_gate_takes_no_baseline(api, tokens, commission):
    """Nothing was agreed, so there is no plan to freeze."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-010", "2026-09-30")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate",
             "gateNotes": "waiting on the client"})
    st, _ = _sign(api, tokens["staff"], "eng_stages", g["id"], "Held")
    assert st == 200
    assert _baselines(api, tokens["staff"], commission["id"]) == []


def test_passed_with_actions_still_takes_one(api, tokens, commission):
    """It is the honest form of a pass, not a lesser one — the stage moves on, so the plan for it
    is agreed and gets frozen like any other."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-011", "2026-09-30")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate",
             "gateActions": "close H-1 before IFC"})
    st, _ = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed with actions")
    assert st == 200
    assert len(_baselines(api, tokens["staff"], commission["id"])) == 1


def test_a_gate_on_a_commission_with_no_deliverables_records_nothing(api, tokens, commission):
    """A baseline of nothing measures nothing, and an empty row would still read as "baselined"
    on every screen that asks whether one exists."""
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, _ = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200
    assert _baselines(api, tokens["staff"], commission["id"]) == []


# ── a browser can never write one ───────────────────────────────────────────────

def test_no_account_can_post_a_baseline(api, tokens, commission):
    """Including an admin. A plan the measured party can write is not a plan."""
    for who in ("staff", "mgr", "admin"):
        st, b = api("POST", "/api/coll/eng_baselines", tokens[who], {
            "projectId": commission["id"], "count": 99, "lines": []})
        assert st != 200, "%s wrote a baseline through the generic API" % who
        assert "gate" in str(b).lower(), "and the refusal says how one is really taken"


def test_a_baseline_cannot_be_edited(api, tokens, commission):
    _deliv(api, tokens, commission, "BSL26-EL-DWG-020", "2026-09-30")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    assert _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")[0] == 200
    bl = _baselines(api, tokens["admin"], commission["id"])[0]

    bl["lines"] = []
    bl["count"] = 0
    st, b = api("PATCH", "/api/coll/eng_baselines/" + bl["id"], tokens["admin"], bl)
    assert st != 200, "a baseline was rewritten"


def test_a_baseline_cannot_be_deleted(api, tokens, commission):
    """Delete-then-retake is edit, in two steps, leaving no trace."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-021", "2026-09-30")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    assert _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")[0] == 200
    bl = _baselines(api, tokens["admin"], commission["id"])[0]

    st, b = api("DELETE", "/api/coll/eng_baselines/" + bl["id"], tokens["admin"])
    assert st != 200, "an admin deleted a baseline"
    assert "new baseline" in str(b).lower(), "and is told what to do instead"


# ── the manual one, for commissions past their gates ────────────────────────────

def test_the_design_authority_can_take_the_first_one(api, tokens, commission):
    """Gates cover the future only. A job already in Detailed Design would otherwise wait months
    for a baseline — which is to say, the jobs that most need one would never get one."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-030", "2026-09-30")
    st, b = api("POST", "/api/eng/baseline", tokens["staff"],
                {"projectId": commission["id"], "reason": "Programme agreed with the client"})
    assert st == 200, b
    assert b["count"] == 1
    rows = _baselines(api, tokens["staff"], commission["id"])
    assert rows[-1]["reason"] == "Programme agreed with the client"
    assert rows[-1]["takenBy"] == "Staff One"


def test_somebody_not_on_the_commission_cannot(api, tokens, commission):
    _deliv(api, tokens, commission, "BSL26-EL-DWG-031", "2026-09-30")
    st, b = api("POST", "/api/eng/baseline", tokens["other"],
                {"projectId": commission["id"], "reason": "why not"})
    assert st != 200, "an engineer on another job re-cut this plan"


def test_a_rebaseline_must_say_why(api, tokens, commission):
    """The count of re-baselines is the number this feature exists to surface. A count with no
    reasons beside it invites exactly one reading."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-032", "2026-09-30")
    st, b = api("POST", "/api/eng/baseline", tokens["staff"], {"projectId": commission["id"]})
    assert st != 200
    assert "why" in str(b).lower()


def test_baselines_accumulate_and_are_numbered(api, tokens, commission):
    """Re-baselining is legitimate and common. What matters is that it is countable."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-040", "2026-09-30")
    for n in (1, 2, 3):
        st, _ = api("POST", "/api/eng/baseline", tokens["staff"],
                    {"projectId": commission["id"], "reason": "re-cut %d" % n})
        assert st == 200
    rows = _baselines(api, tokens["staff"], commission["id"])
    assert [r["seq"] for r in rows] == [1, 2, 3]


def test_an_empty_commission_is_refused_not_silently_baselined(api, tokens):
    empty = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Nothing here yet", "code": "MTY26", "client": "C",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "members": "Staff One"})
    st, b = api("POST", "/api/eng/baseline", tokens["staff"],
                {"projectId": empty["id"], "reason": "too early"})
    assert st != 200
    assert "no deliverables" in str(b).lower()


# ── what it actually records ────────────────────────────────────────────────────

def test_an_undated_deliverable_is_recorded_as_undated(api, tokens, commission):
    """Kept in the snapshot with a blank date rather than left out. A deliverable that had no date
    at baseline and has one now means something different from one added afterwards, and only a
    blank row can tell those apart later."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-050", "2026-09-30")
    _deliv(api, tokens, commission, "BSL26-EL-DWG-051", "")
    st, _ = api("POST", "/api/eng/baseline", tokens["staff"],
                {"projectId": commission["id"], "reason": "with a gap in it"})
    assert st == 200
    bl = _baselines(api, tokens["staff"], commission["id"])[-1]
    assert bl["count"] == 2 and bl["dated"] == 1
    blank = [x for x in bl["lines"] if x["docNo"] == "BSL26-EL-DWG-051"]
    assert blank and blank[0]["plannedIssue"] == ""


def test_a_cancelled_deliverable_is_left_out(api, tokens, commission):
    """It is not part of the plan, and carrying it would make the programme permanently late by
    an amount nobody can ever work off."""
    _deliv(api, tokens, commission, "BSL26-EL-DWG-060", "2026-09-30")
    _deliv(api, tokens, commission, "BSL26-EL-DWG-061", "2026-09-30", creditStatus="Cancelled")
    st, _ = api("POST", "/api/eng/baseline", tokens["staff"],
                {"projectId": commission["id"], "reason": "after a descope"})
    assert st == 200
    bl = _baselines(api, tokens["staff"], commission["id"])[-1]
    assert {x["docNo"] for x in bl["lines"]} == {"BSL26-EL-DWG-060"}


def test_one_commissions_baseline_never_holds_anothers_deliverables(api, tokens, commission):
    other = _mk(api, tokens["admin"], "eng_projects", {
        "name": "Elsewhere", "code": "ELS26", "client": "C2",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "members": "Staff One"})
    _deliv(api, tokens, commission, "BSL26-EL-DWG-070", "2026-09-30")
    _mk(api, tokens["staff"], "eng_deliverables", {
        "projectId": other["id"], "docNo": "ELS26-EL-DWG-001", "title": "Theirs",
        "docType": "Drawing", "discipline": "Electrical", "stage": "Detail",
        "plannedIssue": "2026-09-30"})
    st, _ = api("POST", "/api/eng/baseline", tokens["staff"],
                {"projectId": commission["id"], "reason": "scoped"})
    assert st == 200
    bl = _baselines(api, tokens["staff"], commission["id"])[-1]
    assert all(not x["docNo"].startswith("ELS26") for x in bl["lines"])


# ── and it never costs a signature ──────────────────────────────────────────────

def test_a_failed_capture_never_loses_the_gate_decision(api, tokens, commission, monkeypatch):
    """The worst bug this could have. A baseline is bookkeeping; the gate is the decision."""
    def _boom(*a, **k):
        raise RuntimeError("the baseline store is on fire")
    monkeypatch.setattr(app.Handler, "_eng_take_baseline", _boom, raising=True)

    _deliv(api, tokens, commission, "BSL26-EL-DWG-080", "2026-09-30")
    g = _mk(api, tokens["staff"], "eng_stages",
            {"projectId": commission["id"], "stage": "Detail", "status": "At gate"})
    st, b = _sign(api, tokens["staff"], "eng_stages", g["id"], "Passed")
    assert st == 200, "a signed gate was lost because the baseline threw"
    assert b["item"]["gateSignedBy"] == "Staff One"
