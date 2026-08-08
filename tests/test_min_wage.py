"""The statutory wage floor — the first question on a client's labour-compliance checklist.

Nothing in this portal could answer it. The two things these tests hold down: that the table is
EFFECTIVE-DATED, so a 2025 payslip is never measured against a 2026 decree, and that an employee who
could not be checked is never reported as one who passed.

Figures from Decree 293/2025/NĐ-CP (in force 1 January 2026) and Decree 74/2024/NĐ-CP (1 July 2024).
"""
import min_wage as mw


# ── the region, which is never guessed ───────────────────────────────────────────────────────────

def test_the_region_is_read_in_the_forms_people_actually_type():
    for raw in ("I", "i", " I ", "1", "Vùng I", "vung i"):
        assert mw.region_key(raw) == "I", raw
    assert mw.region_key("IV") == "IV" and mw.region_key("4") == "IV"


def test_an_unrecognised_region_is_refused_rather_than_defaulted():
    """Defaulting would put a whole workforce against the wrong floor, in one direction or other."""
    for bad in ("", None, "V", "Hanoi", "north"):
        assert mw.region_key(bad) is None, bad
        assert mw.at(bad, "2026-08-08") is None, bad


# ── effective dating, which is the whole design ──────────────────────────────────────────────────

def test_the_2026_decree_applies_from_the_first_of_january():
    r = mw.at("I", "2026-01-01")
    assert r["monthly"] == 5_310_000 and r["hourly"] == 25_500
    assert r["decree"] == "Decree 293/2025/NĐ-CP"


def test_the_day_before_still_uses_the_decree_that_was_in_force():
    """A single overwritten constant would rewrite history and report a breach that never existed."""
    r = mw.at("I", "2025-12-31")
    assert r["monthly"] == 4_960_000
    assert r["decree"] == "Decree 74/2024/NĐ-CP"


def test_all_four_regions_carry_both_the_monthly_and_the_hourly_figure():
    got = {k: mw.at(k, "2026-08-08") for k in mw.REGIONS}
    assert [got[k]["monthly"] for k in mw.REGIONS] == [5_310_000, 4_730_000, 4_140_000, 3_700_000]
    assert [got[k]["hourly"] for k in mw.REGIONS] == [25_500, 22_700, 20_000, 17_800]


def test_a_date_before_any_decree_in_the_table_has_no_answer():
    assert mw.at("I", "2020-01-01") is None


def test_every_answer_names_the_decree_it_came_from():
    """So that a figure can be checked against the gazette rather than trusted."""
    for k in mw.REGIONS:
        b = mw.at(k, "2026-08-08")["basis"]
        assert "293/2025" in b and ("Region %s" % k) in b


# ── the check ────────────────────────────────────────────────────────────────────────────────────

def test_a_wage_below_the_floor_is_reported_with_the_shortfall():
    r = mw.check(4_000_000, "I", "2026-08-08")
    assert r["ok"] is False
    assert r["shortfall"] == 1_310_000
    assert "BELOW" in r["why"]


def test_a_wage_exactly_at_the_floor_passes():
    r = mw.check(5_310_000, "I", "2026-08-08")
    assert r["ok"] is True and r["shortfall"] == 0


def test_the_same_wage_can_be_lawful_in_one_region_and_not_another():
    assert mw.check(3_900_000, "IV", "2026-08-08")["ok"] is True
    assert mw.check(3_900_000, "I", "2026-08-08")["ok"] is False


def test_an_unknown_region_gives_ok_None_not_ok_False():
    """A wage nobody could check and a wage that failed are different findings."""
    r = mw.check(4_000_000, "", "2026-08-08")
    assert r["ok"] is None and r["shortfall"] == 0
    assert "not something to estimate" in r["why"]


def test_a_missing_wage_gives_ok_None_too():
    r = mw.check(None, "I", "2026-08-08")
    assert r["ok"] is None
    assert "No monthly wage on record" in r["why"]
    assert r["floor"]["monthly"] == 5_310_000, "and it still says what the floor would be"


def test_a_zero_wage_is_treated_as_missing_not_as_a_breach_of_five_million():
    assert mw.check(0, "I", "2026-08-08")["ok"] is None


# ── the trained-worker uplift, which is policy and not law ───────────────────────────────────────

def test_the_uplift_is_never_applied_unless_the_company_turns_it_on():
    """Encoding a contested figure as law would be worse than leaving it out."""
    r = mw.check(5_310_000, "I", "2026-08-08", trained=True)
    assert r["ok"] is True and r["policyFloor"] is None


def test_with_the_policy_on_a_trained_worker_needs_seven_percent_more():
    r = mw.check(5_310_000, "I", "2026-08-08", trained=True, apply_trained_uplift=True)
    assert r["ok"] is False
    assert r["applies"] == 5_681_700
    assert "trained-worker uplift" in r["why"]


def test_the_policy_does_not_touch_an_untrained_worker():
    r = mw.check(5_310_000, "I", "2026-08-08", trained=False, apply_trained_uplift=True)
    assert r["ok"] is True and r["policyFloor"] is None


def test_the_module_says_the_uplift_is_not_a_statutory_floor():
    assert "not asserted here as a statutory floor" in mw.TRAINED_UPLIFT_NOTE
    assert mw.TRAINED_UPLIFT_NOTE_VN and any(ord(c) > 127 for c in mw.TRAINED_UPLIFT_NOTE_VN)


# ── the register ─────────────────────────────────────────────────────────────────────────────────

EMPS = [
    {"id": "A", "name": "A", "salary": 4_000_000, "wageRegion": "I"},   # below
    {"id": "B", "name": "B", "salary": 9_000_000, "wageRegion": "I"},   # fine
    {"id": "C", "name": "C", "salary": 9_000_000},                      # no region
    {"id": "D", "name": "D", "wageRegion": "I"},                        # no wage
]


def test_the_review_separates_a_breach_from_something_it_could_not_check():
    r = mw.review(EMPS, "2026-08-08")
    assert r["below"] == 1 and r["unchecked"] == 2 and r["checked"] == 2
    assert r["totalShortfall"] == 1_310_000


def test_the_statement_never_claims_compliance_it_did_not_measure():
    r = mw.review(EMPS, "2026-08-08")
    assert "1 employee(s) are paid below" in r["statement"]
    assert "2 could not be checked" in r["statement"]
    assert "nothing is asserted about them either way" in r["statement"]


def test_a_clean_roster_says_how_many_it_actually_checked():
    r = mw.review([{"id": "B", "name": "B", "salary": 9_000_000, "wageRegion": "I"}], "2026-08-08")
    assert r["below"] == 0 and r["unchecked"] == 0
    assert "All 1 employee(s) checked" in r["statement"]


def test_a_default_region_covers_a_single_site_company_without_editing_every_record():
    r = mw.review([{"id": "C", "name": "C", "salary": 4_000_000}], "2026-08-08",
                  default_region="I")
    assert r["below"] == 1 and r["unchecked"] == 0


def test_the_worst_shortfall_comes_first_then_the_uncheckable():
    r = mw.review(EMPS, "2026-08-08")
    assert r["rows"][0]["empId"] == "A"
    assert r["rows"][-1]["ok"] is True


def test_the_review_publishes_the_whole_schedule_so_a_figure_can_be_checked():
    r = mw.review([], "2026-08-08")
    decrees = [x["decree"] for x in r["schedule"]]
    assert "Decree 293/2025/NĐ-CP" in decrees and "Decree 74/2024/NĐ-CP" in decrees
    assert r["schedule"][0]["rates"]["I"]["monthly"] == 5_310_000


def test_every_answer_has_a_vietnamese_wording():
    for kw in ({}, {"region": ""}, {"wage": None}):
        r = mw.check(kw.get("wage", 4_000_000), kw.get("region", "I"), "2026-08-08")
        assert r["whyVn"] and any(ord(c) > 127 for c in r["whyVn"]), kw


def test_the_register_statement_is_bilingual():
    r = mw.review(EMPS, "2026-08-08")
    assert r["statementVn"] and "thấp hơn mức lương tối thiểu" in r["statementVn"]
    assert "chưa đối chiếu được" in r["statementVn"]
