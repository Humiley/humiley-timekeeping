"""The cost of quality — PMBOK §8.1.

Four categories, and the report is the RATIO between them, not the total. Money spent on prevention
and appraisal buys down internal and external failure; a job spending nothing on the first pair and
large sums on the second is not a job with bad luck.

The hazard this file mostly guards is not arithmetic. It is that the figure is only as good as the
classification behind it, and a cost-of-quality screen whose headline is a small confident number
nobody classified reads as "quality is cheap here" — which is the silent-zero antipattern aimed
directly at the one report meant to catch it.
"""
import pytest

import qsurvey as qs


def _c(**kw):
    return dict({"actual": 100_000_000, "coq": "Prevention", "period": "2026-05"}, **kw)


def _q(**kw):
    return qs.cost_of_quality(dict({"costs": [_c()]}, **kw))


def _codes(r):
    return {w["code"] for w in r["warnings"]}


def _row(r, code):
    return next(x for x in r["rows"] if x["code"] == code)


# ── the four categories ──────────────────────────────────────────────────────────────────────────

def test_every_category_is_carried_with_what_it_means():
    """These strings go on a report a quality manager reads a year later."""
    codes = [c["code"] for c in qs.COQ_CATEGORIES]
    assert codes == [qs.COQ_PREVENTION, qs.COQ_APPRAISAL, qs.COQ_INTERNAL, qs.COQ_EXTERNAL]
    for c in qs.COQ_CATEGORIES:
        assert c["label"].strip() and c["labelVn"].strip()
        assert len(c["why"]) > 40, "%s does not say what belongs in it" % c["code"]
        assert c["group"] in ("conformance", "nonconformance")


def test_cost_lands_in_the_category_it_was_classified_as():
    r = _q(costs=[_c(coq="Prevention", actual=10),
                  _c(coq="Appraisal", actual=20),
                  _c(coq="Internal failure", actual=30),
                  _c(coq="External failure", actual=40)])
    assert (r["prevention"], r["appraisal"]) == (10, 20)
    assert (r["internalFailure"], r["externalFailure"]) == (30, 40)
    assert r["conformance"] == 30 and r["nonConformance"] == 70
    assert r["total"] == 100


def test_the_class_is_read_from_the_label_the_dropdown_offers():
    """The stored value is whatever the select puts there, and a code the engine cannot read would
    silently become unclassified — which is the one failure this report cannot afford."""
    for label in ("prevention", "PREVENTION", "Prevention", "  Prevention  "):
        assert _q(costs=[_c(coq=label)])["prevention"] == 100_000_000, label


def test_a_class_the_module_does_not_recognise_is_reported_and_not_guessed():
    r = _q(costs=[_c(coq="quality stuff")])
    assert r["prevention"] == 0 and r["unclassifiedCost"] == 100_000_000
    assert "coq_unknown_class" in _codes(r)


def test_only_actual_cost_counts_because_a_commitment_has_cost_nobody_anything():
    r = _q(costs=[_c(actual="", committed=500_000_000)])
    assert r["total"] == 0 and r["totalCost"] == 0


# ── coverage comes before any ratio ──────────────────────────────────────────────────────────────

def test_the_report_states_how_much_of_the_job_it_actually_looked_at():
    r = _q(costs=[_c(actual=300_000_000), _c(coq="", actual=700_000_000)])
    assert r["classifiedCost"] == 300_000_000
    assert r["unclassifiedCost"] == 700_000_000
    assert r["coverage"] == 30.0


def test_thin_coverage_says_a_small_figure_means_missing_classification_not_cheap_quality():
    """The single most important sentence in this module. Without it the headline reads as good
    news, and the worse the classification the better the news looks."""
    r = _q(costs=[_c(actual=100_000_000), _c(coq="", actual=900_000_000)])
    assert r["meaningful"] is False
    w = [x for x in r["warnings"] if x["code"] == "coq_mostly_unclassified"][0]
    assert w["severity"] == "high"
    assert "not that quality is cheap" in w["msg"]


def test_good_coverage_is_not_warned_about():
    r = _q(costs=[_c(actual=800_000_000), _c(coq="", actual=200_000_000)])
    assert r["meaningful"] is True
    assert "coq_mostly_unclassified" not in _codes(r)


def test_an_empty_ledger_is_not_a_job_with_no_quality_cost():
    r = qs.cost_of_quality({})
    assert r["total"] == 0 and r["coverage"] is None and r["meaningful"] is False
    w = [x for x in r["warnings"] if x["code"] == "no_cost_booked"][0]
    assert "empty ledger" in w["msg"]


def test_no_ratio_is_asserted_from_a_sample_too_thin_to_carry_one():
    """The failure-share warning is the one somebody acts on. Firing it off 4% of the job's cost
    would send a quality manager after a problem the data cannot show exists."""
    r = _q(costs=[_c(coq="Internal failure", actual=40_000_000),
                  _c(coq="", actual=960_000_000)])
    assert r["failureShare"] == 100.0
    assert "failure_cost_dominates" not in _codes(r)


# ── the ratio that matters ───────────────────────────────────────────────────────────────────────

def test_failure_dominating_the_quality_spend_is_the_headline_finding():
    r = _q(costs=[_c(coq="Prevention", actual=100_000_000),
                  _c(coq="Internal failure", actual=400_000_000)])
    assert r["failureShare"] == 80.0
    w = [x for x in r["warnings"] if x["code"] == "failure_cost_dominates"][0]
    assert w["severity"] == "high" and "prevention and appraisal buys this down" in w["msg"]


def test_a_job_spending_on_prevention_and_finding_defects_early_is_not_warned_about():
    r = _q(costs=[_c(coq="Prevention", actual=300_000_000),
                  _c(coq="Appraisal", actual=500_000_000),
                  _c(coq="Internal failure", actual=100_000_000)])
    assert r["failureShare"] < 50
    assert "failure_cost_dominates" not in _codes(r)


def test_failure_cost_with_nothing_classified_as_prevention_is_named():
    r = _q(costs=[_c(coq="Appraisal", actual=600_000_000),
                  _c(coq="Internal failure", actual=400_000_000)])
    w = [x for x in r["warnings"] if x["code"] == "no_prevention_spend"][0]
    assert "or there is not any" in w["msg"]


def test_failure_after_handover_is_always_raised_however_small():
    """It is the most expensive kind there is and the only kind the client sees, so it is not
    gated on coverage the way the ratios are."""
    r = _q(costs=[_c(coq="External failure", actual=5_000_000),
                  _c(coq="", actual=995_000_000)])
    w = [x for x in r["warnings"] if x["code"] == "external_failure_present"][0]
    assert w["severity"] == "high" and "the client sees" in w["msg"]


# ── the cross-check that is never added ──────────────────────────────────────────────────────────

def test_the_ncr_registers_own_cost_is_reported_beside_the_ledger_and_never_summed():
    """Two records of the same rework, added together, describe an event that happened once."""
    r = _q(costs=[_c(coq="Internal failure", actual=400_000_000)],
           ncrs=[{"cost": 380_000_000}, {"cost": 20_000_000}])
    assert r["nonConformance"] == 400_000_000
    assert r["ncrRegisterCost"] == 400_000_000
    assert r["total"] == 400_000_000, "the cross-check was added into the total"
    assert "Nothing here is added to the non-conformance register" in r["note"]


def test_the_two_records_disagreeing_is_itself_the_finding():
    r = _q(costs=[_c(coq="Internal failure", actual=400_000_000)],
           ncrs=[{"cost": 90_000_000}])
    w = [x for x in r["warnings"] if x["code"] == "ncr_cost_disagrees"][0]
    assert "One of the two is incomplete" in w["msg"]


def test_agreeing_within_a_tenth_is_not_reported_as_a_disagreement():
    r = _q(costs=[_c(coq="Internal failure", actual=400_000_000)],
           ncrs=[{"cost": 395_000_000}])
    assert "ncr_cost_disagrees" not in _codes(r)


def test_an_ncr_nobody_priced_does_not_become_an_ncr_costing_nothing():
    """`_rate`, not `_num`. Counted at zero it would drag the register's figure down and
    manufacture a disagreement with the ledger that says the ledger is wrong."""
    r = _q(costs=[_c(coq="Internal failure", actual=400_000_000)],
           ncrs=[{"cost": 400_000_000}, {"cost": ""}, {}])
    assert r["ncrsPriced"] == 1 and r["ncrRegisterCost"] == 400_000_000
    assert "ncr_cost_disagrees" not in _codes(r)


def test_with_no_priced_ncr_the_cross_check_is_unstated_rather_than_nil():
    assert _q()["ncrRegisterCost"] is None


# ── the cut-off ──────────────────────────────────────────────────────────────────────────────────

def test_cost_after_the_cut_off_is_outside_the_report():
    r = _q(cutoff="2026-05-31", costs=[_c(period="2026-05"), _c(period="2026-06", actual=999)])
    assert r["total"] == 100_000_000


def test_the_note_says_the_total_on_its_own_says_very_little():
    assert "the ratio between them is the report" in _q()["note"].lower()


# ── the wiring ───────────────────────────────────────────────────────────────────────────────────

def _html():
    import io
    return io.open("templates/index.html", encoding="utf-8").read()


def _app():
    import io
    return io.open("app.py", encoding="utf-8").read()


def test_the_two_fields_the_report_is_built_from_exist():
    """Without them the report is arithmetic over a column nobody can fill in — a rule enforced
    against data that cannot be entered."""
    html = _html()
    i = html.index("pm_costs: { title: ")
    costs = html[i:html.index("pm_quality: { title: ", i)]
    assert "k: 'coq'" in costs and "options: 'coq_classes'" in costs
    j = html.index("pm_quality: { title: ")
    q = html[j:html.index("pm_quality_itp: { title: ", j)]
    assert "k: 'cost'" in q, "an NCR cannot record what putting it right cost"


def test_the_classes_are_served_and_not_a_second_copy_in_the_browser():
    """A stale copy of what belongs in each category is how a cost gets classified wrongly."""
    src, html = _app(), _html()
    assert '"coqCategories": list(qsurvey.COQ_CATEGORIES)' in src
    i = html.index("if (src === 'coq_classes')")
    body = html[i:html.index("if (src === 'qs_disciplines')", i)]
    assert "d.coqCategories" in body
    assert "v: c.code" in body, "the stored value must be the code, not a translated label"


def test_the_report_is_computed_and_served():
    src = _app()
    assert "qsurvey.cost_of_quality({" in src
    i = src.index("qsurvey.cost_of_quality({")
    call = src[i:i + 500]
    assert '"ncrs": rows["quality"]' in call
    assert '"costOfQuality": coq,' in src, "computed and not returned"


def test_the_tab_exists_and_points_at_a_renderer_that_exists():
    html = _html()
    i = html.index("const _QS_TABS = [")
    tabs = html[i:html.index("];", i)]
    assert "k: 'coq'" in tabs and "fn: '_qsRenderCoq'" in tabs
    assert "function _qsRenderCoq(" in html


def test_the_coverage_statement_is_rendered_before_the_figures_it_qualifies():
    """A footnote under the number is read after the number. The whole point is that it is read
    first — a small cost of quality over an unclassified job reads as good news."""
    html = _html()
    i = html.index("function _qsRenderCoq(")
    body = html[i:html.index("function qsCoqPDF(", i)]
    assert body.index("_qsCoqCoverageCard(c)") < body.index("_qsCoqSplitCard(c)")
    j = html.index("function _qsCoqCoverageCard(")
    card = html[j:html.index("function _qsCoqSplitCard(", j)]
    assert "not that quality is cheap" in card


def test_the_ratio_is_not_drawn_as_a_ratio_where_the_sample_cannot_carry_one():
    html = _html()
    i = html.index("function _qsCoqRatioCard(")
    body = html[i:html.index("function _qsCoqCrossCard(", i)]
    assert "c.meaningful" in body
    assert "too little of the job to be read as a ratio" in body


def test_the_screen_never_adds_the_two_registers_together():
    html = _html()
    i = html.index("function _qsCoqCrossCard(")
    body = html[i:html.index("function _qsRenderCoq(", i)]
    for forbidden in ("c.ncrRegisterCost + c.nonConformance", "c.nonConformance + c.ncrRegisterCost"):
        assert forbidden not in body, "the screen is summing both records: %s" % forbidden
    assert "counts one event twice" in body


def test_the_report_has_a_document_somebody_can_sign():
    html = _html()
    assert "function qsCoqPDF(" in html
    i = html.index("function qsCoqPDF(")
    body = html[i:i + 4200]
    assert "HML-QS-COQ" in body
    assert "_qsSignBlock(doc" in body and "_qsFoot(doc" in body
    assert "_brandFooter" not in body
    assert "coverage" in body, "a PDF that states the figure and not its coverage is the trap"


# ── the defect only running it found ─────────────────────────────────────────────────────────────

def test_a_cost_line_with_no_period_is_still_money_that_was_spent():
    """`_le()` excludes a record it cannot date, and that is right for a MEASUREMENT — work claimed
    in the wrong month moves money. Here the consequence inverts: on the seeded job every cost line
    was undated, so the whole ₫14bn ledger was silently dropped and the report announced "No actual
    cost has been booked on this job." The one report built to stop a confident nil produced one."""
    r = _q(cutoff="2026-05-31", costs=[_c(period="", actual=500_000_000)])
    assert r["totalCost"] == 500_000_000
    assert r["prevention"] == 500_000_000
    assert r["undatedCost"] == 500_000_000
    assert "no_cost_booked" not in _codes(r)
    w = [x for x in r["warnings"] if x["code"] == "cost_no_period"][0]
    assert "it was spent" in w["msg"]


def test_a_cost_line_after_the_cut_off_is_still_excluded():
    r = _q(cutoff="2026-05-31", costs=[_c(period="2026-05"), _c(period="2026-06", actual=999)])
    assert r["totalCost"] == 100_000_000 and r["undatedCost"] == 0


def test_with_no_cut_off_nothing_is_reported_as_undated():
    r = _q(costs=[_c(period="")])
    assert r["totalCost"] == 100_000_000
    assert "cost_no_period" not in _codes(r)
