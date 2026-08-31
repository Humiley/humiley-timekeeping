"""The back-to-back position reaching a screen.

The engine is tested in test_qs_subcontract.py. This file tests the part that has broken before:
a report computed correctly and wired to nothing. The QS module has already shipped a field written
and read by nobody (`evBasis`), a bill sorted on the server and re-sorted in the browser, and two
registers readable at staff level that no staff account could write to — every one of them green in
the engine tests and wrong on the screen.
"""
import io
import re

import pytest


def _html():
    return io.open("templates/index.html", encoding="utf-8").read()


def _app():
    return io.open("app.py", encoding="utf-8").read()


def _schema(html, name, nxt):
    i = html.index(name + ": { title: ")
    return html[i:html.index(nxt + ": { title: ", i)]


# ── the two fields the join is made of ───────────────────────────────────────────────────────────

def test_a_procurement_package_records_the_trade_it_belongs_to():
    """Without it every package lands in the totals and in no trade comparison, which is the whole
    point of the report."""
    f = _schema(_html(), "pm_procurement", "pm_procurement_payments")
    assert "k: 'discipline'" in f and "options: 'qs_disciplines'" in f


def test_a_payment_certificate_records_the_package_it_is_against():
    """It never did. A certificate floated free of the package it paid, so nothing could say
    whether a subcontractor had been certified past what he was bought for."""
    f = _schema(_html(), "pm_procurement_payments", "pm_stakeholders")
    assert "k: 'pkgNo'" in f and "options: 'pm_packages'" in f


def test_the_package_picker_stores_the_number_and_not_the_row_id():
    """subcontract_position() matches by NUMBER, which is also what is written on both pieces of
    paper. Storing an id would match nothing and every certificate would read as an orphan."""
    html = _html()
    i = html.index("if (src === 'pm_packages')")
    body = html[i:html.index("if (src === 'qs_disciplines')", i)]
    assert "v: r.pkgNo" in body, "the picker must store the package number"
    assert "v: r.id" not in body


def test_the_client_certificate_records_the_retention_it_states():
    """Gross and retention are two lines on one certificate. Without the second, the security
    position has nothing to net against and would have shipped permanently blank."""
    html = _html()
    i = html.index("async function qsValCertify(")
    body = html[i:html.index("\n}", i)]
    assert "k: 'certifiedRetention'" in body
    assert "certifiedRetention: val.certifiedRetention" in body, "the field is collected, not sent"


def test_the_certified_gross_and_the_certified_retention_come_off_one_certificate():
    """Found by row, not by two separate scans of the series. Two scans could take the gross from
    June's certificate and the retention from May's, and produce a net that appears on nothing
    anybody signed."""
    src = _app()
    i = src.index("cert_row = next((s for s in reversed(series)")
    body = src[i:i + 900]
    assert 'certified = cert_row["certifiedGross"] if cert_row else None' in body
    assert '(cert_row or {}).get("certifiedRetention")' in src


def test_a_certificate_stating_no_retention_leaves_it_unrecorded_rather_than_nil():
    src = _app()
    i = src.index('cr = qsurvey._rate(body.get("certifiedRetention"))')
    body = src[i:i + 600]
    assert 'qsurvey.r2(cr) if cr is not None else ""' in body


# ── the registers reaching the engine ────────────────────────────────────────────────────────────

def test_the_summary_reads_both_procurement_registers():
    src = _app()
    i = src.index("def _qs_rows(")
    body = src[i:src.index("def _qs_ctx(", i)]
    assert '"procurement": _of("pm_procurement")' in body
    assert '"procurementCerts": _of("pm_procurement_payments")' in body


def test_the_position_is_computed_and_served():
    src = _app()
    assert "qsurvey.subcontract_position({" in src
    i = src.index("qsurvey.subcontract_position({")
    call = src[i:i + 700]
    assert '"packages": rows["procurement"]' in call
    assert '"certificates": rows["procurementCerts"]' in call
    assert '"valueByTrade": value_by_trade' in call
    assert '"subcontracts": sub,' in src, "computed and not returned"


def test_the_client_figure_passed_in_is_the_certificate_and_never_a_zero_default():
    """`certified` is None when no certificate has been recorded. Defaulting it to 0 here would
    report every job as funding itself from its own cash on the day it started."""
    src = _app()
    i = src.index("qsurvey.subcontract_position({")
    call = src[i:i + 700]
    assert '"clientCertified": certified,' in call
    assert '"clientCertified": certified or 0' not in call
    assert 'certified if certified is not None else 0' not in call


def test_the_qs_tab_loads_the_two_registers_the_position_is_built_from():
    """A tab that renders a collection it never asked for paints an empty table and reads as a job
    with no subcontracts."""
    html = _html()
    i = html.index("k: 'qs', label: 'QS / Commercial'")
    entry = html[i:html.index("] },", i)]
    assert "'pm_procurement'" in entry and "'pm_procurement_payments'" in entry


def test_the_need_list_is_still_one_line_and_still_parses():
    """A multi-line comment inside this array once made the loader read it as empty, and the tab
    silently rendered against no data at all."""
    html = _html()
    i = html.index("k: 'qs', label: 'QS / Commercial'")
    entry = html[i:html.index("] },", i)]
    assert "\n" not in entry, "the need list must stay on one line"
    assert len(re.findall(r"'pm_[a-z_]+'", entry)) >= 13


# ── the screen ───────────────────────────────────────────────────────────────────────────────────

def test_the_tab_exists_and_points_at_a_renderer_that_exists():
    html = _html()
    i = html.index("const _QS_TABS = [")
    tabs = html[i:html.index("];", i)]
    assert "k: 'sub'" in tabs and "fn: '_qsRenderSubs'" in tabs
    assert "function _qsRenderSubs(" in html


def test_the_screen_reads_the_served_position_and_computes_no_money_of_its_own():
    """The bill taught this one: a browser that multiplied quantity by rate rendered a provisional
    sum at nil, because a provisional sum carries its amount in the rate column with no quantity."""
    html = _html()
    i = html.index("function _qsRenderSubs(")
    body = html[i:html.index("function qsSubcontractPDF(", i)]
    assert "d.subcontracts" in html[i - 6000:i + 900]
    for forbidden in ("* 100", "/ 100", "* p.retentionPct", "- s.clientCertified"):
        assert forbidden not in body, "the screen is doing arithmetic on money: %s" % forbidden


def test_an_unstated_client_position_prints_a_dash_and_not_a_zero():
    html = _html()
    i = html.index("function _qsSubFundCard(")
    body = html[i:html.index("function _qsSubPkgCard(", i)]
    assert "s.clientCertified == null" in body
    assert "unknown, not nil" in body


def test_a_package_with_no_committed_value_is_shown_as_unrecorded():
    html = _html()
    i = html.index("function _qsSubPkgCard(")
    body = html[i:html.index("/* Certified out against measured in", i)]
    assert "p.value == null" in body and "not recorded" in body


def test_the_orphan_certificates_are_shown_as_inside_the_totals():
    """A reader who cannot see that they are counted will add them again by hand."""
    html = _html()
    i = html.index("function _qsSubOrphanCard(")
    body = html[i:html.index("function _qsRenderSubs(", i)]
    assert "inside the project totals" in body
    assert "o.reason === 'missing'" in body, "the two kinds of orphan must stay distinct"


def test_the_position_has_a_document_somebody_can_sign():
    html = _html()
    assert "function qsSubcontractPDF(" in html
    i = html.index("function qsSubcontractPDF(")
    body = html[i:i + 4200]
    assert "HML-QS-SCP" in body
    assert "_qsSignBlock(doc" in body and "_qsFoot(doc" in body
    assert "_brandFooter" not in body, "_qsFoot already numbers every page"


def test_the_pdf_prints_an_unknown_client_position_as_words_not_as_nil():
    html = _html()
    i = html.index("function qsSubcontractPDF(")
    body = html[i:i + 4200]
    assert "s.clientCertified == null ? 'not recorded'" in body
    assert "s.certifiedAheadOfClient == null ? 'cannot be stated'" in body


def test_a_trade_whose_only_package_has_no_value_prints_a_dash_not_a_zero():
    """₫0 beside "1 without a value" says two contradictory things: that the trade committed
    nothing, and that its commitment is unknown. Only one of them is true."""
    html = _html()
    i = html.index("function _qsSubTradeCard(")
    body = html[i:html.index("/* Certificates that cannot be placed", i)]
    assert "(!t.committed && t.noValue)" in body


def test_the_monthly_commercial_report_carries_the_subcontract_position():
    """A commercial review that states the margin and never says whether the job is paying its
    subcontractors faster than the client is paying it has left out the half that runs the bank
    account. It is the one document a commercial director actually reads."""
    html = _html()
    i = html.index("function qsCommercialReportPDF(")
    body = html[i:html.index("async function qsApplyEot(", i)]
    assert "SUBCONTRACT POSITION" in body
    assert "d.subcontracts" in body
    assert "sb.clientCertified == null ? 'not recorded'" in body, \
        "an unrecorded client certificate must not print as nil in the report either"
    assert "Trades certified out ahead of our own measure" in body


# ── the subcontract variation register ───────────────────────────────────────────────────────────

def test_the_variation_register_exists_as_a_form_somebody_can_fill_in():
    """The engine gained the arithmetic first. A register with no form is a rule enforced against
    data nobody can enter — the competence register shipped exactly that way."""
    f = _schema(_html(), "pm_qs_subvo", "pm_stakeholders")
    for k in ("subVoNo", "pkgNo", "value", "status", "instructedOn", "agreedOn", "reason"):
        assert "k: '%s'" % k in f, "the register has no %s field" % k
    assert "options: 'pm_packages'" in f, "it must point at the same picker the certificates use"


def test_the_register_is_manager_and_above_on_both_gates():
    """It commits the company to pay a subcontractor more. Read and write are two gates and they
    must agree — staff-readable and not staff-writable is the shape that shipped once already and
    made every save fail with 'Manager access required'."""
    src = _app()
    assert '"pm_qs_subvo": "manager"' in src
    i = src.index("STAFF_WRITE = {")
    assert "pm_qs_subvo" not in src[i:src.index("}", i)], "manager-read but staff-write"


def test_the_register_joined_every_guard_list_a_qs_collection_belongs_to():
    src = _app()
    i = src.index("COLLECTIONS = {")
    assert "pm_qs_subvo" in src[i:src.index("}", i)]
    j = src.index("QS_COLLS = (")
    assert "pm_qs_subvo" in src[j:src.index(")", j)]


def test_the_variations_reach_the_engine_and_the_tab_loads_them():
    src, html = _app(), _html()
    assert '"subVariations": _of("pm_qs_subvo")' in src
    i = src.index("qsurvey.subcontract_position({")
    assert '"subVariations": rows["subVariations"]' in src[i:i + 700]
    j = html.index("k: 'qs', label: 'QS / Commercial'")
    assert "'pm_qs_subvo'" in html[j:html.index("] },", j)]


def test_the_register_is_on_the_screen_and_not_only_in_the_payload():
    html = _html()
    assert "function _qsSubVoCard(" in html
    i = html.index("function _qsRenderSubs(")
    assert "_qsSubVoCard(pid)" in html[i:i + 900], "the card is defined and never rendered"


def test_the_pending_variations_are_never_added_into_what_the_package_is_worth():
    """On the screen as in the engine: instructed is an exposure printed beside the figure, never
    inside it. Adding them would make a commitment look settled when nobody has priced it."""
    html = _html()
    i = html.index("function _qsSubPkgCard(")
    body = html[i:html.index("/* Certified out against measured in", i)]
    assert "p.variationsPending" in body and "pending" in body
    for forbidden in ("p.variations + p.variationsPending", "p.value + p.variations"):
        assert forbidden not in body, "the screen is summing variations itself: %s" % forbidden
