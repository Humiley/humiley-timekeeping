"""Young workers — the register Art. 144 requires and the hours Art. 146 allows.

The portal held every employee's date of birth and could produce nothing for the first section of a
client's labour audit. These tests fix the two things that matter: that an age is never guessed,
and that the Art. 146(1) prohibition is a refusal rather than a ceiling somebody can override.

Checked against Labour Code 2019 Arts. 143, 144, 146 and 147.
"""
import minors as m

AS_OF = "2026-08-08"


def _emp(**kw):
    base = {"id": "E1", "name": "Nguyễn Văn A", "dob": "1995-04-12",
            "title": "Kỹ sư Cơ điện", "dept": "Engineering"}
    base.update(kw)
    return base


def _dob(age, born_month=1, born_day=1):
    """A date of birth that makes somebody exactly `age` on AS_OF."""
    return "%d-%02d-%02d" % (2026 - age, born_month, born_day)


# ── Art. 143: the bands ──────────────────────────────────────────────────────────────────────────

def test_the_three_minor_bands_and_the_adult_case():
    assert m.band(_dob(10), AS_OF) == m.UNDER_13
    assert m.band(_dob(14), AS_OF) == m.BAND_13_15
    assert m.band(_dob(16), AS_OF) == m.BAND_15_18
    assert m.band(_dob(25), AS_OF) == m.ADULT


def test_the_boundaries_are_full_years_not_calendar_years():
    """'From full 13' and 'under 18' — somebody turns 18 ON their birthday."""
    assert m.band("2008-08-09", "2026-08-08") == m.BAND_15_18, "one day short of 18"
    assert m.band("2008-08-08", "2026-08-08") == m.ADULT, "18 today"
    assert m.band("2013-08-09", "2026-08-08") == m.UNDER_13, "one day short of 13"
    assert m.band("2013-08-08", "2026-08-08") == m.BAND_13_15, "13 today"


def test_an_unknown_date_of_birth_is_its_own_answer_and_never_adult():
    """The gap is the finding. Collapsing it to 'adult' is what hid it."""
    for bad in ("", None, "not a date", "  "):
        assert m.band(bad, AS_OF) == m.UNKNOWN, bad


def test_a_date_of_birth_in_the_future_is_unknown_rather_than_a_negative_age():
    assert m.band("2030-01-01", AS_OF) == m.UNKNOWN


# ── Art. 146: the hours ──────────────────────────────────────────────────────────────────────────

def test_under_fifteen_is_four_hours_a_day_and_twenty_a_week():
    for age in (10, 14):
        lim = m.limits(_dob(age), AS_OF)
        assert (lim["maxDaily"], lim["maxWeekly"]) == (4, 20), age
        assert lim["minor"] is True


def test_fifteen_to_under_eighteen_is_eight_and_forty():
    lim = m.limits(_dob(16), AS_OF)
    assert (lim["maxDaily"], lim["maxWeekly"]) == (8, 40)


def test_an_adult_has_no_minor_ceiling_and_says_which_articles_do_apply():
    lim = m.limits(_dob(30), AS_OF)
    assert lim["maxDaily"] is None and lim["minor"] is False
    assert "Art. 107" in lim["basis"]


def test_an_unknown_age_refuses_to_state_a_limit():
    lim = m.limits("", AS_OF)
    assert lim["maxDaily"] is None and lim["minor"] is None
    assert "cannot be applied" in lim["basis"]


def test_a_day_over_the_ceiling_is_reported_with_the_ceiling():
    r = m.daily_hours_ok(_dob(14), AS_OF, 6)
    assert r["ok"] is False and r["cap"] == 4
    assert m.daily_hours_ok(_dob(14), AS_OF, 4)["ok"] is True
    assert m.daily_hours_ok(_dob(16), AS_OF, 6)["ok"] is True


# ── Art. 146(1) is a refusal, not a cap ──────────────────────────────────────────────────────────

def test_overtime_is_forbidden_outright_for_an_employee_under_fifteen():
    """Art. 107's monthly limit is a ceiling the Code contemplates exceeding with a reason.
    Art. 146(1) admits no exception, so this must not be offered as an overridable cap."""
    for age in (10, 14):
        r = m.overtime_allowed(_dob(age), AS_OF)
        assert r["allowed"] is False and r["refuse"] is True, age
        assert "prohibition" in r["reason"]
        assert "146(1)" in r["basis"]


def test_fifteen_to_eighteen_is_refused_too_because_this_company_has_no_listed_occupation():
    r = m.overtime_allowed(_dob(16), AS_OF)
    assert r["allowed"] is False and r["refuse"] is True
    assert "146(2)" in r["basis"]
    assert "cleanroom" in r["reason"], "it names why this company cannot rely on the exception"


def test_an_adult_is_allowed_and_is_reminded_that_art_107_still_applies():
    r = m.overtime_allowed(_dob(30), AS_OF)
    assert r["allowed"] is True and r["refuse"] is False
    assert "Art. 107" in r["basis"]


def test_an_unknown_age_refuses_rather_than_allowing():
    """The safe default when the age is unknown is NOT 'adult'."""
    r = m.overtime_allowed("", AS_OF)
    assert r["allowed"] is None and r["refuse"] is True
    assert "Record the date of birth" in r["reason"]


def test_a_minors_refusal_can_never_be_overridden_but_an_unknown_age_can():
    """The difference between a prohibition and a gap in the record. Art. 146(1) admits no
    exception; a missing date of birth is a typing job, and refusing it outright would stop the
    company approving any overtime at all until every record was complete — which is how a correct
    check gets switched off."""
    for dob in (_dob(10), _dob(14), _dob(16)):
        assert m.overtime_allowed(dob, AS_OF)["overridable"] is False, dob
    assert m.overtime_allowed("", AS_OF)["overridable"] is True
    assert m.overtime_allowed(_dob(30), AS_OF)["overridable"] is False


def test_the_unknown_case_tells_the_approver_what_attesting_means():
    r = m.overtime_allowed("", AS_OF)
    assert "recorded against your name" in r["reason"]


def test_every_refusal_has_a_vietnamese_wording():
    for dob in (_dob(14), _dob(16), ""):
        r = m.overtime_allowed(dob, AS_OF)
        assert r["reasonVn"] and any(ord(c) > 127 for c in r["reasonVn"]), dob


# ── Art. 144: the monitoring book ────────────────────────────────────────────────────────────────

def test_a_workforce_of_adults_needs_no_book_and_the_register_says_so():
    r = m.register([_emp(), _emp(id="E2", dob="1988-01-01")], AS_OF)
    assert r["rows"] == [] and r["minors"] == 0 and r["unknownDob"] == 0
    assert "requires no monitoring book" in r["statement"]


def test_the_book_carries_the_four_columns_article_144_names():
    r = m.register([_emp(id="E9", name="Trần Văn B", dob=_dob(16), title="Phụ việc")],
                   AS_OF, health_by_emp={"E9": [{"issued": "2026-02-01", "result": "Fit"}]})
    row = r["rows"][0]
    assert row["name"] == "Trần Văn B"
    assert row["dob"] == _dob(16)
    assert row["work"] == "Phụ việc"
    assert row["healthChecks"] and row["healthChecks"][0]["result"] == "Fit"
    assert row["issues"] == [], "nothing missing, so nothing flagged"


def test_a_minor_with_no_health_examination_is_a_finding():
    r = m.register([_emp(id="E9", dob=_dob(16))], AS_OF)
    assert any("health examination" in i for i in r["rows"][0]["issues"])
    assert r["gaps"] == 1


def test_a_minor_whose_work_is_not_recorded_is_a_finding():
    r = m.register([_emp(id="E9", dob=_dob(16), title="")], AS_OF,
                   health_by_emp={"E9": [{"issued": "2026-02-01"}]})
    assert any("work being done" in i for i in r["rows"][0]["issues"])


def test_an_under_13_carries_the_approval_requirement_on_its_face():
    r = m.register([_emp(id="E9", dob=_dob(11))], AS_OF,
                   health_by_emp={"E9": [{"issued": "2026-02-01"}]})
    assert any("provincial labour agency" in i for i in r["rows"][0]["issues"])


def test_somebody_with_no_date_of_birth_appears_in_the_register_as_a_gap():
    """They might be 17. The register exists to say that nobody knows."""
    r = m.register([_emp(id="E9", dob="")], AS_OF)
    assert r["unknownDob"] == 1
    assert r["rows"][0]["band"] == m.UNKNOWN
    assert any("cannot be shown to be over 18" in i for i in r["rows"][0]["issues"])
    assert "cannot be shown either way" in r["statement"]


def test_an_unknown_dob_is_not_counted_as_a_minor():
    """Two different facts, two different numbers. Merging them would overstate the finding."""
    r = m.register([_emp(id="E1", dob=""), _emp(id="E2", dob=_dob(16))], AS_OF)
    assert r["minors"] == 1 and r["unknownDob"] == 1


def test_the_youngest_come_first_and_the_unknowns_last():
    r = m.register([_emp(id="A", name="A", dob=_dob(17)), _emp(id="B", name="B", dob=""),
                    _emp(id="C", name="C", dob=_dob(12))], AS_OF)
    assert [x["empId"] for x in r["rows"]] == ["C", "A", "B"]


def test_the_register_cites_article_144_in_both_languages():
    r = m.register([], AS_OF)
    assert "Art. 144" in r["basis"] and "Điều 144" in r["basisVn"]
    assert "monitoring book" in r["basis"] and "sổ theo dõi riêng" in r["basisVn"]


def test_the_register_speaks_vietnamese_where_it_will_be_read(m_unused=None):
    """A translated function is not a translated screen — but an English-only FINDING on a Vietnamese
    screen is a finding nobody acts on, and the screen has no business restating the law itself."""
    r = m.register([_emp(id="E9", dob=_dob(16), title="")], AS_OF)
    assert r["statementVn"] and any(ord(c) > 127 for c in r["statementVn"])
    row = r["rows"][0]
    assert len(row["issuesVn"]) == len(row["issues"]) > 0
    assert all(any(ord(c) > 127 for c in i) for i in row["issuesVn"])


def test_a_clean_register_says_so_in_vietnamese_too():
    r = m.register([_emp()], AS_OF)
    assert "không yêu cầu lập sổ theo dõi" in r["statementVn"]
