"""Company identity and contract drafting, end to end.

company.py and contract_doc.py prove the rules. This proves what only the server can: that the legal
identity is admin-only and audited, that a contract with an Art. 21 gap in it is refused at the
server rather than by a hopeful form, and that the draft arrives already knowing what Art. 20 says
about this person's history.
"""
import pytest

import company
import contract_doc as cd
import contracts
import db

FULL_CO = {
    "legalNameVn": "Công ty TNHH Humiley Việt Nam", "regNo": "0316123456",
    "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Văn A", "repTitle": "Giám đốc",
}


@pytest.fixture(autouse=True)
def _clean():
    # Every field _setup_employee writes has to be restored, INCLUDING the name. Leaving it renamed
    # broke three unrelated suites that look people up by name — the sixth time order-dependence has
    # come from a fixture restoring less than it changed.
    before_emp = {e["id"]: {k: e.get(k) for k in
                            ("name", "dob", "gender", "address", "personalId", "salary", "title",
                             "startDate", "contractExempt")}
                  for e in db.list_employees()}
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'contracts'")
    conn.commit()
    conn.close()
    for k in company.FIELD_KEYS:
        db.set_setting("portal_co_" + k, None)
    yield
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'contracts'")
    conn.commit()
    conn.close()
    for k in company.FIELD_KEYS:
        db.set_setting("portal_co_" + k, None)
    for eid, v in before_emp.items():
        db.update_employee(eid, v)


def _setup_company(api, tokens, **kw):
    st, b = api("POST", "/api/hr/company", tokens["admin"], dict(FULL_CO, **kw))
    assert st == 200, b
    return b


def _setup_employee(eid="HML-STF"):
    db.update_employee(eid, {"name": "Nguyễn Đức Huy", "dob": "1995-04-12", "gender": "Male",
                             "address": "45 Lê Lợi, Quận 1", "personalId": "079095001234",
                             "title": "Kỹ sư Cơ điện", "salary": 20_000_000,
                             "startDate": "2026-01-01", "contractExempt": ""})


def _terms(**kw):
    base = {"empId": "HML-STF", "jobTitle": "Kỹ sư Cơ điện", "workplace": "123 Nguyễn Huệ",
            "contractType": contracts.DEFINITE, "startDate": "2026-01-01",
            "endDate": "2028-12-31", "wage": 20_000_000}
    base.update(kw)
    return base


# ── the legal identity ───────────────────────────────────────────────────────────────────────────

def test_an_empty_identity_reports_which_documents_it_blocks(api, tokens):
    code, b = api("GET", "/api/hr/company", tokens["admin"])
    assert code == 200
    assert b["filled"] == 0 and "Labour contract" in b["blocked"]


def test_setting_it_unblocks_the_contract(api, tokens):
    _setup_company(api, tokens)
    _, b = api("GET", "/api/hr/company", tokens["admin"])
    assert b["blocked"] == [] and b["identity"]["signatory"] == "Nguyễn Văn A — Giám đốc"


def test_only_an_admin_may_change_who_signs_for_the_company(api, tokens):
    """Changing the legal representative silently would leave every contract issued afterwards
    naming somebody who did not sign it."""
    for who in ("management", "mgr", "staff"):
        assert api("POST", "/api/hr/company", tokens[who], FULL_CO)[0] == 403
    assert api("POST", "/api/hr/company", tokens["admin"], FULL_CO)[0] == 200


def test_management_may_read_it_but_staff_may_not(api, tokens):
    assert api("GET", "/api/hr/company", tokens["management"])[0] == 200
    assert api("GET", "/api/hr/company", tokens["staff"])[0] == 403


def test_every_change_is_written_to_the_audit_chain_with_both_values(api, tokens):
    _setup_company(api, tokens)
    _setup_company(api, tokens, repName="Trần Thị B")
    trail = [a for a in db.list_collection("audit")
             if a.get("action") == "Company legal identity changed"]
    assert any("Nguyễn Văn A" in a["detail"] and "Trần Thị B" in a["detail"] for a in trail)


def test_an_unchanged_save_records_nothing(api, tokens):
    """Otherwise the audit trail fills with saves that changed nothing and hides the one that did."""
    _setup_company(api, tokens)
    n = len([a for a in db.list_collection("audit")
             if a.get("action") == "Company legal identity changed"])
    _, b = api("POST", "/api/hr/company", tokens["admin"], FULL_CO)
    assert b["changed"] == []
    assert len([a for a in db.list_collection("audit")
                if a.get("action") == "Company legal identity changed"]) == n


def test_a_field_that_is_not_a_field_is_refused_rather_than_stored(api, tokens):
    st, b = api("POST", "/api/hr/company", tokens["admin"], {"legalNameVn": "X", "sneaky": "y"})
    assert st == 400 and "sneaky" in (b.get("error") or "")


# ── the draft ────────────────────────────────────────────────────────────────────────────────────

def test_a_draft_offers_what_the_portal_already_knows(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    code, b = api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens["admin"])
    assert code == 200
    assert b["defaults"]["jobTitle"] == "Kỹ sư Cơ điện"
    assert b["defaults"]["wage"] == 20_000_000
    assert b["defaults"]["workplace"] == FULL_CO["addressVn"]


def test_a_draft_states_its_own_gaps_rather_than_failing(api, tokens):
    """The drafter needs to see the rest of the document to know what to go and find."""
    _setup_employee()
    db.update_employee("HML-STF", {"personalId": ""})
    code, b = api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens["admin"])
    assert code == 200 and b["canIssue"] is False
    assert "personalId" in {m["key"] for m in b["blockers"]["employee"]}
    assert b["blockers"]["company"], "the identity was never set either"


def test_the_draft_arrives_knowing_a_third_fixed_term_is_unlawful(api, tokens):
    """Art. 20(2)(c). The drafter should not have to remember; the default flips to indefinite."""
    _setup_company(api, tokens)
    _setup_employee()
    for i, (s, e) in enumerate((("2022-01-01", "2023-12-31"), ("2024-01-01", "2025-12-31"))):
        db.put_collection_item("contracts", {"id": "old-%d" % i, "empId": "HML-STF",
                                             "type": contracts.DEFINITE,
                                             "startDate": s, "endDate": e})
    _, b = api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens["admin"])
    assert b["position"]["mustBeIndefinite"] is True
    assert b["defaults"]["contractType"] == contracts.INDEFINITE


def test_the_probation_ceilings_travel_with_the_draft(api, tokens):
    _setup_employee()
    _, b = api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens["admin"])
    assert {x["key"]: x["days"] for x in b["probationBands"]}["degree"] == 60
    assert b["probationBands"][0]["days"] == 180, "longest first"


def test_a_draft_for_nobody_is_a_404(api, tokens):
    assert api("GET", "/api/hr/contract/draft?emp=NOPE", tokens["admin"])[0] == 404
    assert api("GET", "/api/hr/contract/draft", tokens["admin"])[0] == 404


# ── issuing ──────────────────────────────────────────────────────────────────────────────────────

def test_a_complete_contract_is_recorded_and_audited(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    code, b = api("POST", "/api/hr/contract", tokens["admin"], _terms(no="HD-2026-001"))
    assert code == 200, b
    assert b["contract"]["empId"] == "HML-STF" and b["contract"]["type"] == contracts.DEFINITE
    assert b["document"]["content"]["đ"]["wageInWords"] == "Hai mươi triệu đồng"
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Labour contract issued"]
    assert any("HML-STF" in a["detail"] for a in trail)


def test_the_contract_reaches_the_register_the_warnings_read(api, tokens):
    """The register was a reader with no writer. This is the whole point of the endpoint."""
    _setup_company(api, tokens)
    _setup_employee()
    api("POST", "/api/hr/contract", tokens["admin"], _terms())
    _, rev = api("GET", "/api/hr/contracts/review", tokens["admin"])
    row = [r for r in rev["rows"] if r["empId"] == "HML-STF"][0]
    assert row["status"] in ("active", "expiring") and row["to"] == "2028-12-31"


def test_a_contract_with_no_company_identity_is_refused_by_the_server(api, tokens):
    """Not by a hopeful form — the form can be bypassed."""
    _setup_employee()
    code, b = api("POST", "/api/hr/contract", tokens["admin"], _terms())
    assert code == 400
    assert {m["key"] for m in b["blockers"]["company"]} >= {"legalNameVn", "repName"}
    assert db.list_collection("contracts") == []


def test_a_contract_with_no_wage_is_refused(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    code, b = api("POST", "/api/hr/contract", tokens["admin"], _terms(wage=0))
    assert code == 400 and "wage" in {m["key"] for m in b["blockers"]["terms"]}


def test_a_fixed_term_beyond_thirty_six_months_is_refused_with_the_lawful_date(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    code, b = api("POST", "/api/hr/contract", tokens["admin"], _terms(endDate="2029-06-30"))
    assert code == 400
    assert any("2028-12-31" in msg for msg in b["blockers"]["term"])


def test_probation_beyond_the_art_25_ceiling_is_refused(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    code, b = api("POST", "/api/hr/contract", tokens["admin"],
                  _terms(probationDays=90, probationBand="degree"))
    assert code == 400 and any("Art. 25" in m for m in b["blockers"]["term"])


def test_an_employee_missing_their_id_number_blocks_the_contract(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    db.update_employee("HML-STF", {"personalId": ""})
    code, b = api("POST", "/api/hr/contract", tokens["admin"], _terms())
    assert code == 400 and "personalId" in {m["key"] for m in b["blockers"]["employee"]}


# ── who may do what ──────────────────────────────────────────────────────────────────────────────

def test_below_management_can_neither_draft_nor_issue(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    for who in ("mgr", "staff"):
        assert api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens[who])[0] == 403
        assert api("POST", "/api/hr/contract", tokens[who], _terms())[0] == 403


def test_management_can(api, tokens):
    _setup_company(api, tokens)
    _setup_employee()
    assert api("GET", "/api/hr/contract/draft?emp=HML-STF", tokens["management"])[0] == 200
    assert api("POST", "/api/hr/contract", tokens["management"], _terms())[0] == 200


# ── the second door ──────────────────────────────────────────────────────────────────────────────

def test_the_generic_collection_route_cannot_create_a_contract_with_no_particulars(api, tokens):
    """Measured before it was fixed: this returned 200 and stored a labour contract with none of the
    ten Art. 21 particulars and no Art. 20 term check. Every check in contract_doc.py was one URL
    away from irrelevant — the same hole that decisions, letters, concerns and accidents had."""
    code, b = api("POST", "/api/coll/contracts", tokens["management"],
                  {"empId": "HML-STF", "type": "definite", "terms": {}})
    assert code in (400, 403), b
    assert "labour contract" in str(b.get("error", "")).lower()


def test_what_was_agreed_cannot_be_edited_after_the_contract_is_issued(api, tokens):
    """A change to the wage, the term or the job is an annex or a new contract, not an edit."""
    _setup_company(api, tokens); _setup_employee()
    code, made = api("POST", "/api/hr/contract", tokens["management"], _terms())
    assert code == 200, made
    cid = made["contract"]["id"]
    code, b = api("PATCH", "/api/coll/contracts/" + cid, tokens["management"],
                  dict(made["contract"], terms=dict(made["contract"]["terms"], wage=1)))
    assert code == 400, b
    assert "cannot be rewritten" in str(b.get("error", ""))


def test_the_signed_scan_and_the_ending_can_still_be_attached(api, tokens):
    _setup_company(api, tokens); _setup_employee()
    code, made = api("POST", "/api/hr/contract", tokens["management"], _terms())
    assert code == 200, made
    rec = made["contract"]
    code, b = api("PATCH", "/api/coll/contracts/" + rec["id"], tokens["management"],
                  dict(rec, fileUrl="https://sp/contract.pdf", signedAt="2026-08-08",
                       status="Signed"))
    assert code == 200, b
