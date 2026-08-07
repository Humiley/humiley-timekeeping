"""Decisions and confirmation letters, end to end.

hr_decision.py and employment_letter.py prove the rules. This proves what only the server can:
that a decision the Labour Code forbids is refused at the server rather than by a hopeful form, that
a termination decision is sourced from the offboarding record instead of retyped, and that an
employee can ask for a letter about themselves but cannot issue one — or ask about anybody else.
"""
import pytest

import company
import db
import employment_letter as el
import hr_decision as hd

FULL_CO = {
    "legalNameVn": "Công ty TNHH Kỹ thuật Humiley Việt Nam", "regNo": "0316889472",
    "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Đức Huy", "repTitle": "Tổng Giám đốc",
}


@pytest.fixture(autouse=True)
def _clean():
    keep = ("name", "startDate", "title", "dept", "salary", "personalId", "status", "endDate")
    before = {e["id"]: {k: e.get(k) for k in keep} for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll IN "
                 "('decisions','hrletters','exits','contracts')")
    conn.commit()
    conn.close()
    for k in company.FIELD_KEYS:
        db.set_setting("portal_co_" + k, None)
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll IN "
                 "('decisions','hrletters','exits','contracts')")
    conn.commit()
    conn.close()
    for k in company.FIELD_KEYS:
        db.set_setting("portal_co_" + k, None)
    for eid, v in before.items():
        db.update_employee(eid, v)


def _co(api, tokens):
    assert api("POST", "/api/hr/company", tokens["admin"], FULL_CO)[0] == 200


def _emp(eid="HML-STF"):
    db.update_employee(eid, {"name": "Lê Văn Minh", "startDate": "2020-03-01",
                             "title": "Kỹ sư Cơ điện", "dept": "Engineering",
                             "salary": 24_500_000, "personalId": "079092004417",
                             "status": "Active", "endDate": None})


# ── decisions: the refusals are the point ────────────────────────────────────────────────────────

def test_a_lawful_decision_is_recorded_and_audited(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/decision", tokens["admin"],
                  {"kind": "appointment", "empId": "HML-STF", "no": "QD-2026-007",
                   "subject": "Appointed Site Manager", "effectiveFrom": "2026-09-01"})
    assert code == 200, b
    assert b["decision"]["kind"] == "appointment"
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Decision issued"]
    assert any("HML-STF" in a["detail"] for a in trail)


def test_a_monetary_fine_is_refused_by_the_server(api, tokens):
    """Art. 127(2). A form can be bypassed; this cannot."""
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/decision", tokens["admin"],
                  {"kind": "discipline", "empId": "HML-STF", "subject": "Late again",
                   "effectiveFrom": "2026-09-01", "measure": "fine",
                   "violationDate": "2026-08-01"})
    assert code == 400
    assert any("Art. 127(2)" in m for m in b["blockers"]["law"])
    assert db.list_collection("decisions") == []


def test_a_dismissal_out_of_time_is_refused_with_the_last_lawful_date(api, tokens):
    """Art. 123 — after six months the company has lost the right, and a decision issued anyway is
    worse than none."""
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/decision", tokens["admin"],
                  {"kind": "discipline", "empId": "HML-STF", "subject": "Theft",
                   "effectiveFrom": "2026-09-01", "measure": "dismissal",
                   "violationDate": "2025-01-10", "issuedOn": "2026-09-01"})
    assert code == 400
    assert any("Out of time" in m and "2025-07-10" in m for m in b["blockers"]["law"])


def test_a_pay_rise_deferred_beyond_six_months_is_refused(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/decision", tokens["admin"],
                  {"kind": "discipline", "empId": "HML-STF", "subject": "x",
                   "effectiveFrom": "2026-09-01", "measure": "defer_raise",
                   "violationDate": "2026-08-01", "deferMonths": 9})
    assert code == 400 and any("Art. 124(2)" in m for m in b["blockers"]["law"])


def test_an_art_36_termination_with_no_stated_ground_is_refused(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/decision", tokens["admin"],
                  {"kind": "termination", "empId": "HML-STF", "subject": "x",
                   "effectiveFrom": "2026-09-01", "ground": "employer_unilateral"})
    assert code == 400 and b["blockers"]["law"]


def test_a_decision_type_that_is_not_one_is_refused(api, tokens):
    _co(api, tokens); _emp()
    assert api("POST", "/api/hr/decision", tokens["admin"],
               {"kind": "banishment", "empId": "HML-STF"})[0] == 400
    assert api("GET", "/api/hr/decision/draft?kind=banishment&emp=HML-STF",
               tokens["admin"])[0] == 400


# ── the draft is sourced from what the portal already knows ──────────────────────────────────────

def test_a_termination_draft_is_seeded_from_the_offboarding_record(api, tokens):
    """The exit already carries the type, the last day and the notice — exactly the facts
    Art. 34/36/45 turn on. Retyping them is how they end up disagreeing."""
    _co(api, tokens); _emp()
    db.put_collection_item("exits", {"id": "ex-1", "empId": "HML-STF", "type": "Resignation",
                                     "lastDay": "2026-10-31", "noticeDays": 45,
                                     "reason": "Relocating", "initiated": "2026-09-01"})
    code, b = api("GET", "/api/hr/decision/draft?kind=termination&emp=HML-STF", tokens["admin"])
    assert code == 200
    assert b["seed"]["ground"] == "employee_unilateral"
    assert b["seed"]["effectiveFrom"] == "2026-10-31"
    assert b["seed"]["exitId"] == "ex-1"


def test_the_draft_carries_the_grounds_and_measures_so_the_ui_need_not_restate_the_law(api, tokens):
    _co(api, tokens); _emp()
    _, b = api("GET", "/api/hr/decision/draft?kind=discipline&emp=HML-STF", tokens["admin"])
    assert [m["key"] for m in b["measures"]] == ["reprimand", "defer_raise", "demotion", "dismissal"]
    assert "fine" in b["forbidden"]


def test_a_draft_for_nobody_is_a_404(api, tokens):
    assert api("GET", "/api/hr/decision/draft?kind=appointment&emp=NOPE", tokens["admin"])[0] == 404


# ── who may issue a decision ─────────────────────────────────────────────────────────────────────

def test_below_management_can_neither_draft_nor_issue_a_decision(api, tokens):
    _co(api, tokens); _emp()
    for who in ("mgr", "staff"):
        assert api("GET", "/api/hr/decision/draft?kind=appointment&emp=HML-STF",
                   tokens[who])[0] == 403
        assert api("POST", "/api/hr/decision", tokens[who],
                   {"kind": "appointment", "empId": "HML-STF", "subject": "x",
                    "effectiveFrom": "2026-09-01"})[0] == 403


def test_an_employee_can_read_their_own_decision_but_not_anybody_elses(api, tokens):
    """The same rule as their contract: a decision about you is yours to read."""
    _co(api, tokens); _emp()
    api("POST", "/api/hr/decision", tokens["admin"],
        {"kind": "appointment", "empId": "HML-STF", "subject": "x", "effectiveFrom": "2026-09-01"})
    api("POST", "/api/hr/decision", tokens["admin"],
        {"kind": "appointment", "empId": "HML-OTH", "subject": "y", "effectiveFrom": "2026-09-01"})
    code, b = api("GET", "/api/coll/decisions", tokens["staff"])
    assert code == 200
    assert {x["empId"] for x in b["items"]} == {"HML-STF"}


# ── confirmation letters: the disclosure rule, enforced ──────────────────────────────────────────

def test_an_employee_may_request_a_letter_about_themselves(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/letter", tokens["staff"],
                  {"purpose": "visa", "addressedTo": "Embassy of Japan"})
    assert code == 200, b
    assert b["letter"]["status"] == "Requested" and "document" not in b


def test_an_employee_may_not_request_one_about_somebody_else(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/letter", tokens["staff"],
                  {"empId": "HML-OTH", "purpose": "bank"})
    assert code == 403 and "yourself" in (b.get("error") or "")
    assert api("GET", "/api/hr/letter/draft?emp=HML-OTH", tokens["staff"])[0] == 403


def test_an_employee_may_not_issue_one_even_about_themselves(api, tokens):
    """The letter is the company speaking, not the employee."""
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/letter", tokens["staff"],
                  {"purpose": "bank", "issue": True})
    assert code == 403 and "company speaking" in (b.get("error") or "")


def test_management_issues_it_and_gets_the_document(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/letter", tokens["management"],
                  {"empId": "HML-STF", "purpose": "bank", "issue": True, "no": "XN-2026-004"})
    assert code == 200, b
    assert b["letter"]["status"] == "Issued"
    assert "salary" in {r["key"] for r in b["document"]["rows"]}


def test_a_visa_letter_issued_through_the_api_still_withholds_the_salary(api, tokens):
    """The rule has to survive the round trip, not just hold inside the module."""
    _co(api, tokens); _emp()
    _, b = api("POST", "/api/hr/letter", tokens["management"],
               {"empId": "HML-STF", "purpose": "visa", "issue": True})
    assert "salary" not in {r["key"] for r in b["document"]["rows"]}
    assert "salary" in {w["key"] for w in b["document"]["withheld"]}
    assert b["letter"]["disclosesSalary"] is False


def test_the_purpose_is_written_to_the_audit_trail_with_whether_pay_was_disclosed(api, tokens):
    """That is the question anybody would ask afterwards."""
    _co(api, tokens); _emp()
    api("POST", "/api/hr/letter", tokens["management"],
        {"empId": "HML-STF", "purpose": "bank", "issue": True})
    trail = [a for a in db.list_collection("audit")
             if str(a.get("action") or "").startswith("Confirmation letter")]
    assert any("purpose: bank" in a["detail"] and "salary disclosed: yes" in a["detail"]
               for a in trail)


def test_a_letter_with_no_purpose_is_refused(api, tokens):
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/hr/letter", tokens["staff"], {})
    assert code == 400 and "purpose" in {m["key"] for m in b["blockers"]["terms"]}


def test_an_employee_can_still_request_before_the_company_identity_is_set(api, tokens):
    """They cannot fix that blocker and should not be stopped by it — but it does stop ISSUING."""
    _emp()
    assert api("POST", "/api/hr/letter", tokens["staff"], {"purpose": "visa"})[0] == 200
    code, b = api("POST", "/api/hr/letter", tokens["management"],
                  {"empId": "HML-STF", "purpose": "visa", "issue": True})
    assert code == 400 and b["blockers"]["company"]


def test_the_draft_shows_the_employee_what_the_letter_will_not_say(api, tokens):
    """Before they send a visa letter to a bank and are turned away."""
    _co(api, tokens); _emp()
    code, b = api("GET", "/api/hr/letter/draft?purpose=visa", tokens["staff"])
    assert code == 200
    assert "salary" in {w["key"] for w in b["withheld"]}
    assert b["canIssueHere"] is False


def test_an_employee_sees_only_their_own_letters(api, tokens):
    _co(api, tokens); _emp()
    api("POST", "/api/hr/letter", tokens["staff"], {"purpose": "visa"})
    api("POST", "/api/hr/letter", tokens["management"],
        {"empId": "HML-OTH", "purpose": "bank", "issue": True})
    _, b = api("GET", "/api/coll/hrletters", tokens["staff"])
    assert {x["empId"] for x in b["items"]} == {"HML-STF"}


# ── the generic collection route must not be a way round the law ─────────────────────────────────

def test_a_decision_cannot_be_created_through_the_generic_collection_route(api, tokens):
    """Measured, not assumed. Before this guard: /api/hr/decision refused measure="fine" with 400
    (Art. 127(2)) and POST /api/coll/decisions accepted the same thing with 200 and wrote the row.
    Every law check in hr_decision.py was one URL away from being irrelevant."""
    _co(api, tokens); _emp()
    assert api("POST", "/api/hr/decision", tokens["admin"],
               {"kind": "discipline", "empId": "HML-STF", "subject": "x",
                "effectiveFrom": "2026-09-01", "measure": "fine",
                "violationDate": "2026-08-01"})[0] == 400
    code, b = api("POST", "/api/coll/decisions", tokens["admin"],
                  {"kind": "discipline", "empId": "HML-STF", "subject": "Fine 500k",
                   "detail": {"measure": "fine"}})
    assert code == 400 and "/api/hr/decision" in (b.get("error") or "")
    assert db.list_collection("decisions") == []


def test_a_letter_cannot_be_created_through_the_generic_collection_route(api, tokens):
    """Otherwise a letter could be marked Issued with no purpose at all, which is the whole
    disclosure design bypassed in one request."""
    _co(api, tokens); _emp()
    code, b = api("POST", "/api/coll/hrletters", tokens["management"],
                  {"empId": "HML-STF", "purpose": "", "status": "Issued",
                   "disclosesSalary": True})
    assert code == 400 and "/api/hr/letter" in (b.get("error") or "")
    assert db.list_collection("hrletters") == []


def test_an_issued_decision_cannot_be_rewritten_into_a_different_one(api, tokens):
    """A wrong decision is superseded, not edited — otherwise the audit row describes something the
    record no longer says."""
    _co(api, tokens); _emp()
    _, b = api("POST", "/api/hr/decision", tokens["admin"],
               {"kind": "appointment", "empId": "HML-STF", "subject": "Appointed Site Manager",
                "effectiveFrom": "2026-09-01"})
    rid = b["decision"]["id"]
    rec = db.get_collection_item("decisions", rid)
    code, r = api("PATCH", "/api/coll/decisions/" + rid, tokens["admin"],
                  dict(rec, subject="Dismissed for theft", kind="discipline"))
    assert code == 400 and "superseding" in (r.get("error") or "")
    assert db.get_collection_item("decisions", rid)["subject"] == "Appointed Site Manager"


def test_attaching_the_signed_scan_is_still_allowed(api, tokens):
    """The guard must not make the record useless — a signed copy still has to be attachable."""
    _co(api, tokens); _emp()
    _, b = api("POST", "/api/hr/decision", tokens["admin"],
               {"kind": "appointment", "empId": "HML-STF", "subject": "x",
                "effectiveFrom": "2026-09-01"})
    rec = db.get_collection_item("decisions", b["decision"]["id"])
    code, _ = api("PATCH", "/api/coll/decisions/" + rec["id"], tokens["admin"],
                  dict(rec, fileUrl="https://sharepoint/qd-007.pdf", note="signed copy filed"))
    assert code == 200


def test_a_letters_purpose_cannot_be_changed_after_it_is_issued(api, tokens):
    """Changing visa -> bank without re-deriving the disclosure is how a salary leaks."""
    _co(api, tokens); _emp()
    _, b = api("POST", "/api/hr/letter", tokens["management"],
               {"empId": "HML-STF", "purpose": "visa", "issue": True})
    rec = db.get_collection_item("hrletters", b["letter"]["id"])
    code, r = api("PATCH", "/api/coll/hrletters/" + rec["id"], tokens["management"],
                  dict(rec, purpose="bank", disclosesSalary=True))
    assert code == 400 and "purpose" in (r.get("error") or "")


def test_an_empty_list_as_an_employee_id_is_a_400_not_a_500(api, tokens):
    """Reachable by any authenticated account with {"empId": []}; it raised IndexError."""
    for path, body in (("/api/hr/letter", {"empId": [], "purpose": "general"}),
                       ("/api/hr/decision", {"kind": "appointment", "empId": []})):
        code, _ = api("POST", path, tokens["admin"], body)
        assert code < 500, (path, code)


def test_the_audit_line_records_the_value_that_was_actually_stored(api, tokens):
    """It recorded the untruncated input while storage kept 300 chars — so the chain described a
    value that never existed, and every later save re-audited the same non-change."""
    long = "X" * 350
    api("POST", "/api/hr/company", tokens["admin"], dict(FULL_CO, repName=long))
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Company legal identity changed"]
    assert trail and ("X" * 350) not in trail[-1]["detail"]
    n = len(trail)
    _, b = api("POST", "/api/hr/company", tokens["admin"], dict(FULL_CO, repName=long))
    assert b["changed"] == [], "the truncated value must compare equal on the next save"
    assert len([a for a in db.list_collection("audit")
                if a.get("action") == "Company legal identity changed"]) == n
