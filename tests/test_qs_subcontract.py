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

def test_certifying_above_the_package_with_nothing_to_explain_it_is_an_over_certification():
    """This used to be reported as one of two possible causes, because nothing recorded a
    subcontract variation. With a register in place the module can say which it is, and with no
    variation on the package there is only one answer left."""
    r = _p(certificates=[_cert(grossClaimed=4_500_000_000, retentionDeducted=225_000_000,
                               netCertified=4_275_000_000)])
    p = _pk(r)
    assert p["overCertified"] is True and p["overBy"] == 500_000_000
    w = [x for x in r["warnings"] if x["code"] == "subcontract_over_certified"][0]
    assert w["severity"] == "high"
    assert "this is an over-certification" in w["msg"]


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

def test_the_module_no_longer_claims_it_cannot_see_a_subcontract_variation():
    """UNRESOLVED named this gap for exactly as long as it was real. A refusal left standing after
    the thing was built is a lie the next reader believes."""
    joined = " ".join(qs.UNRESOLVED)
    assert "VARIATION to a subcontract" not in joined
    # The three that remain are genuinely still unresolved.
    assert len(qs.UNRESOLVED) == 3
    assert "Price fluctuation" in joined and "liquidated damages" in joined


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


# ── subcontract variations: what a package is actually worth now ─────────────────────────────────

def _vo(**kw):
    return dict({"id": "v1", "subVoNo": "SVO-001", "pkgNo": "PKG-001",
                 "title": "Additional fire dampers", "value": 300_000_000,
                 "status": "Agreed", "instructedOn": "2026-04-10",
                 "agreedOn": "2026-05-02"}, **kw)


def test_an_agreed_variation_raises_what_the_package_is_worth():
    r = _p(subVariations=[_vo()])
    p = _pk(r)
    assert p["variations"] == 300_000_000
    assert p["revisedValue"] == 4_300_000_000
    assert r["variations"] == 300_000_000
    assert r["revisedCommitted"] == 4_300_000_000


def test_an_instructed_variation_is_an_exposure_and_does_not_raise_the_package():
    """The same rule our own variations follow: work is being done at a price nobody has set, and
    counting it as agreed would make the commitment look settled when it is not."""
    r = _p(subVariations=[_vo(status="Instructed", agreedOn="")])
    p = _pk(r)
    assert p["variations"] == 0 and p["variationsPending"] == 300_000_000
    assert p["revisedValue"] == 4_000_000_000
    assert r["variationsPending"] == 300_000_000


def test_a_rejected_variation_changes_nothing_and_is_not_an_exposure():
    r = _p(subVariations=[_vo(status="Rejected")])
    p = _pk(r)
    assert p["variations"] == 0 and p["variationsPending"] == 0
    assert p["variationCount"] == 0


def test_an_omission_is_a_negative_variation_and_lowers_the_package():
    """Descoping a subcontractor is the commonest variation of all and the one most often left
    unrecorded, because nobody chases a credit."""
    r = _p(subVariations=[_vo(value=-500_000_000)])
    assert _pk(r)["revisedValue"] == 3_500_000_000


def test_a_variation_nobody_has_priced_is_reported_and_never_counted_at_nil():
    """Counted at zero it would make a package look explained when nothing about it is settled."""
    r = _p(subVariations=[_vo(value="")])
    p = _pk(r)
    assert p["variations"] == 0 and p["variationCount"] == 0
    assert "subcontract_variation_unpriced" in _codes(r)


def test_a_variation_on_an_unknown_commitment_leaves_it_unknown():
    """Something plus an unknown is still an unknown. Revising from None would turn "nobody
    recorded what we bought" into a confident figure."""
    r = _p(packages=[_pkg(value="")], subVariations=[_vo()])
    assert _pk(r)["revisedValue"] is None


def test_a_variation_naming_no_package_explains_nothing_and_says_so():
    r = _p(subVariations=[_vo(pkgNo="PKG-404")])
    assert _pk(r)["variations"] == 0
    assert "subcontract_variation_no_package" in _codes(r)


def test_a_certificate_covered_by_an_agreed_variation_is_not_over_certification():
    """This is the case that used to be reported as a possible fraud. The variation was always
    there; the portal simply had nowhere to write it down."""
    r = _p(subVariations=[_vo(value=600_000_000)],
           certificates=[_cert(grossClaimed=4_500_000_000, retentionDeducted=225_000_000,
                               netCertified=4_275_000_000)])
    p = _pk(r)
    assert p["revisedValue"] == 4_600_000_000
    assert p["overCertified"] is False
    assert not [x for x in r["warnings"] if x["code"].startswith("subcontract_over_certified")]


def test_a_certificate_an_instructed_variation_would_cover_names_that_specifically():
    """A different finding with a different fix: agree the variation, and the certificate is
    covered. Reporting it as a plain over-certification would send a QS looking for the wrong
    thing."""
    r = _p(subVariations=[_vo(status="Instructed", agreedOn="", value=600_000_000)],
           certificates=[_cert(grossClaimed=4_500_000_000, retentionDeducted=225_000_000,
                               netCertified=4_275_000_000)])
    w = [x for x in r["warnings"]
         if x["code"] == "subcontract_over_certified_pending_variation"]
    assert w and "not yet agreed" in w[0]["msg"]
    assert "subcontract_over_certified" not in _codes(r)


def test_an_instructed_variation_too_small_to_cover_the_gap_is_still_an_over_certification():
    """It explains part of it and not the rest, and the rest is the finding."""
    r = _p(subVariations=[_vo(status="Instructed", agreedOn="", value=100_000_000)],
           certificates=[_cert(grossClaimed=4_500_000_000, retentionDeducted=225_000_000,
                               netCertified=4_275_000_000)])
    assert "subcontract_over_certified" in _codes(r)


def test_percent_certified_is_measured_against_the_revised_value():
    r = _p(subVariations=[_vo(value=1_000_000_000)])
    assert _pk(r)["pctCertified"] == 20.0


def test_an_agreed_variation_after_the_cut_off_is_not_in_this_position():
    r = _p(cutoff="2026-04-30", subVariations=[_vo()])
    assert _pk(r)["variations"] == 0


def test_an_instructed_variation_is_dated_by_its_instruction_not_its_agreement():
    """It has no agreement date yet, so dating it by one would drop every pending variation out of
    every cut-off and hide the exposure entirely."""
    r = _p(cutoff="2026-04-30", subVariations=[_vo(status="Instructed", agreedOn="")])
    assert _pk(r)["variationsPending"] == 300_000_000


def test_the_trade_rollup_carries_the_variations_and_a_revised_commitment():
    r = _p(subVariations=[_vo()])
    t = next(x for x in r["trades"] if x["code"] == qs.HVAC)
    assert t["variations"] == 300_000_000
    assert t["revised"] == 4_300_000_000
