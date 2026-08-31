"""Integrated change control (PMBOK §4.6) and earned value from measurement (§7.4).

Two joins the portal never made, and each has one way of being wrong that looks completely right:

  * comparing a change request's COST impact with a variation's agreed PRICE and calling the gap an
    error — the gap is the margin, and flagging it would make the useful comparison unreadable
  * counting materials on site as physical progress — delivered and paid for, built into nothing,
    and including them reports the job further ahead in exactly the month the cash went out

The second group also pins the rule that two progress figures which disagree are REPORTED, never
averaged. A mean of 61% and 45% is a number describing nothing.
"""
import pytest

import qsurvey as qs


# ── integrated change control ────────────────────────────────────────────────────────────────────

def _cr(**kw):
    return dict({"id": "c1", "crNo": "CR-001", "title": "Upgrade Zone 2 to ISO 7",
                 "decision": "Approved", "impactCost": 700_000_000,
                 "impactScheduleDays": 14, "requestedDate": "2026-04-01"}, **kw)


def _vo(**kw):
    return dict({"id": "v1", "voNo": "VO-001", "title": "Upgrade Zone 2 to ISO 7",
                 "status": qs.V_AGREED, "agreedValue": 980_000_000, "basis": qs.VB_STAR_RATE,
                 "agreedOn": "2026-05-08", "crNo": "CR-001"}, **kw)


def test_a_variation_and_its_change_request_are_joined_by_reference():
    r = qs.change_control({"changes": [_cr()], "variations": [_vo()], "cutoff": "2026-05-31"})
    assert r["linkedCount"] == 1
    assert r["rows"][0]["crDecision"] == qs.CR_APPROVED
    assert r["rows"][0]["crImpactCost"] == 700_000_000
    assert not r["unassessed"] and not r["unclaimed"]


def test_a_healthy_variation_priced_above_its_cost_raises_nothing():
    """₫980m charged against ₫700m assessed cost is a variation with margin on it — the normal and
    desired case. If this produced a warning the whole join would be noise."""
    r = qs.change_control({"changes": [_cr()], "variations": [_vo()], "cutoff": "2026-05-31"})
    assert r["agreedBelowCost"] == []
    assert r["warnings"] == []


def test_the_cost_impact_is_never_compared_to_the_price_as_though_they_should_match():
    """THE trap. `impactCost` is what the change costs US; `agreedValue` is what the CLIENT pays.
    A gap between them is the margin. Only a price BELOW the cost is a finding."""
    r = qs.change_control({"changes": [_cr(impactCost=700_000_000)],
                           "variations": [_vo(agreedValue=2_000_000_000)],
                           "cutoff": "2026-05-31"})
    assert r["agreedBelowCost"] == []
    assert not any("impact" in w["code"] for w in r["warnings"])


def test_a_variation_agreed_below_its_assessed_cost_is_raised():
    """Margin given away one instruction at a time, invisible in a project total."""
    r = qs.change_control({"changes": [_cr(impactCost=700_000_000)],
                           "variations": [_vo(agreedValue=520_000_000)],
                           "cutoff": "2026-05-31"})
    assert len(r["agreedBelowCost"]) == 1
    assert r["shortfall"] == 180_000_000
    assert any(w["code"] == "variation_agreed_below_cost" for w in r["warnings"])


def test_a_variation_being_built_with_no_change_request_is_raised():
    r = qs.change_control({"changes": [], "cutoff": "2026-05-31",
                           "variations": [_vo(crNo="", status=qs.V_INSTRUCTED)]})
    assert [x["voNo"] for x in r["unassessed"]] == ["VO-001"]
    assert any(w["code"] == "variation_without_change_request" for w in r["warnings"])


def test_a_merely_identified_variation_is_not_expected_to_have_an_assessment_yet():
    """`identified` is somebody noticing a possible change. Demanding a change request at that
    point would put a warning on every idea anybody had."""
    r = qs.change_control({"changes": [], "cutoff": "2026-05-31",
                           "variations": [_vo(crNo="", status=qs.V_IDENTIFIED)]})
    assert r["unassessed"] == []


def test_an_approved_change_with_no_variation_is_money_left_on_the_table():
    """The finding that pays for the whole join: the work is authorised, it is being built, and
    nothing is billing for it. Nothing else in the portal can see this."""
    r = qs.change_control({"changes": [_cr()], "variations": [], "cutoff": "2026-05-31"})
    assert [c["crNo"] for c in r["unclaimed"]] == ["CR-001"]
    assert r["unclaimedValue"] == 700_000_000
    assert any(w["code"] == "approved_change_not_claimed" for w in r["warnings"])


def test_a_pending_or_rejected_change_is_not_reported_as_unclaimed():
    """Only an APPROVED change is work we are authorised to be doing. A pending one has nothing to
    claim for yet, and reporting it would train people to ignore the list."""
    for d in ("Pending", "Rejected"):
        r = qs.change_control({"changes": [_cr(decision=d)], "variations": [],
                               "cutoff": "2026-05-31"})
        assert r["unclaimed"] == [], d


def test_an_approved_change_with_no_money_on_it_is_not_reported_as_unclaimed():
    """A scope change with no cost impact has nothing to bill. Listing it would be a permanent
    false positive on every no-cost clarification."""
    r = qs.change_control({"changes": [_cr(impactCost=0)], "variations": [], "cutoff": "2026-05-31"})
    assert r["unclaimed"] == []


def test_an_approved_change_raised_after_the_cutoff_waits():
    r = qs.change_control({"changes": [_cr(requestedDate="2026-06-10")], "variations": [],
                           "cutoff": "2026-05-31"})
    assert r["unclaimed"] == []


def test_agreeing_against_an_internally_rejected_change_is_raised_not_blocked():
    """A client instruction has to be built whatever the business decided internally, so this is a
    finding and not a refusal. Blocking it would stop a QS recording what actually happened."""
    r = qs.change_control({"changes": [_cr(decision="Rejected")], "variations": [_vo()],
                           "cutoff": "2026-05-31"})
    assert [x["voNo"] for x in r["againstRejected"]] == ["VO-001"]
    assert any(w["code"] == "agreed_against_a_rejected_change" for w in r["warnings"])


def test_agreeing_before_the_change_was_decided_is_raised_more_softly():
    r = qs.change_control({"changes": [_cr(decision="Pending")], "variations": [_vo()],
                           "cutoff": "2026-05-31"})
    assert [x["voNo"] for x in r["aheadOfDecision"]] == ["VO-001"]
    w = [x for x in r["warnings"] if x["code"] == "agreed_ahead_of_the_decision"]
    assert w and w[0]["severity"] == "medium"


def test_time_impact_that_no_approved_change_accounts_for_is_raised():
    """An extension of time nobody claimed is one nobody gets, and liquidated damages arrive on a
    job the client delayed."""
    r = qs.change_control({"changes": [_cr(impactScheduleDays=0)], "cutoff": "2026-05-31",
                           "variations": [_vo(timeImpactDays=21)]})
    assert [x["voNo"] for x in r["timeNotCarried"]] == ["VO-001"]
    w = [x for x in r["warnings"] if x["code"] == "time_impact_not_carried"]
    assert w and "21 day" in w[0]["msg"]


def test_time_impact_already_carried_by_an_approved_change_is_not_raised():
    r = qs.change_control({"changes": [_cr(impactScheduleDays=14)], "cutoff": "2026-05-31",
                           "variations": [_vo(timeImpactDays=14)]})
    assert r["timeNotCarried"] == []


def test_a_change_request_can_be_referenced_by_id_as_well_as_by_number():
    """A one-click "raise the variation from this change request" writes the id it has to hand; a
    person typing the link writes the number. Both have to work or half the links are silent."""
    r = qs.change_control({"changes": [_cr(crNo="")], "cutoff": "2026-05-31",
                           "variations": [_vo(crNo="", crId="c1")]})
    assert r["linkedCount"] == 1


# ── earned value from measurement ────────────────────────────────────────────────────────────────

def _ev(**kw):
    return qs.earned_value(dict({
        "measured": 7_000_000_000, "variations": 980_000_000, "daywork": 20_000_000,
        "materials": 1_000_000_000, "revisedContractSum": 24_980_000_000,
        "bac": 19_200_000_000, "ac": 6_000_000_000}, **kw))


def test_materials_on_site_are_not_physical_progress():
    """A pump delivered and paid for is built into nothing. Counting it inflates progress in
    exactly the month the cash went out."""
    r = _ev()
    assert r["physicalToDate"] == 8_000_000_000          # 7.0bn + 980m + 20m
    assert r["grossToDate"] == 9_000_000_000             # and the gross still includes them
    assert r["materialsExcluded"] == 1_000_000_000
    assert r["pct"] == round(8_000_000_000 / 24_980_000_000 * 100, 2)
    assert any(w["code"] == "materials_excluded_from_progress" for w in r["warnings"])


def test_earned_value_applies_the_measured_percentage_to_the_budget():
    """The percentage is value-weighted from the CLIENT's rates; earned value is in OUR money. The
    percentage is the only thing that crosses between them."""
    r = _ev()
    assert r["ev"] == round(19_200_000_000 * r["pct"] / 100.0, 2)
    assert r["cpi"] == round(r["ev"] / 6_000_000_000, 4)


def test_no_contract_sum_means_no_percentage_rather_than_a_made_up_one():
    """An invented percentage here flows into EV, into CPI and into the project's RAG colour."""
    r = _ev(revisedContractSum=None)
    assert r["pct"] is None and r["ev"] is None and r["cpi"] is None
    assert any(w["code"] == "no_measured_progress" for w in r["warnings"])


def test_no_budget_means_no_earned_value_even_with_a_percentage():
    r = _ev(bac=None)
    assert r["pct"] is not None
    assert r["ev"] is None and r["cpi"] is None


def test_two_progress_figures_that_disagree_are_both_reported_and_never_averaged():
    """The mean of 61% and 45% is a number describing nothing. The gap IS the finding."""
    r = _ev(independentPct=20, independentBasis="deliverable")
    assert r["pct"] == 32.03
    assert r["independentPct"] == 20
    assert r["gap"] == 12.03
    w = [x for x in r["warnings"] if x["code"] == "progress_methods_disagree"]
    assert w and "not averaged" in w[0]["msg"]
    # And nothing in the payload is the mean of the two.
    assert 26.0 not in (r["pct"], r["independentPct"])


def test_progress_methods_within_a_few_points_are_not_reported_as_disagreeing():
    """Two methods measuring the same job agree as closely as two methods ever do. A warning on
    every rounding difference is a warning nobody reads."""
    r = _ev(independentPct=30)
    assert abs(r["gap"]) < 5
    assert not any(w["code"] == "progress_methods_disagree" for w in r["warnings"])


def test_no_independent_figure_means_no_comparison_rather_than_a_comparison_with_zero():
    """Comparing against a missing figure as though it were 0% would report every project as
    catastrophically disagreeing with itself."""
    r = _ev()
    assert r["independentPct"] is None and r["gap"] is None
    assert not any(w["code"] == "progress_methods_disagree" for w in r["warnings"])


def test_a_cost_performance_index_below_one_against_measured_progress_is_raised():
    r = _ev(ac=9_000_000_000)
    assert r["cpi"] < 0.95
    assert any(w["code"] == "measured_cpi_below_one" for w in r["warnings"])


def test_no_actual_cost_means_no_cpi_rather_than_a_confident_one():
    """CPI with nothing spent falls out as either 0.00 or 1.00 depending on which way it is
    written, and both read as a measurement of something."""
    r = _ev(ac=0)
    assert r["cpi"] is None
    assert r["cpiMeasurable"] is False


def test_measurability_is_stated_in_the_portal_s_own_vocabulary():
    """Every screen in this portal prints an index through _pmIndexTxt(value, measurable), and
    tests/evm_index_honesty.js scans for any that does not. An equivalent guard of my own would
    have been correct and invisible to that scanner — which is how the next one gets it wrong."""
    assert _ev()["cpiMeasurable"] is True
    with open("templates/index.html", encoding="utf-8") as fh:
        html = fh.read()
    i = html.index("function _qsEvCard(d)")
    card = html[i:html.index("\n}", i)]
    assert "_pmIndexTxt(e.cpi, e.cpiMeasurable)" in card
    assert ".toFixed(2)" not in card, "an index is printed bare on the measured-progress card"


def test_the_basis_is_named_so_the_evm_screen_can_grade_its_evidence():
    """_pmEvm already ranks schedule / deliverable / typed. This is the grade above all of them and
    it has to say so, or the screen cannot tell the reader what it is looking at."""
    assert _ev()["basis"] == qs.EV_BASIS_MEASURED == "measured"


# ── the wiring, asserted against the files rather than assumed ───────────────────────────────────

def _html():
    with open("templates/index.html", encoding="utf-8") as fh:
        return fh.read()


def test_the_earned_value_basis_is_actually_displayed():
    """`evBasis` was written by _pmEvm and read by NOTHING, so a CPI built from a typed percentage
    rendered identically to one built from measured quantities. Adding a fourth grade without
    displaying it would have been a fourth invisible grade."""
    html = _html()
    assert "_pmEvBasisStrip(ev, p)" in html, "the Earned Value card does not print its basis"
    i = html.index("const _PM_EV_BASIS = {")
    block = html[i:html.index("};", i)]
    for grade in ("measured", "deliverable", "schedule", "typed"):
        assert grade + ":" in block, "the basis strip cannot name %r" % grade


def test_measurement_outranks_every_other_progress_basis():
    """The whole point: quantities measured against contract rates beat a roll-up and a typed
    number, so when the QS module has a percentage _pmEvm must use it and say so."""
    html = _html()
    i = html.index("function _pmEvm(p) {")
    body = html[i:html.index("function _pmEffectiveRag", i)]
    assert "earnedValue" in body and "qsPct" in body, "_pmEvm no longer reads the QS percentage"
    assert "'measured'" in body, "_pmEvm no longer reports the measured basis"
    # And it must fall back untouched when QS has not been loaded — every other caller (the
    # portfolio, the RAG colour, the status PDF) runs before /api/qs/summary is fetched.
    assert "qsPct != null" in body, (
        "_pmEvm must only use the QS percentage when there IS one, or the portfolio changes "
        "behaviour depending on which tab was opened last")


def test_a_variation_carries_its_change_request_on_the_form():
    """Without the field there is no way to record the assessment behind a variation, and every
    variation would be reported as unassessed for ever."""
    html = _html()
    i = html.index("pm_qs_variations: { title: 'Variation'")
    form = html[i:html.index("pm_qs_commissioning: { title:", i)]
    assert "k: 'crNo'" in form


def test_the_change_control_join_reads_both_reference_shapes():
    """The one-click raise writes an id; a person types a number. A join that reads one of them is
    silently half a join."""
    html = _html()
    i = html.index("function _qsCrOf(v)")
    body = html[i:html.index("}", html.index("return cr ?", i))]
    assert "crNo" in body and "crId" in body


def test_the_qs_tab_loads_the_change_request_log():
    """The server reads pm_changes for the report, but the BROWSER needs it too: the one-click
    "raise the variation" and the crId fallback in _qsCrOf both read it locally. Without it that
    button reports the change request missing on a project where it is sitting right there."""
    html = _html()
    i = html.index("k: 'qs', label: 'QS / Commercial'")
    entry = html[i:html.index("] },", i)]
    assert "'pm_changes'" in entry, "the QS tab does not load the change-request log"
