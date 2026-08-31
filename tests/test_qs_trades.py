"""Trades, the quality gate, and the tests that decide when a cleanroom is finished.

This company builds civil, MEP and cleanroom on the same contract, and each of those three things
fails commercially in a way a project total cannot show:

  * a job at +17% overall can be a cleanroom envelope at +31% carrying an electrical package at -4%
  * ductwork that is built, measured and genuinely there is not payable while it carries an open
    Critical non-conformance — the client's QS deducts exactly that
  * a room that is fully fitted out is not complete until it passes its classification, and a final
    account that ignores an outstanding ISO 14644-1 test is one nobody will sign

Every test below is one of those, at the point where the convenient implementation gets it wrong.
"""
import pytest

import qsurvey as qs


# ── the trade split ──────────────────────────────────────────────────────────────────────────────

def _mixed_bill():
    """One bill, three trades — the shape of every job this company runs."""
    return [
        {"id": "h", "kind": qs.HEADING, "desc": "CLEANROOM"},
        {"id": "c1", "itemNo": "C.1", "desc": "Wall panel system", "unit": "m2",
         "billedQty": 800, "rate": 2_400_000, "discipline": qs.CLEANROOM},
        {"id": "c2", "itemNo": "C.2", "desc": "Cleanroom doors", "unit": "no",
         "billedQty": 24, "rate": 38_000_000, "discipline": qs.CLEANROOM},
        {"id": "m1", "itemNo": "M.1", "desc": "AHU 12,000 m3/h", "unit": "no",
         "billedQty": 6, "rate": 620_000_000, "discipline": qs.HVAC},
        {"id": "e1", "itemNo": "E.1", "desc": "LV distribution board", "unit": "no",
         "billedQty": 4, "rate": 180_000_000, "discipline": qs.ELECTRICAL},
    ]


def test_each_trade_is_measured_against_its_own_billed_value():
    """60% of the cleanroom envelope and 60% of the electrical package are different amounts of
    money. One project percentage hides both."""
    r = qs.by_trade({"boq": _mixed_bill(), "cutoff": "2026-03-31", "measures": [
        # The cleanroom trade is TWO lines — panels AND doors. Half of both is half the trade;
        # half of one of them is not, which is the arithmetic this split exists to get right.
        {"id": "1", "boqItemId": "c1", "qty": 400, "date": "2026-03-01"},
        {"id": "2", "boqItemId": "c2", "qty": 12, "date": "2026-03-01"},
        {"id": "3", "boqItemId": "e1", "qty": 1, "date": "2026-03-01"},   # a quarter of the boards
    ]})
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.CLEANROOM]["billed"] == 800 * 2_400_000 + 24 * 38_000_000
    assert t[qs.CLEANROOM]["measured"] == 400 * 2_400_000 + 12 * 38_000_000
    assert t[qs.CLEANROOM]["pct"] == 50.0
    assert t[qs.ELECTRICAL]["pct"] == 25.0
    assert t[qs.HVAC]["pct"] == 0.0


def test_measuring_one_line_of_a_two_line_trade_is_not_half_the_trade():
    """The mistake this replaces: 400 of 800 panels is half the PANELS and a third of the cleanroom,
    because the trade also carries the doors. A per-line percentage averaged across a trade would
    report 50% here and be wrong by ₫456,000,000."""
    r = qs.by_trade({"boq": _mixed_bill(), "cutoff": "2026-03-31", "measures": [
        {"id": "1", "boqItemId": "c1", "qty": 400, "date": "2026-03-01"}]})
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.CLEANROOM]["measured"] == 400 * 2_400_000
    assert t[qs.CLEANROOM]["pct"] == 33.9


def test_a_trade_percentage_is_against_the_REVISED_trade_value():
    """A trade carrying agreed variations is bigger than its bill said. Measuring against the bill
    would report the cleanroom as further through than it is."""
    r = qs.by_trade({
        "boq": _mixed_bill(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01"}],
        "variations": [{"id": "v", "status": qs.V_AGREED, "agreedValue": 720_000_000,
                        "agreedOn": "2026-03-02", "discipline": qs.HVAC}]})
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.HVAC]["billed"] == 6 * 620_000_000
    assert t[qs.HVAC]["variations"] == 720_000_000
    assert t[qs.HVAC]["revised"] == 6 * 620_000_000 + 720_000_000
    assert t[qs.HVAC]["pct"] == round(6 * 620_000_000 / t[qs.HVAC]["revised"] * 100, 2)


def test_a_line_with_no_trade_is_reported_not_folded_into_the_first_one():
    """Putting an unallocated line into a real trade puts somebody else's money in that trade's
    margin — and the margin by trade is the whole reason this split exists."""
    bill = _mixed_bill() + [{"id": "x", "itemNo": "X.1", "desc": "Unallocated",
                             "billedQty": 1, "rate": 99_000_000}]
    r = qs.by_trade({"boq": bill, "cutoff": "2026-03-31"})
    t = {x["code"]: x for x in r["trades"]}
    assert qs.UNALLOCATED in t
    assert t[qs.UNALLOCATED]["billed"] == 99_000_000
    assert r["unallocatedLines"] == 1
    assert "Not allocated" in t[qs.UNALLOCATED]["label"]


def test_an_unknown_trade_code_becomes_unallocated_rather_than_a_new_trade():
    """A typo in an import must not silently create a twelfth trade nobody can price."""
    r = qs.by_trade({"boq": [{"id": "a", "desc": "x", "billedQty": 1, "rate": 100,
                              "discipline": "HVAV"}], "cutoff": ""})
    assert [x["code"] for x in r["trades"]] == [qs.UNALLOCATED]


def test_a_heading_belongs_to_no_trade_and_carries_no_value():
    r = qs.by_trade({"boq": _mixed_bill(), "cutoff": ""})
    assert sum(x["lines"] for x in r["trades"]) == 4      # the heading is not one of them


def test_the_valuation_carries_the_trade_split():
    v = qs.valuation({"boq": _mixed_bill(), "cutoff": "2026-03-31", "previous": 0,
                      "measures": [{"id": "1", "boqItemId": "c1", "qty": 800,
                                    "date": "2026-03-01"}]})
    t = {x["code"]: x for x in v["trades"]["trades"]}
    assert t[qs.CLEANROOM]["measured"] == 800 * 2_400_000


# ── the quality gate ─────────────────────────────────────────────────────────────────────────────

def _gate(**kw):
    ctx = {"boq": _mixed_bill(), "cutoff": "2026-03-31",
           "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01"},
                        {"id": "2", "boqItemId": "c1", "qty": 800, "date": "2026-03-01"}],
           "quality": [], "itps": []}
    ctx.update(kw)
    return qs.quality_gate(ctx)


def test_an_open_critical_ncr_puts_its_trade_at_risk():
    """The number a contractor needs before the application goes out, not after the certificate
    comes back."""
    r = _gate(quality=[{"id": "n", "refNo": "NCR-004", "type": "NCR", "status": "Open",
                        "severity": "Critical", "discipline": qs.HVAC,
                        "title": "Duct joints not sealed to spec"}])
    assert r["valueAtRisk"] == 6 * 620_000_000
    assert r["atRisk"][0]["discipline"] == qs.HVAC
    assert r["atRisk"][0]["ncrs"][0]["refNo"] == "NCR-004"


def test_a_closed_ncr_puts_nothing_at_risk():
    r = _gate(quality=[{"id": "n", "type": "NCR", "status": "Closed", "severity": "Critical",
                        "discipline": qs.HVAC}])
    assert r["valueAtRisk"] == 0


def test_a_concession_is_the_client_accepting_the_work_so_it_stays_claimable():
    """"Use as is" IS the client agreeing to take what was built. Treating a concession as at-risk
    would tell a QS to hold back money the client has already agreed to pay."""
    r = _gate(quality=[{"id": "n", "refNo": "NCR-6", "type": "NCR", "status": "Open",
                        "severity": "Critical", "discipline": qs.HVAC,
                        "disposition": "Use as is (concession)"}])
    assert r["valueAtRisk"] == 0
    # And it is still an OPEN non-conformance. Dropping it from the register showed a QS three of
    # the four open NCRs on the job with nothing saying the fourth existed.
    assert [n["refNo"] for n in r["openNcrs"]] == ["NCR-6"]
    assert r["openNcrs"][0]["concession"] is True
    assert r["openNcrs"][0]["atRisk"] is False


def test_a_minor_ncr_is_listed_but_does_not_put_value_at_risk():
    """Every trade on a live site carries minor observations. Pricing them all as at-risk would
    make the figure meaningless and it would be ignored — which is the same as not having it."""
    r = _gate(quality=[{"id": "n", "type": "NCR", "status": "Open", "severity": "Minor",
                        "discipline": qs.HVAC}])
    assert r["valueAtRisk"] == 0
    assert len(r["openNcrs"]) == 1


def test_an_ncr_on_a_trade_with_nothing_measured_risks_nothing():
    r = _gate(quality=[{"id": "n", "type": "NCR", "status": "Open", "severity": "Critical",
                        "discipline": qs.FIRE}])
    assert r["valueAtRisk"] == 0


def test_an_inspection_record_is_not_an_ncr():
    """pm_quality holds inspections, audits and tests as well. Only non-conformances gate money."""
    r = _gate(quality=[{"id": "q", "type": "Inspection", "status": "Open", "severity": "Critical",
                        "discipline": qs.HVAC}])
    assert r["valueAtRisk"] == 0
    assert r["openNcrs"] == []


# ── inspection release ───────────────────────────────────────────────────────────────────────────

def _bill_with_itp():
    b = _mixed_bill()
    for line in b:
        if line["id"] == "m1":
            line["itpRef"] = "ITP-HVAC-01"
    return b


def test_a_line_naming_an_itp_is_not_released_without_an_inspection_reference():
    r = qs.quality_gate({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01"}],
        "itps": [{"id": "i", "itpNo": "ITP-HVAC-01", "status": "Approved"}]})
    assert r["valueNotReleased"] == 6 * 620_000_000
    assert "no inspection reference" in r["unreleased"][0]["why"]


def test_released_measurement_clears_the_gate():
    r = qs.quality_gate({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01",
                      "inspectionRef": "WIR-221"}],
        "itps": [{"id": "i", "itpNo": "ITP-HVAC-01", "status": "Approved"}]})
    assert r["valueNotReleased"] == 0


def test_only_the_unreleased_SHARE_of_a_line_is_at_risk():
    """Half a line inspected is half a line at risk. Reporting the whole line would make the figure
    easy to dismiss, and a figure that gets dismissed is not a control."""
    r = qs.quality_gate({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 3, "date": "2026-03-01",
                      "inspectionRef": "WIR-221"},
                     {"id": "2", "boqItemId": "m1", "qty": 3, "date": "2026-03-02"}],
        "itps": [{"id": "i", "itpNo": "ITP-HVAC-01", "status": "Approved"}]})
    assert r["valueNotReleased"] == 3 * 620_000_000


def test_a_draft_itp_cannot_release_anything():
    """An ITP that has not been approved has not been agreed with the client, so nothing can have
    been witnessed against it — whatever the measurement record claims."""
    r = qs.quality_gate({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01",
                      "inspectionRef": "WIR-221"}],
        "itps": [{"id": "i", "itpNo": "ITP-HVAC-01", "status": "Draft"}]})
    assert r["valueNotReleased"] == 6 * 620_000_000
    assert "not approved" in r["unreleased"][0]["why"]


def test_an_itp_reference_pointing_at_nothing_is_reported():
    r = qs.quality_gate({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31",
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01"}],
        "itps": []})
    assert "not on the register" in r["unreleased"][0]["why"]


def test_a_line_naming_no_itp_is_not_gated_at_all():
    """Nobody witnesses site establishment. Gating every line would bury the ones that matter."""
    r = _gate()
    assert r["valueNotReleased"] == 0
    assert r["linesGatedByItp"] == 0


def test_the_valuation_raises_both_quality_warnings():
    v = qs.valuation({
        "boq": _bill_with_itp(), "cutoff": "2026-03-31", "previous": 0,
        "measures": [{"id": "1", "boqItemId": "m1", "qty": 6, "date": "2026-03-01"}],
        "quality": [{"id": "n", "type": "NCR", "status": "Open", "severity": "Major",
                     "discipline": qs.HVAC}],
        "itps": [{"id": "i", "itpNo": "ITP-HVAC-01", "status": "Approved"}]})
    codes = {w["code"] for w in v["warnings"]}
    assert "quality_value_at_risk" in codes
    assert "measured_without_inspection" in codes


def test_the_gate_says_whether_it_had_anything_to_look_at():
    """An empty gate and a clean gate look identical on screen. A caller that passed no registers
    must not be told the job is clean."""
    v = qs.valuation({"boq": _mixed_bill(), "cutoff": "2026-03-31", "previous": 0})
    assert v["quality"]["available"] is False
    v2 = qs.valuation({"boq": _mixed_bill(), "cutoff": "2026-03-31", "previous": 0, "quality": []})
    assert v2["quality"]["available"] is True


# ── margin by trade ──────────────────────────────────────────────────────────────────────────────

def test_a_losing_trade_inside_a_profitable_job_is_raised():
    """The report this whole split exists for. A project total is the one number that cannot show
    it, which is why nobody sees it until the subcontractor claims."""
    r = qs.cvr({"valueToDate": 1_000_000_000, "costToDate": 830_000_000,
                "valueByTrade": {qs.CLEANROOM: 700_000_000, qs.ELECTRICAL: 300_000_000},
                "costByTrade": {qs.CLEANROOM: 480_000_000, qs.ELECTRICAL: 350_000_000}})
    assert r["marginPct"] == 17.0
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.ELECTRICAL]["margin"] == -50_000_000
    assert t[qs.CLEANROOM]["margin"] == 220_000_000
    w = [x for x in r["warnings"] if x["code"] == "trade_losing_inside_a_profitable_job"]
    assert w and "Electrical" in w[0]["msg"]


def test_cost_booked_to_a_trade_with_nothing_valued_is_raised():
    r = qs.cvr({"valueToDate": 100_000_000, "costToDate": 140_000_000,
                "valueByTrade": {qs.CLEANROOM: 100_000_000},
                "costByTrade": {qs.CLEANROOM: 90_000_000, qs.FIRE: 50_000_000}})
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.FIRE]["costWithoutValue"] is True
    assert any(x["code"] == "cost_on_a_trade_with_no_value" for x in r["warnings"])


def test_unallocated_cost_is_not_spread_across_the_trades():
    """Spreading it pro-rata would put one trade's overspend in another trade's margin, and it would
    look plausible in every column."""
    r = qs.cvr({"valueToDate": 100_000_000, "costToDate": 80_000_000,
                "valueByTrade": {qs.CLEANROOM: 100_000_000},
                "costByTrade": {qs.CLEANROOM: 60_000_000, qs.UNALLOCATED: 20_000_000}})
    t = {x["code"]: x for x in r["trades"]}
    assert t[qs.CLEANROOM]["cost"] == 60_000_000
    assert t[qs.UNALLOCATED]["cost"] == 20_000_000
    assert t[qs.UNALLOCATED]["label"] == "Not allocated to a trade"


def test_the_trade_rows_put_unallocated_last():
    r = qs.cvr({"valueToDate": 1, "costToDate": 1,
                "valueByTrade": {qs.UNALLOCATED: 10, qs.HVAC: 10, qs.CIVIL: 10}})
    assert r["trades"][-1]["code"] == qs.UNALLOCATED


# ── commissioning and qualification ──────────────────────────────────────────────────────────────

def test_every_listed_test_names_a_standard_and_an_acceptance_criterion():
    """A test with no acceptance criterion is not a test, it is an opinion — and this list is what
    the register offers, so a blank here would propagate to every project."""
    for t in qs.COMMISSIONING_TESTS:
        assert t["standard"].strip(), "%s has no standard" % t["code"]
        assert len(t["criterion"].strip()) > 20, "%s has no real criterion" % t["code"]
        assert t["discipline"] in qs.DISCIPLINE_CODES, "%s: bad trade" % t["code"]


def test_the_cleanroom_set_covers_iso_14644_and_gmp_qualification():
    """The tests that actually decide whether a cleanroom is finished. If one of these is dropped
    from the catalogue, a project schedule built from it silently stops asking for it."""
    codes = {t["code"] for t in qs.COMMISSIONING_TESTS}
    for required in (qs.CT_CLASSIFICATION, qs.CT_FILTER_INTEGRITY, qs.CT_AIRFLOW,
                     qs.CT_PRESSURE, qs.CT_RECOVERY, qs.CT_IQ, qs.CT_OQ, qs.CT_PQ):
        assert required in codes
    iso = [t for t in qs.COMMISSIONING_TESTS if "14644" in t["standard"]]
    assert len(iso) >= 6, "the ISO 14644 suite is not represented"


def test_a_failed_test_blocks_the_final_account():
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "commissioning": [{"id": "t", "testCode": qs.CT_CLASSIFICATION, "status": qs.CS_FAILED,
                           "area": "Zone 2 - ISO 7"}]})
    assert r["agreed"] is False
    assert any("FAILED" in b and "Zone 2" in b for b in r["blockedBy"])


def test_an_outstanding_gating_test_blocks_the_final_account():
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "commissioning": [{"id": "t", "testCode": qs.CT_FILTER_INTEGRITY,
                           "status": qs.CS_NOT_STARTED, "area": "AHU-01",
                           "gatesFinalAccount": True}]})
    assert r["agreed"] is False
    assert any("AHU-01" in b for b in r["blockedBy"])


def test_a_test_marked_not_applicable_is_a_decision_and_does_not_block():
    """A blank and a considered "not applicable" are different facts, and the difference is what a
    GMP auditor asks about."""
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "commissioning": [{"id": "t", "testCode": qs.CT_PQ, "status": qs.CS_NA,
                           "gatesFinalAccount": True}]})
    assert r["agreed"] is True


def test_a_non_gating_test_does_not_block_the_account():
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "commissioning": [{"id": "t", "testCode": qs.CT_LIGHT_NOISE,
                           "status": qs.CS_NOT_STARTED, "gatesFinalAccount": False}]})
    assert r["agreed"] is True


def test_a_pass_with_no_acceptance_criterion_is_flagged():
    """It goes in the handover file and somebody reads it in an audit years later."""
    r = qs.commissioning({"tests": [{"id": "t", "title": "Ad-hoc check", "status": qs.CS_PASSED}]})
    assert r["rows"][0]["criterionMissing"] is True
    assert any(w["code"] == "no_acceptance_criterion" for w in r["warnings"])


def test_a_listed_test_inherits_its_standard_and_criterion():
    """The register does not make somebody retype ISO 14644-1 on every project."""
    r = qs.commissioning({"tests": [{"id": "t", "testCode": qs.CT_CLASSIFICATION,
                                     "status": qs.CS_PASSED}]})
    assert "14644-1" in r["rows"][0]["standard"]
    assert r["rows"][0]["criterionMissing"] is False


def test_an_empty_schedule_says_so_rather_than_reading_as_complete():
    r = qs.commissioning({"tests": []})
    assert r["pct"] is None
    assert any(w["code"] == "no_commissioning_schedule" for w in r["warnings"])


def test_progress_counts_passed_witnessed_and_not_applicable():
    r = qs.commissioning({"tests": [
        {"id": "1", "testCode": qs.CT_TAB, "status": qs.CS_PASSED},
        {"id": "2", "testCode": qs.CT_IQ, "status": qs.CS_WITNESSED},
        {"id": "3", "testCode": qs.CT_PQ, "status": qs.CS_NA},
        {"id": "4", "testCode": qs.CT_OQ, "status": qs.CS_IN_PROGRESS}]})
    assert r["done"] == 3
    assert r["pct"] == 75.0


def test_the_trade_list_is_internally_consistent():
    """Codes are unique, every one carries a colour the screen can use, and every one is a real
    trade this company sells — a duplicate code would silently merge two trades' money."""
    codes = [d["code"] for d in qs.DISCIPLINES]
    assert len(codes) == len(set(codes))
    assert qs.UNALLOCATED not in codes, "unallocated is a state, not a trade"
    for d in qs.DISCIPLINES:
        assert d["hex"].startswith("#") and len(d["hex"]) == 7
        assert d["labelVn"].strip(), "%s has no Vietnamese label" % d["code"]
        assert len(d["note"].strip()) > 20, "%s does not say what it covers" % d["code"]


# ── the three defects that only running it against a real bill found ─────────────────────────────

def test_a_quality_discipline_is_mapped_onto_a_trade_not_dropped():
    """pm_quality speaks its own vocabulary — Civil, Structural, Architectural, MEP, Mechanical,
    Process / Piping — written long before these trades existed. Every one of them used to fall
    through to UNALLOCATED."""
    assert qs.quality_discipline("Mechanical") == qs.HVAC
    assert qs.quality_discipline("Process / Piping") == qs.CLEAN_UTILITIES
    assert qs.quality_discipline("Structural") == qs.CIVIL
    assert qs.quality_discipline("Electrical") == qs.ELECTRICAL
    # Our own codes pass through, so a register that starts using them needs no migration.
    assert qs.quality_discipline(qs.CLEANROOM) == qs.CLEANROOM


def test_a_discipline_naming_more_than_one_trade_is_not_guessed():
    """"MEP" is mechanical AND electrical AND plumbing. Picking one would put a money figure
    somebody acts on against a trade nobody chose."""
    assert qs.quality_discipline("MEP") == qs.UNATTRIBUTED
    assert qs.quality_discipline("General / Multi") == qs.UNATTRIBUTED
    assert qs.UNATTRIBUTED != qs.UNALLOCATED


def test_an_unattributable_ncr_does_not_match_the_un_traded_bill_lines():
    """The bug this pins, exactly as it happened: a Critical NCR logged against "MEP" fell to
    UNALLOCATED, the bill lines had also fallen to UNALLOCATED, the two matched, and the gate
    reported the WHOLE JOB at risk with total confidence. Two absences are not the same absence."""
    bill = [{"id": "a", "itemNo": "A.1", "desc": "Untraded work", "billedQty": 1,
             "rate": 5_000_000_000}]
    r = qs.quality_gate({
        "boq": bill, "cutoff": "2026-03-31",
        "measures": [{"id": "m", "boqItemId": "a", "qty": 1, "date": "2026-03-01"}],
        "quality": [{"id": "n", "refNo": "NCR-1", "type": "NCR", "status": "Open",
                     "severity": "Critical", "discipline": "MEP"}]})
    assert r["valueAtRisk"] == 0, "an unattributable NCR must not risk the un-traded lines"
    assert [n["refNo"] for n in r["unattributedNcrs"]] == ["NCR-1"]


def test_an_ncr_that_maps_still_matches_its_trade():
    """The other half: mapping must actually work, or the gate quietly stops finding anything."""
    bill = [{"id": "d", "itemNo": "D.1", "desc": "Ductwork", "billedQty": 100, "rate": 1_000_000,
             "discipline": qs.HVAC}]
    r = qs.quality_gate({
        "boq": bill, "cutoff": "2026-03-31",
        "measures": [{"id": "m", "boqItemId": "d", "qty": 100, "date": "2026-03-01"}],
        "quality": [{"id": "n", "refNo": "NCR-2", "type": "NCR", "status": "Open",
                     "severity": "Critical", "discipline": "Mechanical"}]})
    assert r["valueAtRisk"] == 100_000_000
    assert r["atRisk"][0]["discipline"] == qs.HVAC


def test_a_failed_test_blocks_the_final_account_exactly_once():
    """The blocker list is what a QS works through to close a job. A failed test appeared in it
    twice — once as failed and once as outstanding — which is noise in the one place noise costs."""
    r = qs.final_account({
        "contractSum": 1_000_000_000,
        "commissioning": [{"id": "t", "testCode": qs.CT_DUCT_LEAKAGE, "status": qs.CS_FAILED,
                           "area": "Zone 2 riser", "gatesFinalAccount": True}]})
    hits = [b for b in r["blockedBy"] if "Zone 2 riser" in b]
    assert len(hits) == 1, hits
    assert "FAILED" in hits[0]


def test_a_trade_can_be_named_the_way_a_quantity_surveyor_types_it():
    """A bill comes out of Excel typed by a person. They write "HVAC" and "Cleanroom envelope", not
    "hvac" and "cleanroom", and an import that rejected those would be an import nobody uses."""
    assert qs.discipline_code("HVAC") == qs.HVAC
    assert qs.discipline_code("hvac") == qs.HVAC
    assert qs.discipline_code("Cleanroom envelope") == qs.CLEANROOM
    assert qs.discipline_code("  Electrical  ") == qs.ELECTRICAL
    # The Vietnamese name too — this company's bills are written in both.
    assert qs.discipline_code("Vỏ phòng sạch") == qs.CLEANROOM


def test_an_unrecognised_trade_is_None_not_a_default():
    """None means "that is not a trade" and the import rejects the row by name. Defaulting to
    unallocated would file a typo in the same place as a blank while looking allocated."""
    assert qs.discipline_code("HVAV") is None
    assert qs.discipline_code("Mechanical") is None, (
        "the pm_quality vocabulary is mapped by quality_discipline, not accepted on a bill")
    assert qs.discipline_code("") == ""
    assert qs.discipline_code(None) == ""
