"""The two costing models, and the quotation they produce.

Four failures matter more than any other arithmetic here, and each has a price attached.

Vietnamese import tax cascades — duty on CIF, SCT on CIF plus duty, VAT on all three. Assessing
them all on CIF understates the tax, and the gap grows with the duty rate.

Import VAT is recoverable. A landed cost carrying 10% VAT prices the company out of its own
market on every quotation it touches.

An FTA rate is a fact about a certificate, not about the goods. Claiming 0% with no Form E in the
file is a customs finding, not a saving.

And a production line switched off must leave the quotation entirely. A zero line in a tender
document reads to a customer as "we forgot to price this".
"""
import pytest

import tender as t


A = t.assumptions()


# ── assumptions ──────────────────────────────────────────────────────────────────────────────────

def test_a_missing_assumption_falls_back_to_its_default_rather_than_zero():
    """A zero FX rate would price every imported item at nothing and the quotation would still
    add up, which is the worst possible way for this to fail."""
    a = t.assumptions({"fxUsd": ""})
    assert a["fxUsd"] == 25500
    assert t.assumptions(None)["outputVatPct"] == 10.0


def test_a_stored_assumption_wins_over_the_default():
    assert t.assumptions({"fxUsd": 26100})["fxUsd"] == 26100


def test_a_rate_field_holds_a_percentage_and_only_a_percentage():
    """This was once written to accept either a fraction or a percentage, treating anything under
    1 as already a fraction. That rule read 0.3% marine insurance as 30% of cargo value and a
    0.5% bank charge as half the revenue. Sub-1 rates are the COMMON case here, so the ambiguity
    is removed rather than guessed at."""
    assert t._frac(5) == pytest.approx(0.05)
    assert t._frac(0.5) == pytest.approx(0.005)      # half a percent, not half
    assert t._frac(0.3) == pytest.approx(0.003)
    assert t._frac(0) == 0


# ── 1. the customs chain ─────────────────────────────────────────────────────────────────────────

def _imp(**kw):
    base = {"id": "i1", "itemCode": "IMP-001", "desc": "Pump", "unit": "PCS", "qty": 2,
            "exwUnit": 8500, "currency": "USD", "hsCode": "8413.70"}
    base.update(kw)
    return base


def test_the_international_leg_builds_cif_before_any_tax():
    # 2 x 8500 = 17,000 EXW; legs 1% + 0.5% + 5% + 0.3% = 6.8% -> 18,156 CIF USD.
    r = t.landed_line(_imp(), A)
    assert r["exwTotal"] == 17000
    assert r["cifFx"] == pytest.approx(18156.0)
    assert r["cif"] == t.vnd(18156.0 * 25500)


def test_duty_sct_and_vat_cascade_rather_than_all_sitting_on_cif():
    """The whole point. On CIF 1,000,000 with 10% duty and 10% SCT:
       duty     = 100,000                  (on CIF)
       SCT      = 110,000                  (on CIF + duty, NOT on CIF)
       VAT      = 121,000                  (on CIF + duty + SCT)
    Flat-rating all three on CIF would give 100,000 / 100,000 / 100,000 and understate by 31,000."""
    r = t.landed_line(_imp(qty=1, exwUnit=1000000 / 25500, inlandPct=0, originPct=0,
                           freightPct=0, insurancePct=0, mfnDutyPct=10, sctPct=10, vatPct=10), A)
    assert r["cif"] == 1_000_000
    assert r["duty"] == 100_000
    assert r["sct"] == 110_000
    assert r["vatRecoverable"] == 121_000


def test_import_vat_is_reported_but_never_lands_in_the_cost():
    """It is a receivable from the state. A landed cost carrying it prices the company out."""
    r = t.landed_line(_imp(qty=1, exwUnit=1000000 / 25500, inlandPct=0, originPct=0, freightPct=0,
                           insurancePct=0, mfnDutyPct=0, customsPct=0, handlingPct=0,
                           localTransPct=0, bankPct=0, inspectPct=0, vatPct=10), A)
    assert r["vatRecoverable"] == 100_000
    assert r["landed"] == 1_000_000          # the VAT is NOT in here


def test_local_charges_are_assessed_on_cif_and_do_land_in_the_cost():
    r = t.landed_line(_imp(qty=1, exwUnit=1000000 / 25500, inlandPct=0, originPct=0, freightPct=0,
                           insurancePct=0, mfnDutyPct=0, customsPct=1, handlingPct=1,
                           localTransPct=2, bankPct=0, inspectPct=0), A)
    assert r["chargesTotal"] == 40_000       # 1% + 1% + 2% of 1,000,000
    assert r["landed"] == 1_040_000


# ── the certificate, not the hope ────────────────────────────────────────────────────────────────

def test_an_fta_rate_applies_only_when_a_certificate_of_origin_is_named():
    r = t.landed_line(_imp(coForm="Form EUR.1 (EVFTA)", ftaDutyPct=0, mfnDutyPct=20), A)
    assert r["dutyRate"] == 0
    assert "FTA" in r["dutyBasis"]


def test_without_a_certificate_the_mfn_rate_applies_whatever_was_typed_in_the_fta_column():
    """Claiming 0% with no Form E in the file is a customs finding, not a saving."""
    r = t.landed_line(_imp(coForm="", ftaDutyPct=0, mfnDutyPct=20), A)
    assert r["dutyRate"] == 20
    assert r["dutyBasis"] == "MFN"


def test_the_word_none_in_the_certificate_field_is_not_a_certificate():
    for word in ("None", "none", "N/A", "-"):
        r = t.landed_line(_imp(coForm=word, ftaDutyPct=0, mfnDutyPct=20), A)
        assert r["dutyRate"] == 20, word


def test_an_unpriced_hs_code_falls_back_to_the_default_duty_and_says_so():
    r = t.landed_line(_imp(mfnDutyPct=None), A)
    assert r["dutyRate"] == 5
    assert "default" in r["dutyBasis"]


# ── currency ─────────────────────────────────────────────────────────────────────────────────────

def test_a_supplier_invoicing_in_euro_converts_at_the_euro_rate():
    usd = t.landed_line(_imp(qty=1, exwUnit=1000, currency="USD"), A)
    eur = t.landed_line(_imp(qty=1, exwUnit=1000, currency="EUR"), A)
    assert eur["fx"] == 27800 and usd["fx"] == 25500
    assert eur["cif"] > usd["cif"]


def test_a_rate_typed_on_the_line_overrides_the_master_assumption():
    r = t.landed_line(_imp(fx=26100), A)
    assert r["fx"] == 26100


# ── local Vietnam ────────────────────────────────────────────────────────────────────────────────

def test_a_local_line_carries_transport_and_handling_but_not_its_recoverable_vat():
    r = t.local_line({"id": "l1", "itemCode": "LOC-001", "qty": 1, "unitPrice": 95_000_000,
                      "vatPct": 8, "transPct": 5, "handlingPct": 1}, A)
    assert r["netExVat"] == 95_000_000
    assert r["vatRecoverable"] == 7_600_000
    assert r["transport"] == 4_750_000 and r["handling"] == 950_000
    assert r["landed"] == 100_700_000       # net + transport + handling, no VAT


# ── the cost master ──────────────────────────────────────────────────────────────────────────────

def test_the_cost_master_consolidates_both_sources_and_keeps_them_apart_in_the_totals():
    m = t.cost_master([_imp()], [{"id": "l1", "itemCode": "LOC-001", "qty": 1,
                                  "unitPrice": 10_000_000}], A)
    assert len(m["rows"]) == 2
    assert m["landedTotal"] == m["importTotal"] + m["localTotal"]
    assert m["localTotal"] == 10_000_000


def test_the_same_item_code_bought_twice_two_ways_is_surfaced_rather_than_silently_picked():
    m = t.cost_master([_imp(itemCode="X-1")], [{"id": "l1", "itemCode": "x-1", "qty": 1,
                                                "unitPrice": 1}], A)
    assert m["duplicateCodes"] == ["x-1"] or m["duplicateCodes"] == ["X-1"]


# ── 2. EPC ───────────────────────────────────────────────────────────────────────────────────────

def _bom():
    return [
        {"id": "b1", "costCentre": "CIV", "code": "C-001", "descEn": "Slab", "unit": "m2",
         "qty": 1000, "unitCostUsd": 100},
        {"id": "b2", "costCentre": "CLR", "code": "R-001", "descEn": "Panels", "unit": "m2",
         "qty": 500, "unitCostUsd": 200},
        {"id": "b3", "costCentre": "OSD", "code": "O-001", "descEn": "Tablet press", "unit": "set",
         "qty": 2, "unitCostUsd": 150000},
    ]


def test_each_cost_centre_carries_its_own_markup_because_a_slab_and_a_cleanroom_do_not_earn_alike():
    r = t.bom_rollup(_bom(), A)
    by = {c["costCentre"]: c for c in r["centres"]}
    assert by["CIV"]["markupPct"] == pytest.approx(12, abs=0.01)
    assert by["CLR"]["markupPct"] == pytest.approx(15, abs=0.01)
    assert by["OSD"]["markupPct"] == pytest.approx(20, abs=0.01)


def test_a_line_can_override_its_centres_default_markup():
    r = t.bom_rollup([{"id": "b", "costCentre": "CIV", "qty": 1, "unitCostUsd": 100,
                       "markupPct": 30}], A)
    assert r["centres"][0]["markupPct"] == pytest.approx(30, abs=0.01)


def test_switching_a_production_line_off_removes_it_from_the_quotation_entirely():
    """Not zeroed — absent. A zero line in a tender reads as 'we forgot to price this'."""
    on = t.bom_rollup(_bom(), A)
    off = t.bom_rollup(_bom(), A, {"OSD": {"include": False}})
    assert "OSD" in [c["costCentre"] for c in on["centres"]]
    assert "OSD" not in [c["costCentre"] for c in off["centres"]]
    assert off["excludedCentres"] == ["OSD"]
    assert off["costUsd"] < on["costUsd"]


def test_the_permanent_plant_cannot_be_switched_off_only_the_production_lines():
    off = t.bom_rollup(_bom(), A, {"CIV": {"include": False}})
    assert "CIV" in [c["costCentre"] for c in off["centres"]]


def test_capacity_scale_multiplies_quantity_not_unit_price():
    half = t.bom_rollup(_bom(), A, {"OSD": {"scale": 0.5}})
    osd = [c for c in half["centres"] if c["costCentre"] == "OSD"][0]
    line = [l for l in half["lines"] if l["costCentre"] == "OSD"][0]
    assert line["qty"] == 1                       # half of 2 sets
    assert line["unitCostUsd"] == 150000          # the price of a press does not halve
    assert osd["costUsd"] == 150000


def test_the_rollup_is_ordered_the_way_the_plant_is_built_not_alphabetically():
    r = t.bom_rollup(_bom(), A)
    assert [c["costCentre"] for c in r["centres"]] == ["CIV", "CLR", "OSD"]


# ── 3. the quotation ─────────────────────────────────────────────────────────────────────────────

def _trading_tender(**kw):
    d = {"id": "T1", "costingType": t.TRADING, "quoteNo": "QT-2026-001", "client": "ABC Co",
         "clientTaxCode": "0123456789", "issueDate": "2026-08-20", "validUntil": "2026-09-19"}
    d.update(kw); return d


def test_a_trading_quotation_prices_every_cost_master_line_at_the_default_markup():
    m = t.cost_master([_imp()], [], A)
    q = t.quotation(_trading_tender(), master=m)
    assert q["lineCount"] == 1
    line = q["lines"][0]
    assert line["unitSell"] == t.vnd(line["unitCost"] * 1.25)
    assert q["gross"] == q["net"] + q["vat"]


def test_a_line_can_be_excluded_from_the_quotation_without_being_deleted_from_the_costing():
    m = t.cost_master([_imp(id="i1"), _imp(id="i2", itemCode="IMP-002")], [], A)
    q = t.quotation(_trading_tender(), master=m, overrides=[{"srcId": "i2", "exclude": True}])
    assert q["lineCount"] == 1


def test_the_effective_markup_is_reported_after_line_by_line_discounting():
    m = t.cost_master([_imp(id="i1"), _imp(id="i2", itemCode="IMP-002")], [], A)
    q = t.quotation(_trading_tender(), master=m,
                    overrides=[{"srcId": "i1", "markupPct": 10}, {"srcId": "i2", "markupPct": 40}])
    # Neither 10 nor 40 — the blended truth, weighted by value.
    assert 10 < q["effectiveMarkupPct"] < 40
    assert q["grossMarginPct"] == pytest.approx(
        (q["net"] - q["cogs"]) / q["net"] * 100, abs=0.01)


def test_an_epc_quotation_shows_one_line_per_cost_centre_not_nine_hundred_bolts():
    r = t.bom_rollup(_bom(), A)
    q = t.quotation({"id": "E1", "costingType": t.EPC}, rollup=r)
    assert q["lineCount"] == 3
    assert {l["itemCode"] for l in q["lines"]} == {"CIV", "CLR", "OSD"}
    assert q["net"] == r["sellVnd"]


def test_the_customers_copy_of_the_document_carries_no_cost_and_no_markup():
    """The single most expensive thing that can go out in a PDF."""
    m = t.cost_master([_imp()], [], A)
    q = t.quotation(_trading_tender(), master=m)
    doc = t.document(_trading_tender(), q)
    for line in doc["lines"]:
        assert "unitCost" not in line
        assert "cogs" not in line
        assert "markupPct" not in line
    assert doc["totals"]["net"] == q["net"]


def est_doc(**kw):
    """A finished document from a trading tender, for the letter-shape tests."""
    company = kw.pop("company", None)
    td = _trading_tender(**kw)
    m = t.cost_master([_imp()], [], A)
    return t.document(td, t.quotation(td, master=m), company)


# ── 4. P&L ───────────────────────────────────────────────────────────────────────────────────────

def test_the_pnl_runs_revenue_through_to_net_profit():
    m = t.cost_master([_imp()], [], A)
    td = _trading_tender()
    q = t.quotation(td, master=m)
    p = t.pnl(q, td)
    assert p["revenue"] == q["net"]
    assert p["grossProfit"] == q["net"] - q["cogs"]
    assert p["ebit"] == p["grossProfit"] + p["opexTotal"]
    assert p["netProfit"] == p["ebit"] + p["cit"]
    assert p["cit"] < 0


def test_a_loss_making_tender_does_not_generate_a_tax_credit():
    td = _trading_tender(assump={"markupPct": 0, "adminLump": 500_000_000})
    m = t.cost_master([_imp()], [], A)
    q = t.quotation(td, master=m)
    p = t.pnl(q, td)
    assert p["ebit"] < 0
    assert p["cit"] == 0


# ── 5. the gate before a quotation may be sent ───────────────────────────────────────────────────

def test_a_quotation_with_no_validity_date_cannot_be_issued():
    td = _trading_tender(validUntil="")
    m = t.cost_master([_imp()], [], A)
    chk = t.issue_check(td, t.quotation(td, master=m))
    assert chk["canIssue"] is False
    assert "Valid until" in chk["missing"]


def test_a_complete_quotation_can_be_issued():
    td = _trading_tender()
    m = t.cost_master([_imp()], [], A)
    assert t.issue_check(td, t.quotation(td, master=m))["canIssue"] is True


def test_a_thin_margin_is_a_warning_not_a_block_because_it_may_be_the_right_decision():
    td = _trading_tender(assump={"markupPct": 2})
    m = t.cost_master([_imp()], [], A)
    q = t.quotation(td, master=m)
    chk = t.issue_check(td, q)
    assert chk["canIssue"] is True
    assert any("margin" in w.lower() for w in chk["warnings"])


def test_a_line_priced_with_no_cost_behind_it_is_flagged():
    td = _trading_tender()
    m = t.cost_master([], [{"id": "l1", "itemCode": "FREE", "qty": 1, "unitPrice": 0}], A)
    chk = t.issue_check(td, t.quotation(td, master=m))
    assert any("no cost behind it" in w for w in chk["warnings"])


def test_an_empty_quotation_cannot_be_issued():
    td = _trading_tender()
    chk = t.issue_check(td, t.quotation(td, master=t.cost_master([], [], A)))
    assert chk["canIssue"] is False


def test_the_document_falls_back_to_the_standard_terms_when_none_were_written():
    doc = t.document(_trading_tender(), t.quotation(_trading_tender(), master=t.cost_master([], [], A)))
    assert len(doc["terms"]) == len(t.TERMS_DEFAULT)
    assert doc["terms"][0]["label"] == "Currency"


# ── the letter, not a data table ─────────────────────────────────────────────────────────────────

def test_the_document_is_a_letter_with_a_place_a_date_and_a_reference():
    doc = est_doc()
    assert doc["placeDate"].startswith("Ho Chi Minh City, ")
    assert doc["quoteNo"] == "QT-2026-001"
    assert doc["subject"].startswith("Sales Quotation No.")


def test_a_letter_dates_itself_in_words_not_in_iso():
    """\"valid until 2026-09-19\" mid-sentence reads as a database field, which is what it is and
    what the customer must not see."""
    doc = est_doc(validUntil="2026-09-19")
    assert "19 September 2026" in doc["termsParagraph"]
    assert "2026-09-19" not in doc["termsParagraph"]


def test_an_unconfigured_deployment_still_produces_a_real_letterhead():
    """A quotation with an empty company block is not on anybody's letterhead."""
    doc = est_doc()
    assert doc["company"]["name"] == "HUMILEY ENGINEERING & SOLUTIONS"
    assert doc["company"]["address"]
    assert "www.humiley.com" in doc["company"]["contact"]


def test_configured_company_settings_win_over_the_fallback():
    doc = est_doc(company={"name": "Humiley Trading JSC", "address": "Somewhere else",
                           "website": "w", "email": "e", "phone": "p"})
    assert doc["company"]["name"] == "HUMILEY TRADING JSC"
    assert doc["company"]["contact"] == "w   ·   e   ·   p"


def test_the_terms_read_as_prose_in_a_fixed_order():
    doc = est_doc(incoterm="CIF Ho Chi Minh City", leadTime="10 weeks",
                  paymentTerms="30% / 70%", warranty="24 months")
    t = doc["termsParagraph"]
    assert t.index("CIF Ho Chi Minh City") < t.index("10 weeks") < t.index("30% / 70%") < t.index("24 months")
    assert t.endswith("All prices are in Vietnamese Dong (VND).")


def test_a_hand_written_terms_paragraph_replaces_the_assembled_one_entirely():
    doc = est_doc(termsParagraph="Net 30. Nothing else applies.")
    assert doc["termsParagraph"] == "Net 30. Nothing else applies."


# ── the cost of DELIVERING the goods, not just buying them ───────────────────────────────────────

def test_project_fees_are_priced_off_the_goods_value_not_off_the_selling_price():
    """A fee that moves when the mark-up moves is not a fee, it is more mark-up."""
    f = t.project_fees({"assump": {"pmFeePct": 5}}, 1_000_000_000)
    assert f["total"] == 50_000_000
    assert f["lines"][0]["base"] == 1_000_000_000


def test_a_fee_can_be_a_percentage_a_lump_or_both():
    f = t.project_fees({"assump": {"pmFeePct": 5, "pmFeeLump": 20_000_000}}, 1_000_000_000)
    assert f["lines"][0]["amount"] == 70_000_000


def test_every_project_fee_defaults_to_zero_so_no_existing_tender_reprices():
    assert t.project_fees({}, 1_000_000_000)["total"] == 0


def test_a_fee_left_at_zero_is_omitted_rather_than_listed_at_nil():
    """Ten fees all reading zero teaches a reader to skip the block, which is the last thing it
    should teach them."""
    f = t.project_fees({"assump": {"commissioningPct": 2}}, 1_000_000_000)
    assert [l["label"] for l in f["lines"]] == ["Testing & commissioning"]


def test_delivery_costs_sit_in_cogs_so_they_cannot_flatter_the_gross_margin():
    """Below the gross-profit line they would hide every job that is only profitable if nobody
    installs it."""
    m = t.cost_master([_imp()], [], A)
    plain = _trading_tender()
    withfee = _trading_tender(assump={"pmFeePct": 5, "supervisionPct": 3})
    q = t.quotation(plain, master=m)
    p0, p1 = t.pnl(q, plain), t.pnl(t.quotation(withfee, master=m), withfee)
    assert p1["projectFeesTotal"] < 0
    assert p1["cogs"] < p0["cogs"]                      # more cost, so more negative
    assert p1["grossMarginPct"] < p0["grossMarginPct"]  # and the gross margin feels it
    assert p1["goodsCost"] == p0["goodsCost"]           # the goods themselves did not change


def test_the_pnl_still_reconciles_with_fees_in_it():
    td = _trading_tender(assump={"pmFeePct": 5, "contingencyPct": 2})
    m = t.cost_master([_imp()], [], A)
    q = t.quotation(td, master=m)
    p = t.pnl(q, td)
    assert p["grossProfit"] == p["revenue"] + p["cogs"]        # cogs is negative
    assert p["ebit"] == p["grossProfit"] + p["opexTotal"]
    assert p["netProfit"] == p["ebit"] + p["cit"]


# ── conditions: default, but editable and extensible ─────────────────────────────────────────────

def test_the_conditions_default_to_the_standard_set_filled_in_from_the_tender():
    c = t.conditions(_trading_tender(leadTime="6 to 8 weeks", paymentTerms="50/50"))
    labels = [x["label"] for x in c]
    assert labels[:3] == ["Validity", "Delivery", "Payment"]
    assert "6 to 8 weeks" in c[1]["text"]
    assert t.is_default_conditions(_trading_tender()) is True


def test_a_condition_with_nothing_to_say_is_left_out_rather_than_printed_blank():
    """'Payment terms are .' on a quotation is worse than no sentence about payment."""
    c = t.conditions(_trading_tender())          # no leadTime, no paymentTerms, no warranty
    assert [x["key"] for x in c] == ["validity", "scope", "currency"]


def test_a_stored_list_replaces_the_defaults_outright():
    """Somebody edited the wording or removed a clause; the defaults must not creep back in."""
    td = _trading_tender(conditions=[{"label": "Retention", "text": "5% retained for 12 months."}])
    c = t.conditions(td)
    assert len(c) == 1 and c[0]["label"] == "Retention"
    assert t.is_default_conditions(td) is False
    assert t.document(td, t.quotation(td, master=t.cost_master([], [], A)))["termsParagraph"] \
        == "5% retained for 12 months."


def test_conditions_can_be_added_to_not_only_edited():
    td = _trading_tender(conditions=t.default_conditions(_trading_tender())
                         + [{"label": "Site access", "text": "Continuous site access assumed."}])
    c = t.conditions(td)
    assert c[-1]["label"] == "Site access"
    assert "Continuous site access assumed." in t.terms_paragraph(td)


def test_an_empty_or_malformed_stored_list_falls_back_to_the_defaults():
    for bad in ([], [{}], [{"text": "  "}], "not a list", None):
        assert t.conditions(_trading_tender(conditions=bad))[0]["key"] == "validity"
