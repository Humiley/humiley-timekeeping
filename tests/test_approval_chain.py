"""3-level approval enforcement (_appr_check) — the core financial control for claims/travel/payments/leave.

Perform (submit) -> Review (direct manager) -> Approve (Editor/Admin) -> Paid (Management). Enforces:
segregation of duties (reviewer != approver), no self-review/approve, review only by the requester's
DIRECT manager, level gates, and denial of any non-standard status (which would otherwise let a requester
self-sign an intermediate status and skip the mandatory manager review). Previously untested.

Called on a bare Handler instance: _appr_check uses only helper methods + module db (no socket state).
The `base_url` fixture seeds the employees that db.get_employee() reads for the direct-manager check.
"""
import app
import db


def _h():
    return app.Handler.__new__(app.Handler)


# Seeded org (conftest): HML-STF's direct manager is mgr@humiley.com (HML-MGR).
STAFF = {"id": "HML-STF", "role": "staff", "level": "staff", "email": "staff1@humiley.com"}
DIRECT_MGR = {"id": "HML-MGR", "role": "manager", "level": "manager", "email": "mgr@humiley.com"}
OTHER_MGR = {"id": "HML-ZZZ", "role": "manager", "level": "manager", "email": "notdirect@humiley.com"}
EDITOR = {"id": "HML-EDT", "role": "manager", "level": "editor", "email": "editor@humiley.com"}
DIRECTOR = {"id": "HML-MGT", "role": "manager", "level": "management", "email": "fin@humiley.com"}
ADMIN = {"id": "HML-ADM", "role": "manager", "level": "admin", "email": "admin@humiley.com"}


# ---- Review (level 2: the requester's DIRECT manager) --------------------------------------------
def test_review_requires_manager_role(base_url):
    err = _h()._appr_check(STAFF, "claims", "Submitted", "reviewed", [], "HML-STF")
    assert err and "manager" in err.lower()


def test_cannot_review_own_request(base_url):
    err = _h()._appr_check(DIRECT_MGR, "claims", "Submitted", "reviewed", [], "HML-MGR")
    assert err and "your own" in err.lower()


def test_review_must_come_from_the_direct_manager(base_url):
    err = _h()._appr_check(OTHER_MGR, "claims", "Submitted", "reviewed", [], "HML-STF")
    assert err and "direct manager" in err.lower()


def test_direct_manager_may_review(base_url):
    assert _h()._appr_check(DIRECT_MGR, "claims", "Submitted", "reviewed", [], "HML-STF") is None


def test_cannot_review_an_already_reviewed_request(base_url):
    err = _h()._appr_check(DIRECT_MGR, "claims", "Reviewed", "reviewed", [], "HML-STF")
    assert err and "already been reviewed" in err.lower()


# ---- Approve (level 3: Editor/Admin only — a plain manager or a Director cannot) -----------------
def test_final_approval_requires_approver_level_or_above(base_url):
    """POLICY CHANGE (owner decision): the bar for final approval moved from Editor down to
    Approver (Management). It used to be that the access level literally labelled
    "Approver (Management)" could not approve anything — promoting someone to Approver did nothing
    and they never appeared in the requester's approver dropdown. A Director now approves; a
    Contributor still cannot. See tests/test_approver_level.py for the separation this must not
    break — above all, approving still confers no ability to RELEASE money."""
    err = _h()._appr_check(DIRECT_MGR, "claims", "Reviewed", "approved", [], "HML-STF")
    assert err and "approver" in err.lower(), ("contributor must still be refused", err)

    assert _h()._appr_check(DIRECTOR, "claims", "Reviewed", "approved", [], "HML-STF") is None, \
        "Approver (Management) must now be able to give final approval"


def test_cannot_approve_own_request(base_url):
    err = _h()._appr_check(EDITOR, "claims", "Reviewed", "approved", [], "HML-EDT")
    assert err and "your own" in err.lower()


def test_reviewer_cannot_also_give_final_approval(base_url):
    # Segregation of duties: the same person who reviewed must not approve.
    sigs = [{"userId": "HML-EDT", "setStatus": "reviewed"}]
    err = _h()._appr_check(EDITOR, "claims", "Reviewed", "approved", sigs, "HML-STF")
    assert err and "different person" in err.lower()


def test_editor_may_approve_after_someone_else_reviewed(base_url):
    sigs = [{"userId": "HML-MGR", "setStatus": "reviewed"}]
    assert _h()._appr_check(EDITOR, "claims", "Reviewed", "approved", sigs, "HML-STF") is None


# ---- Paid / disbursement (Editor + Admin ONLY, and only from an approved state) -----------------
def test_mark_paid_requires_editor_or_admin(base_url):
    # Below Editor cannot disburse — neither staff NOR an Approver (management), who may approve but
    # must not release the money.
    assert _h()._appr_check(STAFF, "payments", "Approved", "paid", [], "HML-STF")
    assert _h()._appr_check(DIRECTOR, "payments", "Approved", "paid", [], "HML-STF")


def test_mark_paid_only_from_approved(base_url):
    assert _h()._appr_check(EDITOR, "payments", "Reviewed", "paid", [], "HML-STF")          # not approved -> denied
    assert _h()._appr_check(EDITOR, "payments", "Approved", "paid", [], "HML-STF") is None  # editor + approved -> allowed


def test_cannot_release_payment_on_own_request(base_url):
    # Disbursement SoD: an Editor/Admin who is the requester cannot pay their own approved request.
    err = _h()._appr_check(EDITOR, "payments", "Approved", "paid", [], "HML-EDT")
    assert err and "your own" in err.lower()


def test_approver_cannot_also_release_payment(base_url):
    # Disbursement SoD: the person who gave final approval must not also release the money.
    sigs = [{"userId": "HML-EDT", "setStatus": "approved"}]
    err = _h()._appr_check(EDITOR, "payments", "Approved", "paid", sigs, "HML-STF")
    assert err and "different person" in err.lower()


def test_a_second_editor_may_release_after_someone_else_approved(base_url):
    # A DIFFERENT Editor/Admin than the approver may pay — the intended two-person flow.
    sigs = [{"userId": "HML-EDT", "setStatus": "approved"}]
    assert _h()._appr_check(ADMIN, "payments", "Approved", "paid", sigs, "HML-STF") is None


def test_payer_separation_can_be_relaxed_but_owner_guard_stays(base_url):
    # A single-finance-person org can turn OFF approver!=payer via portal_payerSeparation; paying your
    # OWN request stays blocked regardless.
    db.set_setting("portal_payerSeparation", "0")
    try:
        sigs = [{"userId": "HML-EDT", "setStatus": "approved"}]
        assert _h()._appr_check(EDITOR, "payments", "Approved", "paid", sigs, "HML-STF") is None   # approver may now pay
        err = _h()._appr_check(EDITOR, "payments", "Approved", "paid", [], "HML-EDT")               # but not your own
        assert err and "your own" in err.lower()
    finally:
        db.set_setting("portal_payerSeparation", "1")


# ---- Bypass prevention + non-three-level collections --------------------------------------------
def test_arbitrary_status_is_not_a_valid_step(base_url):
    # A requester self-signing an intermediate status must NOT advance past manager review.
    err = _h()._appr_check(STAFF, "claims", "Submitted", "Pending Approval", [], "HML-STF")
    assert err and "valid approval step" in err.lower()


def test_non_three_level_collection_still_gates_decisions_to_managers(base_url):
    # e.g. crm_deals: staff cannot approve/reject/mark-paid, a manager can.
    assert _h()._appr_check(STAFF, "crm_deals", "Open", "approved", [], "HML-STF")
    assert _h()._appr_check(DIRECT_MGR, "crm_deals", "Open", "approved", [], "HML-STF") is None
