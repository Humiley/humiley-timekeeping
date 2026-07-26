"""Executive Dashboard summary — the company-on-one-screen aggregate. Management+ only; shape + types.
   Composes the tested digest gatherer (approvals in flight) with bounded reads of the other collections."""


def test_exec_summary_requires_management(api, tokens):
    st, _ = api("GET", "/api/exec/summary")
    assert st in (401, 403), "must require a signed-in session"
    st2, _ = api("GET", "/api/exec/summary", tokens["staff"])
    assert st2 == 403, "a plain staff user must not see the company-wide exec summary"


def test_exec_summary_shape_and_types(api, tokens):
    st, body = api("GET", "/api/exec/summary", tokens["admin"])
    assert st == 200
    for k in ("headcount", "onLeaveToday", "leaveLiabilityDays", "pendingLeave",
              "apprAwait", "apprReview", "apprOverdue", "payMonthCount",
              "invoiceCount", "projectCount", "projectActive"):
        assert k in body and isinstance(body[k], int), "int field missing/wrong: " + k
    for k in ("apprValue", "payMonth", "invoiceTotal", "invoiceVat"):
        assert k in body and isinstance(body[k], (int, float)), "number field missing/wrong: " + k
    assert body["headcount"] >= 0
    assert 0 <= body["projectActive"] <= body["projectCount"]
    assert body.get("month") and body.get("at"), "must stamp month + timestamp"
