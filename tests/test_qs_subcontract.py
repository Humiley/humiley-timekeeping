"""The back-to-back position — PMBOK §12.3 Control Procurements.

The portal held both halves of a main contractor's cash and had never put them together. Packages
lived in pm_procurement, certificates in pm_procurement_payments, and a certificate did not even
record which package it was against — so no screen could say whether a subcontractor had been
certified past what he was bought for, whether the retention securing his work was actually being
held, or whether the job was paying out faster than it was being paid.

The rules under test are the module's usual ones landing in a new place: a missing figure is not
nil, two different absences are not one absence, and nothing here restates a certificate somebody
has already signed.
"""
import pytest

import qsurvey as qs


def _pkg(**kw):
    return dict({"id": "p1", "pkgNo": "PKG-001", "title": "HVAC ductwork & AHUs",
                 "vendor": "Thanh Cong M&E", "type": "Subcontract", "status": "Active",
                 "discipline": "HVAC", "value": 4_000_000_000,
                 "retentionPct": 5}, **kw)


def _cert(**kw):
    return dict({"id": "c1", "certNo": "IPC-001", "pkgNo": "PKG-001", "period": "2026-05",
                 "grossClaimed": 1_000_000_000, "retentionDeducted": 50_000_000,
                 "netCertified": 950_000_000, "status": "Certified",
                 "certDate": "2026-05-28"}, **kw)


def _p(**kw):
    return qs.subcontract_position(dict({"packages": [_pkg()], "certificates": [_cert()],
                                         "clientCertified": 6_000_000_000}, **kw))


def _codes(r):
    return {w["code"] for w in r["warnings"]}


def _pk(r, no="PKG-001"):
    return next(p for p in r["packages"] if p["pkgNo"] == no)


# ── matching a certificate to what it was issued against ─────────────────────────────────────────

def test_a_certificate_lands_on_the_package_it_names():
    p = _pk(_p())
    assert p["certifiedGross"] == 1_000_000_000
    assert p["retentionHeld"] == 50_000_000
    assert p["certifiedNet"] == 950_000_000
    assert p["certs"] == 1


def test_the_package_number_matches_regardless_of_case_and_padding():
    """It is typed twice by two people, on two documents, weeks apart."""
    assert _pk(_p(certificates=[_cert(pkgNo="  pkg-001 ")]))["certifiedGross"] == 1_000_000_000


def test_a_submitted_certificate_is_a_claim_and_not_a_liability():
    """The same rule as our own applications: what a subcontractor says he is owed is not what has
    been certified to him, and adding the two would state a liability nobody has accepted."""
    p = _pk(_p(certificates=[_cert(status="Submitted")]))
    assert p["certifiedGross"] == 0 and p["submitted"] == 1_000_000_000
    assert _p(certificates=[_cert(status="Submitted")])["submittedNotCertified"] == 1_000_000_000


def test_paid_is_counted_inside_certified_and_also_on_its_own():
    r = _p(certificates=[_cert(status="Certified"),
                         _cert(id="c2", certNo="IPC-002", status="Paid",
                               grossClaimed=500_000_000, retentionDeducted=25_000_000,
                               netCertified=475_000_000)])
    assert r["certifiedGross"] == 1_500_000_000
    assert r["paidNet"] == 475_000_000
    assert r["outstandingNet"] == 950_000_000


# ── certified past what was bought ───────────────────────────────────────────────────────────────

def test_certifying_above_the_committed_value_is_named_with_both_of_its_causes():
    """It is either a subcontract variation nobody recorded or an over-certification, and this
    module has no register that can tell them apart. Guessing one would be wrong half the time."""
    r = _p(certificates=[_cert(grossClaimed=4_500_000_000, retentionDeducted=225_000_000,
                               netCertified=4_275_000_000)])
    p = _pk(r)
    assert p["overCertified"] is True and p["overBy"] == 500_000_000
    w = [x for x in r["warnings"] if x["code"] == "subcontract_over_certified"][0]
    assert w["severity"] == "high"
    assert "variation" in w["msg"] and "over-certified" in w["msg"]


def test_a_package_with_no_committed_value_says_so_rather_than_reading_as_nil():
    """`_num` would make it 0, every certificate against it would read as over-certification, and
    the real finding — that nobody recorded what we bought — would never be stated."""
    r = _p(packages=[_pkg(value="")])
    p = _pk(r)
    assert p["value"] is None and p["pctCertified"] is None
    assert p["overCertified"] is False, "an unknown commitment is not a commitment of nil"
    assert "subcontract_no_value" in _codes(r)


def test_a_package_with_no_value_and_no_certificates_is_not_a_finding():
    """A package still out to tender has no value yet and nothing has been certified on it."""
    assert "subcontract_no_value" not in _codes(_p(packages=[_pkg(value="", status="Tendered")],
                                                   certificates=[]))


def test_percent_certified_is_against_the_package_and_not_the_job():
    assert _pk(_p())["pctCertified"] == 25.0


# ── the retention securing the work ──────────────────────────────────────────────────────────────

def test_retention_that_should_have_been_deducted_and_was_not_is_reported():
    r = _p(certificates=[_cert(retentionDeducted=0, netCertified=1_000_000_000)])
    p = _pk(r)
    assert p["retentionDue"] == 50_000_000
    assert p["retentionShort"] == 50_000_000
    assert r["retentionShortfall"] == 50_000_000
    w = [x for x in r["warnings"] if x["code"] == "subcontract_retention_short"][0]
    assert w["severity"] == "high" and "security" in w["msg"]


def test_a_retention_shortfall_never_restates_the_certificate():
    """The subcontractor was paid against the paper. Correcting the net here would produce a figure
    that disagrees with the bank advice, which is worse than the shortfall it was hiding."""
    r = _p(certificates=[_cert(retentionDeducted=0, netCertified=1_000_000_000)])
    p = _pk(r)
    assert p["certifiedNet"] == 1_000_000_000, "the certificate was rewritten"
    assert p["retentionHeld"] == 0
    assert r["certifiedNet"] == 1_000_000_000


def test_retention_deducted_in_full_raises_nothing():
    assert "subcontract_retention_short" not in _codes(_p())
    assert _p()["retentionShortfall"] == 0


def test_a_retention_of_nil_is_a_contract_fact_and_a_missing_one_is_not():
    """Nil means this subcontract carries no retention, which is something somebody agreed. Absent
    means nobody wrote it down, and no shortfall can be computed at all — reading one as the other
    either invents security we do not hold or hides that we cannot tell."""
    nil = _p(packages=[_pkg(retentionPct=0)],
             certificates=[_cert(retentionDeducted=0, netCertified=1_000_000_000)])
    assert _pk(nil)["retentionDue"] == 0 and _pk(nil)["retentionShort"] == 0
    assert "subcontract_no_retention_pct" not in _codes(nil)

    absent = _p(packages=[_pkg(retentionPct="")],
                certificates=[_cert(retentionDeducted=0, netCertified=1_000_000_000)])
    assert _pk(absent)["retentionDue"] is None
    assert _pk(absent)["retentionShort"] == 0, "a shortfall cannot be computed with no percentage"
    assert "subcontract_no_retention_pct" in _codes(absent)


def test_no_retention_percentage_on_a_package_nobody_has_certified_is_not_raised():
    assert "subcontract_no_retention_pct" not in _codes(
        _p(packages=[_pkg(retentionPct="")], certificates=[]))


# ── a certificate that does not add up ───────────────────────────────────────────────────────────

def test_a_certificate_whose_own_arithmetic_disagrees_is_reported_not_corrected():
    r = _p(certificates=[_cert(grossClaimed=1_000_000_000, retentionDeducted=50_000_000,
                               netCertified=980_000_000)])
    assert "certificate_does_not_add_up" in _codes(r)
    assert _pk(r)["certifiedNet"] == 980_000_000, "the stated net was replaced by a computed one"


def test_a_certificate_with_no_net_stated_is_computed_from_its_own_two_figures():
    r = _p(certificates=[_cert(netCertified="")])
    assert _pk(r)["certifiedNet"] == 950_000_000
    assert "certificate_does_not_add_up" not in _codes(r)


# ── the certificate nobody can place ─────────────────────────────────────────────────────────────

def test_a_certificate_naming_no_package_still_counts_in_the_project_totals():
    """The money is owed whether or not somebody typed a package number. Dropping it from the total
    would understate the exposure this whole report exists to state."""
    r = _p(certificates=[_cert(pkgNo="")])
    assert _pk(r)["certifiedGross"] == 0
    assert r["certifiedGross"] == 1_000_000_000
    assert r["certifiedNet"] == 950_000_000
    assert r["retentionHeld"] == 50_000_000
    assert r["orphanGross"] == 1_000_000_000 and r["orphanCount"] == 1


def test_no_package_named_and_a_package_that_does_not_exist_are_different_findings():
    """Same consequence, different cause and different fix: one is a field nobody filled, the other
    is a number somebody got wrong."""
    r = _p(certificates=[_cert(pkgNo=""),
                         _cert(id="c2", certNo="IPC-002", pkgNo="PKG-099")])
    assert {o["reason"] for o in r["orphans"]} == {"missing", "unknown"}
    assert {"certificate_no_package", "certificate_unknown_package"} <= _codes(r)


def test_an_orphan_that_is_only_submitted_is_not_added_to_the_liability():
    r = _p(certificates=[_cert(pkgNo="", status="Submitted")])
    assert r["orphanGross"] == 0 and r["orphanCount"] == 1


def test_two_packages_sharing_a_number_are_reported_because_neither_can_be_matched():
    r = _p(packages=[_pkg(), _pkg(id="p2", pkgNo="PKG-001", title="Duplicate")])
    assert "duplicate_package_no" in _codes(r)


# ── the trade comparison ─────────────────────────────────────────────────────────────────────────

def test_certified_out_above_what_we_measured_in_is_the_headline_finding():
    """Our subcontractor's measure and our own measure of the same physical work should track, with
    our margin between them. Certified out above valued in means we are paying for work we are not
    billing, and nothing in the portal could see it."""
    r = _p(certificates=[_cert(grossClaimed=3_000_000_000, retentionDeducted=150_000_000,
                               netCertified=2_850_000_000)],
           valueByTrade={qs.HVAC: 2_500_000_000})
    t = next(x for x in r["trades"] if x["code"] == qs.HVAC)
    assert t["ahead"] is True and t["aheadBy"] == 500_000_000
    w = [x for x in r["warnings"] if x["code"] == "certified_out_ahead_of_measure"][0]
    assert w["trade"] == qs.HVAC and "not billing" in w["msg"]


def test_certified_out_inside_our_own_measure_is_the_normal_case_and_is_silent():
    r = _p(valueByTrade={qs.HVAC: 2_500_000_000})
    t = next(x for x in r["trades"] if x["code"] == qs.HVAC)
    assert t["ahead"] is False and t["aheadBy"] == 0
    assert "certified_out_ahead_of_measure" not in _codes(r)


def test_a_trade_we_have_not_valued_is_not_compared_against_nothing():
    """A trade with no measured value yet is not a trade worth nil, and reading it as nil would
    report every package on it as certified ahead on the day it was awarded."""
    r = _p(valueByTrade={})
    t = next(x for x in r["trades"] if x["code"] == qs.HVAC)
    assert t["valuedIn"] is None and t["ahead"] is False
    assert "certified_out_ahead_of_measure" not in _codes(r)


def test_a_package_with_no_trade_is_in_the_totals_and_in_no_comparison():
    r = _p(packages=[_pkg(discipline="")], valueByTrade={qs.UNALLOCATED: 1})
    t = next(x for x in r["trades"] if x["code"] == qs.UNALLOCATED)
    assert t["certifiedOut"] == 1_000_000_000
    # This is the trap that once reported ₫21.8bn at risk: an unallocated PACKAGE and an
    # unallocated BILL LINE are two different absences, and comparing them reads as a finding.
    assert t["valuedIn"] is None and t["ahead"] is False
    assert r["certifiedGross"] == 1_000_000_000
    assert "package_no_trade" in _codes(r)


def test_a_trade_row_counts_the_packages_whose_value_it_could_not_add():
    r = _p(packages=[_pkg(), _pkg(id="p2", pkgNo="PKG-002", value="")])
    t = next(x for x in r["trades"] if x["code"] == qs.HVAC)
    assert t["committed"] == 4_000_000_000 and t["noValue"] == 1
    assert r["committed"] == 4_000_000_000 and r["packagesWithoutValue"] == 1


def test_trades_come_out_in_the_module_order_not_in_insert_order():
    r = _p(packages=[_pkg(id="p2", pkgNo="PKG-002", discipline="Electrical"), _pkg()])
    assert [t["code"] for t in r["trades"]].index(qs.HVAC) < \
           [t["code"] for t in r["trades"]].index(qs.ELECTRICAL)


# ── the funding position ─────────────────────────────────────────────────────────────────────────

def test_certifying_out_faster_than_being_certified_in_is_stated_as_our_own_cash():
    r = _p(certificates=[_cert(grossClaimed=7_000_000_000, retentionDeducted=350_000_000,
                               netCertified=6_650_000_000)])
    assert r["certifiedAheadOfClient"] == 1_000_000_000
    w = [x for x in r["warnings"] if x["code"] == "certified_out_ahead_of_in"][0]
    assert w["severity"] == "high" and "our own cash" in w["msg"]


def test_being_certified_in_ahead_of_certifying_out_is_the_healthy_case():
    r = _p()
    assert r["certifiedAheadOfClient"] == 0
    assert r["coverPct"] == 600.0
    assert "certified_out_ahead_of_in" not in _codes(r)


def test_no_client_certificate_makes_the_position_unknown_and_never_nil():
    """Nil would say the client has certified nothing, which is a statement about the job. This is
    a statement about the record, and the two lead to opposite decisions."""
    r = _p(clientCertified=None)
    assert r["clientCertified"] is None
    assert r["certifiedAheadOfClient"] is None and r["coverPct"] is None
    w = [x for x in r["warnings"] if x["code"] == "no_client_certificate"][0]
    assert "not nil" in w["msg"]


def test_a_client_certificate_of_genuinely_nil_is_not_the_same_as_no_record_of_one():
    r = _p(clientCertified=0)
    assert r["clientCertified"] == 0
    assert r["certifiedAheadOfClient"] == 1_000_000_000
    assert "no_client_certificate" not in _codes(r)


def test_the_retention_position_nets_what_we_hold_against_what_is_held_from_us():
    r = _p(retentionFromUs=120_000_000)
    assert r["retentionHeld"] == 50_000_000
    assert r["retentionNet"] == -70_000_000


def test_retention_held_from_us_that_nobody_recorded_leaves_the_net_unstated():
    assert _p()["retentionNet"] is None


# ── the cut-off ──────────────────────────────────────────────────────────────────────────────────

def test_a_certificate_after_the_cut_off_is_outside_the_position():
    r = _p(cutoff="2026-05-31",
           certificates=[_cert(), _cert(id="c2", certNo="IPC-002", certDate="2026-06-28")])
    assert _pk(r)["certifiedGross"] == 1_000_000_000


def test_a_certificate_with_no_date_is_excluded_and_named_rather_than_swept_in():
    """A record with no date cannot be shown to fall before the cut-off. Including it silently is
    how money gets certified into the wrong month."""
    r = _p(cutoff="2026-05-31", certificates=[_cert(certDate="")])
    assert r["certifiedGross"] == 0
    assert "certificate_no_date" in _codes(r)


def test_with_no_cut_off_an_undated_certificate_is_simply_in():
    r = _p(certificates=[_cert(certDate="")])
    assert r["certifiedGross"] == 1_000_000_000
    assert "certificate_no_date" not in _codes(r)


# ── what it refuses to invent ────────────────────────────────────────────────────────────────────

def test_the_module_says_out_loud_that_it_has_no_subcontract_variation_register():
    joined = " ".join(qs.UNRESOLVED)
    assert "VARIATION to a subcontract" in joined
    assert "pm_procurement" in joined


def test_an_empty_job_produces_a_position_rather_than_an_error():
    r = qs.subcontract_position({})
    assert r["committed"] == 0 and r["packages"] == [] and r["trades"] == []
    assert r["clientCertified"] is None


def test_the_register_comes_out_in_package_number_order():
    """The bill taught this: a document printed in insert order is a different document. A payment
    position a QS reads down has to be in the order the packages are numbered."""
    r = _p(packages=[_pkg(id="c", pkgNo="PKG-003"), _pkg(id="a", pkgNo="PKG-001"),
                     _pkg(id="b", pkgNo="PKG-002")])
    assert [p["pkgNo"] for p in r["packages"]] == ["PKG-001", "PKG-002", "PKG-003"]


def test_a_package_with_no_number_sorts_last_rather_than_first():
    r = _p(packages=[_pkg(id="x", pkgNo="", title="Unnumbered"), _pkg()])
    assert [p["pkgNo"] for p in r["packages"]] == ["PKG-001", ""]
