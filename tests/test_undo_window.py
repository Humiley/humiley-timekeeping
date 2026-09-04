"""The undo window: for a short time after you sign a decision, you may sign one reversal of it.

People misclick, and before this a misclick was permanent — an approval was final the instant it
landed, and a request approved two minutes after submission could never be corrected by anybody.

The design constraint that shapes every test below: **an e-signature must never silently become
untrue.** So an undo does not edit the record and pretend nothing happened. It appends a REVERSAL
signature; the original stays exactly where it is, saying exactly what it said, and simply stops
counting. The audit log gains a row and never loses one.

The things that must remain impossible are the point of this file, not a footnote:

  * undoing somebody else's signature — including as an admin;
  * undoing after the window, or with a clock rewound;
  * undoing when anything at all happened to the record after you signed;
  * undoing an undo, or a submission, or an amendment;
  * using an undo to launder your way around the two-person rule;
  * a reversed payment presenting to the next payer as though it had never been released;
  * losing the bank slip that proves a payment happened.
"""
import time

import pytest
import app
import db

# Every pm_ row below writes to project "P1" on a staff token, and pm_ writes are now scoped by
# project membership — so the fixture states the membership these scenarios always assumed.
pytestmark = pytest.mark.usefixtures("staff_on_p1")

PDF = "data:application/pdf;base64,QQ=="
SLIP = "data:application/pdf;base64,YmFuay1zbGlw"


def _pay(api, tokens, ref, who="staff"):
    st, b = api("POST", "/api/coll/payments", tokens[who],
                {"reqNo": ref, "payee": "Vendor", "amount": 1000, "attachment": PDF})
    assert st == 200, b
    return b["item"]["id"]


def _row(coll, iid):
    return next(x for x in db.list_collection(coll) if x.get("id") == iid)


def _sign(api, token, coll, iid, status, meaning="act", attach=None):
    body = {"coll": coll, "id": iid, "meaning": meaning, "setStatus": status}
    if attach:
        body["attach"] = attach
    return api("POST", "/api/esign", token, body)


def _undo(api, token, coll, iid, reason=None):
    body = {"coll": coll, "id": iid, "meaning": "Undo", "undo": True}
    if reason:
        body["undoReason"] = reason
    return api("POST", "/api/esign", token, body)


# ── it works ──────────────────────────────────────────────────────────────────────────────────────

def test_you_can_take_back_an_approval_you_just_signed(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-1")
    assert _sign(api, tokens["management"], "payments", pid, "Approved")[0] == 200
    assert _row("payments", pid)["status"] == "Approved"
    st, b = _undo(api, tokens["management"], "payments", pid)
    assert st == 200 and b.get("undone") is True, b
    r = _row("payments", pid)
    # Restored to EXACTLY what was there before — a freshly raised payment carries no status key at
    # all, and putting one back would be inventing history rather than undoing it. What matters is
    # that the approval engine sees it as pending again.
    assert app.Handler._appr_state(r.get("status")) == "submit", r.get("status")
    assert not r.get("approvedBy"), "the approver stamp was removed with the decision"


def test_the_original_signature_survives_and_the_reversal_is_appended(api, tokens, monkeypatch):
    """Part 11: nothing is ever deleted or rewritten. The trail grows; it never shrinks."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-2")
    _sign(api, tokens["management"], "payments", pid, "Approved", "Approve — PR-UNDO-2")
    before = list(_row("payments", pid)["signatures"])
    assert _undo(api, tokens["management"], "payments", pid)[0] == 200
    after = _row("payments", pid)["signatures"]
    assert after[:len(before)] == before, "an existing signature changed — that must never happen"
    assert len(after) == len(before) + 1
    rev = after[-1]
    assert rev["undo"] is True and rev["undoKind"] == "reversal"
    assert rev["voidsIndex"] == len(before) - 1
    assert "Approve — PR-UNDO-2" in rev["meaning"]
    assert "setStatus" not in rev, "a reversal must not read as a decision to the SoD checks"


def test_the_response_hands_the_client_the_servers_own_deadline(api, tokens, monkeypatch):
    """The browser clock is not the clock the window is measured against, so it is told the answer."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-HINT")
    st, b = _sign(api, tokens["management"], "payments", pid, "Approved")
    assert st == 200, b
    hint = b.get("undo")
    assert hint and hint["can"] is True and hint["label"] == "Approved"
    assert hint["seconds"] == app.Handler.UNDO_WINDOW_SEC
    assert hint["until"].endswith("Z") and hint["needsReason"] is False


def test_an_audit_row_is_written_and_the_original_one_stays(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-AUD")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    _undo(api, tokens["management"], "payments", pid)
    rows = [a for a in db.list_collection("audit") if ("payments/" + pid) in str(a.get("target") or "")]
    assert any(str(a["action"]).startswith("E-signature — ") for a in rows), "original entry lost"
    rev = [a for a in rows if "reversed" in str(a["action"]).lower()]
    assert rev, "no reversal recorded"
    # Must keep the literal "e-signature" so it appears in the Signature Governance view, which
    # filters on that substring — a reversal that only admins can see is not a trail.
    assert "e-signature" in rev[0]["action"].lower()
    assert "undo · was Approved" in rev[0]["detail"]


# ── who may not ───────────────────────────────────────────────────────────────────────────────────

def test_you_cannot_undo_somebody_elses_signature(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-OTHER")
    assert _sign(api, tokens["management"], "payments", pid, "Approved")[0] == 200
    for who in ("mgr", "editor", "staff"):
        st, b = _undo(api, tokens[who], "payments", pid)
        assert st == 403, (who, st, b)
    assert _row("payments", pid)["status"] == "Approved"


def test_not_even_an_admin_can_undo_for_you(api, tokens, monkeypatch):
    """Undoing is un-saying something you personally attested to. Nobody un-says it on your behalf."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-ADMIN")
    assert _sign(api, tokens["management"], "payments", pid, "Approved")[0] == 200
    st, b = _undo(api, tokens["admin"], "payments", pid)
    assert st == 403, (st, b)
    assert _row("payments", pid)["status"] == "Approved"


# ── the window ────────────────────────────────────────────────────────────────────────────────────

def test_the_window_closes(api, tokens, monkeypatch):
    """Pinned to zero rather than waiting fifteen minutes — the guard is the same one either way."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-LATE")
    assert _sign(api, tokens["management"], "payments", pid, "Approved")[0] == 200
    monkeypatch.setattr(app.Handler, "UNDO_WINDOW_SEC", 0)
    time.sleep(1.1)
    st, b = _undo(api, tokens["management"], "payments", pid)
    assert st == 403 and "window" in (b.get("error") or "").lower(), b
    assert _row("payments", pid)["status"] == "Approved"


def test_a_signature_dated_in_the_future_does_not_open_the_window(api, tokens, monkeypatch):
    """A rewound or skewed clock must fail closed, not hand out an unbounded window."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-SKEW")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    row = _row("payments", pid)
    row["signatures"][-1]["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200))
    db.put_collection_item("payments", row)
    st, b = _undo(api, tokens["management"], "payments", pid)
    assert st == 403, (st, b)


def test_undo_refuses_once_anything_else_has_happened(api, tokens, monkeypatch):
    """Two independent anchors: the status must still be what you set, AND the record's revision must
       be the one your signature produced. The second catches a content-only edit that leaves the
       status alone, which the first cannot see."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-MOVED")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    row = _row("payments", pid)
    row["note"] = "an admin touched this afterwards"
    db.put_collection_item("payments", row)          # bumps _rev, leaves status alone
    st, b = _undo(api, tokens["management"], "payments", pid)
    assert st == 403 and "changed since" in (b.get("error") or "").lower(), b


def test_you_cannot_undo_an_undo(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-TWICE")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    assert _undo(api, tokens["management"], "payments", pid)[0] == 200
    st, b = _undo(api, tokens["management"], "payments", pid)
    assert st == 403, (st, b)


def test_you_cannot_undo_a_submission(api, tokens, monkeypatch):
    """A submission is not a decision — there is nothing to un-say, and withdrawing is a separate
       verb with its own rules."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-SUB")
    assert api("POST", "/api/esign", tokens["staff"],
               {"coll": "payments", "id": pid, "meaning": "Submitted"})[0] == 200
    st, b = _undo(api, tokens["staff"], "payments", pid)
    assert st == 403, (st, b)


def test_an_undo_may_not_carry_a_status_or_an_item_id(api, tokens, monkeypatch):
    """The line an undo addresses comes from the stored signature the SERVER wrote. Accepting either
       from the client would let somebody reverse something they never signed."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-BODY")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    for extra in ({"setStatus": "Submitted"}, {"itemId": "line-1"}):
        body = {"coll": "payments", "id": pid, "meaning": "Undo", "undo": True}
        body.update(extra)
        st, b = api("POST", "/api/esign", tokens["management"], body)
        assert st == 400, (extra, st, b)


# ── separation of duties survives ─────────────────────────────────────────────────────────────────

def test_you_cannot_review_undo_then_approve_your_own_review(api, tokens, monkeypatch):
    """THE attack this design exists to defeat. If a reversal counted as a decision, a single person
       could review, take the review back, and then give final approval to their own work."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-SOD")
    assert _sign(api, tokens["management"], "payments", pid, "Reviewed")[0] == 200
    assert _undo(api, tokens["management"], "payments", pid)[0] == 200
    assert app.Handler._appr_state(_row("payments", pid).get("status")) == "submit"
    # Re-review, then try to approve what you reviewed. Still refused.
    assert _sign(api, tokens["management"], "payments", pid, "Reviewed")[0] == 200
    st, b = _sign(api, tokens["management"], "payments", pid, "Approved")
    assert st == 403 and "different person" in (b.get("error") or "").lower(), b


def test_undoing_an_approval_does_not_let_you_pay_your_own_request(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    st, b = api("POST", "/api/coll/payments", tokens["management"],
                {"reqNo": "PR-UNDO-OWN", "payee": "V", "amount": 1000, "attachment": PDF})
    pid = b["item"]["id"]
    st, b = _sign(api, tokens["management"], "payments", pid, "Approved")
    assert st == 403, "approving your own request was never allowed"


# ── money ─────────────────────────────────────────────────────────────────────────────────────────

def _paid(api, tokens, ref):
    pid = _pay(api, tokens, ref)
    assert _sign(api, tokens["management"], "payments", pid, "Approved")[0] == 200
    st, b = _sign(api, tokens["editor"], "payments", pid, "Paid", attach={"bankSlip": SLIP, "bankSlipName": "s.pdf"})
    assert st == 200, b
    return pid


def test_reversing_a_payment_requires_a_reason(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-1")
    st, b = _undo(api, tokens["editor"], "payments", pid)
    assert st == 400 and "why" in (b.get("error") or "").lower(), b
    st, b = _undo(api, tokens["editor"], "payments", pid, reason="not-a-real-code")
    assert st == 400, b


def test_a_reversed_payment_does_not_go_back_to_approved(api, tokens, monkeypatch):
    """It must never present to the next payer as though it had never been released."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-2")
    st, b = _undo(api, tokens["editor"], "payments", pid, reason="not-executed")
    assert st == 200, b
    r = _row("payments", pid)
    assert r["status"] == "Payment reversed"
    assert not r.get("paidOn") and not r.get("paidBy")
    assert r["reversedPaidBy"] == "Editor User", "who had marked it paid is still on the record"


def test_the_bank_slip_is_kept_as_withdrawn_evidence_not_deleted(api, tokens, monkeypatch):
    """It is the only proof of payment the system holds. Restoring it to 'absent' would destroy it."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-3")
    _undo(api, tokens["editor"], "payments", pid, reason="wrong-record")
    r = _row("payments", pid)
    assert not r.get("bankSlip"), "the live slip was cleared"
    voided = r.get("voidedBankSlips") or []
    assert len(voided) == 1 and voided[0]["slip"] == SLIP
    assert voided[0]["reason"] == "wrong-record" and voided[0]["reversedBy"] == "Editor User"


def test_the_person_who_reversed_a_payment_cannot_release_it_again_alone(api, tokens, monkeypatch):
    """Paying it a second time is a NEW decision, and not one the mis-attester makes by themselves."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-4")
    _undo(api, tokens["editor"], "payments", pid, reason="not-executed")
    st, b = _sign(api, tokens["editor"], "payments", pid, "Paid",
                  attach={"bankSlip": SLIP, "bankSlipName": "again.pdf"})
    assert st == 403 and "different authorised payer" in (b.get("error") or "").lower(), b
    assert _row("payments", pid)["status"] == "Payment reversed"


def test_re_paying_demands_a_fresh_slip_the_withdrawn_one_will_not_do(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-5")
    _undo(api, tokens["editor"], "payments", pid, reason="not-executed")
    st, b = _sign(api, tokens["admin"], "payments", pid, "Paid")     # a different payer, no slip
    assert st == 400 and "slip" in (b.get("error") or "").lower(), b


def test_a_reversed_payment_is_still_frozen_against_content_edits(api, tokens, monkeypatch):
    """Reversed is a decided state, not a draft again — the amount and payee stay put."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _paid(api, tokens, "PR-UNDO-PAID-6")
    _undo(api, tokens["editor"], "payments", pid, reason="wrong-record")
    row = _row("payments", pid)
    st, b = api("PATCH", "/api/coll/payments/" + pid, tokens["staff"], dict(row, amount=999999))
    assert st == 403, (st, b)
    assert _row("payments", pid)["amount"] == 1000


def test_a_reason_is_refused_on_anything_that_is_not_a_payment(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _pay(api, tokens, "PR-UNDO-NOREASON")
    _sign(api, tokens["management"], "payments", pid, "Approved")
    st, b = _undo(api, tokens["management"], "payments", pid, reason="not-executed")
    assert st == 400, (st, b)


# ── the PMC registers ─────────────────────────────────────────────────────────────────────────────

def test_a_variation_order_decision_can_be_taken_back(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    st, b = api("POST", "/api/coll/pm_changes", tokens["staff"],
                {"crNo": "CR-UNDO", "title": "Extra ductwork", "impactCost": 500_000_000,
                 "impactScheduleDays": 30, "projectId": "P1"})
    cid = b["item"]["id"]
    assert _sign(api, tokens["mgr"], "pm_changes", cid, "Approved")[0] == 200
    assert _row("pm_changes", cid)["decision"] == "Approved"
    st, b = _undo(api, tokens["mgr"], "pm_changes", cid)
    assert st == 200, b
    r = _row("pm_changes", cid)
    assert not r.get("decision") and not r.get("decidedBy")
    # and with the decision reversed, the record is editable again
    st, b = api("PATCH", "/api/coll/pm_changes/" + cid, tokens["staff"],
                {"id": cid, "crNo": "CR-UNDO", "title": "Extra ductwork", "impactCost": 400_000_000})
    assert st == 200, b


def test_a_payroll_run_can_never_be_undone(api, tokens):
    """payruns are deliberately outside the window: a finalised run stays immutable."""
    assert "payruns" not in app.Handler.UNDOABLE_COLLS
