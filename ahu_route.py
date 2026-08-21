"""The AHU production process, written as data you can test.

The company already owns this process on paper: AHU-SOP-MASTER-001 defines seven controlled stages
with six gates between them, nine workstations, five in-process hold points and a thirteen-item test
matrix, and the four product Design Standards (HML-AHU-DS-MOD/PKG/HYG/OUT-001) say which of those
apply to which family. What it did not own was a way to stop a unit moving to the next step before
the previous one was signed. A folder of Word forms cannot refuse.

This module is the process itself — the order of the steps, the document that governs each one, the
quantity that has to be measured and the limit it has to meet. It is pure: no database, no request,
no clock. Everything below is exercised by tests/test_ahu_route.py rather than trusted, which is the
point of having it in code instead of in a docx.

Three sources, kept apart deliberately:

  SOP        AHU-SOP-MASTER-001 sections 10.3 and 11.2 — the company's own hold points and test
             matrix. Where a figure appears here with src "SOP", it is the company's number.
  EN 1886    The published class thresholds. These are NOT retyped from the SOP: they are the same
             tables AeroSelect classifies against (packages/calculations/src/standards.ts), so the
             class a unit is SOLD as and the class it is TESTED against cannot drift apart.
  DS         The product Design Standards — panel construction, and the default/premium class
             targets per family.

One deliberate correction. SOP section 11.2 T2 reads "D2: <= 4 mm/m". EN 1886 puts 4 mm/m at D1 and
10 mm/m at D2, and AeroSelect classifies on the published table. Encoding the SOP's figure would
make the factory reject D2 casings that pass the standard the unit is sold against. The published
thresholds are used, and SOP_DISCREPANCIES records the difference so it can be corrected on the next
revision of the SOP rather than quietly diverge.

A limit is never invented here. Where the acceptance figure is a property of the unit rather than of
the process — the EN 1886 class it was sold as, its IP rating, its cleanroom class — the check
carries `limit_from` and the limit is RESOLVED from what the unit declares. A check whose limit
cannot be resolved is reported as undeterminable, never as a pass.
"""

# ── EN 1886 class thresholds ─────────────────────────────────────────────────────────────────────
# Mirrors packages/calculations/src/standards.ts EN1886 in the AeroSelect repo. If one moves, both
# move: tests/test_ahu_route.py::test_en1886_matches_aeroselect asserts the tables agree.
EN1886_STRENGTH = {"D1": 4.0, "D2": 10.0, "D3": float("inf")}          # relative deflection, mm/m
EN1886_LEAK_NEG400 = {"L1": 0.15, "L2": 0.44, "L3": 1.32}              # l/(s.m2) at -400 Pa
EN1886_LEAK_POS700 = {"L1": 0.22, "L2": 0.63, "L3": 1.90}              # l/(s.m2) at +700 Pa
EN1886_THERMAL_U = {"T1": 0.5, "T2": 1.0, "T3": 1.4, "T4": 2.0, "T5": float("inf")}   # W/(m2.K)
EN1886_BRIDGING = {"TB1": 0.75, "TB2": 0.60, "TB3": 0.45, "TB4": 0.30, "TB5": 0.0}    # kb, higher better
# EN 1886 section 5.4 filter bypass, as the SOP states it.
EN1886_BYPASS = {"F8": 1.0, "F9": 0.5}                                 # % bypass, maximum

SOP_DISCREPANCIES = [
    {"where": "SOP AHU-SOP-MASTER-001 section 11.2, test T2",
     "sop_says": "D2: <= 4 mm/m  (corrected in the source on 21 Aug 2026)",
     "standard_says": "EN 1886 places 4 mm/m at D1; D2 is <= 10 mm/m",
     "status": "Source corrected — approval and PDF re-issue outstanding",
     "resolution": (
         "The published EN 1886 threshold is applied here and always has been. The .docx and .pptx "
         "sources have since been corrected to match (13 replacements across 7 files, including "
         "HML-AHU-DS-COMP-001 which also had D1 = 2.5 mm/m). Two things are still outstanding, so "
         "this entry stays: the change is NOT yet approved by the QA/QC Manager, and the PDFs — "
         "which are what people actually read — still state the old figure. See "
         "DOCUMENT-CHANGE-RECORD_EN1886-D-class.md in the AHU Production folder. It also raises a "
         "question only QA/QC can answer: the KPI target reads 'D2 or better', which now means "
         "<= 10 mm/m, where the document previously implied <= 4 mm/m. If a 4 mm/m casing was "
         "intended, the target should say D1.")},
]

# ── Panel construction, from the Design Standards ────────────────────────────────────────────────
PANEL_PU_DENSITY_KGM3 = 45.0        # DS-MOD-001 section 4: injected PU 45 kg/m3
PANEL_PU_DENSITY_TOL = 0.10         # +/-10% on a destructive sample - a foam figure is not a gauge reading
PANEL_LAMBDA_MAX = 0.022            # W/mK, DS-MOD-001 section 4

# Default EN 1886 targets per family, from the Design Standards. A unit may declare its own; these
# are what it inherits when the order does not say.
FAMILY_CLASS_DEFAULTS = {
    "modular":  {"D": "D2", "L": "L2", "F": "F8", "TB": "TB2", "T": "T2"},
    "packaged": {"D": "D2", "L": "L2", "F": "F8", "TB": "TB2", "T": "T2"},
    "hygienic": {"D": "D1", "L": "L1", "F": "F9", "TB": "TB1", "T": "T1"},
    "outdoor":  {"D": "D2", "L": "L2", "F": "F8", "TB": "TB2", "T": "T2"},
}

FAMILIES = {
    "modular":  {"label": "Modular",  "label_vn": "Dang module",   "ds": "HML-AHU-DS-MOD-001", "ga": "HML-AHU-GA-MOD-001"},
    "packaged": {"label": "Packaged", "label_vn": "Dang packaged", "ds": "HML-AHU-DS-PKG-001", "ga": "HML-AHU-GA-PKG-001"},
    "hygienic": {"label": "Hygienic", "label_vn": "Vo trung",      "ds": "HML-AHU-DS-HYG-001", "ga": "HML-AHU-GA-HYG-001"},
    "outdoor":  {"label": "Outdoor",  "label_vn": "Ngoai troi",    "ds": "HML-AHU-DS-OUT-001", "ga": "HML-AHU-GA-OUT-001"},
}

# ── The seven stages and the six gates between them (SOP section 5) ──────────────────────────────
# `requires` names predicates the SERVER evaluates against the unit's own records — the route library
# declares what a gate demands, app.py knows how to look it up. Keeping the two apart is what lets
# this file stay pure and testable.
STAGES = [
    {"no": 1, "k": "order",    "title": "Sales Order Management",    "title_vn": "Quan ly don hang",
     "owner": "Sales",       "cycle": "1 - 3 working days", "output": "Confirmed PO + technical specification",
     "gate": "G1", "gate_title": "Order Acceptance", "gate_title_vn": "Chap nhan don hang",
     "gate_sign": "sales", "forms": ["AHU-FM-101", "AHU-FM-102", "AHU-FM-103"],
     "requires": ["contract_review_signed", "no_open_exceptions", "pin_registered", "schedule_baselined"]},
    {"no": 2, "k": "design",   "title": "Engineering & Design",      "title_vn": "Thiet ke ky thuat",
     "owner": "Engineering", "cycle": "3 - 7 days", "output": "GA drawing, BOM, selection report",
     "gate": "G2", "gate_title": "Design Release", "gate_title_vn": "Phat hanh thiet ke",
     "gate_sign": "engineering", "forms": ["AHU-FM-201", "AHU-FM-204"],
     "requires": ["ga_issued", "bom_released", "selection_attached", "no_open_ecn"]},
    {"no": 3, "k": "material", "title": "Raw Material Management",   "title_vn": "Quan ly vat tu",
     "owner": "Warehouse",   "cycle": "1 - 2 days", "output": "Kitted material per AHU",
     "gate": "G3", "gate_title": "Material Ready", "gate_title_vn": "San sang vat tu",
     "gate_sign": "warehouse", "forms": ["AHU-FM-302", "AHU-FM-303"],
     "requires": ["bom_fully_kitted", "iqc_closed", "no_shortage"]},
    {"no": 4, "k": "procure",  "title": "Procurement",               "title_vn": "Mua hang",
     "owner": "Procurement", "cycle": "7 - 30 days", "output": "Released POs + delivered items",
     "gate": None, "forms": ["AHU-FM-401", "AHU-FM-403"], "requires": []},
    {"no": 5, "k": "produce",  "title": "Production Workflow",       "title_vn": "Dong san xuat",
     "owner": "Production",  "cycle": "3 - 10 days / unit", "output": "Assembled AHU",
     "gate": "G4", "gate_title": "Production Complete", "gate_title_vn": "Hoan thanh san xuat",
     "gate_sign": "production", "forms": ["AHU-FM-501", "AHU-FM-502", "AHU-FM-503"],
     "requires": ["all_ops_signed", "all_ipqc_passed", "no_open_ncr", "assembly_checklist_complete"]},
    {"no": 6, "k": "test",     "title": "Testing & Quality Control", "title_vn": "Kiem tra chat luong",
     "owner": "QA/QC",       "cycle": "0.5 - 1 day", "output": "Test report + acceptance certificate",
     "gate": "G5", "gate_title": "QC Released", "gate_title_vn": "Thong qua QC",
     "gate_sign": "qaqc", "forms": ["AHU-FM-601", "AHU-FM-602", "AHU-FM-603"],
     "requires": ["all_tests_passed", "fat_signed_if_required", "punch_list_closed", "no_open_ncr"]},
    {"no": 7, "k": "dispatch", "title": "Packaging & Dispatch",      "title_vn": "Dong goi & giao hang",
     "owner": "Logistics",   "cycle": "0.5 - 1 day", "output": "Crated AHU, BOL, manuals",
     "gate": "G6", "gate_title": "Ready for Dispatch", "gate_title_vn": "San sang giao hang",
     "gate_sign": "logistics", "forms": ["AHU-FM-701", "AHU-FM-702", "AHU-FM-703", "AHU-FM-704"],
     "requires": ["dossier_complete", "packing_recorded", "loading_photos", "customer_notified"]},
]
STAGE_BY_K = {s["k"]: s for s in STAGES}
STAGE_BY_NO = {s["no"]: s for s in STAGES}

# Human wording for each gate predicate, so a refusal reads as a reason rather than a token.
GATE_REASONS = {
    "contract_review_signed": "Contract review AHU-FM-101 is not signed",
    "no_open_exceptions": "Commercial or technical exceptions are still open",
    "pin_registered": "The unit has no Production Identification Number",
    "schedule_baselined": "The master schedule has not been baselined",
    "ga_issued": "No GA drawing has been issued for this unit",
    "bom_released": "The bill of materials has not been released",
    "selection_attached": "No AeroSelect selection report is attached",
    "no_open_ecn": "An engineering change is still open against this unit",
    "bom_fully_kitted": "Not every BOM line is kitted",
    "iqc_closed": "Incoming inspection (IQC) is not closed on every received line",
    "no_shortage": "The unit has an open material shortage",
    "all_ops_signed": "Not every workstation operation is signed off",
    "all_ipqc_passed": "An IPQC hold point has not passed",
    "no_open_ncr": "A non-conformance is still open against this unit",
    "assembly_checklist_complete": "Final assembly checklist AHU-FM-501 is incomplete",
    "all_tests_passed": "Not every applicable test has passed",
    "fat_signed_if_required": "The FAT report is required for this unit and is not signed",
    "punch_list_closed": "The punch list AHU-FM-603 has open items",
    "dossier_complete": "The document dossier is missing a required document",
    "packing_recorded": "No packing record has been raised",
    "loading_photos": "The loading photo set has not been uploaded",
    "customer_notified": "The customer has not been notified of dispatch",
}

# ── Stage 5: the nine workstations (SOP section 10.2) ────────────────────────────────────────────
# `sign` is the role that signs the operation complete; `tact` is the SOP's typical cycle, carried so
# the shop-floor board can show a step running long rather than only running.
WORKSTATIONS = [
    {"code": "WS-01", "title": "Sheet Metal Preparation", "title_vn": "Chuan bi ton",
     "activity": "CNC cut, laser cut and CNC bend skin panels per drawing.",
     "wi": "HML-AHU-WI-WS01-001", "tact": "20 - 60 min / panel set", "sign": "production",
     "after": [], "families": None},
    {"code": "WS-02", "title": "Frame & Profile Assembly", "title_vn": "Lap khung profile",
     "activity": "Cut profiles to length, drill, form section frames.",
     "wi": "HML-AHU-WI-WS02-001", "tact": "30 - 90 min / section", "sign": "production",
     "after": ["WS-01"], "families": None},
    {"code": "WS-03", "title": "Panel Foaming / Insulation", "title_vn": "Phun PU / cach nhiet",
     "activity": "PU foam injection or rockwool fill between inner and outer skin.",
     "wi": "HML-AHU-WI-WS03-001", "tact": "30 min cure (PU) / 15 min (rockwool)", "sign": "production",
     "after": ["WS-02"], "families": None},
    {"code": "WS-04", "title": "Section Assembly", "title_vn": "Lap khoang",
     "activity": "Assemble panels onto frame, install gaskets, add internals (fan, coil, filter, damper).",
     "wi": "HML-AHU-WI-WS04-001", "tact": "1 - 4 h / section", "sign": "production",
     "after": ["WS-03"], "families": None},
    {"code": "WS-05", "title": "Drain Pan & Hygienic Detail", "title_vn": "Khay xa & chi tiet ve sinh",
     "activity": "Slope test of drain pan, sealant continuity, FDA gasket fit.",
     "wi": "HML-AHU-WI-WS05-001", "tact": "30 min / coil section", "sign": "production",
     "after": ["WS-04"], "families": None},
    {"code": "WS-06", "title": "Electrical Pre-wire", "title_vn": "Di day dien truoc",
     "activity": "Run cables, terminate motor and sensors, fit junction box on each section.",
     "wi": "HML-AHU-WI-WS06-001", "tact": "1 - 2 h / section", "sign": "production",
     "after": ["WS-05"], "families": None},
    {"code": "WS-07", "title": "Final Assembly (Joining Sections)", "title_vn": "Lap tong (ghep khoang)",
     "activity": "Bolt sections together with gaskets, align, seal joints.",
     "wi": "HML-AHU-WI-WS07-001", "tact": "3 - 8 h / AHU", "sign": "production",
     "after": ["WS-06"], "families": ["modular", "hygienic", "outdoor"]},
    {"code": "WS-08", "title": "Control Panel & Final Wiring", "title_vn": "Lap tu & di day cuoi",
     "activity": "Mount control panel, run trunking, terminate to controller, label.",
     "wi": "HML-AHU-WI-WS08-001", "tact": "2 - 4 h / AHU", "sign": "production",
     "after": ["WS-07", "WS-06"], "families": None},
    {"code": "WS-09", "title": "Pre-test Visual & 5S", "title_vn": "Kiem truc quan & 5S",
     "activity": "Section gaps, gasket continuity, finish and labelling before the unit goes to test.",
     "wi": "HML-AHU-WI-WS09-001", "tact": "30 min / AHU", "sign": "production",
     "after": ["WS-08"], "families": None,
     "checks": [
         {"key": "section_gap", "label": "Section-to-section gap", "unit": "mm", "op": "<=", "limit": 1.0,
          "src": "SOP 10.2 WS-09"},
         {"key": "gasket_continuous", "label": "Gasket continuous, no breaks", "op": "yes",
          "src": "SOP 10.2 WS-09"},
         {"key": "finish_defect_free", "label": "Finish free of scratches and dents", "op": "yes",
          "src": "SOP 10.2 WS-09"},
         {"key": "labels_fitted", "label": "All labels and nameplate fitted", "op": "yes",
          "src": "SOP 10.2 WS-09"},
     ]},
]

# WS-07 joins sections together; a packaged unit is built as one piece and has no section joints, so
# neither the operation nor IPQC-4 that inspects its seals applies. That is a real difference in the
# product, not a shortcut — see DS-PKG-001.

# ── Stage 5: the five in-process hold points (SOP section 10.3) ──────────────────────────────────
# A hold point is inspected by QA/QC, not by the person who did the work. `witness_not` names the
# operation whose signer may not also sign this inspection — the server enforces it.
IPQC = [
    {"code": "IPQC-1", "title": "Frame & Profile Inspection", "title_vn": "Kiem tra khung profile",
     "doc": "HML-AHU-IPQC-1-001", "form": "AHU-FM-502", "after": ["WS-02"], "witness_not": "WS-02",
     "families": None,
     "checks": [
         {"key": "squareness", "label": "Frame diagonal squareness", "label_vn": "Do vuong goc khung",
          "unit": "mm/m", "op": "<=", "limit": 1.0, "src": "SOP 10.3 IPQC-1"},
     ]},
    {"code": "IPQC-2", "title": "PU Foaming Inspection", "title_vn": "Kiem tra phun PU",
     "doc": "HML-AHU-IPQC-2-001", "form": "AHU-FM-502", "after": ["WS-03"], "witness_not": "WS-03",
     "families": None, "sampling": "Destructive sample, 1 per 50 panels (SOP 10.3)",
     "checks": [
         {"key": "foam_density", "label": "Foam core density", "label_vn": "Mat do loi foam",
          "unit": "kg/m3", "op": "range",
          "limit": PANEL_PU_DENSITY_KGM3 * (1 - PANEL_PU_DENSITY_TOL),
          "limit2": PANEL_PU_DENSITY_KGM3 * (1 + PANEL_PU_DENSITY_TOL),
          "src": "DS-MOD-001 section 4 (45 kg/m3 +/-10%)"},
         {"key": "foam_adhesion", "label": "Adhesion to both skins, no delamination", "op": "yes",
          "src": "SOP 10.3 IPQC-2"},
     ]},
    {"code": "IPQC-3", "title": "Section Assembly Inspection", "title_vn": "Kiem tra lap khoang",
     "doc": "HML-AHU-IPQC-3-001", "form": "AHU-FM-502", "after": ["WS-04"], "witness_not": "WS-04",
     "families": None,
     "checks": [
         {"key": "coil_hydro_bar", "label": "Coil hydrostatic test pressure", "label_vn": "Ap thu thuy tinh coil",
          "unit": "bar", "op": ">=", "limit_from": "coil_test_bar",
          "src": "SOP 10.3 IPQC-3 (25 bar minimum, or 1.5x design)"},
         {"key": "coil_hydro_min", "label": "Hold time at pressure", "unit": "min", "op": ">=", "limit": 30.0,
          "src": "SOP 10.3 IPQC-3"},
         {"key": "coil_no_drop", "label": "No pressure drop, no leak", "op": "yes", "src": "SOP 10.3 IPQC-3"},
         {"key": "pan_slope", "label": "Drain pan slopes to outlet", "op": "yes", "src": "SOP 10.3 IPQC-3"},
         {"key": "fan_rotation", "label": "Fan rotation direction correct", "op": "yes", "src": "SOP 10.3 IPQC-3"},
     ]},
    {"code": "IPQC-4", "title": "Final Assembly / Joining Inspection", "title_vn": "Kiem tra ghep khoang",
     "doc": "HML-AHU-IPQC-4-001", "form": "AHU-FM-502", "after": ["WS-07"], "witness_not": "WS-07",
     "families": ["modular", "hygienic", "outdoor"],
     "checks": [
         {"key": "seal_continuity", "label": "Section-to-section seal continuity (torch / smoke pen)",
          "op": "yes", "src": "SOP 10.3 IPQC-4"},
     ]},
    {"code": "IPQC-5", "title": "Control Panel & Final Wiring Inspection", "title_vn": "Kiem tra tu dien & day",
     "doc": "HML-AHU-IPQC-5-001", "form": "AHU-FM-502", "after": ["WS-08"], "witness_not": "WS-08",
     "families": None,
     "checks": [
         {"key": "continuity", "label": "Circuit continuity proven", "op": "yes", "src": "SOP 10.3 IPQC-5"},
         {"key": "megger_mohm", "label": "Insulation resistance at 500 VDC", "label_vn": "Dien tro cach dien",
          "unit": "Mohm", "op": ">=", "limit": 5.0, "src": "SOP 10.3 IPQC-5"},
         {"key": "earth_ohm", "label": "Earth bond resistance", "label_vn": "Dien tro tiep dia",
          "unit": "ohm", "op": "<=", "limit": 0.1, "src": "SOP 10.3 IPQC-5"},
         {"key": "polarity", "label": "Phase / polarity correct", "op": "yes", "src": "SOP 10.3 IPQC-5"},
     ]},
]

# ── Stage 6: the test matrix (SOP section 11.2) ──────────────────────────────────────────────────
# `limit_from` means the acceptance figure is a property of THIS unit — the class it was sold as, its
# design pressure, its supply voltage — and is resolved from the unit's declaration at evaluation
# time. A test whose limit cannot be resolved reports undeterminable, never pass.
TESTS = [
    {"code": "T1", "title": "Visual & dimensional", "title_vn": "Truc quan & kich thuoc",
     "method": "Master drawing with tape / laser. ISO 2859-1 sampling.", "std": "ISO 2859-1",
     "families": None,
     "checks": [
         {"key": "dim_dev", "label": "Overall dimensional deviation", "unit": "mm", "op": "range",
          "limit": -3.0, "limit2": 3.0, "src": "SOP 11.2 T1"},
         {"key": "finish_ok", "label": "Finish defect-free", "op": "yes", "src": "SOP 11.2 T1"},
     ]},
    {"code": "T2", "title": "Casing strength (D-class)", "title_vn": "Do ben vo (cap D)",
     "method": "Pressurise to design differential pressure and measure relative deflection.",
     "std": "EN 1886 section 5.1", "families": None,
     "checks": [
         {"key": "deflection", "label": "Relative deflection", "label_vn": "Do vong tuong doi",
          "unit": "mm/m", "op": "<=", "limit_from": "class_D",
          "src": "EN 1886 (D1 <= 4, D2 <= 10 mm/m)"},
     ]},
    {"code": "T3", "title": "Casing leakage (L-class)", "title_vn": "Ro ri vo (cap L)",
     "method": "Blank off, pressurise to -400 Pa, measure leakage rate.",
     "std": "EN 1886 section 5.2", "families": None,
     "checks": [
         {"key": "leak_neg400", "label": "Leakage rate at -400 Pa", "label_vn": "Luu luong ro o -400 Pa",
          "unit": "l/(s.m2)", "op": "<=", "limit_from": "class_L",
          "src": "EN 1886 (L1 0.15, L2 0.44, L3 1.32)"},
     ]},
    {"code": "T4", "title": "Filter bypass (F-class)", "title_vn": "Ro qua phin loc (cap F)",
     "method": "Aerosol injection upstream, scan downstream.", "std": "EN 1886 section 5.4",
     "families": None,
     "checks": [
         {"key": "bypass_pct", "label": "Filter bypass leakage", "unit": "%", "op": "<=",
          "limit_from": "class_F", "src": "SOP 11.2 T4 (F8 <= 1%, F9 <= 0.5%)"},
     ]},
    {"code": "T5", "title": "Coil pressure test", "title_vn": "Thu ap coil",
     "method": "Hydrostatic at 1.5x design pressure, minimum 25 bar for 30 minutes.",
     "std": "SOP 11.2 T5", "families": None,
     "checks": [
         {"key": "test_bar", "label": "Test pressure held", "unit": "bar", "op": ">=",
          "limit_from": "coil_test_bar", "src": "SOP 11.2 T5"},
         {"key": "hold_min", "label": "Hold time", "unit": "min", "op": ">=", "limit": 30.0,
          "src": "SOP 11.2 T5"},
         {"key": "no_drop", "label": "Zero pressure drop, no leak", "op": "yes", "src": "SOP 11.2 T5"},
     ]},
    {"code": "T6", "title": "Drain test", "title_vn": "Thu thoat nuoc",
     "method": "Fill drain pan to overflow, verify slope, flush trap.", "std": "SOP 11.2 T6",
     "families": None,
     "checks": [
         {"key": "empty_min", "label": "Time for pan to empty", "unit": "min", "op": "<=", "limit": 5.0,
          "src": "SOP 11.2 T6"},
         {"key": "no_pooling", "label": "No standing water left in pan", "op": "yes", "src": "SOP 11.2 T6"},
     ]},
    {"code": "T7", "title": "Earth bonding", "title_vn": "Tiep dia",
     "method": "10 A AC for 10 s between any conductive part and PE.", "std": "IEC 60204-1",
     "families": None,
     "checks": [
         {"key": "earth_ohm", "label": "Earth continuity resistance", "unit": "ohm", "op": "<=",
          "limit": 0.1, "src": "SOP 11.2 T7 / IEC 60204-1"},
     ]},
    {"code": "T8", "title": "Insulation resistance", "title_vn": "Dien tro cach dien",
     "method": "500 VDC megger between live conductors and PE.", "std": "IEC 60204-1",
     "families": None,
     "checks": [
         {"key": "megger_mohm", "label": "Insulation resistance", "unit": "Mohm", "op": ">=", "limit": 5.0,
          "src": "SOP 11.2 T8"},
     ]},
    {"code": "T9", "title": "Hi-Pot (dielectric)", "title_vn": "Cao the",
     "method": "1500 VAC for 1 min on a 230 V circuit; 2000 VAC on a 400 V circuit.",
     "std": "IEC 60204-1", "families": None,
     "checks": [
         {"key": "applied_v", "label": "Test voltage applied", "unit": "V", "op": ">=",
          "limit_from": "hipot_v", "src": "SOP 11.2 T9"},
         {"key": "leak_ma", "label": "Leakage current", "unit": "mA", "op": "<=", "limit": 5.0,
          "src": "SOP 11.2 T9"},
         {"key": "no_breakdown", "label": "No dielectric breakdown", "op": "yes", "src": "SOP 11.2 T9"},
     ]},
    {"code": "T10", "title": "Functional / no-load run", "title_vn": "Chay thu khong tai",
     "method": "Run all motors, dampers, sensors and alarms through the control panel.",
     "std": "HML-AHU-SOO-001 sequence of operations", "families": None,
     "checks": [
         {"key": "loops_ok", "label": "Every control loop responds per the sequence of operations",
          "op": "yes", "src": "SOP 11.2 T10"},
     ]},
    {"code": "T11", "title": "Vibration (fan)", "title_vn": "Rung dong (quat)",
     "method": "Measure RMS velocity on the bearing housing.", "std": "ISO 14694 G6.3 / ISO 21940-11",
     "families": None,
     "checks": [
         {"key": "vib_mms", "label": "RMS velocity at bearing housing", "unit": "mm/s", "op": "<=",
          "limit": 4.5, "src": "SOP 11.2 T11"},
     ]},
    {"code": "T12", "title": "Sound power", "title_vn": "Do on",
     "method": "Sound power measurement where a qualified laboratory is available.",
     "std": "AHRI 260 / ISO 3741", "families": None, "optional": True,
     "checks": [
         {"key": "pwl_dev", "label": "Deviation from rated sound power", "unit": "dB", "op": "range",
          "limit": -3.0, "limit2": 3.0, "src": "SOP 11.2 T12"},
     ]},
    {"code": "T13", "title": "Hygienic / particle count", "title_vn": "Ve sinh / dem hat",
     "method": "Particle count downstream of the HEPA filter.", "std": "ISO 14644-1 / VDI 6022",
     "families": ["hygienic"],
     "checks": [
         {"key": "particle_count", "label": "Particles >= 0.5 um per m3", "unit": "/m3", "op": "<=",
          "limit_from": "cleanroom", "src": "ISO 14644-1, class declared on the order"},
         {"key": "hepa_integrity", "label": "HEPA installed-filter leak test passed", "op": "yes",
          "src": "VDI 6022 / ISO 14644-3"},
     ]},
    {"code": "T-IP", "title": "Weather / ingress protection", "title_vn": "Chong nuoc / bui",
     "method": "Water spray and ingress check against the declared IP rating.",
     "std": "IEC 60529, recorded on AHU-FM-203", "families": ["outdoor"],
     "checks": [
         {"key": "ingress_none", "label": "No water ingress at the declared IP rating", "op": "yes",
          "src": "DS-OUT-001 / AHU-FM-203"},
         {"key": "ip_declared", "label": "IP rating declared on the order", "op": "note",
          "src": "DS-OUT-001"},
     ]},
]

# ── Stage 7: the dispatch operations (SOP section 12) ────────────────────────────────────────────
DISPATCH_OPS = [
    {"code": "PK-01", "title": "Pre-packing checklist", "title_vn": "Checklist truoc dong goi",
     "activity": "Blank every opening, bag loose items, fit desiccant, mark lifting points.",
     "form": "AHU-FM-701", "sign": "logistics", "after": [], "families": None,
     "checks": [
         {"key": "openings_blanked", "label": "All openings blanked with foam plug and film", "op": "yes",
          "src": "SOP 12.2"},
         {"key": "loose_items", "label": "Loose items bagged and stowed in the fan section", "op": "yes",
          "src": "SOP 12.2"},
         {"key": "desiccant", "label": "Silica gel fitted in electronic enclosures (1 per 50 L)",
          "op": "yes", "src": "SOP 12.2"},
         {"key": "lift_marked", "label": "Forklift slots and lifting eyes marked", "op": "yes",
          "src": "SOP 12.2"},
     ]},
    {"code": "PK-02", "title": "Packing & marking", "title_vn": "Dong goi & ghi nhan",
     "activity": "Pack to the agreed configuration, apply shipping marks and handling icons.",
     "form": "AHU-FM-701", "sign": "logistics", "after": ["PK-01"], "families": None,
     "checks": [
         {"key": "marks_two_sides", "label": "Shipping marks on at least two sides", "op": "yes",
          "src": "SOP 12.4"},
         {"key": "nameplate", "label": "Bilingual nameplate riveted near the control panel", "op": "yes",
          "src": "SOP 12.4"},
     ]},
    {"code": "PK-03", "title": "Loading inspection", "title_vn": "Kiem tra xep tai",
     "activity": "Photograph the unit, supervise loading, lash to the CTU Code.",
     "form": "AHU-FM-704", "sign": "logistics", "after": ["PK-02"], "families": None,
     "checks": [
         {"key": "photos_6", "label": "Photo set taken: 6 angles plus nameplate close-up", "op": "yes",
          "src": "SOP 12.6"},
         {"key": "lashing", "label": "Lashed per CTU Code, minimum 4 ratchet straps", "op": "yes",
          "src": "SOP 12.6"},
         {"key": "shock_indicator", "label": "Shock / tilt indicators applied where required", "op": "note",
          "src": "SOP 12.6"},
     ]},
]

# Packaging configurations (SOP section 12.3) — offered as a choice on the dispatch record.
PACKAGING = [
    {"k": "stretch", "label": "Stretch-wrap on skid",
     "when": "Domestic truck, under 2 days transit, sheltered storage.",
     "spec": "Hardwood skid 100 mm, at least 4 layers stretch film, edge protectors."},
    {"k": "crate", "label": "Bubble + plywood crate",
     "when": "Domestic truck, mixed load, over 2 days, possible rain.",
     "spec": "Bubble wrap full body, 9 mm plywood crate on skid."},
    {"k": "ispm15", "label": "Export wooden case (ISPM-15)",
     "when": "Sea or air export.",
     "spec": "Heat-treated wood, ISPM-15 stamped, VCI inner film, desiccant per m3."},
    {"k": "steelframe", "label": "Export steel frame + tarpaulin",
     "when": "Oversize AHU over 12 m long or over 4 m high.",
     "spec": "Custom welded frame, weatherproof tarpaulin Class 2."},
]

# The documents that must travel with the unit (SOP section 12.5). `always` documents are what the
# G6 dossier check demands; the rest apply when their condition is met.
DOSSIER = [
    {"k": "packing_list", "label": "Packing List", "form": "AHU-FM-701", "always": True},
    {"k": "bol", "label": "Bill of Lading / Delivery Note", "form": "AHU-FM-702", "always": True},
    {"k": "test_cert", "label": "Test certificate, signed", "form": "AHU-FM-601", "always": True},
    {"k": "om_manual", "label": "O&M manual", "form": "HML-AHU-OM-001", "always": True},
    {"k": "asbuilt", "label": "As-built electrical drawings", "form": "HML-AHU-DRSTD-001", "always": True},
    {"k": "warranty", "label": "Warranty card", "form": "AHU-FM-703", "always": True},
    {"k": "fat_report", "label": "FAT report", "form": "AHU-FM-602", "always": False,
     "when": "FAT was performed"},
    {"k": "co_ce", "label": "Certificate of Origin / CE / CB", "form": None, "always": False,
     "when": "Export or CE-marked supply"},
]


# ── Building a unit's route ──────────────────────────────────────────────────────────────────────
# Sequence numbers are stage*1000 plus an offset, with the stage's gate parked at +900. Stage 5 can
# carry fourteen steps (nine stations and five hold points), so the older stage*100 scheme ran the
# last station straight into the stage-6 block and shuffled the route. The gap also leaves room to
# insert a project-specific step later without renumbering anything already signed.
STAGE_SEQ = 1000
GATE_SEQ_OFFSET = 900
def _applies(spec, family):
    fams = spec.get("families")
    return True if fams is None else family in fams


def build_route(family, opts=None):
    """The ordered list of steps for one AHU.

    `family` is one of FAMILIES. `opts` may carry:
        fat            True if a Factory Acceptance Test was sold with the unit
        sound_test     True to include the optional T12 sound measurement
        skip           a list of step codes the project has agreed do not apply

    Every step returned has a stable `code`, so a route can be rebuilt after a spec change without
    losing the signatures already recorded against a code.
    """
    opts = opts or {}
    family = (family or "modular").strip().lower()
    if family not in FAMILIES:
        raise ValueError("Unknown AHU family: %r" % (family,))
    skip = {str(s).strip().upper() for s in (opts.get("skip") or [])}
    steps = []

    def add(step):
        if step["code"].upper() in skip:
            return
        steps.append(step)

    # Stages 1-4: the gates only. What happens inside those stages is the order, the design and the
    # purchasing — each already has a home elsewhere in the portal, and duplicating it here would
    # create a second version of the truth.
    #
    # The gates are chained to each other. SOP section 5 is explicit that no stage starts until the
    # previous gate is signed, so G2 waits on G1 and G3 waits on G2 — otherwise a unit could be
    # kitted against a design nobody had released.
    prev_gate = None
    for st in STAGES:
        if st["no"] > 4 or not st.get("gate"):
            continue
        add({"code": st["gate"], "kind": "gate", "seq": st["no"] * STAGE_SEQ + GATE_SEQ_OFFSET,
             "stage": st["no"], "title": st["gate_title"], "title_vn": st.get("gate_title_vn", ""),
             "sign": st["gate_sign"], "after": ([prev_gate] if prev_gate else []),
             "forms": st["forms"], "requires": st["requires"], "checks": []})
        prev_gate = st["gate"]

    # Stage 5: workstations, with each hold point immediately after the station it inspects.
    ipqc_after = {}
    for hp in IPQC:
        if _applies(hp, family):
            for a in hp["after"]:
                ipqc_after.setdefault(a, []).append(hp)

    offset = 10
    prev_op = None
    for ws in WORKSTATIONS:
        if not _applies(ws, family):
            continue
        after = [a for a in ws["after"] if any(w["code"] == a and _applies(w, family)
                                               for w in WORKSTATIONS)]
        # A packaged unit has no WS-07, so WS-08's predecessor collapses to WS-06. Taking whatever
        # survives keeps the chain unbroken instead of pointing at a step that does not exist.
        if not after:
            after = [prev_op] if prev_op else ["G3"]
        add({"code": ws["code"], "kind": "op", "seq": 5 * STAGE_SEQ + offset, "stage": 5,
             "title": ws["title"], "title_vn": ws["title_vn"], "activity": ws["activity"],
             "wi": ws["wi"], "tact": ws["tact"], "sign": ws["sign"], "after": after,
             "checks": list(ws.get("checks") or []), "forms": ["AHU-FM-501"]})
        prev_op = ws["code"]
        offset += 10
        for hp in ipqc_after.get(ws["code"], []):
            add({"code": hp["code"], "kind": "ipqc", "seq": 5 * STAGE_SEQ + offset, "stage": 5,
                 "title": hp["title"], "title_vn": hp["title_vn"], "doc": hp["doc"],
                 "forms": [hp["form"]], "sign": "qaqc", "after": [ws["code"]],
                 "witness_not": hp.get("witness_not"), "sampling": hp.get("sampling"),
                 "checks": list(hp["checks"])})
            offset += 10

    g4 = STAGE_BY_K["produce"]
    add({"code": g4["gate"], "kind": "gate", "seq": 5 * STAGE_SEQ + GATE_SEQ_OFFSET, "stage": 5,
         "title": g4["gate_title"], "title_vn": g4["gate_title_vn"], "sign": g4["gate_sign"],
         "forms": g4["forms"], "after": [s["code"] for s in steps if s["stage"] == 5],
         "requires": g4["requires"], "checks": []})

    # Stage 6: the test matrix.
    toffset = 10
    for t in TESTS:
        if not _applies(t, family):
            continue
        if t["code"] == "T12" and not opts.get("sound_test"):
            continue
        add({"code": t["code"], "kind": "test", "seq": 6 * STAGE_SEQ + toffset, "stage": 6,
             "title": t["title"], "title_vn": t["title_vn"], "method": t["method"],
             "std": t["std"], "sign": "qaqc", "after": ["G4"], "forms": ["AHU-FM-601"],
             "optional": bool(t.get("optional")), "checks": list(t["checks"])})
        toffset += 10

    g5 = STAGE_BY_K["test"]
    add({"code": g5["gate"], "kind": "gate", "seq": 6 * STAGE_SEQ + GATE_SEQ_OFFSET, "stage": 6,
         "title": g5["gate_title"], "title_vn": g5["gate_title_vn"], "sign": g5["gate_sign"],
         "forms": g5["forms"], "after": [s["code"] for s in steps if s["stage"] == 6],
         "requires": g5["requires"], "checks": [], "fat": bool(opts.get("fat"))})

    # Stage 7: packing and dispatch.
    poffset = 10
    for op in DISPATCH_OPS:
        if not _applies(op, family):
            continue
        add({"code": op["code"], "kind": "op", "seq": 7 * STAGE_SEQ + poffset, "stage": 7,
             "title": op["title"], "title_vn": op["title_vn"], "activity": op["activity"],
             "forms": [op["form"]], "sign": op["sign"],
             "after": op["after"] or ["G5"], "checks": list(op["checks"])})
        poffset += 10

    g6 = STAGE_BY_K["dispatch"]
    add({"code": g6["gate"], "kind": "gate", "seq": 7 * STAGE_SEQ + GATE_SEQ_OFFSET, "stage": 7,
         "title": g6["gate_title"], "title_vn": g6["gate_title_vn"], "sign": g6["gate_sign"],
         "forms": g6["forms"], "after": [s["code"] for s in steps if s["stage"] == 7],
         "requires": g6["requires"], "checks": []})

    steps.sort(key=lambda s: s["seq"])
    return steps


def route_codes(family, opts=None):
    return [s["code"] for s in build_route(family, opts)]


# ── Resolving a limit that belongs to the unit rather than to the process ────────────────────────
# `decl` is what the unit declares about itself: the EN 1886 classes it was sold as, its coil design
# pressure, its supply voltage, its cleanroom class. Returns (limit, note) or (None, why-not).
def resolve_limit(check, decl):
    src = check.get("limit_from")
    if not src:
        lim = check.get("limit")
        return (lim, None) if lim is not None else (None, "no limit defined")
    decl = decl or {}

    if src == "class_D":
        cls = str(decl.get("classD") or "").strip().upper()
        if cls not in EN1886_STRENGTH:
            return None, "the unit has not declared an EN 1886 D class"
        return EN1886_STRENGTH[cls], "EN 1886 %s" % cls
    if src == "class_L":
        cls = str(decl.get("classL") or "").strip().upper()
        if cls not in EN1886_LEAK_NEG400:
            return None, "the unit has not declared an EN 1886 L class"
        return EN1886_LEAK_NEG400[cls], "EN 1886 %s at -400 Pa" % cls
    if src == "class_F":
        cls = str(decl.get("classF") or "").strip().upper()
        if cls not in EN1886_BYPASS:
            return None, "the unit has not declared an EN 1886 F class"
        return EN1886_BYPASS[cls], "EN 1886 %s" % cls
    if src == "class_T":
        cls = str(decl.get("classT") or "").strip().upper()
        if cls not in EN1886_THERMAL_U:
            return None, "the unit has not declared an EN 1886 T class"
        return EN1886_THERMAL_U[cls], "EN 1886 %s" % cls
    if src == "class_TB":
        cls = str(decl.get("classTB") or "").strip().upper()
        if cls not in EN1886_BRIDGING:
            return None, "the unit has not declared an EN 1886 TB class"
        return EN1886_BRIDGING[cls], "EN 1886 %s" % cls

    if src == "coil_test_bar":
        # SOP 11.2 T5: 1.5x design pressure, minimum 25 bar. With no declared design pressure the
        # floor still stands on its own, so this one CAN be answered - the 25 bar is the SOP's.
        try:
            design = float(decl.get("coilDesignBar") or 0)
        except (TypeError, ValueError):
            design = 0.0
        if design > 0:
            return max(25.0, 1.5 * design), "1.5 x %g bar design, floor 25 bar" % design
        return 25.0, "SOP floor of 25 bar (no coil design pressure declared)"

    if src == "hipot_v":
        try:
            volts = float(decl.get("voltage") or 0)
        except (TypeError, ValueError):
            volts = 0.0
        if volts <= 0:
            return None, "the unit has not declared a supply voltage"
        # SOP 11.2 T9: 1500 V for a 230 V circuit, 2000 V for a 400 V circuit.
        return (2000.0, "2000 VAC for a 400 V circuit") if volts > 300 else \
               (1500.0, "1500 VAC for a 230 V circuit")

    if src == "cleanroom":
        # ISO 14644-1 Table 1, class N, particles >= 0.5 um per m3. Only the classes an AHU is
        # realistically tested against are listed; anything else declines rather than extrapolates.
        table = {"ISO5": 3520, "ISO6": 35200, "ISO7": 352000, "ISO8": 3520000}
        cls = str(decl.get("cleanroom") or "").strip().upper().replace(" ", "").replace("-", "")
        if cls not in table:
            return None, "the order has not declared an ISO 14644-1 class"
        return float(table[cls]), "ISO 14644-1 %s" % cls

    return None, "unknown limit source %r" % (src,)


# ── Judging a reading ────────────────────────────────────────────────────────────────────────────
# Four outcomes, and the difference between the last two is the whole point: a check nobody has
# filled in is INCOMPLETE, and a check whose limit cannot be worked out is UNDETERMINABLE. Neither
# is a pass. Collapsing either one into a pass is how a unit ships on a test that never happened.
PASS, FAIL, INCOMPLETE, UNDETERMINABLE, RECORDED = \
    "pass", "fail", "incomplete", "undeterminable", "recorded"


def _num(v):
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate_check(check, value, decl=None):
    """Judge one reading. Returns a dict with status, the limit applied and a human sentence."""
    op = check.get("op") or "note"
    out = {"key": check.get("key"), "label": check.get("label"), "unit": check.get("unit"),
           "op": op, "value": value, "src": check.get("src")}

    if op == "note":
        out["status"] = RECORDED
        out["message"] = "Recorded for the file; not judged."
        return out

    if op == "yes":
        if value is None or (isinstance(value, str) and not value.strip()):
            out["status"] = INCOMPLETE
            out["message"] = "Not yet confirmed."
            return out
        ok = value is True or str(value).strip().lower() in ("yes", "y", "true", "1", "ok", "pass")
        out["status"] = PASS if ok else FAIL
        out["message"] = "Confirmed." if ok else "Not confirmed — this is a fail, not a blank."
        return out

    limit, note = resolve_limit(check, decl)
    out["limitNote"] = note
    v = _num(value)
    if v is None:
        out["status"] = INCOMPLETE
        out["message"] = "No reading recorded."
        out["limit"] = limit
        return out
    if limit is None and op != "range":
        out["status"] = UNDETERMINABLE
        out["message"] = "Cannot be judged: %s." % (note or "no limit available")
        return out

    if op == "<=":
        out["limit"] = limit
        out["status"] = PASS if v <= limit else FAIL
        out["message"] = "%g %s (limit %g%s)" % (v, check.get("unit") or "", limit,
                                                 ", " + note if note else "")
    elif op == ">=":
        out["limit"] = limit
        out["status"] = PASS if v >= limit else FAIL
        out["message"] = "%g %s (minimum %g%s)" % (v, check.get("unit") or "", limit,
                                                   ", " + note if note else "")
    elif op == "range":
        lo, hi = check.get("limit"), check.get("limit2")
        if lo is None or hi is None:
            out["status"] = UNDETERMINABLE
            out["message"] = "Cannot be judged: the range is not defined."
            return out
        out["limit"], out["limit2"] = lo, hi
        out["status"] = PASS if lo <= v <= hi else FAIL
        out["message"] = "%g %s (allowed %g to %g)" % (v, check.get("unit") or "", lo, hi)
    else:
        out["status"] = UNDETERMINABLE
        out["message"] = "Unknown comparison %r." % (op,)
    return out


# A fail outranks everything: one failed check fails the step even if others are still blank.
_RANK = {FAIL: 0, UNDETERMINABLE: 1, INCOMPLETE: 2, PASS: 3, RECORDED: 4}


def evaluate_step(step, readings, decl=None):
    """Judge every check on a step. Returns {status, checks[], failures[]}.

    A step with no checks is judged PASS on its checks alone — whether it may actually be SIGNED is
    a separate question about predecessors and authority, and app.py answers that one.
    """
    readings = readings or {}
    results = [evaluate_check(c, readings.get(c.get("key")), decl) for c in (step.get("checks") or [])]
    if not results:
        status = PASS
    else:
        status = min((r["status"] for r in results), key=lambda s: _RANK.get(s, 9))
        if status == RECORDED:
            status = PASS          # notes alone do not hold a step open
    return {"status": status, "checks": results,
            "failures": [r for r in results if r["status"] == FAIL],
            "open": [r for r in results if r["status"] in (INCOMPLETE, UNDETERMINABLE)]}


# ── Progress ─────────────────────────────────────────────────────────────────────────────────────
# Counting signed steps, not opinion. Gates are worth more than a single operation because passing
# one is the thing that actually moves the unit; without that weighting a unit sitting at 8 of 9
# workstations reads nearly finished when it has not passed a single gate since G3.
STEP_WEIGHT = {"gate": 3, "ipqc": 2, "test": 2, "op": 1}


def route_progress(steps, signed_codes):
    """Percentage of the route completed, weighted by step kind. `signed_codes` is the set of step
    codes that carry a signature."""
    signed = {str(c).strip().upper() for c in (signed_codes or [])}
    total = done = 0
    for s in steps:
        w = STEP_WEIGHT.get(s.get("kind"), 1)
        if s.get("optional"):
            w = 0 if s["code"].upper() not in signed else w
        total += w
        if s["code"].upper() in signed:
            done += w
    return round(100.0 * done / total, 1) if total else 0.0


def next_steps(steps, signed_codes):
    """The steps whose predecessors are all signed and which are not signed themselves — what the
    shop floor can actually start right now."""
    signed = {str(c).strip().upper() for c in (signed_codes or [])}
    out = []
    for s in steps:
        if s["code"].upper() in signed:
            continue
        if all(str(a).strip().upper() in signed for a in (s.get("after") or [])):
            out.append(s)
    return out


def blocked_by(step, signed_codes):
    """Which of a step's predecessors are still unsigned."""
    signed = {str(c).strip().upper() for c in (signed_codes or [])}
    return [a for a in (step.get("after") or []) if str(a).strip().upper() not in signed]
