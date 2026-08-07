"""Drafting a labour contract, and refusing to draft one with a silent gap in it.

Art. 21(1) lists ten particulars a labour contract must contain. The value of this module is not
formatting — it is that a draft shows its own holes, grouped by whose record has to change, so
nobody discovers a blank line after printing and signing.
"""
import contract_doc as cd
import contracts

COMPANY = {
    "legalNameVn": "Công ty TNHH Humiley Việt Nam", "regNo": "0316123456",
    "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Văn A", "repTitle": "Giám đốc",
}
EMP = {
    "id": "HML-001", "name": "Nguyễn Đức Huy", "dob": "1995-04-12", "gender": "Male",
    "address": "45 Lê Lợi, Quận 1, TP. Hồ Chí Minh", "personalId": "079095001234",
    "title": "Kỹ sư Cơ điện", "dept": "Engineering", "salary": 20_000_000,
    "startDate": "2026-01-01",
}


def _terms(**kw):
    base = {"jobTitle": "Kỹ sư Cơ điện", "workplace": "123 Nguyễn Huệ, Quận 1",
            "contractType": contracts.DEFINITE, "startDate": "2026-01-01",
            "endDate": "2028-12-31", "wage": 20_000_000}
    base.update(kw)
    return base


# ── the blockers, grouped by whose record it is ──────────────────────────────────────────────────

def test_a_complete_draft_can_be_issued():
    assert cd.can_issue(COMPANY, EMP, _terms())


def test_the_three_kinds_of_gap_are_reported_separately():
    """The company identity is fixed by an administrator in settings, the employee fields by HR on
    the person's record, the terms by whoever is drafting. One flat red list sends everybody to the
    wrong screen."""
    b = cd.blockers({}, {}, {})
    assert b["company"] and b["employee"] and b["terms"]
    assert {m["key"] for m in b["employee"]} == {k for k, _, _ in cd.EMPLOYEE_REQUIRED}


def test_an_incomplete_employee_blocks_the_contract_by_field_name():
    b = cd.blockers(COMPANY, dict(EMP, personalId="", dob=""), _terms())
    assert {m["key"] for m in b["employee"]} == {"personalId", "dob"}
    assert not b["company"] and not b["terms"]


def test_a_wage_of_zero_is_a_missing_wage_not_a_wage_of_zero():
    """The string test that came first read _s(0) as "0" and let it through — a contract with no
    wage on it, which is the one term nobody can afford to leave blank."""
    assert "wage" in {m["key"] for m in cd.blockers(COMPANY, EMP, _terms(wage=0))["terms"]}
    assert "wage" not in {m["key"] for m in cd.blockers(COMPANY, EMP, _terms())["terms"]}


def test_a_wage_that_is_not_a_number_is_missing_too():
    assert "wage" in {m["key"] for m in cd.blockers(COMPANY, EMP, _terms(wage="soon"))["terms"]}


def test_every_blocker_carries_a_vietnamese_label():
    b = cd.blockers({}, {}, {})
    for group in ("company", "employee", "terms"):
        assert all(m["labelVn"] for m in b[group]), group


# ── the term: Art. 20, reused rather than restated ───────────────────────────────────────────────

def test_a_definite_term_over_thirty_six_months_is_refused_with_the_lawful_date():
    """Telling somebody the term is too long without saying how long it may be makes them guess."""
    out = cd.term_check(_terms(endDate="2029-06-30"))
    assert out and "36 months" in out[0] and "2028-12-31" in out[0]


def test_exactly_thirty_six_months_is_lawful():
    assert cd.term_check(_terms(startDate="2026-01-01", endDate="2028-12-31")) == []


def test_a_definite_term_with_no_end_date_is_not_definite():
    out = cd.term_check(_terms(endDate=""))
    assert out and "end date" in out[0]


def test_an_indefinite_contract_with_an_end_date_is_a_contradiction():
    out = cd.term_check(_terms(contractType=contracts.INDEFINITE))
    assert out and "no end date" in out[0]


def test_an_indefinite_contract_without_one_is_fine():
    assert cd.term_check(_terms(contractType=contracts.INDEFINITE, endDate="")) == []


def test_a_contract_that_ends_before_it_starts():
    out = cd.term_check(_terms(startDate="2026-06-01", endDate="2026-01-01"))
    assert out and "ends before it starts" in out[0]


def test_a_type_that_is_not_a_type_is_named_rather_than_ignored():
    out = cd.term_check(_terms(contractType="seasonal"))
    assert out and "seasonal" in out[0] and "Art. 20" in out[0]


# ── probation: Art. 25 ───────────────────────────────────────────────────────────────────────────

def test_each_band_has_its_own_ceiling():
    assert cd.probation_cap("manager")["days"] == 180
    assert cd.probation_cap("degree")["days"] == 60
    assert cd.probation_cap("intermediate")["days"] == 30
    assert cd.probation_cap("other")["days"] == 6


def test_a_band_that_is_not_a_band_has_no_ceiling_rather_than_a_default_one():
    """Falling back to the longest would let anybody be probated for six months."""
    assert cd.probation_cap("") is None and cd.probation_cap("senior") is None


def test_probation_beyond_the_ceiling_is_refused_and_cites_the_article():
    out = cd.term_check(_terms(probationDays=90, probationBand="degree"))
    assert out and "60-day ceiling" in out[0] and "Art. 25" in out[0]


def test_probation_without_a_band_cannot_be_checked_and_says_so():
    out = cd.term_check(_terms(probationDays=30))
    assert out and "kind of post" in out[0]


def test_probation_within_the_ceiling_passes():
    assert cd.term_check(_terms(probationDays=60, probationBand="degree")) == []


def test_no_probation_needs_no_band():
    assert cd.term_check(_terms()) == []


# ── what the portal offers versus what it asserts ────────────────────────────────────────────────

def test_the_portal_offers_what_it_knows_as_a_starting_point():
    d = cd.defaults_from(EMP, COMPANY)
    assert d["jobTitle"] == "Kỹ sư Cơ điện" and d["wage"] == 20_000_000
    assert d["workplace"] == COMPANY["addressVn"]


def test_the_defaults_are_not_treated_as_agreed():
    """A job title on an HR record is what somebody is called day to day; a contract states what
    they were hired to do. The draft must still be able to disagree with the record."""
    d = cd.defaults_from(EMP, COMPANY)
    drafted = cd.assemble(COMPANY, EMP, dict(_terms(), jobTitle="Trưởng nhóm Cơ điện"))
    assert drafted["content"]["c"]["jobTitle"] == "Trưởng nhóm Cơ điện" != d["jobTitle"]


# ── the assembled document ───────────────────────────────────────────────────────────────────────

def test_all_ten_particulars_are_present_and_each_says_where_it_came_from():
    doc = cd.assemble(COMPANY, EMP, _terms())
    assert len(doc["particulars"]) == 10
    assert {p["code"] for p in doc["particulars"]} == set("abcdđeghik")
    assert {p["source"] for p in doc["particulars"]} == {"company", "employee", "terms", "statutory"}
    assert set(doc["content"]) == {p["code"] for p in doc["particulars"]}


def test_the_wage_is_stated_in_words_as_well_as_figures():
    doc = cd.assemble(COMPANY, EMP, _terms())
    assert doc["content"]["đ"]["wage"] == 20_000_000
    assert doc["content"]["đ"]["wageInWords"] == "Hai mươi triệu đồng"


def test_the_term_reads_as_a_sentence_in_both_languages_with_the_month_count():
    doc = cd.assemble(COMPANY, EMP, _terms())
    assert "36" in doc["content"]["d"]["text"] and "36" in doc["content"]["d"]["textVn"]
    assert "xác định thời hạn" in doc["content"]["d"]["textVn"]


def test_an_indefinite_contract_does_not_claim_a_month_count():
    doc = cd.assemble(COMPANY, EMP, _terms(contractType=contracts.INDEFINITE, endDate=""))
    assert "không xác định thời hạn" in doc["content"]["d"]["textVn"]
    assert doc["content"]["d"]["endDate"] == ""


def test_the_insurance_particular_states_the_statute_rather_than_a_negotiated_figure():
    doc = cd.assemble(COMPANY, EMP, _terms())
    assert "Luật Bảo hiểm xã hội" in doc["content"]["i"]["textVn"]
    assert [p for p in doc["particulars"] if p["code"] == "i"][0]["source"] == "statutory"


def test_a_draft_with_gaps_still_assembles_and_carries_its_own_gaps():
    """An error message is less useful than a draft that shows what is missing — the drafter needs
    to see the rest of it to know what to go and find."""
    doc = cd.assemble({}, {}, {})
    assert doc["canIssue"] is False
    assert doc["content"] and doc["blockers"]["company"]


def test_the_two_copies_rule_travels_with_the_document():
    """Art. 13(1) — the employee gets one. A portal that holds the only copy is the failure mode."""
    doc = cd.assemble(COMPANY, EMP, _terms())
    assert "two copies" in doc["copies"] and "Art. 13(1)" in doc["copies"]
    assert "hai bản" in doc["copiesVn"]


def test_the_legal_basis_comes_back_with_the_document():
    doc = cd.assemble(COMPANY, EMP, _terms())
    for cite in ("Art. 21(1)", "Art. 20", "Art. 25", "Circular 10/2020"):
        assert cite in doc["basis"], cite


def test_a_date_the_parser_cannot_read_is_refused_rather_than_silently_disabling_art_20():
    """The whole point of this module. A drafter typing 30/01/2026 in the Vietnamese format got the
    36-month ceiling switched off entirely, and a 15-year fixed term issued without a word."""
    out = cd.term_check(_terms(startDate="01/01/2026", endDate="2040-12-31"))
    assert out and "not a date" in out[0]
    assert not cd.can_issue(COMPANY, EMP, _terms(startDate="01/01/2026", endDate="2040-12-31"))


def test_an_unreadable_end_date_is_named_too():
    out = cd.term_check(_terms(endDate="31/12/2028"))
    assert any("end date" in m and "not a date" in m for m in out)
