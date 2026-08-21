"""This factory's units measured against what the European AHU industry recommends.

Eurovent 6/18-2022 is a recommendation, not an acceptance criterion, so the sharpest tests here are
about what this module REFUSES to conclude: it never turns a recommendation into a refusal, and it
never resolves the one ambiguity that actually matters — whether a declared casing class was
established on a real unit or on a model box.
"""
import ahu_eurovent as E
import ahu_route as R


def _row(rows, label_starts):
    return next(r for r in rows if r["label"].startswith(label_starts))


# ── the class ordering ───────────────────────────────────────────────────────────────────────────

def test_class_one_is_the_best_for_every_casing_indicator():
    """D1 is stiffer than D2, L1 leaks less than L2, and TB1 (kb 0.75-1) bridges less heat than TB5
    (kb < 0.3). Getting TB backwards would report the worst units as the best."""
    assert E._rank("D1", "D") == 1 and E._rank("D3", "D") == 3
    assert E._rank("TB1", "TB") == 1 and E._rank("TB5", "TB") == 5
    # And the underlying table agrees: a higher kb is better, so TB1 holds the highest figure.
    assert R.EN1886_BRIDGING["TB1"] > R.EN1886_BRIDGING["TB5"]


def test_a_class_that_is_not_a_class_is_not_forced_into_one():
    for junk in ("", None, "good", "D", "DX", "TB-", 5):
        assert E._rank(junk, "D") is None or junk == 5


def test_the_tb_prefix_is_not_confused_with_the_t_prefix():
    """'TB3' starts with 'T'. Reading it as a T class would compare a bridging figure against a
    transmittance minimum and report a confident wrong answer."""
    assert E._rank("TB3", "T") is None


# ── the real-unit / model-box distinction ────────────────────────────────────────────────────────

def test_a_class_with_no_basis_is_reported_as_undetermined_not_assumed():
    """THE test. Eurovent states its strength minimum as D2 (R). A D2 established on a model box is
    a different claim, and guessing either way puts a conclusion on a record that has none."""
    rows = E.assess_casing({"classD": "D2"})
    d = _row(rows, "Casing mechanical strength")
    assert d["status"] == E.UNDETERMINED
    assert "real unit (R) or a model box (M)" in d["why"]


def test_a_real_unit_basis_meets_the_recommendation():
    d = _row(E.assess_casing({"classD": "D2 (R)"}), "Casing mechanical strength")
    assert d["status"] == E.MEETS and d["basis"] == E.REAL


def test_a_model_box_basis_does_not_satisfy_a_real_unit_minimum():
    d = _row(E.assess_casing({"classD": "D2 (M)"}), "Casing mechanical strength")
    assert d["status"] == E.BELOW
    assert "model box" in d["why"]


def test_a_transmittance_minimum_is_stated_on_a_model_box_basis():
    """T and TB are model-box figures by nature. Demanding (R) for them would be wrong in the other
    direction, and this module's KPI half already refuses to report an ACHIEVED T for the same
    reason: nothing on this line measures one."""
    t = _row(E.assess_casing({"classT": "T3 (M)"}), "Thermal transmittance")
    assert t["status"] == E.MEETS


def test_thermal_bridging_names_no_basis_so_a_bare_class_is_enough():
    tb = _row(E.assess_casing({"classTB": "TB3"}), "Thermal bridging")
    assert tb["status"] == E.MEETS


# ── the verdicts ─────────────────────────────────────────────────────────────────────────────────

def test_a_class_worse_than_the_minimum_is_reported_as_below():
    d = _row(E.assess_casing({"classD": "D3 (R)"}), "Casing mechanical strength")
    assert d["status"] == E.BELOW and "below the recommended minimum" in d["why"]


def test_a_class_better_than_the_minimum_meets_it():
    d = _row(E.assess_casing({"classD": "D1 (R)"}), "Casing mechanical strength")
    assert d["status"] == E.MEETS


def test_an_undeclared_class_says_so_rather_than_passing_or_failing():
    d = _row(E.assess_casing({}), "Casing mechanical strength")
    assert d["status"] == E.NOT_DECLARED


def test_every_recommendation_carries_the_citation_it_came_from():
    """A recommendation with no source is an opinion. Somebody has to be able to check it."""
    for row in E.assess_casing({"classD": "D2 (R)"}):
        assert "Eurovent 6/18" in row["where"]
        assert row["says"]


def test_assessing_a_unit_that_declares_nothing_does_not_raise():
    assert len(E.assess_casing(None)) == len(E.CASING_MINIMUMS)


# ── the document list ────────────────────────────────────────────────────────────────────────────

def test_the_sop_dossier_is_missing_the_documents_eurovent_names():
    """Reported, not added. Whether the SOP adopts them is the SOP owner's decision, and quietly
    inserting a gate criterion is the mistake this module was written to avoid."""
    gaps = E.document_gaps(R.DOSSIER)
    labels = " | ".join(g["label"] for g in gaps)
    assert "Spare parts list" in labels
    assert "name plate" in labels
    for g in gaps:
        assert g["where"].startswith("Eurovent 6/18 section 12.2")


def test_a_document_the_sop_does_cover_is_not_reported_as_a_gap():
    """The O&M manual is on the SOP's list. Reporting it would make the real gaps unreadable."""
    labels = " | ".join(g["label"] for g in E.document_gaps(R.DOSSIER))
    assert "installation, commissioning and maintenance" not in labels


def test_a_dossier_covering_everything_reports_no_gaps():
    full = [{"k": item["matches"][0], "label": item["label"]} for item in E.DELIVERED_WITH_UNIT]
    assert E.document_gaps(full) == []


def test_an_empty_dossier_reports_every_item_as_a_gap():
    assert len(E.document_gaps([])) == len(E.DELIVERED_WITH_UNIT)
    assert len(E.document_gaps(None)) == len(E.DELIVERED_WITH_UNIT)


# ── the obsolete filter classification ───────────────────────────────────────────────────────────

def test_the_module_still_speaks_en_779_and_the_replacement_table_is_carried():
    """`ahu_route.EN1886_BYPASS` holds F8/F9 — EN 779 classes, withdrawn and replaced by
    EN ISO 16890 in 2018. That is what the SOP states, so it is not rewritten here; the current
    classification is carried alongside so the difference is visible rather than assumed away."""
    assert set(R.EN1886_BYPASS) == {"F8", "F9"}
    assert any("ISO ePM1 80%" in f for f, _ in E.ISO16890_BYPASS_MAX_PCT)
    assert dict(E.ISO16890_BYPASS_MAX_PCT)["ISO ePM1 80% - 95%"] == 0.5


def test_the_summary_holds_together():
    s = E.summary({"classD": "D2 (R)", "classL": "L2 (R)", "classT": "T3 (M)", "classTB": "TB3"},
                  R.DOSSIER)
    assert s["casingBelow"] == []
    assert s["citation"].startswith("Eurovent 6/18 - 2022")
    assert len(s["directives"]) == 5 and len(s["beforeDelivery"]) == 5
