"""The access level labelled "Approver (Management)" can actually approve.

It could not before. Final approval demanded Editor (Payroll) or Admin, so promoting somebody to
Approver did nothing at all — they could not approve, and they never even appeared in the requester's
approver dropdown. The label now means what it says.

The point of these tests is the SEPARATION that survives the change. Widening approval must not
widen anything else:

  * approving is Approver+ ...
  * ... but RELEASING MONEY is still only a named authorised payer,
  * approving your own request is still blocked,
  * approving a request you reviewed yourself is still blocked,
  * and payroll is still Editor+.
"""
import app
import db

SLIP = "data:application/pdf;base64,YmFuay1zbGlw"


def _submit(api, tokens, ref="PR-APPR"):
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": ref, "payee": "Vendor", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    return b["item"]["id"]


def _row(pid):
    return next(x for x in db.list_collection("payments") if x.get("id") == pid)


def _esign(api, token, pid, status, ref="PR-APPR", attach=None):
    body = {"coll": "payments", "id": pid, "meaning": status + " — " + ref, "setStatus": status}
    if attach:
        body["attach"] = attach
    return api("POST", "/api/esign", token, body)


# ── the change itself ─────────────────────────────────────────────────────────────────────────────

def test_management_level_can_now_give_final_approval(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _submit(api, tokens)
    st, b = _esign(api, tokens["management"], pid, "Approved")
    assert st == 200, b
    assert _row(pid)["status"] == "Approved"


def test_editor_and_admin_still_approve(api, tokens, monkeypatch):
    """Widening the bar must not accidentally exclude the people who already had the right."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    for who in ("editor", "admin"):
        pid = _submit(api, tokens, "PR-" + who)
        st, b = _esign(api, tokens[who], pid, "Approved", "PR-" + who)
        assert st == 200, (who, b)


def test_contributor_and_staff_still_cannot_approve(api, tokens, monkeypatch):
    """The bar moved down one level, not off."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    for who in ("mgr", "staff"):
        pid = _submit(api, tokens, "PR-no-" + who)
        st, b = _esign(api, tokens[who], pid, "Approved", "PR-no-" + who)
        assert st == 403, (who, st, b)
        assert _row(pid).get("status") != "Approved"


def test_the_helper_bar_is_management_not_editor():
    h = app.Handler
    assert h._LEVEL_RANK["management"] < h._LEVEL_RANK["editor"], "level order changed unexpectedly"


# ── what must NOT have widened ────────────────────────────────────────────────────────────────────

def test_approving_does_not_confer_paying(api, tokens, monkeypatch):
    """THE load-bearing test. Approver level can approve; it must not be able to release money."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "nancy.duong@humiley.com")   # management is NOT a payer
    pid = _submit(api, tokens, "PR-SPLIT")
    st, b = _esign(api, tokens["management"], pid, "Approved", "PR-SPLIT")
    assert st == 200, b
    st, b = _esign(api, tokens["management"], pid, "Paid", "PR-SPLIT",
                   {"bankSlip": SLIP, "bankSlipName": "s.pdf"})
    assert st == 403 and "authorised payer" in (b.get("error") or "").lower(), b
    assert _row(pid)["status"] == "Approved", "the money must not have moved"


def test_still_cannot_approve_your_own_request(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    st, b = api("POST", "/api/coll/payments", tokens["management"],
                {"reqNo": "PR-OWN2", "payee": "V", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    pid = b["item"]["id"]
    st, b = _esign(api, tokens["management"], pid, "Approved", "PR-OWN2")
    assert st == 403 and "your own request" in (b.get("error") or "").lower(), b


def test_still_cannot_approve_what_you_reviewed(api, tokens, monkeypatch):
    """Two-person rule inside the approval chain survives the wider bar."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _submit(api, tokens, "PR-REVAPPR")
    st, b = _esign(api, tokens["management"], pid, "Reviewed", "PR-REVAPPR")
    assert st == 200, b
    st, b = _esign(api, tokens["management"], pid, "Approved", "PR-REVAPPR")
    assert st == 403 and "different person" in (b.get("error") or "").lower(), b


def test_payroll_is_still_editor_only(api, tokens):
    """Approver level must NOT have gained payroll rights."""
    st, b = api("POST", "/api/coll/payruns", tokens["management"],
                {"scope": "company", "period": "March 2026", "count": 1, "gross": 1_000_000,
                 "net": 900_000, "ee": 50_000, "er": 50_000, "pit": 0, "erCost": 1_100_000})
    assert st == 403, b


def test_bank_detail_backfill_is_still_editor_only(api, tokens):
    """Finance's backfill on decided payments is a Finance duty, not an approval one."""
    pid = _submit(api, tokens, "PR-BANKLVL")
    st, b = api("POST", "/api/payments/bankdetails", tokens["management"],
                {"id": pid, "fields": {"bankName": "Vietcombank"}})
    assert st == 403, b


def test_frontend_gate_matches_the_backend_bar():
    """The dropdown and the inbox must use the same bar as _can_approve, or the UI offers an
       approver the server then rejects — the exact bug the old comment warned about."""
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "templates", "index.html")
    with open(p, encoding="utf-8") as fh:
        src = fh.read()
    assert "const _APPROVE_MIN = 'management';" in src
    assert "_canApprove = e => (typeof _lvlRank === 'function') && _canFinalApprove(e.level)" in src, \
        "the approver dropdown must use the shared predicate"
    assert "const isApprover = _canFinalApprove(_userLevel);" in src
    # and the duties that must NOT have widened still say 'editor'
    assert "_lvlRank(_userLevel) >= _lvlRank('editor') && _payBankMissing(p)" in src, \
        "the Finance bank-detail action must stay Editor-only"
