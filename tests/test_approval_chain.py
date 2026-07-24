"""3-level approval enforcement (_appr_check) — the core financial control for claims/travel/payments/leave.

Perform (submit) -> Review (direct manager) -> Approve (Editor/Admin) -> Paid (Management). Enforces:
segregation of duties (reviewer != approver), no self-review/approve, review only by the requester's
DIRECT manager, level gates, and denial of any non-standard status (which would otherwise let a requester
self-sign an intermediate status and skip the mandatory manager review). Previously untested.

Called on a bare Handler instance: _appr_check uses only helper methods + module db (no socket state).
The `base_url` fixture seeds the employees that db.get_employee() reads for the direct-manager check.
"""
import app


def _h():
    return app.Handler.__new__(app.Handler)


# Seeded org (conftest): HML-STF's direct manager is mgr@humiley.com (HML-MGR).
STAFF = {"id": "HML-STF", "role": "staff", "level": "staff", "email": "staff1@humiley.com"}
DIRECT_MGR = {"id": "HML-MGR", "role": "manager", "level": "manager", "email": "mgr@humiley.com"}
OTHER_MGR = {"id": "HML-ZZZ", "role": "manager", "level": "manager", "email": "notdirect@humiley.com"}
EDITOR = {"id": "HML-EDT", "role": "manager", "level": "editor", "email": "editor@humiley.com"}
DIRECTOR = {"id": "HML-MGT", "role": "manager", "level": "management", "email": "fin@humiley.com"}


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
def test_final_approval_requires_editor_or_admin(base_url):
    for who in (DIRECT_MGR, DIRECTOR):   # manager (2) and management/Director (3) are below editor (4)
        err = _h()._appr_check(who, "claims", "Reviewed", "approved", [], "HML-STF")
        assert err and ("editor" in err.lower() or "admin" in err.lower()), (who["level"], err)


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


# ---- Paid (Management only, and only from an approved state) -------------------------------------
def test_mark_paid_requires_management(base_url):
    assert _h()._appr_check(STAFF, "payments", "Approved", "paid", [], "HML-STF")


def test_mark_paid_only_from_approved(base_url):
    assert _h()._appr_check(DIRECTOR, "payments", "Reviewed", "paid", [], "HML-STF")          # not approved -> denied
    assert _h()._appr_check(DIRECTOR, "payments", "Approved", "paid", [], "HML-STF") is None  # approved -> allowed


# ---- Bypass prevention + non-three-level collections --------------------------------------------
def test_arbitrary_status_is_not_a_valid_step(base_url):
    # A requester self-signing an intermediate status must NOT advance past manager review.
    err = _h()._appr_check(STAFF, "claims", "Submitted", "Pending Approval", [], "HML-STF")
    assert err and "valid approval step" in err.lower()


def test_non_three_level_collection_still_gates_decisions_to_managers(base_url):
    # e.g. crm_deals: staff cannot approve/reject/mark-paid, a manager can.
    assert _h()._appr_check(STAFF, "crm_deals", "Open", "approved", [], "HML-STF")
    assert _h()._appr_check(DIRECT_MGR, "crm_deals", "Open", "approved", [], "HML-STF") is None
