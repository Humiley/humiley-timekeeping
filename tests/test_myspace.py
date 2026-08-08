"""My Space summary endpoint + the server-side claim rollup that feeds its 'pending' count.

The summary replaces six full company-wide collection loads on the staff landing page with one small
counts request. Its 'pending' claim count MUST match the frontend _claimRollup, so we pin the port.
"""
import app


# --------------------------------------------------------------- claim rollup port matches the UI
def test_claim_rollup_matches_frontend_cases():
    # legacy claim (no items) → falls back to its own status
    assert app._claim_rollup({"status": "Approved"}) == "Approved"
    assert app._claim_rollup({}) == "Submitted"
    # all lines approved / rejected / reviewed
    assert app._claim_rollup({"items": [{"status": "Approved"}, {"status": "Approved"}]}) == "Approved"
    assert app._claim_rollup({"items": [{"status": "Rejected"}, {"status": "Rejected"}]}) == "Rejected"
    assert app._claim_rollup({"items": [{"status": "Reviewed"}, {"status": "Reviewed"}]}) == "Reviewed"
    # any Submitted line with another decided line → Partially approved; else Submitted
    assert app._claim_rollup({"items": [{"status": "Submitted"}, {"status": "Approved"}]}) == "Partially approved"
    assert app._claim_rollup({"items": [{"status": "Submitted"}, {"status": "Submitted"}]}) == "Submitted"
    # a line with no status defaults to Submitted
    assert app._claim_rollup({"items": [{}, {"status": "Approved"}]}) == "Partially approved"
    # reviewed + approved (no submitted) → still awaiting approval = Reviewed
    assert app._claim_rollup({"items": [{"status": "Reviewed"}, {"status": "Approved"}]}) == "Reviewed"


def test_claim_pending_rule_excludes_decided():
    """A claim counts as 'pending' on My Space iff its rollup is not a decided state."""
    decided = ("Approved", "Rejected", "Paid", "Cancelled")
    assert app._claim_rollup({"items": [{"status": "Approved"}]}) in decided        # not pending
    assert app._claim_rollup({"items": [{"status": "Submitted"}]}) not in decided    # pending
    assert app._claim_rollup({"items": [{"status": "Reviewed"}]}) not in decided     # pending


# --------------------------------------------------------------- endpoint: authed, self-scoped, shape
def test_myspace_summary_requires_auth(api):
    st, _ = api("GET", "/api/myspace/summary")
    assert st in (401, 403), "the summary must require a signed-in session"


def test_myspace_summary_shape_and_types(api, tokens):
    st, body = api("GET", "/api/myspace/summary", tokens["staff"])
    assert st == 200
    for k in ("pending", "trips", "claims", "payments", "devices", "trainDone", "trainTotal", "trainAvg"):
        assert k in body, "missing count: " + k
        assert isinstance(body[k], int), k + " must be an int count"
    assert body["pending"] >= 0 and body["trainAvg"] >= 0
    assert body["trainDone"] <= body["trainTotal"]
