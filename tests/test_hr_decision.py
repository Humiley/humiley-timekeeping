"""Company decisions about staff, and the parts of them the law actually governs.

Most of a quyết định is convention. These tests are about the parts that are not: a dismissal issued
eight months after the incident is void, a "fine" is an act Art. 127 forbids outright, and the notice
a termination owes has two special cases that a straight reading of the ladder gets wrong.

Article text checked against the official English translation of Labour Code 45/2019/QH14.
"""
import pytest

import hr_decision as hd

COMPANY = {
    "legalNameVn": "Công ty TNHH Kỹ thuật Humiley Việt Nam", "regNo": "0316889472",
    "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "repName": "Nguyễn Đức Huy", "repTitle": "Tổng Giám đốc",
}
EMP = {"id": "HML-001", "name": "Lê Văn Minh", "title": "Kỹ sư Cơ điện", "dept": "Engineering"}


# ── Art. 36(2)/(3): the notice ladder, and its two traps ─────────────────────────────────────────

def test_the_plain_ladder_by_contract_type():
    assert hd.notice_required("indefinite")["days"] == 45
    assert hd.notice_required("definite", 24)["days"] == 30
    assert hd.notice_required("definite", 6)["days"] == 3


def test_a_short_contract_counts_working_days_not_calendar_days():
    """Art. 36(2)(c) says "03 working days". Three calendar days over a weekend is not three."""
    assert hd.notice_required("definite", 6)["working"] is True
    assert hd.notice_required("indefinite")["working"] is False


def test_the_long_illness_ground_is_three_working_days_whatever_the_contract_says():
    """The first trap. Art. 36(2)(c) names Art. 36(1)(b) alongside the under-12-month contracts, so
    an indefinite contract terminated on that ground owes 3 working days, NOT 45. Reading the ladder
    off the contract type alone gets this wrong by six weeks."""
    n = hd.employer_notice("long_illness", "indefinite")
    assert n["days"] == 3 and n["working"] is True
    assert hd.notice_required("indefinite")["days"] == 45, "the plain ladder still says 45"


def test_two_grounds_carry_no_advance_notice_at_all():
    """The second trap — Art. 36(3) exempts points (d) and (e) entirely."""
    for key in ("absent_after_suspension", "absent_five_days"):
        n = hd.employer_notice(key, "indefinite")
        assert n["days"] == 0, key
        assert "Art. 36(3)" in n["basis"]


def test_the_other_grounds_do_follow_the_ladder():
    for key in ("underperformance", "force_majeure", "retirement", "untruthful"):
        assert hd.employer_notice(key, "indefinite")["days"] == 45, key
        assert hd.employer_notice(key, "definite", 24)["days"] == 30, key


def test_a_ground_that_is_not_an_art_36_ground_has_no_employer_notice():
    """Returning a default would invent an obligation for a termination Art. 36 does not cover."""
    assert hd.employer_notice("expiry", "indefinite") is None
    assert hd.employer_notice("", "indefinite") is None


def test_the_basis_names_the_article_so_nobody_has_to_take_it_on_trust():
    assert "Art. 36(2)(a)" in hd.notice_required("indefinite")["basis"]
    assert "Art. 36(3)" in hd.employer_notice("absent_five_days", "indefinite")["basis"]


# ── Art. 45(1): which terminations need a written notice ─────────────────────────────────────────

def test_the_five_exempt_grounds_are_exactly_art_34_clauses_four_to_eight():
    """The exception list in Art. 45(1) is exact, and it is why some exits produce a decision and
    some do not. Getting it wrong either omits a required notice or demands an impossible one — you
    cannot serve a termination notice on somebody who has died."""
    exempt = {g["key"] for g in hd.TERMINATION_GROUNDS if not g["notice"]}
    assert exempt == {"imprisoned", "expelled", "employee_dead", "employer_gone", "dismissal"}
    assert {g["clause"] for g in hd.TERMINATION_GROUNDS if not g["notice"]} == {4, 5, 6, 7, 8}


def test_an_ordinary_termination_needs_written_notice():
    for key in ("expiry", "mutual", "employer_unilateral", "employee_unilateral", "redundancy"):
        assert hd.needs_written_notice(key)["required"] is True, key


def test_a_dismissal_needs_no_separate_notice_because_the_disciplinary_decision_is_the_document():
    r = hd.needs_written_notice("dismissal")
    assert r["required"] is False and "Art. 34(8)" in r["basis"]


def test_a_ground_that_is_not_a_ground_returns_nothing_rather_than_false():
    """False would read as "no notice needed", which is the dangerous answer."""
    assert hd.needs_written_notice("banana") is None


# ── Art. 123: the clock on a disciplinary decision ───────────────────────────────────────────────

def test_the_ordinary_limit_is_six_months_from_the_violation():
    d = hd.discipline_deadline("2026-01-15")
    assert d["deadline"] == "2026-07-15" and d["months"] == 6


def test_finance_assets_and_trade_secrets_get_twelve():
    assert hd.discipline_deadline("2026-01-15", serious=True)["deadline"] == "2027-01-15"


def test_the_sixty_day_extension_runs_from_the_end_of_the_art_122_4_period():
    """The first version added 60 days to the DEADLINE. Art. 123(2) runs them from the end of the
    Art. 122(4) suspension — so a maternity leave outlasting the 6-month limit, which is the
    ordinary case the clause exists for, was refusing a lawful dismissal."""
    d = hd.discipline_deadline("2026-01-10", suspended_until="2026-12-31")
    assert d["deadline"] == "2027-03-01" and d["extended"] is True
    assert d["baseDeadline"] == "2026-07-10"


def test_the_extension_is_not_granted_when_the_limit_still_has_sixty_days_to_run():
    """Art. 123(2) applies only where the limit has expired by then, or has under 60 days left."""
    d = hd.discipline_deadline("2026-01-15", suspended_until="2026-02-01")
    assert d["extended"] is False and d["deadline"] == "2026-07-15"


def test_the_extension_is_not_automatic():
    assert hd.discipline_deadline("2026-01-15")["extended"] is False


def test_a_flag_that_arrives_as_the_string_false_is_false():
    """A form posts strings, and bool("false") is True — which doubled the Art. 123 limit and let a
    time-barred dismissal through."""
    assert hd._flag("false") is False and hd._flag("0") is False and hd._flag("") is False
    assert hd._flag("true") is True and hd._flag(True) is True and hd._flag(1) is True


def test_a_decision_inside_the_limit_passes():
    assert hd.discipline_check("reprimand", "2026-06-01", "2026-07-01") == []


def test_a_decision_outside_it_is_refused_and_says_the_last_lawful_date():
    out = hd.discipline_check("dismissal", "2025-01-10", "2026-07-01")
    assert out and "Out of time" in out[0] and "2025-07-10" in out[0]


def test_a_decision_dated_before_the_violation_is_refused():
    out = hd.discipline_check("reprimand", "2026-06-01", "2026-05-01")
    assert out and "before the violation" in out[0]


def test_without_the_violation_date_nobody_can_say_whether_it_is_in_time():
    out = hd.discipline_check("reprimand", "", "2026-07-01")
    assert out and "date of the violation" in out[0]


# ── Art. 124 / 127: what is and is not a disciplinary measure ────────────────────────────────────

def test_there_are_exactly_four_measures():
    assert [m["key"] for m in hd.MEASURES] == ["reprimand", "defer_raise", "demotion", "dismissal"]
    assert [m["clause"] for m in hd.MEASURES] == [1, 2, 3, 4]


def test_a_monetary_fine_is_refused_by_name():
    """Art. 127(2). A portal that rendered this would be helping to do something unlawful."""
    out = hd.discipline_check("fine", "2026-06-01", "2026-07-01")
    assert out and "Art. 127(2)" in out[0] and "fines" in out[0]


def test_deducting_wages_is_refused_and_the_lawful_alternative_is_named():
    """Somebody reaching for this usually means Art. 129 damage recovery, which is a different
    thing with a different procedure — saying so is more useful than just refusing."""
    out = hd.discipline_check("salary_deduction", "2026-06-01", "2026-07-01")
    assert out and "Art. 127(2)" in out[0] and "Art. 129" in out[0]


def test_unpaid_suspension_is_not_one_of_the_four():
    out = hd.discipline_check("suspension_unpaid", "2026-06-01", "2026-07-01")
    assert out and "Art. 124" in out[0]


def test_an_invented_measure_is_refused_and_the_four_are_listed():
    out = hd.discipline_check("banishment", "2026-06-01", "2026-07-01")
    assert out and "Art. 124 allows exactly four" in out[0]


def test_a_forbidden_measure_is_refused_before_anything_else_is_checked():
    """It is not a measure at all, so "and by the way it is out of time" only muddies the message."""
    out = hd.discipline_check("fine", "2020-01-01", "2026-07-01")
    assert len(out) == 1 and "Art. 127(2)" in out[0]


def test_a_pay_rise_may_be_deferred_by_at_most_six_months():
    assert hd.discipline_check("defer_raise", "2026-06-01", "2026-07-01", defer_months=6) == []
    out = hd.discipline_check("defer_raise", "2026-06-01", "2026-07-01", defer_months=9)
    assert out and "at most 6 months" in out[0] and "Art. 124(2)" in out[0]


# ── termination as recorded ──────────────────────────────────────────────────────────────────────

def test_an_art_36_termination_must_say_which_of_the_seven_grounds_it_rests_on():
    """The notice owed depends on it, and a termination on no stated ground is unlawful."""
    out = hd.termination_check("employer_unilateral", "indefinite")
    assert len(out) == 1
    assert "which of the seven grounds in art. 36(1)" in out[0].lower()


def test_short_notice_is_reported_with_both_numbers():
    out = hd.termination_check("employer_unilateral", "indefinite",
                               employer_ground="underperformance",
                               notice_date="2026-08-01", last_day="2026-08-20")
    assert out and "Short notice" in out[0] and "45" in out[0] and "19" in out[0]


def test_full_notice_passes():
    assert hd.termination_check("employer_unilateral", "indefinite",
                                employer_ground="underperformance",
                                notice_date="2026-06-01", last_day="2026-08-01") == []


def test_a_ground_needing_no_notice_never_complains_about_it():
    assert hd.termination_check("employer_unilateral", "indefinite",
                                employer_ground="absent_five_days") == []


def test_an_unrecorded_notice_date_is_reported_rather_than_assumed_compliant():
    out = hd.termination_check("employer_unilateral", "indefinite",
                               employer_ground="underperformance", last_day="2026-08-20")
    assert out and "does not say when the employee was told" in out[0]


def test_a_resignation_on_short_notice_is_a_NOTE_and_never_blocks_the_record():
    """It was a blocker, which stopped the commonest exit there is from being recorded at all — and
    Art. 35(2) lists seven grounds on which the employee owes no notice whatever."""
    assert hd.termination_check("employee_unilateral", "indefinite",
                                notice_date="2026-08-01", last_day="2026-08-10") == []
    notes = hd.notes("termination", {"ground": "employee_unilateral", "contractType": "indefinite",
                                     "noticeDate": "2026-08-01", "effectiveFrom": "2026-08-10"})
    assert notes and "The employee gave 9" in notes[0] and "Art. 35(2)" in notes[0]


def test_a_dismissal_recorded_as_a_termination_still_faces_the_art_123_clock():
    """Art. 34(8) — a dismissal IS a disciplinary measure. Recording it under kind="termination"
    with ground="dismissal" used to skip every Art. 122-127 check, so the one refusal the module
    exists to enforce was whichever the caller felt like."""
    out = hd.termination_check("dismissal", "indefinite",
                               violation_date="2025-01-10", issued_on="2026-08-07")
    assert out and "Out of time" in out[0]
    assert hd.termination_check("dismissal", "indefinite",
                                violation_date="2026-06-01", issued_on="2026-08-07") == []


def test_a_three_working_day_notice_is_counted_in_working_days():
    """Friday to Monday is three calendar days and two working ones. Comparing the Art. 36(2)(c)
    requirement against calendar days certified an unlawfully short notice as lawful."""
    out = hd.termination_check("employer_unilateral", "indefinite",
                               employer_ground="long_illness",
                               notice_date="2026-08-07", last_day="2026-08-10")
    assert out and "Short notice" in out[0] and "working day" in out[0]
    assert hd.termination_check("employer_unilateral", "indefinite",
                                employer_ground="long_illness",
                                notice_date="2026-08-07", last_day="2026-08-11") == []


def test_the_deferment_period_is_stated_in_the_operative_article_not_the_statutory_ceiling():
    """Điều 1 said "kéo dài thời hạn nâng lương không quá 06 tháng" for a 3-month penalty — a
    decision that imposes nothing an employee could plan around."""
    d = hd.assemble("discipline", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-08-10",
                     "measure": "defer_raise", "deferMonths": 3})
    a1 = d["articles"][0]["textVn"]
    assert "Thời hạn kéo dài: 3 tháng" in a1 and "không quá 06 tháng" not in a1


def test_a_deferment_with_no_period_is_refused():
    out = hd.discipline_check("defer_raise", "2026-06-01", "2026-07-01")
    assert out and "for how many months" in out[0]
    assert hd.discipline_check("defer_raise", "2026-06-01", "2026-07-01", defer_months=0)


def test_a_ground_that_is_not_in_art_34_is_refused():
    out = hd.termination_check("because_i_said_so", "indefinite")
    assert out and "Art. 34" in out[0]


def test_the_offboarding_exit_types_all_map_onto_an_art_34_ground():
    """_EXIT_TYPES in the frontend. An unmapped type would mean an exit that can never produce a
    decision, which is exactly the reader-with-no-writer failure this work exists to end."""
    for t in ("Resignation", "End of contract", "Termination", "Retirement", "Mutual agreement"):
        key = hd.ground_for_exit(t)
        assert key, t
        assert key in {g["key"] for g in hd.TERMINATION_GROUNDS}, t


def test_an_unknown_exit_type_maps_to_nothing_rather_than_a_default():
    assert hd.ground_for_exit("Vanished") == ""


# ── the assembled decision ───────────────────────────────────────────────────────────────────────

def test_every_decision_type_declares_whether_the_law_governs_it():
    governed = {k for k, v in hd.DECISIONS.items() if v["governed"]}
    assert governed == {"termination", "discipline"}
    assert all(v["basis"] for v in hd.DECISIONS.values())


def test_the_document_carries_the_conventional_vietnamese_shape():
    d = hd.assemble("appointment", COMPANY, EMP,
                    {"subject": "Appointed Site Manager", "subjectVn": "Bổ nhiệm Chỉ huy trưởng",
                     "effectiveFrom": "2026-09-01"}, doc_no="12", as_of="2026-08-07")
    assert d["nationalHeading"] == "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
    assert d["recitals"] and all(r.startswith("Căn cứ") for r in d["recitals"])
    assert [a["no"] for a in d["articles"]] == [1, 2]
    assert d["recipients"], "Nơi nhận"


def test_the_employee_is_always_on_the_recipient_list():
    """A decision about somebody that they are not given is not a decision they can answer."""
    d = hd.assemble("discipline", COMPANY, EMP,
                    {"subject": "x", "measure": "reprimand", "effectiveFrom": "2026-09-01"})
    assert any("Người lao động" in r for r in d["recipients"])


def test_a_termination_cites_the_exact_clause_it_rests_on():
    """The recitals are assembled from the rules that actually apply, so a decision cannot cite an
    article it does not rest on."""
    d = hd.assemble("termination", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-09-01",
                     "ground": "employer_unilateral", "employerGround": "underperformance"})
    assert any("khoản 10 Điều 34" in r for r in d["recitals"])
    assert any("điểm a khoản 1 Điều 36" in r for r in d["recitals"])


def test_a_termination_that_is_not_under_art_36_cites_no_art_36_point():
    d = hd.assemble("termination", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-09-01", "ground": "expiry"})
    assert any("khoản 1 Điều 34" in r for r in d["recitals"])
    assert not any("Điều 36" in r for r in d["recitals"])


def test_a_discipline_decision_cites_the_procedure_articles():
    d = hd.assemble("discipline", COMPANY, EMP,
                    {"subject": "x", "measure": "demotion", "effectiveFrom": "2026-09-01"})
    assert any("Điều 122" in r and "Điều 124" in r for r in d["recitals"])


def test_the_last_article_is_always_the_implementation_clause():
    for kind, extra in (("appointment", {}), ("termination", {"ground": "expiry"}),
                        ("discipline", {"measure": "reprimand"})):
        d = hd.assemble(kind, COMPANY, EMP,
                        dict({"subject": "x", "effectiveFrom": "2026-09-01"}, **extra))
        assert "chịu trách nhiệm thi hành" in d["articles"][-1]["textVn"], kind
        assert d["articles"][-1]["no"] == len(d["articles"]), kind


def test_an_unknown_decision_type_is_an_error_not_a_blank_document():
    with pytest.raises(ValueError):
        hd.assemble("promotion_to_wizard", COMPANY, EMP, {})
    with pytest.raises(ValueError):
        hd.blockers("promotion_to_wizard", COMPANY, EMP, {})


# ── blockers ─────────────────────────────────────────────────────────────────────────────────────

def test_a_complete_decision_can_be_issued():
    assert hd.can_issue("appointment", COMPANY, EMP,
                        {"subject": "Appointed Site Manager", "effectiveFrom": "2026-09-01"})


def test_the_gaps_are_grouped_by_whose_record_they_are():
    b = hd.blockers("appointment", {}, {}, {})
    assert b["company"] and b["employee"] and b["terms"]
    assert {m["key"] for m in b["terms"]} == {"subject", "effectiveFrom"}


def test_a_governed_decision_reports_its_legal_problems_separately_from_its_blank_fields():
    """A missing field and an unlawful measure are different kinds of problem — one is an omission,
    the other is a refusal — so they do not share a list."""
    b = hd.blockers("discipline", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-09-01", "measure": "fine",
                     "violationDate": "2026-06-01"})
    assert b["terms"] == [] and b["law"] and "Art. 127(2)" in b["law"][0]


def test_an_ungoverned_decision_has_no_legal_problems_to_report():
    b = hd.blockers("appointment", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-09-01"})
    assert b["law"] == []


def test_a_draft_with_gaps_still_assembles_and_carries_them():
    d = hd.assemble("termination", {}, {}, {})
    assert d["canIssue"] is False and d["blockers"]["company"]
    assert d["articles"], "the drafter still needs to see the rest of it"


def test_an_unrecorded_contract_type_refuses_to_invent_a_notice_period():
    """It returned the 30-day middle rung for a blank type — inventing an obligation from missing
    data, and wrong in both directions: indefinite owes 45, a short fixed term owes 3 working days."""
    assert hd.notice_required("")["days"] is None
    assert hd.notice_required("definite")["days"] is None, "no term length recorded"
    out = hd.termination_check("employer_unilateral", "", employer_ground="underperformance",
                               notice_date="2026-07-01", last_day="2026-08-05")
    assert out and "not recorded" in out[0]


def test_a_known_contract_still_gets_its_rung():
    assert hd.notice_required("indefinite")["days"] == 45
    assert hd.notice_required("definite", 24)["days"] == 30
    assert hd.notice_required("definite", 6)["days"] == 3


def test_a_termination_not_under_art_36_does_not_recite_an_art_36_point():
    """A consensual exit reciting the 5-day-unexcused-absence clause misstates the ground on the
    face of a signed document."""
    d = hd.assemble("termination", COMPANY, EMP,
                    {"subject": "x", "effectiveFrom": "2026-09-01",
                     "ground": "mutual", "employerGround": "absent_five_days"})
    assert not any("Điều 36" in r for r in d["recitals"])
    assert any("khoản 3 Điều 34" in r for r in d["recitals"])


# ── Decree 145/2020 Art. 7: the rung the ladder never had ────────────────────────────────────────

def test_an_enterprise_manager_on_an_indefinite_contract_is_owed_120_days_not_45():
    """Art. 36(2)(d) and Art. 35(1)(d) do not state a period — they hand it to the Government, and
    Decree 145/2020 Art. 7 sets it at 120 days. The portal certified 45 as compliant for this
    company's own Director and printed a quyết định reciting Art. 36 to say so."""
    n = hd.notice_required(hd.INDEFINITE, special_job=True)
    assert n["days"] == 120 and n["working"] is False
    assert "145/2020" in n["basis"]
    assert hd.notice_required(hd.INDEFINITE)["days"] == 45, "and the ordinary rung is untouched"


def test_a_twelve_month_or_longer_fixed_term_is_also_120():
    assert hd.notice_required(hd.DEFINITE, 12, special_job=True)["days"] == 120
    assert hd.notice_required(hd.DEFINITE, 36, special_job=True)["days"] == 120
    assert hd.notice_required(hd.DEFINITE, 36)["days"] == 30


def test_a_shorter_term_is_a_quarter_of_it_rounded_up_never_three_days():
    """Art. 7(2): at least one quarter of the term. Rounded up — the decree sets a floor."""
    n = hd.notice_required(hd.DEFINITE, 8, special_job=True)
    assert n["days"] == 60, "8 months ≈ 240 days, a quarter is 60"
    assert hd.notice_required(hd.DEFINITE, 3, special_job=True)["days"] == 23   # ceil(90/4)
    assert hd.notice_required(hd.DEFINITE, 8)["days"] == 3, "the ordinary rung is 3 WORKING days"


def test_it_binds_both_sides_not_just_the_employer():
    """Art. 35(1)(d) is the employee's side of the same clause."""
    notes = hd.termination_notes("employee_unilateral", hd.INDEFINITE, notice_date="2026-01-01",
                                last_day="2026-02-20", special_job=True)
    assert notes and "120" in notes[0]
    assert not hd.termination_notes("employee_unilateral", hd.INDEFINITE,
                                   notice_date="2026-01-01", last_day="2026-02-20")


def test_a_manager_terminated_on_45_days_notice_is_refused_with_the_figure():
    out = hd.termination_check("employer_unilateral", hd.INDEFINITE,
                              employer_ground="underperformance",
                              notice_date="2026-01-01", last_day="2026-02-15",
                              special_job=True)
    assert out and "Short notice" in out[0] and "120" in out[0]
    assert hd.termination_check("employer_unilateral", hd.INDEFINITE,
                               employer_ground="underperformance",
                               notice_date="2026-01-01", last_day="2026-02-15") == []


def test_the_grounds_that_need_no_notice_still_need_none():
    """Art. 36(3) is not overridden by Art. 7 — a special job does not create notice where the
    Labour Code says none is owed."""
    for g in ("absent_5_days", "abandoned"):
        n = hd.employer_notice(g, hd.INDEFINITE, special_job=True)
        if n and n["days"] == 0:
            assert "36(3)" in n["basis"]


def test_who_the_special_rung_covers_is_stated_rather_than_guessed_from_a_title():
    """The Law on Enterprises definition turns on the company charter, and no regex reads a
    charter — so this is an explicit flag, and the module says who it means."""
    assert "charter" in hd.SPECIAL_JOBS["help"]
    assert "NOT" in hd.SPECIAL_JOBS["help"], "a head of department is not automatically one"
    assert hd.SPECIAL_JOBS["helpVn"] and hd.SPECIAL_JOBS["labelVn"]
