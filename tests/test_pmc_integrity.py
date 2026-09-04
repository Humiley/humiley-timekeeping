"""PMC record integrity: variation orders, payment certificates and NCR close-out.

These three were the least protected records in the system, which is backwards — a variation order
and an interim payment certificate are where money and time actually move on a construction contract,
and they are the first documents a dispute or an audit asks for. A 200,000₫ taxi claim was better
guarded than a 500M₫ variation:

  * the signature object was built in the BROWSER, so the signer's name was whatever the client sent;
  * the manager gate lived only on screen, and pm_changes is staff-writable, so any staff account with
    PM access could PATCH a decision plus an arbitrary signer name onto any CR;
  * the figures could be edited after signing while the ✍ kept rendering;
  * and the signed-record delete guard covered claims / travel / payments — and nothing else.

Signing now goes through /api/esign like every other controlled record: the server re-authenticates
the signer, stamps their identity, and freezes what was signed.

The NCR half is the same idea one register over. Closing a nonconformance gates retention release and
handover, so it takes a recorded disposition and a signed verification — not a button that quietly set
the result to "Pass" with nothing recorded about who decided that.
"""
import os
import re

import pytest
import app
import db

# Every pm_ row below writes to project "P1" on a staff token, and pm_ writes are now scoped by
# project membership — so the fixture states the membership these scenarios always assumed.
pytestmark = pytest.mark.usefixtures("staff_on_p1")

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")


def _src():
    with open(IDX, encoding="utf-8") as fh:
        return fh.read()


def _row(coll, iid):
    return next(x for x in db.list_collection(coll) if x.get("id") == iid)


def _mk(api, token, coll, body):
    st, b = api("POST", "/api/coll/" + coll, token, body)
    assert st == 200, b
    return b["item"]["id"]


def _sign(api, token, coll, iid, status, meaning="test"):
    return api("POST", "/api/esign", token,
               {"coll": coll, "id": iid, "meaning": meaning, "setStatus": status})


def _cr(api, tokens, title="Extra ductwork"):
    return _mk(api, tokens["staff"], "pm_changes",
               {"crNo": "CR-001", "title": title, "type": "Scope",
                "impactCost": 500_000_000, "impactScheduleDays": 30, "projectId": "P1"})


def _ipc(api, tokens, ref="IPC-001"):
    return _mk(api, tokens["mgr"], "pm_procurement_payments",
               {"certNo": ref, "period": "2026-07", "grossClaimed": 900_000_000,
                "netCertified": 800_000_000, "status": "Submitted", "projectId": "P1"})


# ── who may decide ────────────────────────────────────────────────────────────────────────────────

def test_a_manager_can_decide_and_the_server_stamps_who(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    cid = _cr(api, tokens)
    st, b = _sign(api, tokens["mgr"], "pm_changes", cid, "Approved")
    assert st == 200, b
    r = _row("pm_changes", cid)
    assert r["decision"] == "Approved"
    assert r["decidedBy"] == "Dept Manager", "the signer must come from the session, not the browser"
    assert r.get("decidedOn"), "the decision date must be stamped"
    assert len(r.get("signatures") or []) == 1


def test_staff_cannot_decide_a_change_request(api, tokens, monkeypatch):
    """The gate used to exist only in the browser — and pm_changes is staff-writable."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    cid = _cr(api, tokens, "Staff tries to self-approve")
    st, b = _sign(api, tokens["staff"], "pm_changes", cid, "Approved")
    assert st == 403, (st, b)
    assert "manager" in (b.get("error") or "").lower()
    assert _row("pm_changes", cid).get("decidedBy") is None


def test_a_forged_signer_name_never_reaches_the_record(api, tokens, monkeypatch):
    """The old path took `{name: me, by: me}` straight from the client."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    cid = _cr(api, tokens, "Forgery attempt")
    st, b = api("PATCH", "/api/coll/pm_changes/" + cid, tokens["staff"],
                {"id": cid, "crNo": "CR-001", "title": "Forgery attempt",
                 "decision": "Approved", "decidedBy": "Managing Director",
                 "decidedOn": "2026-01-01",
                 "signatures": [{"name": "Managing Director", "meaning": "Change Request Approved"}]})
    assert st == 200, b     # the edit itself is fine; the signature fields must simply not stick
    r = _row("pm_changes", cid)
    assert not r.get("signatures"), "a signature must never arrive through the generic write path"
    assert r.get("decidedBy") is None, "signer identity must never arrive through the generic path"


# ── what a signature freezes ──────────────────────────────────────────────────────────────────────

def test_a_signed_variation_cannot_be_re_priced(api, tokens, monkeypatch):
    """The headline defect: sign for +500M / +30d, then quietly edit the figures."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    cid = _cr(api, tokens, "Re-price me")
    assert _sign(api, tokens["mgr"], "pm_changes", cid, "Approved")[0] == 200
    st, b = api("PATCH", "/api/coll/pm_changes/" + cid, tokens["staff"],
                {"id": cid, "crNo": "CR-001", "title": "Re-price me",
                 "impactCost": 5_000_000_000, "impactScheduleDays": 300})
    assert st == 403, (st, b)
    r = _row("pm_changes", cid)
    assert r["impactCost"] == 500_000_000, "the signed figure moved"
    assert r["impactScheduleDays"] == 30


def test_a_signed_variation_cannot_be_deleted(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    cid = _cr(api, tokens, "Delete me")
    assert _sign(api, tokens["mgr"], "pm_changes", cid, "Approved")[0] == 200
    for who in ("staff", "mgr", "admin"):
        st, b = api("DELETE", "/api/coll/pm_changes/" + cid, tokens[who])
        assert st == 403, (who, st, b)
    assert _row("pm_changes", cid)["decision"] == "Approved"


def test_an_unsigned_change_request_is_still_freely_editable(api, tokens):
    """Freezing signed records must not turn the register read-only while it is still a draft."""
    cid = _cr(api, tokens, "Still a draft")
    st, b = api("PATCH", "/api/coll/pm_changes/" + cid, tokens["staff"],
                {"id": cid, "crNo": "CR-001", "title": "Still a draft", "impactCost": 1_000})
    assert st == 200, b
    assert _row("pm_changes", cid)["impactCost"] == 1_000


# ── payment certificates ──────────────────────────────────────────────────────────────────────────

def test_certifying_stamps_the_certifier(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _ipc(api, tokens)
    st, b = _sign(api, tokens["mgr"], "pm_procurement_payments", pid, "Certified")
    assert st == 200, b
    r = _row("pm_procurement_payments", pid)
    assert r["status"] == "Certified" and r["certifiedBy"] == "Dept Manager" and r.get("certDate")


def test_a_certified_certificate_may_still_be_recorded_as_paid(api, tokens, monkeypatch):
    """Payment is a later fact about the document, not a change to what was certified."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _ipc(api, tokens, "IPC-PAID")
    assert _sign(api, tokens["mgr"], "pm_procurement_payments", pid, "Certified")[0] == 200
    st, b = api("PATCH", "/api/coll/pm_procurement_payments/" + pid, tokens["mgr"],
                {"id": pid, "certNo": "IPC-PAID", "status": "Paid"})
    assert st == 200, b
    r = _row("pm_procurement_payments", pid)
    assert r["status"] == "Paid"
    assert r["netCertified"] == 800_000_000, "marking paid must not rewrite the certified amount"
    assert r["certifiedBy"] == "Dept Manager"


def test_the_paid_exception_cannot_smuggle_an_amount_change(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _ipc(api, tokens, "IPC-SMUG")
    assert _sign(api, tokens["mgr"], "pm_procurement_payments", pid, "Certified")[0] == 200
    st, b = api("PATCH", "/api/coll/pm_procurement_payments/" + pid, tokens["mgr"],
                {"id": pid, "certNo": "IPC-SMUG", "status": "Paid", "netCertified": 9_000_000_000})
    assert st == 200, b     # the Paid transition is allowed …
    assert _row("pm_procurement_payments", pid)["netCertified"] == 800_000_000, \
        "… but only the status may change with it"


# ── NCR close-out ─────────────────────────────────────────────────────────────────────────────────

def _ncr(api, token, ref="QA-NCR-1", **kw):
    body = {"refNo": ref, "title": "Rebar spacing out of tolerance", "type": "NCR",
            "severity": "Major", "status": "Open", "projectId": "P1"}
    body.update(kw)
    return _mk(api, token, "pm_quality", body)


def test_closing_an_ncr_records_who_verified_it(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    qid = _ncr(api, tokens["staff"])
    st, b = _sign(api, tokens["staff"], "pm_quality", qid, "Closed", "NCR verified & closed — Rework")
    assert st == 200, b
    r = _row("pm_quality", qid)
    assert r["status"] == "Closed"
    assert r["verifiedBy"] == "Staff One" and r.get("verifiedOn") and r.get("closedDate")
    assert r["result"] == "Closed", "a closed NCR must never be recorded as a bare Pass"


def test_the_assignee_can_close_an_ncr_they_did_not_raise(api, tokens, monkeypatch):
    """The normal case on site. The e-sign ownership gate only knew about empId / createdById, so a
       QA engineer could never sign the closure of an NCR someone else logged."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    qid = _ncr(api, tokens["mgr"], "QA-NCR-2", assignedTo="Staff One")
    st, b = _sign(api, tokens["staff"], "pm_quality", qid, "Closed")
    assert st == 200, b
    assert _row("pm_quality", qid)["verifiedBy"] == "Staff One"


def test_an_unrelated_staff_member_still_cannot_close_it(api, tokens, monkeypatch):
    """Widening ownership to the named parties must not open it to everyone."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    qid = _ncr(api, tokens["mgr"], "QA-NCR-3", assignedTo="Staff One")
    st, b = _sign(api, tokens["other"], "pm_quality", qid, "Closed")
    assert st == 403, (st, b)
    assert _row("pm_quality", qid)["status"] != "Closed"


def test_a_verification_signature_cannot_be_forged_by_patch(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    qid = _ncr(api, tokens["staff"], "QA-NCR-4")
    st, b = api("PATCH", "/api/coll/pm_quality/" + qid, tokens["staff"],
                {"id": qid, "refNo": "QA-NCR-4", "type": "NCR", "status": "Closed",
                 "verifiedBy": "Managing Director", "verifiedOn": "2026-01-01",
                 "signatures": [{"name": "Managing Director"}]})
    assert st == 200, b
    r = _row("pm_quality", qid)
    assert r.get("verifiedBy") is None and not r.get("signatures")


def test_a_closed_ncr_stays_editable_for_evidence(api, tokens, monkeypatch):
    """A QA register legitimately gains photos and notes after closure — freezing it would be wrong.
       Only WHO verified it is immutable."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    qid = _ncr(api, tokens["staff"], "QA-NCR-5")
    assert _sign(api, tokens["staff"], "pm_quality", qid, "Closed")[0] == 200
    st, b = api("PATCH", "/api/coll/pm_quality/" + qid, tokens["staff"],
                {"id": qid, "refNo": "QA-NCR-5", "type": "NCR", "status": "Closed",
                 "description": "Photos attached after close-out", "verifiedBy": "Someone Else"})
    assert st == 200, b
    r = _row("pm_quality", qid)
    assert r["description"] == "Photos attached after close-out"
    assert r["verifiedBy"] == "Staff One", "the verifier must survive a later edit"


# ── the browser side of the same guarantees ───────────────────────────────────────────────────────

def test_the_browser_no_longer_builds_the_signature_itself():
    src = _src()
    assert "tkESign({" in src.split("function pmSignDecisionSave")[1][:1200], \
        "the PM decision must go through the shared e-sign path"
    body = src.split("function pmSignDecisionSave")[1][:1600]
    assert "method: 'PATCH'" not in body, "signing must not write through the generic collection PATCH"
    assert "image: img" not in body, "the client must not construct the signature object"


def test_an_ncr_is_never_closed_as_pass_by_a_button():
    src = _src()
    body = src.split("async function pmCloseToday")[1][:700]
    assert "pmNcrClose(id); return;" in body, \
        "a nonconformance must be routed to the verified close-out, not auto-passed"
    assert "function pmNcrClose(" in src and "function pmNcrCloseSave(" in src


def test_the_ncr_register_shows_owner_due_and_verifier():
    """All three were captured and displayed nowhere."""
    src = _src()
    reg = src.split("function pmRenderQuality")[1][:6000]
    for col in ("'Owner / Due'", "'Disposition'", "'Verified'", "'NCRs overdue'"):
        assert col in reg, "missing register column/KPI: " + col


def test_ncrs_reach_my_project_actions():
    src = _src()
    assert "'pm_quality_itp', 'pm_quality']" in src, "pm_quality must be loaded for My Actions"
    assert "sec('NCRs to close out'" in src


# ── the charter's scope paragraphs ────────────────────────────────────────────────────────────────

def test_the_charter_form_can_finally_fill_its_own_scope_section():
    """The Charter PDF printed a section headed "Assumptions & Constraints" followed by a literal '-'
       on every project ever exported, and the on-screen Scope card told users to fill it via the Edit
       button — which had no such fields. Exclusions and assumptions are the paragraphs you quote back
       when defending a variation claim or an extension-of-time notice."""
    src = _src()
    # To the END of the form, not a fixed number of characters. A character window silently stops
    # covering the last fields the moment anybody adds one — which is exactly how this test came to
    # fail over `constraints` on a change that added two unrelated contract fields above it.
    after = src.split("pm_projects: { title: 'Project Charter'")[1]
    # To the NEXT schema entry, not to the first `] },` — a select field's inline `options: [...] },`
    # matches that too, which cut the slice off in the middle of the form.
    spec = after[:re.search(r"\n  [a-z_]+: \{ title:", after).start()]
    for k in ("scopeInclusions", "scopeExclusions", "scopeAssumptions", "constraints"):
        assert "k: '%s'" % k in spec, "the project form still cannot capture " + k


def test_the_charter_pdf_reads_the_field_the_form_writes():
    """`assumptions` and `scopeAssumptions` were two orphan names for one concept — fill one and the
       other stayed blank."""
    src = _src()
    pdf = src.split("function pmCharterPDF")[1][:3000]
    assert "p.scopeAssumptions || p.assumptions" in pdf, "the PDF must accept either name"
    assert "['Inclusions', p.scopeInclusions" in pdf and "['Exclusions', p.scopeExclusions" in pdf
    card = src.split("function pmRenderScope")[1][:2500]
    assert "p.scopeAssumptions || p.assumptions" in card, "the on-screen card must agree with the PDF"
