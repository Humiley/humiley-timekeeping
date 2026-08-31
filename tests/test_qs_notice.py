"""The notice clock, and the exposures nobody reviews.

The claim a contractor loses is almost never the weak one. It is the good one served on day 31 of a
28-day window, because under most standard forms notice is a CONDITION PRECEDENT — miss it and the
entitlement is gone, not weakened. Nothing was counting: the variation register knew the instruction
date, the contract knew the period, and no screen put those two facts together.

The second group is the other half of the same problem: every exposure this module computes is
reviewed by nobody, because it lives on a commercial screen rather than on the register the project
walks through every week.
"""
import pytest

import qsurvey as qs


def _v(**kw):
    return dict({"id": "v1", "voNo": "VO-001", "title": "Additional HEPA filters",
                 "status": qs.V_INSTRUCTED, "estimatedValue": 90_000_000,
                 "instructedOn": "2026-05-01", "timeImpactDays": 14}, **kw)


def _n(**kw):
    return qs.notice_position(dict({"variations": [_v()], "noticeDays": 28,
                                    "today": "2026-05-10"}, **kw))


# ── the clock ────────────────────────────────────────────────────────────────────────────────────

def test_the_clock_starts_at_the_instruction_and_runs_for_the_contract_period():
    r = _n()
    assert r["rows"][0]["noticeDue"] == "2026-05-29"
    assert r["rows"][0]["daysLeft"] == 19
    assert r["rows"][0]["state"] == qs.NOTICE_DUE


def test_a_notice_already_served_stops_the_clock():
    r = _n(variations=[_v(noticeGivenOn="2026-05-06", noticeRef="NOT-011")])
    assert r["rows"][0]["state"] == qs.NOTICE_OK
    assert r["lapsed"] == [] and r["urgent"] == [] and r["due"] == []


def test_a_window_about_to_shut_is_urgent_not_merely_due():
    """Five days is the last point at which a notice can still be drafted, checked and served. A
    warning that only fires on the day it expires is a warning nobody can act on."""
    r = _n(today="2026-05-26")
    assert r["rows"][0]["daysLeft"] == 3
    assert r["rows"][0]["state"] == qs.NOTICE_URGENT
    w = [x for x in r["warnings"] if x["code"] == "notice_period_closing"]
    assert w and w[0]["severity"] == "high"


def test_a_lapsed_notice_says_the_entitlement_is_gone_not_weakened():
    r = _n(today="2026-06-15")
    assert r["rows"][0]["state"] == qs.NOTICE_LAPSED
    assert r["atRiskDays"] == 14
    w = [x for x in r["warnings"] if x["code"] == "notice_period_lapsed"]
    assert w and "gone" in w[0]["msg"]


def test_a_notice_served_after_the_window_is_recorded_as_late_rather_than_as_done():
    """The client will raise it against the claim, so it is a fact about the claim and not a tick."""
    r = _n(variations=[_v(noticeGivenOn="2026-06-10")], today="2026-06-15")
    assert r["rows"][0]["state"] == qs.NOTICE_OK
    assert r["rows"][0]["servedLate"] is True
    assert any(w["code"] == "notice_served_late" for w in r["warnings"])


def test_a_notice_served_inside_the_window_is_not_late():
    r = _n(variations=[_v(noticeGivenOn="2026-05-20")], today="2026-06-15")
    assert r["rows"][0]["servedLate"] is False
    assert not any(w["code"] == "notice_served_late" for w in r["warnings"])


def test_a_variation_carrying_no_time_has_no_clock():
    """Most variations are money only. A notice warning on every one of them would bury the ones
    that matter — the same reason only ITP-named bill lines are quality-gated."""
    assert _n(variations=[_v(timeImpactDays=0)])["rows"] == []


def test_a_variation_nobody_instructed_has_no_event_to_count_from():
    assert _n(variations=[_v(status=qs.V_IDENTIFIED)])["rows"] == []


def test_no_notice_period_in_the_contract_is_reported_not_treated_as_compliant():
    """It is a number in the contract and it decides whether a good claim survives. Absent, the
    module says so rather than showing every claim as fine."""
    r = _n(noticeDays=0)
    assert r["rows"][0]["state"] == qs.NOTICE_NO_PERIOD
    assert r["noticeDays"] is None
    assert r["lapsed"] == []
    assert any(w["code"] == "no_notice_period" for w in r["warnings"])


def test_a_variation_with_no_instruction_date_cannot_have_its_clock_run():
    """No event, no deadline. Counting from nothing would invent a date that decides an entitlement."""
    r = _n(variations=[_v(instructedOn="")])
    assert r["rows"][0]["noticeDue"] is None
    assert r["rows"][0]["state"] == qs.NOTICE_NO_PERIOD


def test_the_clock_never_reads_a_clock_of_its_own():
    """`today` is passed in. A module that read the system clock could not be tested for the day
    before an expiry, which is the only day the warning is worth anything."""
    early = _n(today="2026-05-02")["rows"][0]["state"]
    late = _n(today="2026-07-01")["rows"][0]["state"]
    assert early == qs.NOTICE_DUE and late == qs.NOTICE_LAPSED


def test_several_claims_are_counted_separately_and_the_days_at_risk_add_up():
    r = _n(today="2026-06-15", variations=[
        _v(id="a", voNo="VO-1", timeImpactDays=14),
        _v(id="b", voNo="VO-2", timeImpactDays=7),
        _v(id="c", voNo="VO-3", timeImpactDays=5, noticeGivenOn="2026-05-10")])
    assert len(r["lapsed"]) == 2
    assert r["atRiskDays"] == 21


# ── the exposures ────────────────────────────────────────────────────────────────────────────────

def _e(**kw):
    return qs.exposures(dict({
        "qualityAtRisk": 7_092_000_000, "notReleased": 3_352_000_000,
        "variationExposure": 210_000_000, "approvedNotClaimed": 265_000_000,
        "underCertified": 300_000_000, "ldExposure": 308_000_000,
        "contingencyShortfall": 70_000_000, "noticeLapsedDays": 14}, **kw))


def test_every_exposure_the_module_computes_reaches_one_list():
    codes = {e["code"] for e in _e()["items"]}
    assert codes == {"quality_at_risk", "not_released", "variation_exposure",
                     "approved_not_claimed", "under_certified", "ld_exposure",
                     "contingency_short", "notice_lapsed"}


def test_an_exposure_of_nothing_is_not_listed():
    """A list of eight rows of zero is a list nobody reads."""
    r = qs.exposures({"qualityAtRisk": 5_000_000})
    assert [e["code"] for e in r["items"]] == ["quality_at_risk"]


def test_the_biggest_money_exposure_comes_first_and_time_comes_last():
    items = _e()["items"]
    assert items[0]["code"] == "quality_at_risk"
    assert items[-1]["code"] == "notice_lapsed"


def test_time_is_carried_in_DAYS_and_never_priced_at_an_assumed_rate():
    """A day of delay only becomes money through a rate somebody agreed. Pricing it here would put
    a number on the register that nobody in the contract ever wrote down."""
    t = [e for e in _e()["items"] if e["code"] == "notice_lapsed"][0]
    assert t["unit"] == "days" and t["amount"] == 14
    assert _e()["daysTotal"] == 14


def test_the_money_total_excludes_the_days():
    """14 days must not be added to a total of dong. The second assertion here replaced one that
    could not fail — `x != x + d - d + 1` is true for every x, which is a check examining nothing."""
    r = _e()
    money = [e["amount"] for e in r["items"] if e["unit"] == "money"]
    assert r["moneyTotal"] == sum(money)
    assert r["daysTotal"] == 14
    assert r["moneyTotal"] == sum(money) and 14 not in (r["moneyTotal"] - sum(money),)
    # Concretely: the days figure is nowhere inside the money figure.
    assert abs(r["moneyTotal"] - sum(money)) < 0.005
    assert r["moneyTotal"] > 1_000_000, "a total of dong should not be a handful of days"


def test_the_list_says_the_total_is_not_one_loss():
    """Some of it is value a client may deduct, some is work nobody is billing for. Adding them
    produces a figure describing no single event, and the payload says so where somebody printing
    it will see it."""
    note = _e()["note"].lower()
    assert "not one number" in note or "no single event" in note


def test_every_exposure_kind_says_what_it_is_and_why_it_matters():
    """These strings go on a risk register somebody reads a year later."""
    for e in qs.EXPOSURE_KINDS:
        assert e["label"].strip() and e["labelVn"].strip()
        assert len(e["why"].strip()) > 20, "%s does not say why it matters" % e["code"]
        assert e["category"] in ("Quality", "Commercial", "Schedule")


# ── the wiring ───────────────────────────────────────────────────────────────────────────────────

def _html():
    with open("templates/index.html", encoding="utf-8") as fh:
        return fh.read()


def test_a_paginating_document_stamps_its_footer_once():
    """`_qsPdfRows` used to draw a footer on its way past a page break, and `_qsFoot` draws one on
    every page at the end — so page 1 of a two-page report carried two footers on top of each
    other, and the one drawn on the way past said "page N of N", making page 1 claim to be page 1
    of 1. It was invisible while both said the same words and appeared the moment a document had a
    "(cont.)" heading."""
    html = _html()
    i = html.index("function _qsPdfRows(")
    body = html[i:html.index("function _qsSignBlock", i)]
    assert "_brandFooter" not in body, (
        "_qsPdfRows stamps a footer again — _qsFoot already walks every page with the real numbers")
    foot = html[html.index("function _qsFoot("):]
    assert "_brandFooter(doc, i, tot, code)" in foot[:400], "_qsFoot no longer numbers the pages"


def test_the_notice_fields_exist_on_the_variation_and_the_period_on_the_project():
    """Without them the clock has nothing to count from and reports every claim as having no
    period — a warning nobody can act on."""
    html = _html()
    i = html.index("pm_qs_variations: { title: 'Variation'")
    form = html[i:html.index("pm_qs_commissioning: { title:", i)]
    assert "k: 'noticeGivenOn'" in form and "k: 'noticeRef'" in form
    j = html.index("pm_projects: { title: 'Project Charter'")
    proj = html[j:html.index("pm_changes: { title:", j)]
    assert "k: 'eotNoticeDays'" in proj


def test_the_qs_tab_loads_the_risk_register_it_writes_to():
    """The exposure list reads pm_risks to know what has already been raised. Without it every
    exposure would offer the button for ever, including ones already on the register."""
    html = _html()
    i = html.index("k: 'qs', label: 'QS / Commercial'")
    entry = html[i:html.index("] },", i)]
    assert "'pm_risks'" in entry


def test_raising_a_risk_writes_a_marker_that_survives_a_rename():
    """The dedupe reads the marker out of the DESCRIPTION, so renaming the risk on the register
    does not make the button come back and offer a duplicate."""
    html = _html()
    i = html.index("async function qsRaiseRisk(")
    body = html[i:html.index("\n}", i)]
    assert "_QS_RISK_TAG + x.code" in body
    assert "description:" in body, "the marker must go in the description, not the title"


def test_a_time_exposure_is_never_given_a_cost_impact():
    """A day of delay only becomes money through a rate somebody agreed. Writing one onto the risk
    register would put a figure there that no contract contains."""
    html = _html()
    i = html.index("async function qsRaiseRisk(")
    body = html[i:html.index("\n}", i)]
    assert "costImpact: money ? x.amount : ''" in body


def test_applying_the_extension_never_touches_the_planned_finish():
    """endPlanned is what every variance on the project is measured against. Moving it would make
    a late job look on time by rewriting the thing it was late against."""
    with open("app.py", encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("def _qs_eot_ep(")
    body = src[i:src.index("def _qs_cvr_ep(", i)]
    assert 'upd["contractCompletionRevised"]' in body
    for forbidden in ('upd["endPlanned"]', 'upd["endBaseline"]', 'pm_tasks'):
        assert forbidden not in body, "_qs_eot_ep writes %s — it must not" % forbidden
