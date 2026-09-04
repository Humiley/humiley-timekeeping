"""The certificate register, end to end.

certificates.py proves the cadences. This proves what only the server can answer: that the
requirement follows the employee's own recorded working conditions and age, that a manager sees
their crew and not the company, and that the people who need attention come first.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: {"workConditions": e.get("workConditions"), "oshGroup": e.get("oshGroup"),
                        "dob": e.get("dob"), "disabled": e.get("disabled")}
              for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'certificates'")
    conn.commit()
    conn.close()
    # These tests are about the health-check CADENCE for an adult. Without a date of birth the
    # register now (correctly) reports that the interval it applied is the adult one and nobody can
    # tell whether it should have been the six-monthly minor one — a finding of its own, and not
    # the finding these tests are making.
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": "1990-05-20"})
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'certificates'")
    conn.commit()
    conn.close()
    for eid, v in before.items():
        db.update_employee(eid, v)


def _add(api, tokens, emp_id, kind, issued, expiry=None, title=None):
    st, b = api("POST", "/api/coll/certificates", tokens["admin"],
                {"empId": emp_id, "kind": kind, "issuedDate": issued,
                 "expiryDate": expiry, "title": title})
    assert st == 200, b
    return b["item"]


def _rows(b):
    return {r["empId"]: r for r in b["rows"]}


def _states(row):
    return {(i["kind"], i["state"]) for i in row["issues"]}


# ── the answer a plain list cannot give ──────────────────────────────────────────────────────────

def test_somebody_with_no_health_check_at_all_is_a_finding(api, tokens):
    st, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert st == 200, b
    assert ("health_check", "missing") in _states(_rows(b)["HML-STF"])


def test_a_current_health_check_clears_it(api, tokens):
    _add(api, tokens, "HML-STF", "health_check", "2026-03-01")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-STF"]["issues"] == []


def test_the_cadence_follows_the_employee_s_own_working_conditions(api, tokens):
    """The same certificate that keeps an office worker covered for a year covers a site crew for
    six months. One cadence for everybody is how the exposure goes unnoticed."""
    _add(api, tokens, "HML-STF", "health_check", "2025-11-01")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-STF"]["issues"] == []
    db.update_employee("HML-STF", {"workConditions": "heavy"})
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert ("health_check", "expired") in _states(_rows(b)["HML-STF"])


def test_an_elderly_worker_is_on_the_six_month_cadence_too(api, tokens):
    """Art. 148. The trigger is 60 rather than the moving retirement age of Art. 169, which can only
    ever ask for more checks than the law requires."""
    _add(api, tokens, "HML-STF", "health_check", "2025-11-01")
    db.update_employee("HML-STF", {"dob": "1960-01-01"})
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert ("health_check", "expired") in _states(_rows(b)["HML-STF"])


def test_safety_training_is_asserted_only_where_the_company_has_classified_somebody(api, tokens):
    _add(api, tokens, "HML-STF", "health_check", "2026-05-01")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-STF"]["issues"] == []
    db.update_employee("HML-STF", {"oshGroup": "3"})
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert ("osh_training", "missing") in _states(_rows(b)["HML-STF"])


def test_safety_training_older_than_two_years_is_expired(api, tokens):
    db.update_employee("HML-STF", {"oshGroup": "3"})
    _add(api, tokens, "HML-STF", "health_check", "2026-05-01")
    _add(api, tokens, "HML-STF", "osh_training", "2024-01-01")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert ("osh_training", "expired") in _states(_rows(b)["HML-STF"])


def test_a_refresher_supersedes_the_certificate_it_renews(api, tokens):
    db.update_employee("HML-STF", {"oshGroup": "3"})
    _add(api, tokens, "HML-STF", "health_check", "2026-05-01")
    _add(api, tokens, "HML-STF", "osh_training", "2024-01-01")
    _add(api, tokens, "HML-STF", "osh_training", "2026-01-15")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    assert _rows(b)["HML-STF"]["issues"] == []


def test_a_trade_ticket_is_tracked_on_its_own_printed_expiry(api, tokens):
    _add(api, tokens, "HML-STF", "health_check", "2026-05-01")
    _add(api, tokens, "HML-STF", "welding", "2024-02-01", expiry="2026-02-01",
         title="6G welding qualification")
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    msg = " ".join(i["message"] for i in _rows(b)["HML-STF"]["issues"])
    assert "6G welding" in msg


def test_the_people_who_need_attention_come_first(api, tokens):
    _add(api, tokens, "HML-OTH", "health_check", "2026-05-01")     # covered
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["admin"])
    order = [r["empId"] for r in b["rows"]]
    assert order.index("HML-STF") < order.index("HML-OTH")
    assert b["flagged"] >= 1


# ── who may see it ───────────────────────────────────────────────────────────────────────────────

def test_a_manager_sees_their_own_crew_and_not_the_company(api, tokens):
    """Not compensation data — a site manager has to know whether their crew is covered before
    sending them out — but still somebody's medical cadence, so not company-wide for everyone."""
    st, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["mgr"])
    assert st == 200
    assert set(_rows(b)) == {"HML-MGR", "HML-STF"}


def test_management_sees_everybody(api, tokens):
    _, b = api("GET", "/api/hr/certificates/review?asOf=2026-06-01", tokens["management"])
    assert "HML-OTH" in _rows(b)


def test_staff_cannot_read_the_register(api, tokens):
    st, _ = api("GET", "/api/hr/certificates/review", tokens["staff"])
    assert st == 403


def test_a_junk_date_falls_back_rather_than_erroring(api, tokens):
    st, b = api("GET", "/api/hr/certificates/review?asOf=nonsense", tokens["admin"])
    assert st == 200 and len(b["asOf"]) == 10
