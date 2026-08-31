"""The cash position — certified against actually moved.

A contractor does not fail because a job loses money. It fails because the money leaves before it
arrives. Every figure this needs already existed: the client's certificates carried `certifiedOn`
and `paidOn` since the valuation register was built, and nothing had ever read the second one.

The distinction the whole report turns on is CERTIFIED versus PAID — a certificate is a promise
with a date on it, cash is what is in the account — and the two sides have opposite shapes: a
client certificate states GROSS TO DATE, a subcontractor's states the amount of that certificate.
Reading either one the other way is wrong in both directions.
"""
import pytest

import qsurvey as qs


def _v(**kw):
    return dict({"valNo": "VAL-001", "status": "certified", "certifiedGross": 2_000_000_000,
                 "certifiedRetention": 100_000_000, "certifiedOn": "2026-04-28",
                 "paidOn": ""}, **kw)


def _c(**kw):
    return dict({"certNo": "IPC-001", "pkgNo": "PKG-001", "status": "Certified",
                 "grossClaimed": 800_000_000, "retentionDeducted": 40_000_000,
                 "netCertified": 760_000_000, "certDate": "2026-04-28"}, **kw)


def _f(**kw):
    return qs.cash_flow(dict({"valuations": [_v()], "subCertificates": [_c()],
                              "today": "2026-06-15"}, **kw))


def _codes(r):
    return {w["code"] for w in r["warnings"]}


def _per(r, m):
    return next(p for p in r["periods"] if p["period"] == m)


# ── money in: a certificate states GROSS TO DATE ─────────────────────────────────────────────────

def test_the_payment_a_certificate_generates_is_its_movement_not_its_gross():
    """Adding the gross figures together counts the whole job once a month. It is the same rule the
    valuation series already follows for certified-to-date."""
    r = _f(valuations=[_v(),
                       _v(valNo="VAL-002", certifiedGross=3_200_000_000,
                          certifiedRetention=160_000_000, certifiedOn="2026-05-28")])
    assert r["certificatesIn"][0]["movement"] == 1_900_000_000
    assert r["certificatesIn"][1]["movement"] == 1_140_000_000
    assert r["receivable"] == 3_040_000_000


def test_the_movement_is_net_of_retention_because_that_is_what_gets_paid():
    assert _f()["certificatesIn"][0]["movement"] == 1_900_000_000


def test_a_certificate_with_no_retention_recorded_is_computed_on_gross_and_says_so():
    """Taking an unrecorded retention as nil silently overstates every payment on the timeline."""
    r = _f(valuations=[_v(certifiedRetention="")])
    assert r["certificatesIn"][0]["retentionToDate"] is None
    assert r["certificatesIn"][0]["movement"] == 2_000_000_000
    assert "certificate_in_no_retention" in _codes(r)


def test_a_valuation_the_client_has_not_certified_is_not_money():
    for st in ("draft", "submitted", "cancelled"):
        assert _f(valuations=[_v(status=st)])["certificatesIn"] == []


def test_certified_and_unpaid_is_a_receivable_and_paid_is_not():
    assert _f()["receivable"] == 1_900_000_000
    paid = _f(valuations=[_v(status="paid", paidOn="2026-05-10")])
    assert paid["receivable"] == 0 and paid["received"] == 1_900_000_000


# ── money out: a subcontractor's certificate states ITS OWN amount ───────────────────────────────

def test_subcontractor_certificates_add_up_directly():
    """Opposite shape to the client side. Treating them as to-date figures would report a single
    payment as the whole liability."""
    r = _f(subCertificates=[_c(), _c(certNo="IPC-002", netCertified=500_000_000)])
    assert r["payable"] == 1_260_000_000


def test_a_certificate_only_submitted_is_not_yet_owed():
    assert _f(subCertificates=[_c(status="Submitted")])["payable"] == 0


def test_a_certificate_with_no_net_stated_is_computed_from_its_own_two_figures():
    assert _f(subCertificates=[_c(netCertified="")])["payable"] == 760_000_000


def test_paid_out_leaves_the_payable_and_stays_in_the_cash():
    r = _f(subCertificates=[_c(status="Paid")])
    assert r["payable"] == 0 and r["paidOut"] == 760_000_000


# ── the timeline ─────────────────────────────────────────────────────────────────────────────────

def test_every_month_between_the_first_and_last_appears_even_with_no_movement():
    """A gap in a contractor's cash-in is the single most important thing this report can show, and
    printing only the months that had a certificate makes a gap look like continuity."""
    r = _f(valuations=[_v(), _v(valNo="VAL-004", certifiedGross=5_000_000_000,
                                certifiedRetention=250_000_000, certifiedOn="2026-07-28")])
    assert [p["period"] for p in r["periods"]] == ["2026-04", "2026-05", "2026-06", "2026-07"]
    assert _per(r, "2026-05")["certifiedIn"] == 0


def test_the_running_total_counts_cash_and_not_certificates():
    """A certificate is a promise with a date on it. Only the payment is money."""
    r = _f(valuations=[_v(status="paid", paidOn="2026-05-10")],
           subCertificates=[_c(status="Paid", certDate="2026-04-28", paidOn="2026-04-30")])
    assert _per(r, "2026-04")["cumulativeCash"] == -760_000_000
    assert _per(r, "2026-05")["cumulativeCash"] == 1_140_000_000


def test_a_certificate_is_placed_by_its_certificate_date_and_a_payment_by_its_payment_date():
    r = _f(valuations=[_v(status="paid", certifiedOn="2026-04-28", paidOn="2026-06-09")])
    assert _per(r, "2026-04")["certifiedIn"] == 1_900_000_000
    assert _per(r, "2026-04")["receivedIn"] == 0
    assert _per(r, "2026-06")["receivedIn"] == 1_900_000_000


def test_an_undated_certificate_is_counted_in_the_totals_and_named_as_being_in_no_month():
    """The money exists whether or not somebody typed a date. Dropping it from the totals would
    understate the position; putting it in an arbitrary month would misstate the timeline."""
    r = _f(valuations=[_v(certifiedOn="")])
    assert r["receivable"] == 1_900_000_000
    assert r["periods"] == [] or all(p["certifiedIn"] == 0 for p in r["periods"])
    assert "certificate_in_no_date" in _codes(r)


def test_a_payment_marked_paid_with_no_date_is_still_paid():
    r = _f(valuations=[_v(status="paid", paidOn="")])
    assert r["received"] == 1_900_000_000 and r["receivable"] == 0
    assert "payment_in_no_date" in _codes(r)


# ── what it refuses to net ───────────────────────────────────────────────────────────────────────

def test_the_receivable_and_the_payable_are_never_subtracted_into_a_cash_position():
    """They fall due on different days to different people, and a positive net has never once
    stopped a subcontractor suspending for non-payment."""
    r = _f()
    assert r["receivable"] == 1_900_000_000 and r["payable"] == 760_000_000
    assert "cashPosition" not in r and "netPosition" not in r
    assert "never netted" in r["note"]


def test_owing_out_more_than_we_are_owed_is_stated_as_having_to_come_from_somewhere_else():
    r = _f(valuations=[_v(status="paid", paidOn="2026-05-10")],
           subCertificates=[_c(netCertified=900_000_000)])
    w = [x for x in r["warnings"] if x["code"] == "owed_out_exceeds_owed_in"][0]
    assert w["severity"] == "high" and "somewhere else" in w["msg"]


def test_retention_is_shown_as_held_and_never_given_a_release_date():
    """When it comes back depends on practical completion and the defects period, which are in the
    contract and not in this module. sales_contract.retention_release() owns that."""
    r = _f(retentionFromUs=390_000_000, retentionFromSubs=388_250_000)
    assert r["retentionFromUs"] == 390_000_000 and r["retentionFromSubs"] == 388_250_000
    assert "retentionRelease" not in r and "retentionDue" not in r
    assert "not scheduled" in r["note"]


def test_retention_nobody_recorded_stays_unstated_rather_than_nil():
    assert _f()["retentionFromUs"] is None


# ── the forecast ─────────────────────────────────────────────────────────────────────────────────

def test_the_forecast_spreads_what_is_left_over_the_months_to_completion():
    r = _f(revisedContractSum=12_000_000_000, certifiedToDate=6_000_000_000,
           completion="2026-12-31")
    f = r["forecast"]
    assert f["monthsRemaining"] == 6
    assert f["remainingValue"] == 6_000_000_000
    assert f["perMonth"] == 1_000_000_000
    assert [x["period"] for x in f["rows"]][0] == "2026-07"


def test_the_forecast_says_out_loud_that_it_is_an_assumption_and_not_a_plan():
    """The shape of the real curve lives in the programme, and this module does not read it."""
    r = _f(revisedContractSum=12_000_000_000, certifiedToDate=6_000_000_000,
           completion="2026-12-31")
    w = [x for x in r["warnings"] if x["code"] == "forecast_is_straight_line"][0]
    assert "assumption, not a plan" in w["msg"]
    assert "evenly" in r["forecast"]["basis"]


def test_no_completion_date_makes_the_forecast_unavailable_and_never_nil():
    r = _f(revisedContractSum=12_000_000_000, certifiedToDate=6_000_000_000)
    assert r["forecast"] is None
    w = [x for x in r["warnings"] if x["code"] == "no_completion_date"][0]
    assert "unavailable, not nil" in w["msg"]


def test_a_completion_date_already_passed_is_reported_with_what_is_still_outstanding():
    """Spreading it over zero months would divide by zero or, worse, quietly report nothing left."""
    r = _f(revisedContractSum=12_000_000_000, certifiedToDate=6_000_000_000,
           completion="2026-03-31")
    assert r["forecast"] is None
    w = [x for x in r["warnings"] if x["code"] == "completion_passed"][0]
    assert "6,000,000,000" in w["msg"]


def test_no_contract_sum_leaves_nothing_to_forecast_against():
    r = _f(completion="2026-12-31")
    assert r["forecast"] is None
    assert "no_contract_sum" in _codes(r)


def test_an_empty_job_produces_a_position_rather_than_an_error():
    r = qs.cash_flow({})
    assert r["periods"] == [] and r["receivable"] == 0 and r["payable"] == 0
    assert r["forecast"] is None


# ── the wiring ───────────────────────────────────────────────────────────────────────────────────

def _html():
    import io
    return io.open("templates/index.html", encoding="utf-8").read()


def _app():
    import io
    return io.open("app.py", encoding="utf-8").read()


def test_the_position_is_computed_and_served():
    src = _app()
    assert "qsurvey.cash_flow({" in src
    i = src.index("qsurvey.cash_flow({")
    call = src[i:i + 900]
    assert '"valuations": series' in call
    assert '"subCertificates": rows["procurementCerts"]' in call
    assert '"cash": cash,' in src, "computed and not returned"


def test_the_forecast_is_spread_over_the_REVISED_completion_where_one_was_granted():
    """An extension moves the date the remaining work has to be spread over. Forecasting against
    the original would compress the same money into fewer months and overstate every one of them."""
    src = _app()
    i = src.index("qsurvey.cash_flow({")
    call = src[i:i + 900]
    assert 'eot.get("revisedCompletion") or project.get("endPlanned")' in call


def test_the_tab_exists_and_points_at_a_renderer_that_exists():
    html = _html()
    i = html.index("const _QS_TABS = [")
    tabs = html[i:html.index("];", i)]
    assert "k: 'cash'" in tabs and "fn: '_qsRenderCash'" in tabs
    assert "function _qsRenderCash(" in html


def test_the_screen_never_nets_the_two_sides_into_one_number():
    """The engine refuses to; a screen that did it anyway would undo the refusal where somebody
    reads it."""
    html = _html()
    i = html.index("function _qsCashOwedCard(")
    body = html[i:html.index("function _qsCashChart(", i)]
    for forbidden in ("c.receivable - c.payable", "c.payable - c.receivable"):
        assert forbidden not in body, "the screen is netting: %s" % forbidden
    assert "c.workingCapitalGap" in body, "the gap must come from the engine, not the browser"


def test_an_unrecorded_retention_prints_a_dash_and_not_a_zero():
    html = _html()
    i = html.index("function _qsCashOwedCard(")
    body = html[i:html.index("function _qsCashChart(", i)]
    assert "c.retentionFromUs == null ? '—'" in body


def test_the_chart_labels_each_month_with_cash_and_not_with_certificates():
    html = _html()
    i = html.index("function _qsCashChart(")
    body = html[i:html.index("function _qsCashForecastCard(", i)]
    assert "p.cumulativeCash" in body
    assert "cash to date" in body or "cash to date" in body.lower()


def test_the_forecast_card_carries_its_own_assumption_warning():
    """A straight line printed without the sentence beside it is read as a plan."""
    html = _html()
    i = html.index("function _qsCashForecastCard(")
    body = html[i:html.index("function _qsRenderCash(", i)]
    assert "an assumption, not a plan" in body.lower()


def test_an_unavailable_forecast_explains_itself_rather_than_disappearing():
    html = _html()
    i = html.index("function _qsCashForecastCard(")
    body = html[i:html.index("function _qsRenderCash(", i)]
    assert "no_completion_date" in body and "completion_passed" in body


def test_the_position_has_a_document_somebody_can_sign():
    html = _html()
    assert "function qsCashPDF(" in html
    i = html.index("function qsCashPDF(")
    body = html[i:i + 4200]
    assert "HML-QS-CSH" in body
    assert "_qsSignBlock(doc" in body and "_qsFoot(doc" in body
    assert "_brandFooter" not in body, "_qsFoot already numbers every page"
    assert "NOT netted" in body


# ── the defect only running it found ─────────────────────────────────────────────────────────────

def test_money_leaving_is_dated_by_the_payment_and_not_by_the_certificate():
    """The client side has always drawn this distinction. The outgoing side silently did not, so a
    certificate raised in April and paid in June was drawn on the timeline as leaving in April —
    confidently, with no warning, in the one report whose entire subject is certified versus paid.
    Found by running it against real dates, not by a test."""
    r = _f(subCertificates=[_c(status="Paid", certDate="2026-04-28", paidOn="2026-06-09")])
    assert _per(r, "2026-04")["certifiedOut"] == 760_000_000
    assert _per(r, "2026-04")["paidOut"] == 0
    assert _per(r, "2026-06")["paidOut"] == 760_000_000


def test_a_subcontractor_payment_with_no_date_is_still_paid_and_is_named():
    r = _f(subCertificates=[_c(status="Paid", paidOn="")])
    assert r["paidOut"] == 760_000_000 and r["payable"] == 0
    assert "payment_out_no_date" in _codes(r)


def test_a_payment_month_beyond_the_last_certificate_extends_the_timeline():
    """Otherwise the month the money actually left falls off the end of the chart."""
    r = _f(subCertificates=[_c(status="Paid", certDate="2026-04-28", paidOn="2026-08-09")])
    assert [p["period"] for p in r["periods"]][-1] == "2026-08"


def test_the_certificate_records_the_date_the_money_left():
    import io
    html = io.open("templates/index.html", encoding="utf-8").read()
    i = html.index("pm_procurement_payments: { title: ")
    f = html[i:html.index("pm_qs_subvo: { title: ", i)]
    assert "k: 'paidOn'" in f, "nothing on the form records when the payment was actually made"
