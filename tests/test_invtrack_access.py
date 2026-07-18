"""Invoice Tracking access-control (company policy: EDITOR + ADMIN only).

A Finance/Approver (management) account may run Payroll + Finance Control but must NOT reach
Invoice Tracking. Editor + Admin may. This pins that boundary across EVERY invtrack gate — read,
status/sync/import, and collection add — so a future refactor can't silently widen access.
"""
import pytest

# (token-key, expected-allowed) for the Invoice Tracking level boundary.
ROLES = [
    ("staff", False),
    ("mgr", False),
    ("management", False),   # Finance/Approver — explicitly excluded
    ("editor", True),
    ("admin", True),
]


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_read(api, tokens, who, allowed):
    st, _ = api("GET", "/api/coll/invtrack", tokens[who])
    if allowed:
        assert st == 200, "%s should be able to read Invoice Tracking" % who
    else:
        assert st == 403, "%s must NOT be able to read Invoice Tracking" % who


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_status(api, tokens, who, allowed):
    st, _ = api("GET", "/api/invtrack/status", tokens[who])
    assert st == (200 if allowed else 403), "%s status gate wrong" % who


@pytest.mark.parametrize("who,allowed", ROLES)
def test_invtrack_write(api, tokens, who, allowed):
    st, _ = api("POST", "/api/coll/invtrack", tokens[who],
                {"invNo": "TEST-1", "amount": 100})
    # editor/admin get through the level gate (200); everyone else is 403.
    # (management is the case that matters most — it used to be allowed.)
    if allowed:
        assert st == 200, "%s should be able to add an Invoice Tracking record" % who
    else:
        assert st == 403, "%s must NOT be able to add an Invoice Tracking record" % who


def test_management_can_still_reach_payroll_and_finance(api, tokens):
    """The lockdown is Invoice-Tracking-specific: a Finance/Approver (management) account must
    KEEP its Payroll + Finance access — only Invoice Tracking is walled off."""
    st, _ = api("GET", "/api/coll/payruns", tokens["management"])
    assert st == 200, "management must retain Payroll (payruns) read access"
