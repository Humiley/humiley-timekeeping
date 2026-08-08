"""Server-side money validation on payroll records (payruns / payadjust).

Payroll writes are Editor/Admin-only and were previously the one money path with NO amount sanity
check: a fat-fingered salary, a negative override, or a NaN/inf (which then breaks the whole
collection's JSON response) flowed straight into gross/net/employer-cost. These assert the guard.
"""
_VALID_RUN = {"scope": "individual", "empId": "HML-STF", "empName": "Staff One", "period": "January 2026",
              "count": 1, "gross": 20_000_000, "net": 17_500_000, "ee": 2_100_000, "er": 4_600_000,
              "pit": 400_000, "erCost": 24_600_000, "status": "Finalised"}


def test_valid_payrun_is_accepted(api, tokens):
    st, b = api("POST", "/api/coll/payruns", tokens["editor"], dict(_VALID_RUN))
    assert st == 200, b


def test_negative_payrun_total_is_rejected(api, tokens):
    bad = dict(_VALID_RUN, gross=-5_000_000)
    st, b = api("POST", "/api/coll/payruns", tokens["editor"], bad)
    assert st == 400 and "negative" in (b.get("error", "").lower())


def test_absurd_payrun_total_is_rejected(api, tokens):
    bad = dict(_VALID_RUN, erCost=500_000_000_000)   # > 100bn VND ceiling
    st, b = api("POST", "/api/coll/payruns", tokens["editor"], bad)
    assert st == 400 and "maximum" in (b.get("error", "").lower())


def test_negative_payadjust_component_is_rejected(api, tokens):
    st, b = api("POST", "/api/coll/payadjust", tokens["editor"],
                {"empId": "HML-STF", "name": "Staff One", "period": "January 2026", "basic": -1, "pit": 0})
    assert st == 400 and "negative" in (b.get("error", "").lower())


def test_valid_payadjust_is_accepted(api, tokens):
    st, b = api("POST", "/api/coll/payadjust", tokens["editor"],
                {"empId": "HML-STF", "name": "Staff One", "period": "February 2026",
                 "basic": 15_000_000, "pit": 300_000, "eeBhxh": 1_200_000})
    assert st == 200, b
