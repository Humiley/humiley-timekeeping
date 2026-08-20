"""Gate exit criteria — the checks that stop a unit moving before it is ready.

A gate that passes when a criterion could not be evaluated is worse than no gate: it produces a
signed record saying the unit was checked. These tests pin the refusals, and in particular the two
failure shapes that hide longest — a criterion nobody implemented, and a lookup that raised.

The context is built by hand rather than through the API so each predicate can be cornered on its
own. The API path is covered by tests/test_ahu_api.py.
"""
import pytest

import ahu
import ahu_route as R


def ctx(unit=None, order=None, **rest):
    base = {"unit": unit or {"id": "U1", "family": "modular", "pin": "PIN-001"},
            "order": order or {}, "steps": [], "bom": [], "docs": [], "trace": [],
            "ncr": [], "dispatch": []}
    base.update(rest)
    return base


# ── every criterion the process names has an implementation ──────────────────────────────────────

def test_every_gate_criterion_is_implemented():
    """If ahu_route names a criterion that ahu.py does not implement, the gate silently checks one
    fewer thing than it claims to."""
    named = set()
    for s in R.STAGES:
        named |= set(s["requires"])
    assert named <= set(ahu.PREDICATES), named - set(ahu.PREDICATES)


def test_an_unimplemented_criterion_blocks_rather_than_passes(monkeypatch):
    """The important direction: unknown means refuse, not allow."""
    monkeypatch.setitem(ahu.PREDICATES, "pin_registered", None)
    monkeypatch.delitem(ahu.PREDICATES, "pin_registered")
    blockers = ahu.gate_blockers("G1", ctx())
    assert any("not implemented" in b for b in blockers), blockers


def test_a_criterion_that_raises_blocks_rather_than_passes(monkeypatch):
    def boom(_c):
        raise RuntimeError("database went away")
    monkeypatch.setitem(ahu.PREDICATES, "pin_registered", boom)
    blockers = ahu.gate_blockers("G1", ctx())
    assert any("could not be checked" in b for b in blockers), blockers


def test_an_unknown_gate_is_refused():
    assert ahu.gate_blockers("G9", ctx())


# ── G1: order acceptance ─────────────────────────────────────────────────────────────────────────

def test_g1_refuses_a_unit_with_no_order():
    assert any("not linked to a customer order" in b for b in ahu.gate_blockers("G1", ctx()))


def test_g1_refuses_an_unsigned_contract_review():
    c = ctx(order={"id": "O1", "poNumber": "PO-99", "scheduleBaselined": True})
    assert any("AHU-FM-101" in b for b in ahu.gate_blockers("G1", c))


def test_g1_refuses_a_unit_with_no_pin():
    c = ctx(unit={"id": "U1", "family": "modular"},
            order={"contractReviewSigned": True, "scheduleBaselined": True})
    assert any("Production Identification Number" in b for b in ahu.gate_blockers("G1", c))


def test_g1_passes_a_complete_order():
    c = ctx(order={"contractReviewSigned": True, "scheduleBaselined": True})
    assert ahu.gate_blockers("G1", c) == []


def test_g1_counts_open_exceptions_whether_a_list_or_a_number():
    for val in ([{"x": 1}, {"y": 2}], "2"):
        c = ctx(order={"contractReviewSigned": True, "scheduleBaselined": True,
                       "openExceptions": val})
        assert any("exception" in b for b in ahu.gate_blockers("G1", c)), val


# ── G2: design release ───────────────────────────────────────────────────────────────────────────

def _g2_ready():
    return ctx(unit={"id": "U1", "family": "modular", "pin": "P", "bomStatus": "Released",
                     "selectionRef": "AS-1234"},
               bom=[{"qty": 2, "kittedQty": 0}],
               docs=[{"kind": "GA drawing", "status": "Issued"}])


def test_g2_passes_when_the_design_is_released():
    assert ahu.gate_blockers("G2", _g2_ready()) == []


def test_g2_refuses_without_an_issued_ga_drawing():
    c = _g2_ready()
    c["docs"] = [{"kind": "GA drawing", "status": "Draft"}]
    assert any("general-arrangement" in b for b in ahu.gate_blockers("G2", c))


def test_g2_refuses_when_the_bom_is_not_released():
    c = _g2_ready()
    c["unit"]["bomStatus"] = "Draft"
    assert any("not marked released" in b for b in ahu.gate_blockers("G2", c))


def test_g2_refuses_without_a_selection_report():
    c = _g2_ready()
    c["unit"].pop("selectionRef")
    assert any("selection report" in b for b in ahu.gate_blockers("G2", c))


def test_a_unit_with_no_design_link_reports_no_open_changes():
    """No linked commission means nothing to check — not an invented blocker."""
    assert ahu.open_ecns(ctx()) == []


# ── G3: material ready ───────────────────────────────────────────────────────────────────────────

def test_g3_refuses_a_partly_kitted_bom():
    c = ctx(bom=[{"partNo": "FAN-01", "qty": 2, "kittedQty": 1}])
    assert any("not fully kitted" in b for b in ahu.gate_blockers("G3", c))


def test_g3_passes_a_fully_kitted_bom():
    c = ctx(bom=[{"partNo": "FAN-01", "qty": 2, "kittedQty": 2, "receivedQty": 2,
                  "iqcStatus": "Passed"}])
    assert ahu.gate_blockers("G3", c) == []


def test_g3_refuses_while_incoming_inspection_is_open():
    c = ctx(bom=[{"partNo": "COIL-1", "qty": 1, "kittedQty": 1, "receivedQty": 1,
                  "iqcStatus": "Pending"}])
    assert any("Incoming inspection" in b for b in ahu.gate_blockers("G3", c))


def test_g3_refuses_an_open_shortage():
    c = ctx(bom=[{"partNo": "X", "qty": 1, "kittedQty": 1, "shortageQty": 3}])
    assert any("shortage" in b for b in ahu.gate_blockers("G3", c))


def test_a_blank_quantity_reads_as_zero_not_as_satisfied():
    c = ctx(bom=[{"partNo": "X", "qty": 5, "kittedQty": ""}])
    assert any("not fully kitted" in b for b in ahu.gate_blockers("G3", c))


# ── G4: production complete ──────────────────────────────────────────────────────────────────────

def _steps(*specs):
    return [{"code": c, "kind": k, "stage": st, "status": s, "seq": i}
            for i, (c, k, st, s) in enumerate(specs)]


def test_g4_refuses_while_a_workstation_is_unsigned():
    c = ctx(steps=_steps(("WS-01", "op", 5, "Complete"), ("WS-02", "op", 5, "Pending")),
            docs=[{"form": "AHU-FM-501"}])
    assert any("WS-02" in b for b in ahu.gate_blockers("G4", c))


def test_g4_refuses_while_a_hold_point_is_unsigned():
    c = ctx(steps=_steps(("WS-01", "op", 5, "Complete"), ("IPQC-1", "ipqc", 5, "Pending")),
            docs=[{"form": "AHU-FM-501"}])
    assert any("IPQC-1" in b for b in ahu.gate_blockers("G4", c))


def test_g4_refuses_while_a_non_conformance_is_open():
    c = ctx(steps=_steps(("WS-01", "op", 5, "Complete")),
            docs=[{"form": "AHU-FM-501"}],
            ncr=[{"ncrNo": "NCR-7", "status": "Open"}])
    assert any("NCR-7" in b for b in ahu.gate_blockers("G4", c))


def test_a_waived_step_does_not_count_as_signed():
    """Waiving is a decision to skip something the standard asked for. It must not read as done."""
    c = ctx(steps=_steps(("WS-01", "op", 5, "Waived")), docs=[{"form": "AHU-FM-501"}])
    assert any("WS-01" in b for b in ahu.gate_blockers("G4", c))


def test_an_orphaned_step_is_left_out_of_the_gate_count():
    """A step that left the route after a spec change but kept its signature must not block."""
    c = ctx(steps=[{"code": "WS-99", "kind": "op", "stage": 5, "status": "Pending", "orphan": True}],
            docs=[{"form": "AHU-FM-501"}])
    assert ahu.gate_blockers("G4", c) == []


# ── G5: QC released ──────────────────────────────────────────────────────────────────────────────

def test_g5_refuses_while_a_test_is_unsigned():
    c = ctx(steps=_steps(("T3", "test", 6, "Pending")))
    assert any("T3" in b for b in ahu.gate_blockers("G5", c))


def test_g5_ignores_an_optional_test_that_was_not_sold():
    c = ctx(steps=[{"code": "T12", "kind": "test", "stage": 6, "status": "Pending",
                    "optional": True, "seq": 1}])
    assert ahu.gate_blockers("G5", c) == []


def test_g5_demands_a_signed_fat_report_when_a_fat_was_sold():
    c = ctx(unit={"id": "U1", "family": "modular", "pin": "P", "fatRequired": True})
    assert any("FAT report" in b for b in ahu.gate_blockers("G5", c))


def test_g5_refuses_a_fat_report_that_is_attached_but_unsigned():
    c = ctx(unit={"id": "U1", "family": "modular", "pin": "P", "fatRequired": True},
            docs=[{"form": "AHU-FM-602", "status": "Draft"}])
    assert any("not signed" in b for b in ahu.gate_blockers("G5", c))


def test_g5_does_not_demand_a_fat_report_when_no_fat_was_sold():
    assert ahu.gate_blockers("G5", ctx()) == []


def test_g5_refuses_open_punch_items():
    c = ctx(ncr=[{"kind": "punch", "status": "Open"}])
    assert any("punch" in b for b in ahu.gate_blockers("G5", c))


# ── G6: ready for dispatch ───────────────────────────────────────────────────────────────────────

def _full_dossier_docs():
    return [{"form": d["form"]} for d in R.DOSSIER if d["always"] and d["form"]]


def test_g6_refuses_an_incomplete_dossier():
    c = ctx(docs=_full_dossier_docs()[:-1],
            dispatch=[{"photos": ["a"], "customerNotified": True}])
    assert any("dossier is missing" in b for b in ahu.gate_blockers("G6", c))


def test_g6_passes_with_a_complete_dossier_and_a_dispatch_record():
    c = ctx(docs=_full_dossier_docs(),
            dispatch=[{"photos": ["a", "b"], "customerNotified": True}])
    assert ahu.gate_blockers("G6", c) == []


def test_g6_refuses_without_loading_photos():
    c = ctx(docs=_full_dossier_docs(), dispatch=[{"customerNotified": True}])
    assert any("photo" in b for b in ahu.gate_blockers("G6", c))


def test_g6_refuses_without_notifying_the_customer():
    c = ctx(docs=_full_dossier_docs(), dispatch=[{"photos": ["a"]}])
    assert any("notified" in b for b in ahu.gate_blockers("G6", c))


def test_g6_demands_the_fat_report_in_the_dossier_when_a_fat_was_sold():
    c = ctx(unit={"id": "U1", "family": "modular", "pin": "P", "fatRequired": True},
            docs=_full_dossier_docs(),
            dispatch=[{"photos": ["a"], "customerNotified": True}])
    assert any("FAT" in b for b in ahu.gate_blockers("G6", c))


# ── what the unit declares ───────────────────────────────────────────────────────────────────────

def test_a_unit_inherits_its_family_class_targets_when_it_declares_none():
    d = ahu.unit_decl({"family": "hygienic"})
    assert d["classD"] == "D1" and d["classL"] == "L1" and d["classF"] == "F9"


def test_a_unit_can_declare_classes_that_override_the_family_default():
    d = ahu.unit_decl({"family": "modular", "classL": "L1"})
    assert d["classL"] == "L1" and d["classD"] == "D2"


def test_the_cleanroom_class_and_voltage_are_never_assumed():
    """Defaulting either would put a number nobody chose onto a validation or hi-pot record."""
    d = ahu.unit_decl({"family": "hygienic"})
    assert d["cleanroom"] is None and d["voltage"] is None


# ── route instantiation ──────────────────────────────────────────────────────────────────────────

def test_instantiating_a_route_produces_one_row_per_step():
    unit = {"id": "U1", "family": "modular"}
    rows = ahu.instantiate(unit)
    assert [r["code"] for r in rows] == R.route_codes("modular")
    assert all(r["status"] == "Pending" for r in rows)


def test_rebuilding_a_route_keeps_what_people_recorded():
    unit = {"id": "U1", "family": "modular"}
    first = ahu.instantiate(unit)
    ws01 = next(r for r in first if r["code"] == "WS-01")
    ws01.update({"status": "Complete", "operator": "Nguyen Van A",
                 "readings": {"section_gap": 0.5}, "signedBy": "QC Lead"})
    again = ahu.instantiate(unit, existing=first)
    kept = next(r for r in again if r["code"] == "WS-01")
    assert kept["status"] == "Complete"
    assert kept["operator"] == "Nguyen Van A"
    assert kept["signedBy"] == "QC Lead"


def test_a_signed_step_that_leaves_the_route_is_flagged_not_deleted():
    """Changing a modular unit to packaged drops WS-07. A signature on it must survive and be
    visible, because somebody has to decide what it now means."""
    unit = {"id": "U1", "family": "modular"}
    first = ahu.instantiate(unit)
    for r in first:
        if r["code"] == "WS-07":
            r["status"] = "Complete"
            r["signedBy"] = "Production Lead"
    again = ahu.instantiate({"id": "U1", "family": "packaged"}, existing=first)
    ws07 = next((r for r in again if r["code"] == "WS-07"), None)
    assert ws07 is not None, "a signed step was silently discarded"
    assert ws07["orphan"] is True


def test_an_unsigned_step_that_leaves_the_route_is_dropped():
    unit = {"id": "U1", "family": "modular"}
    first = ahu.instantiate(unit)
    again = ahu.instantiate({"id": "U1", "family": "packaged"}, existing=first)
    assert not any(r["code"] == "WS-07" for r in again)


def test_the_verdict_reads_the_readings_recorded_on_the_step():
    unit = {"id": "U1", "family": "modular"}
    step = {"code": "IPQC-1", "readings": {"squareness": 0.4}}
    assert ahu.verdict(unit, step)["status"] == R.PASS
    step["readings"]["squareness"] = 2.0
    assert ahu.verdict(unit, step)["status"] == R.FAIL


def test_a_step_that_is_not_in_this_units_route_has_no_verdict():
    assert ahu.verdict({"id": "U1", "family": "packaged"}, {"code": "IPQC-4"}) is None
