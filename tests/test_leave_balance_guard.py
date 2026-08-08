"""Leave `days` must be a strict positive number at create time.

A non-numeric value (e.g. "5 days") was previously stored verbatim because the float() parse sat inside
the date try/except and its failure was swallowed; on approval the balance-decrement float() then failed
silently too, granting approved paid leave that consumed zero balance. Creation must reject it outright.
"""


def test_leave_rejects_non_numeric_days(api, tokens):
    st, b = api("POST", "/api/leave", tokens["staff"], {
        "type": "Annual", "startDate": "2026-08-03", "endDate": "2026-08-07", "days": "5 days",
    })
    assert st == 400, "non-numeric leave days must be rejected at create (got %s: %r)" % (st, b)


def test_leave_rejects_zero_or_negative_days(api, tokens):
    for bad in (0, -3):
        st, b = api("POST", "/api/leave", tokens["staff"], {
            "type": "Annual", "startDate": "2026-08-03", "endDate": "2026-08-07", "days": bad,
        })
        assert st == 400, "non-positive leave days (%r) must be rejected (got %s: %r)" % (bad, st, b)


def test_leave_accepts_valid_days(api, tokens):
    st, b = api("POST", "/api/leave", tokens["staff"], {
        "type": "Annual", "startDate": "2026-09-01", "endDate": "2026-09-03", "days": 3,
    })
    assert st == 200, "a well-formed leave request must still succeed (got %s: %r)" % (st, b)
