"""The labour contract register, end to end.

contracts.py proves the Art. 20 arithmetic. This proves the parts only the server can answer: that a
contract is compensation data and scoped accordingly, that an employee can read their own and nobody
else's, and that the review surfaces the person whose contract ran out rather than hiding them.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'contracts'")
    conn.commit()
    conn.close()
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'contracts'")
    conn.commit()
    conn.close()


def _add(api, tokens, emp_id, start, end=None, type_=None, **kw):
    body = dict({"empId": emp_id, "startDate": start, "endDate": end,
                 "type": type_ or ("indefinite" if end is None else "definite")}, **kw)
    st, b = api("POST", "/api/coll/contracts", tokens["admin"], body)
    assert st == 200, b
    return b["item"]


def _rows(b):
    return {r["empId"]: r for r in b["rows"]}


# ── who may see a contract ───────────────────────────────────────────────────────────────────────

def test_a_contract_is_compensation_data_and_staff_cannot_list_the_company_s(api, tokens):
    _add(api, tokens, "HML-OTH", "2026-01-01", "2026-12-31", salary=30_000_000)
    st, b = api("GET", "/api/coll/contracts", tokens["staff"])
    assert st == 200
    assert b["items"] == [], "somebody else's contract states their wage"


def test_an_employee_can_read_their_own_contract(api, tokens):
    """Art. 13(1) entitles them to a copy. A portal that holds it and will not show it to them is
    worse than one that never held it."""
    _add(api, tokens, "HML-STF", "2026-01-01", "2026-12-31", no="HD-2026-011")
    _, b = api("GET", "/api/coll/contracts", tokens["staff"])
    assert [c["no"] for c in b["items"]] == ["HD-2026-011"]


def test_a_manager_cannot_read_the_contract_register(api, tokens):
    _add(api, tokens, "HML-STF", "2026-01-01", "2026-12-31")
    st, _ = api("GET", "/api/hr/contracts/review", tokens["mgr"])
    assert st == 403


def test_management_can(api, tokens):
    st, _ = api("GET", "/api/hr/contracts/review", tokens["management"])
    assert st == 200


# ── the review ───────────────────────────────────────────────────────────────────────────────────

def test_an_employee_with_no_contract_on_file_is_the_first_finding(api, tokens):
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["status"] == "none"
    assert [i["kind"] for i in r["issues"]] == ["missing"]


def test_a_healthy_indefinite_contract_raises_nothing(api, tokens):
    _add(api, tokens, "HML-STF", "2020-01-01", None, "indefinite")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["status"] == "indefinite" and r["issues"] == []


def test_a_contract_about_to_expire_is_surfaced_with_the_days_left(api, tokens):
    _add(api, tokens, "HML-STF", "2026-01-01", "2026-12-31")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-11-20", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["status"] == "expiring" and r["daysLeft"] == 41


def test_a_contract_that_lapsed_says_it_has_already_become_indefinite(api, tokens):
    """Art. 20(2)(b): 30 days after expiry with nothing signed, it already changed. The record is
    now wrong about what kind of contract this person is on, and only the portal can say so."""
    _add(api, tokens, "HML-STF", "2025-01-01", "2025-12-31")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["status"] == "lapsed"
    assert "ALREADY an indefinite-term contract" in " ".join(i["message"] for i in r["issues"])


def test_the_worst_cases_are_listed_first(api, tokens):
    """A register that buries the lapsed contract under thirty healthy ones is a list, not a review."""
    _add(api, tokens, "HML-OTH", "2020-01-01", None, "indefinite")
    _add(api, tokens, "HML-STF", "2025-01-01", "2025-12-31")          # lapsed
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    order = [r["empId"] for r in b["rows"]]
    assert order.index("HML-STF") < order.index("HML-OTH")


def test_a_third_fixed_term_is_called_out_before_anybody_signs_it(api, tokens):
    _add(api, tokens, "HML-STF", "2024-01-01", "2024-12-31")
    _add(api, tokens, "HML-STF", "2025-01-01", "2026-12-31")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-11-25", tokens["admin"])
    r = _rows(b)["HML-STF"]
    assert r["definiteCount"] == 2 and r["mustBeIndefinite"] is True
    assert "must_be_indefinite" in [i["kind"] for i in r["issues"]]


def test_a_fixed_term_longer_than_three_years_is_flagged(api, tokens):
    _add(api, tokens, "HML-STF", "2026-01-01", "2030-12-31")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    assert "term_too_long" in [i["kind"] for i in _rows(b)["HML-STF"]["issues"]]


def test_a_named_exemption_may_keep_renewing_on_fixed_terms(api, tokens):
    """Art. 20(2)(c) carves out an elderly employee, a foreign worker, a hired director of a
    state-capital enterprise and a full-time union officer."""
    db.update_employee("HML-STF", {"contractExempt": "foreign"})
    try:
        _add(api, tokens, "HML-STF", "2024-01-01", "2024-12-31")
        _add(api, tokens, "HML-STF", "2025-01-01", "2026-12-31")
        _, b = api("GET", "/api/hr/contracts/review?asOf=2026-11-25", tokens["admin"])
        assert _rows(b)["HML-STF"]["mustBeIndefinite"] is False
    finally:
        db.update_employee("HML-STF", {"contractExempt": ""})


def test_the_review_counts_how_many_people_need_attention(api, tokens):
    _add(api, tokens, "HML-STF", "2025-01-01", "2025-12-31")          # lapsed
    _add(api, tokens, "HML-OTH", "2020-01-01", None, "indefinite")    # fine
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    flagged = {r["empId"] for r in b["rows"] if r["issues"]}
    assert "HML-STF" in flagged and "HML-OTH" not in flagged
    assert b["flagged"] == len(flagged)


def test_a_junk_as_of_date_falls_back_to_today_rather_than_erroring(api, tokens):
    st, b = api("GET", "/api/hr/contracts/review?asOf=whenever", tokens["admin"])
    assert st == 200 and len(b["asOf"]) == 10


def test_whether_a_signed_copy_is_attached_is_part_of_the_answer(api, tokens):
    """Art. 13 requires the contract in writing. Knowing one exists is not the same as having it."""
    _add(api, tokens, "HML-STF", "2026-01-01", "2026-12-31")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-STF"]["hasFile"] is False
    _add(api, tokens, "HML-OTH", "2026-01-01", "2026-12-31", file="data:application/pdf;base64,AAA")
    _, b = api("GET", "/api/hr/contracts/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-OTH"]["hasFile"] is True
