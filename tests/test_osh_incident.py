"""Occupational accidents — the register, and the call that has to be made today.

Most of an accident record is description. The parts that are not: whether this had to be declared
to the labour inspectorate within hours, and when the investigation report is due. Both are
measured from the moment somebody is hurt, so a company that learns them afterwards has missed them.

Checked against Law on OSH 2015 Art. 35(4) and Decree 39/2016 Art. 10 and Art. 24.
"""
import osh_incident as o


def _inc(**kw):
    base = {"class": o.SERIOUS, "injuredCount": 1, "occurredOn": "2026-08-01",
            "notifiedOn": "2026-08-01", "empId": "E1",
            "what": "Fell from the second lift of the scaffold while fitting duct."}
    base.update(kw)
    return base


# ── Decree 39/2016 Art. 10: what must be declared at once ────────────────────────────────────────

def test_a_fatal_accident_must_be_declared_at_once_to_the_inspectorate_AND_the_police():
    d = o.declare_immediately(_inc(**{"class": o.FATAL}))
    assert d["required"] is True and len(d["to"]) == 2
    assert any("police" in t.lower() for t in d["to"])
    assert "fastest means" in d["how"]


def test_a_serious_accident_injuring_two_or_more_must_be_declared_at_once():
    assert o.declare_immediately(_inc(injuredCount=2))["required"] is True
    assert o.declare_immediately(_inc(injuredCount=5))["required"] is True


def test_a_serious_accident_injuring_one_does_not_trigger_the_immediate_duty():
    """Reporting it immediately anyway is not wrong — asserting it is REQUIRED would be."""
    d = o.declare_immediately(_inc(injuredCount=1))
    assert d["required"] is False and d["to"] == []
    assert "periodic return" in d["basis"]


def test_a_minor_accident_never_does_however_many_people():
    assert o.declare_immediately(_inc(**{"class": o.MINOR, "injuredCount": 6}))["required"] is False


def test_the_instruction_names_the_recipients_rather_than_leaving_a_flag_to_interpret():
    """This duty is measured in hours. "true" is not an instruction."""
    d = o.declare_immediately(_inc(**{"class": o.FATAL}))
    # Each recipient names an actual body somebody could ring, not a category.
    assert any("Department of Labour" in t for t in d["to"])
    assert any("police" in t.lower() for t in d["to"])
    # And it says how fast, in words somebody will act on today.
    assert "fastest means" in d["how"] and "Not a letter" in d["how"]


# ── Law on OSH 2015 Art. 35(4): the investigation clock ──────────────────────────────────────────

def test_each_class_has_its_own_number_of_days():
    day = lambda **k: o.investigation_deadline(_inc(**k), "2026-08-02")["days"]
    assert day(**{"class": o.MINOR}) == 4
    assert day(**{"class": o.SERIOUS, "injuredCount": 1}) == 7
    assert day(**{"class": o.SERIOUS, "injuredCount": 2}) == 20
    assert day(**{"class": o.FATAL}) == 30


def test_a_case_needing_forensic_examination_gets_sixty_whatever_the_class():
    for k in (o.MINOR, o.SERIOUS, o.FATAL):
        d = o.investigation_deadline(_inc(**{"class": k, "forensic": True}), "2026-08-02")
        assert d["days"] == 60, k


def test_the_clock_runs_from_the_day_NOTICE_was_received_not_the_accident():
    """Usually the same day and occasionally not; the statute names the notice."""
    d = o.investigation_deadline(_inc(occurredOn="2026-08-01", notifiedOn="2026-08-05",
                                      **{"class": o.MINOR}), "2026-08-06")
    assert d["from"] == "2026-08-05" and d["due"] == "2026-08-09"


def test_with_no_notice_date_it_falls_back_to_the_day_it_happened():
    d = o.investigation_deadline(_inc(notifiedOn="", **{"class": o.MINOR}), "2026-08-02")
    assert d["from"] == "2026-08-01"


def test_the_extension_may_be_taken_once_and_only_for_the_same_period_again():
    """Art. 35(4). Not an open-ended extension, and not two of them."""
    d = o.investigation_deadline(_inc(**{"class": o.FATAL, "extended": True}), "2026-08-02")
    assert d["baseDue"] == "2026-08-31" and d["due"] == "2026-09-30"
    assert d["due"] == d["extensionLimit"], "the extension cannot exceed the original period"


def test_an_unpublished_report_past_its_date_is_late():
    d = o.investigation_deadline(_inc(**{"class": o.MINOR}), "2026-08-20")
    assert d["late"] is True and d["published"] is False


def test_publishing_late_is_still_recorded_as_late():
    d = o.investigation_deadline(_inc(**{"class": o.MINOR, "reportPublishedOn": "2026-08-20"}),
                                 "2026-09-01")
    assert d["published"] is True and d["late"] is True


def test_publishing_in_time_is_not():
    d = o.investigation_deadline(_inc(**{"class": o.MINOR, "reportPublishedOn": "2026-08-04"}),
                                 "2026-09-01")
    assert d["late"] is False


def test_a_class_that_is_not_a_class_has_no_deadline_rather_than_a_guessed_one():
    assert o.investigation_deadline(_inc(**{"class": "bruise"}), "2026-08-02") is None
    assert o.investigation_deadline({"occurredOn": "2026-08-01"}, "2026-08-02") is None


# ── Decree 39/2016 Art. 24: the periodic returns ─────────────────────────────────────────────────

def test_the_two_filing_dates_are_5_july_and_10_january():
    assert o.next_report_due("2026-03-01")["due"] == "2026-07-05"
    assert o.next_report_due("2026-08-07")["due"] == "2027-01-10"
    assert o.next_report_due("2026-12-20")["due"] == "2027-01-10"


def test_the_day_of_the_deadline_still_counts_as_due_not_past():
    assert o.next_report_due("2026-07-05")["due"] == "2026-07-05"


def test_the_return_says_which_authority_it_goes_to():
    assert "Department of Labour" in o.next_report_due("2026-03-01")["basis"]


# ── the frequency rate ───────────────────────────────────────────────────────────────────────────

INC = [{"class": o.SERIOUS, "daysLost": 12}, {"class": o.MINOR, "daysLost": 0},
       {"class": o.MINOR, "daysLost": 3}]


def test_it_refuses_to_quote_a_rate_without_the_hours():
    """It is the single figure a client compares across contractors, so it would be compared."""
    r = o.lost_time_rate(INC, None)
    assert r["rate"] is None and "guessed denominator" in r["why"]
    assert o.lost_time_rate(INC, 0)["rate"] is None


def test_with_hours_it_is_lost_time_injuries_per_million_hours():
    r = o.lost_time_rate(INC, 200000)
    assert r["lostTimeInjuries"] == 2, "the serious one, and the minor one with days lost"
    assert r["rate"] == 10.0


def test_a_serious_or_fatal_accident_counts_as_lost_time_even_with_no_days_recorded():
    assert o.lost_time_rate([{"class": o.FATAL}], 1000000)["lostTimeInjuries"] == 1
    assert o.lost_time_rate([{"class": o.MINOR}], 1000000)["lostTimeInjuries"] == 0


# ── what it refuses to record ────────────────────────────────────────────────────────────────────

def test_a_complete_record_has_no_blockers():
    assert o.blockers(_inc()) == []


def test_the_class_is_required_because_every_deadline_depends_on_it():
    out = o.blockers(_inc(**{"class": ""}))
    assert out and "declared today" in out[0]


def test_the_date_it_happened_is_required():
    assert any("counted from" in m for m in o.blockers(_inc(occurredOn="")))


def test_somebody_not_on_the_payroll_can_be_named_instead_of_chosen():
    """A subcontractor or a visitor hurt on your site is still your accident."""
    assert o.blockers(_inc(empId="", personName="Nguyễn Văn B (subcontractor)")) == []
    assert any("who was hurt" in m for m in o.blockers(_inc(empId="", personName="")))


def test_a_one_line_description_is_refused():
    assert any("follow it" in m for m in o.blockers(_inc(what="fell")))


# ── the register ─────────────────────────────────────────────────────────────────────────────────

def test_an_undeclared_immediate_case_is_the_first_thing_the_register_says():
    r = o.review([_inc(id="a", **{"class": o.FATAL}), _inc(id="b", **{"class": o.MINOR})],
                 "2026-08-07")
    assert [u["id"] for u in r["undeclared"]] == ["a"]
    assert r["rows"][0]["id"] == "a", "it sorts to the top"


def test_a_declared_one_stops_being_flagged():
    r = o.review([_inc(id="a", **{"class": o.FATAL, "declaredOn": "2026-08-01"})], "2026-08-07")
    assert r["undeclared"] == []


def test_the_register_counts_late_investigations_and_days_lost():
    r = o.review([_inc(**{"class": o.MINOR, "daysLost": 3}),
                  _inc(**{"class": o.SERIOUS, "daysLost": 12,
                          "reportPublishedOn": "2026-08-05"})], "2026-08-20")
    assert r["daysLost"] == 15
    assert r["lateInvestigations"] == 1, "the minor one is 4 days and still unpublished"
    assert r["open"] == 1


def test_the_register_carries_the_statement_an_auditor_asks_for():
    r = o.review([_inc(daysLost=4)], "2026-08-07")
    assert "1 accident(s) recorded" in r["statement"] and "4 day(s) lost" in r["statement"]


def test_an_empty_register_still_reports_the_next_filing_date():
    r = o.review([], "2026-03-01")
    assert r["total"] == 0 and r["nextReport"]["due"] == "2026-07-05"
    assert r["frequency"]["rate"] is None


# ── the instruction has to be readable by the person who has to act on it ────────────────────────

def test_the_declaration_instruction_comes_back_in_vietnamese_too():
    """Read under time pressure, on a Vietnamese-language site. English alone is not an instruction."""
    d = o.declare_immediately(_inc(**{"class": o.FATAL}))
    assert len(d["toVn"]) == len(d["to"]) == 2
    assert any("Thanh tra lao động" in t for t in d["toVn"])
    assert any("Công an" in t for t in d["toVn"])
    assert "nhanh nhất" in d["howVn"]
    assert "Nghị định 39/2016" in d["basisVn"]


def test_the_serious_multi_case_names_only_the_inspectorate_in_both_languages():
    d = o.declare_immediately(_inc(injuredCount=2))
    assert len(d["to"]) == len(d["toVn"]) == 1
    assert "Công an" not in d["toVn"][0], "the police duty is the fatal case only"


def test_even_the_not_required_answer_explains_itself_in_vietnamese():
    d = o.declare_immediately(_inc(injuredCount=1))
    assert d["toVn"] == [] and "báo cáo định kỳ" in d["basisVn"]


def test_the_deadline_states_its_article_and_days_in_vietnamese():
    d = o.investigation_deadline(_inc(**{"class": o.FATAL}), "2026-08-02")
    assert "Điều 35(4)" in d["basisVn"] and "30 ngày" in d["basisVn"]
    assert "tai nạn chết người" in d["basisVn"]


def test_every_deadline_reason_has_a_vietnamese_wording_not_just_the_common_one():
    """The fixed part of the sentence is Vietnamese whatever happens, so asserting the SENTENCE has
    diacritics proves nothing — one untranslated reason survived exactly that check. Assert on the
    reason itself, and that the English wording never leaks into the Vietnamese sentence."""
    for kw in ({"class": o.MINOR}, {"class": o.SERIOUS, "injuredCount": 1},
               {"class": o.SERIOUS, "injuredCount": 2}, {"class": o.FATAL},
               {"class": o.MINOR, "forensic": True}):
        d = o.investigation_deadline(_inc(**kw), "2026-08-02")
        assert d["whyVn"] and d["whyVn"] != d["why"], kw
        assert any(ord(c) > 127 for c in d["whyVn"]), kw
        assert d["why"] not in d["basisVn"], kw
        assert d["whyVn"] in d["basisVn"], kw
        assert "%d ngày" % d["days"] in d["basisVn"], kw


def test_the_periodic_return_says_what_it_covers_in_vietnamese():
    for as_of, frag in (("2026-03-01", "sáu tháng đầu năm"), ("2026-08-07", "cả năm")):
        r = o.next_report_due(as_of)
        assert frag in r["coversVn"], as_of
        assert "Nghị định 39/2016" in r["basisVn"]


def test_the_refusal_to_quote_a_rate_is_explained_in_vietnamese_as_well():
    assert "phỏng đoán" in o.lost_time_rate(INC, None)["whyVn"]
    assert "1.000.000 giờ" in o.lost_time_rate(INC, 200000)["whyVn"]


def test_the_undeclared_banner_carries_the_instruction_in_both_languages():
    """The banner is the ONE thing on the screen measured in hours. It was built from a copy of the
    instruction that kept only the English keys, so the Vietnamese wording existed and never
    reached the reader. Assert on the banner entry, not on declare_immediately()."""
    r = o.review([_inc(id="a", **{"class": o.FATAL})], "2026-08-07")
    u = r["undeclared"][0]
    assert any("Thanh tra lao động" in t for t in u["toVn"])
    assert any("Công an" in t for t in u["toVn"])
    assert "Nghị định 39/2016" in u["basisVn"]
    assert "nhanh nhất" in u["howVn"]
    assert u["to"] and u["basis"] and u["how"], "and the English is still there"
