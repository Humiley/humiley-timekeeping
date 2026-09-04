"""The employment confirmation letter, and what it is allowed to say about somebody.

The letter has no statutory form, which is why it needs a rule of its own: with no form to follow,
the easy implementation prints everything it knows, and everything it knows includes the salary. So
the purpose decides the disclosure, and most of these tests are about that.
"""
import pytest

import employment_letter as el

COMPANY = {
    "legalNameVn": "Công ty TNHH Kỹ thuật Humiley Việt Nam", "legalNameEn": "Humiley Vietnam",
    "regNo": "0316889472", "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Đức Huy", "repTitle": "Tổng Giám đốc",
}
EMP = {
    "id": "HML-001", "name": "Lê Văn Minh", "personalId": "079092004417", "dob": "1992-08-19",
    "title": "Kỹ sư Cơ điện", "dept": "Engineering", "startDate": "2020-03-01",
    "status": "Active", "salary": 24_500_000, "taxId": "8412345678",
}


# ── the disclosure rule, which is the whole point ────────────────────────────────────────────────

def test_only_the_bank_letter_states_the_salary():
    """A consulate and a prospective employer have no business knowing what somebody is paid."""
    assert el.discloses_salary("bank") is True
    for p in ("visa", "new_employer", "general"):
        assert el.discloses_salary(p) is False, p


def test_the_salary_really_is_absent_from_the_rendered_letter_not_just_the_flag():
    """The flag being right is not the same as the field being gone."""
    for p in ("visa", "new_employer", "general"):
        d = el.assemble(COMPANY, EMP, {"purpose": p})
        assert "salary" not in {r["key"] for r in d["rows"]}, p
    d = el.assemble(COMPANY, EMP, {"purpose": "bank"})
    assert "salary" in {r["key"] for r in d["rows"]}


def test_what_was_withheld_is_named_rather_than_silently_dropped():
    """So the employee can see the letter did not say what they hoped and ask for another purpose,
    instead of sending it to the bank and being turned away."""
    d = el.assemble(COMPANY, EMP, {"purpose": "visa"})
    assert "salary" in {w["key"] for w in d["withheld"]}
    assert all(w["labelVn"] for w in d["withheld"])


def test_the_bank_letter_withholds_nothing_it_holds():
    d = el.assemble(COMPANY, EMP, {"purpose": "bank"})
    assert "salary" not in {w["key"] for w in d["withheld"]}


def test_every_purpose_says_why_it_discloses_what_it_does():
    """"Because the template had a field for it" is the answer this exists to prevent."""
    for key, spec in el.PURPOSES.items():
        assert len(spec["why"]) > 40, key
        assert spec["labelVn"], key


def test_the_base_fields_are_on_every_letter():
    for p in el.PURPOSES:
        keys = {r["key"] for r in el.assemble(COMPANY, EMP, {"purpose": p})["rows"]}
        assert {"name", "title", "startDate", "status"} <= keys, p


def test_a_purpose_that_is_not_a_purpose_is_an_error_not_a_maximal_letter():
    """Falling back to "print everything" would make an unknown purpose the most revealing one."""
    with pytest.raises(ValueError):
        el.fields_for("curiosity")


def test_an_unrecognised_purpose_blocks_the_letter():
    b = el.blockers(COMPANY, EMP, {"purpose": "curiosity"})
    assert "purpose" in {m["key"] for m in b["terms"]}
    assert not el.can_issue(COMPANY, EMP, {})


def test_a_letter_assembled_without_a_purpose_falls_back_to_the_base_fields_only():
    """It still cannot be issued — but if it renders at all it must render the LEAST, not the most."""
    d = el.assemble(COMPANY, EMP, {})
    assert d["canIssue"] is False
    assert "salary" not in {r["key"] for r in d["rows"]}


# ── length of service ────────────────────────────────────────────────────────────────────────────

def test_service_is_stated_in_years_and_months():
    s = el.service("2020-03-01", "2026-08-07")
    assert s["months"] == 77 and "6 năm" in s["textVn"] and "5 tháng" in s["textVn"]


def test_less_than_a_year_still_says_months():
    s = el.service("2026-03-01", "2026-08-07")
    assert s["months"] == 5 and s["textVn"] == "5 tháng"


def test_a_start_date_in_the_future_produces_nothing_rather_than_a_negative():
    assert el.service("2027-01-01", "2026-08-07") is None
    assert el.service("", "2026-08-07") is None


def test_singular_and_plural_read_correctly_in_english():
    assert el.service("2025-08-07", "2026-08-07")["text"].strip() == "1 year"
    assert el.service("2026-07-07", "2026-08-07")["text"].strip() == "1 month"


# ── blockers ─────────────────────────────────────────────────────────────────────────────────────

def test_a_complete_request_can_be_issued():
    assert el.can_issue(COMPANY, EMP, {"purpose": "visa"})


def test_the_gaps_are_grouped_by_whose_record_they_are():
    b = el.blockers({}, {}, {})
    assert b["company"] and b["employee"] and b["terms"]


def test_a_letter_needs_a_name_and_a_start_date_because_without_them_it_proves_nothing():
    b = el.blockers(COMPANY, {"name": "X"}, {"purpose": "visa"})
    assert {m["key"] for m in b["employee"]} == {"startDate"}


def test_the_registration_number_does_not_block_this_letter():
    """company.DOCUMENTS deliberately asks for less here than for a contract — a confirmation
    letter has no model form that demands the MSDN."""
    assert el.can_issue(dict(COMPANY, regNo=""), EMP, {"purpose": "visa"})


# ── the rendered document ────────────────────────────────────────────────────────────────────────

def test_the_body_reads_as_a_sentence_in_both_languages():
    d = el.assemble(COMPANY, EMP, {"purpose": "general"}, as_of="2026-08-07")
    assert "xác nhận ông/bà Lê Văn Minh" in d["bodyVn"]
    assert "Kỹ sư Cơ điện" in d["bodyVn"]
    assert "is employed by the company" in d["body"]


def test_the_purpose_is_recorded_on_the_letter_itself():
    """If a salary was disclosed there is a reason on file for why."""
    d = el.assemble(COMPANY, EMP, {"purpose": "bank"}, doc_no="XN-2026-004")
    assert d["purpose"] == "bank" and d["purposeLabelVn"] == "Vay vốn ngân hàng"
    assert d["docNo"] == "XN-2026-004" and d["disclosesSalary"] is True


def test_the_choice_of_purposes_travels_with_the_document_so_the_ui_need_not_restate_it():
    d = el.assemble(COMPANY, EMP, {"purpose": "visa"})
    assert {p["key"] for p in d["purposes"]} == set(el.PURPOSES)


def test_approved_leave_appears_only_on_the_visa_letter_and_only_if_supplied():
    d = el.assemble(COMPANY, EMP, {"purpose": "visa", "leaveApproved": "05/09/2026 – 15/09/2026"})
    assert "leaveApproved" in {r["key"] for r in d["rows"]}
    d2 = el.assemble(COMPANY, EMP, {"purpose": "bank", "leaveApproved": "05/09/2026"})
    assert "leaveApproved" not in {r["key"] for r in d2["rows"]}


def test_an_empty_field_is_omitted_rather_than_printed_blank():
    d = el.assemble(COMPANY, dict(EMP, dept=""), {"purpose": "general"})
    assert "dept" not in {r["key"] for r in d["rows"]}


def test_the_company_name_is_not_prefixed_with_company_twice():
    """The registered name already carries its own legal form. The first letter that printed said
    "Công ty Công ty TNHH Kỹ thuật Humiley Việt Nam"."""
    d = el.assemble(COMPANY, EMP, {"purpose": "general"})
    assert d["bodyVn"].startswith("Công ty TNHH Kỹ thuật Humiley Việt Nam xác nhận")
    assert "Công ty Công ty" not in d["bodyVn"]


def test_the_status_is_stated_in_vietnamese_on_a_vietnamese_letter():
    """Somebody signs this. It should not say "Active"."""
    rows = {r["key"]: r["value"] for r in el.assemble(COMPANY, EMP, {"purpose": "general"})["rows"]}
    assert rows["status"] == "Đang làm việc"
    off = el.assemble(COMPANY, dict(EMP, status="Inactive"), {"purpose": "general"})
    assert {r["key"]: r["value"] for r in off["rows"]}["status"] == "Đã nghỉ việc"


def test_an_unmapped_status_is_printed_as_stored_rather_than_dropped():
    rows = {r["key"]: r["value"] for r in
            el.assemble(COMPANY, dict(EMP, status="Seconded"), {"purpose": "general"})["rows"]}
    assert rows["status"] == "Seconded"


# ── somebody who has left ────────────────────────────────────────────────────────────────────────

GONE = dict(EMP, endDate="2022-03-31", status="Inactive")


def test_a_letter_for_a_leaver_says_they_WERE_employed():
    """The first version asserted current employment in the signed sentence while the rows beneath
    printed "Đã nghỉ việc" — a document contradicting itself on one page, sent to a bank."""
    d = el.assemble(COMPANY, GONE, {"purpose": "new_employer"}, as_of="2026-08-07")
    assert d["hasLeft"] is True
    assert "đã công tác" in d["bodyVn"] and "hiện đang công tác" not in d["bodyVn"]
    assert "was employed" in d["body"] and "is employed" not in d["body"]
    assert "2022-03-31" in d["bodyVn"]


def test_service_stops_on_the_last_day_rather_than_counting_on_after_they_left():
    d = el.assemble(COMPANY, GONE, {"purpose": "general"}, as_of="2026-08-07")
    # 25, not 77: datespan.whole_months counts the end date as the LAST DAY INCLUDED, so
    # 1 Mar 2020 to 31 Mar 2022 is 2 years and 1 month.
    assert d["service"]["months"] == 25, "stops at the last day, does not run to today"
    assert el.service(GONE["startDate"], "2026-08-07")["months"] == 77, "what it used to print"


def test_an_inactive_status_alone_is_enough_even_with_no_end_date():
    d = el.assemble(COMPANY, dict(EMP, status="Inactive"), {"purpose": "general"})
    assert d["hasLeft"] is True and "đã công tác" in d["bodyVn"]


def test_a_current_employee_is_still_described_in_the_present():
    d = el.assemble(COMPANY, EMP, {"purpose": "general"}, as_of="2026-08-07")
    assert d["hasLeft"] is False and "hiện đang công tác" in d["bodyVn"]


def test_a_future_end_date_does_not_make_somebody_a_leaver_yet():
    """Notice served, last day still ahead — they are employed until then."""
    d = el.assemble(COMPANY, dict(EMP, endDate="2026-12-31"), {"purpose": "bank"},
                    as_of="2026-08-07")
    assert d["hasLeft"] is False and "is employed" in d["body"]


def test_the_english_service_line_has_no_trailing_space_at_an_anniversary():
    """It printed "a service of 1 year ." — the visible tell that it was machine-written."""
    b = el.assemble(COMPANY, dict(EMP, startDate="2020-01-01"), {"purpose": "general"},
                    as_of="2021-01-01")["body"]
    assert "1 year ." not in b and "a service of 1 year." in b


# ── the citizen ID is a disclosure, not a header field ───────────────────────────────────────────

def test_a_reference_to_a_prospective_employer_does_not_carry_the_citizen_id():
    """In Vietnam the CCCD is what banks and telcos use for e-KYC. Handing it to somebody who asked
    only whether this person works here is not what they asked for."""
    assert "personalId" not in el.fields_for("new_employer")
    assert "personalId" not in el.fields_for("general")


def test_a_bank_letter_does_carry_it_because_the_lender_must_identify_the_borrower():
    assert "personalId" in el.fields_for("bank")


def test_a_visa_letter_carries_it_so_the_consulate_can_match_the_travel_document():
    assert "personalId" in el.fields_for("visa")


def test_the_letter_says_the_id_was_withheld_rather_than_silently_dropping_it():
    """The employee should be able to see what the letter did not say, and ask for another purpose."""
    doc = el.assemble(COMPANY, dict(EMP, personalId="079095001234"),
                      {"purpose": "new_employer", "addressedTo": "ABC Co."}, as_of="2026-08-08")
    assert "personalId" not in [r["key"] for r in doc["rows"]]
    assert "personalId" in [w["key"] for w in doc["withheld"]]


def test_no_purpose_ever_prints_an_id_that_is_not_on_the_record():
    for purpose in el.PURPOSES:
        doc = el.assemble(COMPANY, dict(EMP, personalId=""),
                          {"purpose": purpose, "addressedTo": "X"}, as_of="2026-08-08")
        assert "personalId" not in [r["key"] for r in doc["rows"]], purpose
