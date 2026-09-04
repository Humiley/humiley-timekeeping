"""How this factory's units stand against what the European AHU industry recommends.

Source: **Eurovent 6/18 - 2022, "Quality criteria for Air Handling Units", First Edition,
published 13 October 2022.** Eurovent's Product Group 'Air Handling Units' represents most
manufacturers active on the European market, so this is the closest thing there is to a statement of
what the industry as a whole considers a good AHU. Section 13 of that document summarises its
specific recommendations; they are transcribed here with their citations.

── What this module is NOT ──────────────────────────────────────────────────────────────────────

It is not an acceptance criterion and nothing here refuses a gate. AHU-SOP-MASTER-001 is what this
factory has agreed to build to, and Eurovent 6/18 is a recommendation from an industry association.
Where the two differ that is a decision for the QA/QC Manager and the SOP owner, not for a module —
the last time this codebase quietly picked its own number, `ahu_route` was rejecting foam panels the
company's own inspection procedure accepts.

So this reports, in the same spirit as `ahu_route.SOP_DISCREPANCIES`: here is what the industry
recommends, here is what this unit declares, here is the difference. Somebody decides.

── The distinction that matters most ────────────────────────────────────────────────────────────

Eurovent 6/18 section 1.2:

    "Casing indicator values must be identified with the extension (R) for real units and (M) for
    model box according to EN 1886:2007."

A model box is not the unit. Per EN 1886 it is a two-section assembly of frame, doors, panels and
filter frame, with no windows, hoses, piping or dampers — built to compare casing constructions.
Eurovent's own minimums are stated in those terms and they are not interchangeable: **D2 (R)** and
**L2 (R)** are demanded of a real unit, while **T4 (M)** and **T3 (M)** are model-box figures.

A unit that declares "D2" without saying which is making an ambiguous claim, and a D2 established
on a model box does not satisfy a D2 (R) recommendation. That is reported as undeclared rather than
assumed either way.
"""

CITATION = ("Eurovent 6/18 - 2022, Quality criteria for Air Handling Units, First Edition, "
            "published 13 October 2022")

# Verdicts.
MEETS = "MEETS"
BELOW = "BELOW"
NOT_DECLARED = "NOT_DECLARED"
UNDETERMINED = "UNDETERMINED"

# The two bases a casing indicator value can be established on (EN 1886).
REAL = "R"
MODEL_BOX = "M"


def _rank(cls, prefix):
    """The numeric part of a class designation, or None if it is not one.

    For all five casing indicators class 1 is the best and the number rises as performance falls —
    D1 is stiffer than D2, L1 leaks less than L2, T1 insulates better than T2, and TB1 (kb 0.75-1)
    bridges less heat than TB5 (kb < 0.3). So "at least class N" means a number no higher than N.
    """
    s = str(cls or "").strip().upper()
    if not s.startswith(prefix):
        return None
    tail = s[len(prefix):].split("(")[0].strip()
    return int(tail) if tail.isdigit() else None


def _basis(cls):
    """The (R) or (M) suffix on a declared class, or None when it does not carry one."""
    s = str(cls or "").strip().upper()
    if "(R)" in s or s.endswith(" R"):
        return REAL
    if "(M)" in s or s.endswith(" M"):
        return MODEL_BOX
    return None


# ── Section 13: the recommendations, as published ───────────────────────────────────────────────
# `want_basis` is the basis Eurovent states the minimum in. Where it is None the recommendation does
# not name one.
CASING_MINIMUMS = [
    {"key": "classD", "prefix": "D", "worst": 2, "want_basis": REAL,
     "label": "Casing mechanical strength",
     "says": "Minimum mechanical strength class D2 (R)",
     "where": "Eurovent 6/18 section 13, Casing"},
    {"key": "classL", "prefix": "L", "worst": 2, "want_basis": REAL,
     "label": "Casing air leakage",
     "says": "Minimum casing air leakage class L2 (R)",
     "where": "Eurovent 6/18 section 13, Casing"},
    {"key": "classT", "prefix": "T", "worst": 3, "want_basis": MODEL_BOX,
     "label": "Thermal transmittance",
     "says": ("Minimum T3 (M) for units with cooling or air heating components; T4 (M) for units "
              "without thermodynamic air treatment"),
     "note": ("T3 is applied here because every family in this module's route carries a coil. A "
              "unit genuinely without thermodynamic air treatment is held to T4 instead."),
     "where": "Eurovent 6/18 section 13, Casing"},
    {"key": "classTB", "prefix": "TB", "worst": 3, "want_basis": None,
     "label": "Thermal bridging",
     "says": ("TB3 as a minimum; TB2 for outdoor units in a colder climate (ODA below -7 C in "
              "winter) with humidity in ETA above 40%, or with humidity in SUP above 40%"),
     "note": ("TB3 is applied as the floor. Whether TB2 is required depends on the installation "
              "climate and the humidity of the extract or supply air, which the production record "
              "does not hold — so a unit meeting TB3 is reported as meeting the minimum, not as "
              "meeting the requirement for its site."),
     "where": "Eurovent 6/18 section 13, Casing"},
]


def assess_casing(decl):
    """One row per casing indicator: what is recommended, what the unit declares, and the verdict.

    `decl` is `ahu.unit_decl(unit)`. Nothing here raises and nothing here refuses.
    """
    out = []
    for m in CASING_MINIMUMS:
        declared = (decl or {}).get(m["key"])
        row = {"label": m["label"], "says": m["says"], "where": m["where"],
               "declared": declared or None, "wantBasis": m["want_basis"]}
        if m.get("note"):
            row["note"] = m["note"]
        n = _rank(declared, m["prefix"])
        if n is None:
            row["status"] = NOT_DECLARED
            row["why"] = "The unit does not declare a %s class." % m["prefix"]
            out.append(row)
            continue
        row["basis"] = _basis(declared)
        if n > m["worst"]:
            row["status"] = BELOW
            row["why"] = ("%s is below the recommended minimum of %s%d."
                          % (declared, m["prefix"], m["worst"]))
        elif m["want_basis"] and row["basis"] is None:
            # The number is good enough; the claim is not complete. Eurovent's minimum names a
            # basis, and a class established on a model box is a different statement from the same
            # class established on the unit that ships.
            row["status"] = UNDETERMINED
            row["why"] = ("%s meets %s%d numerically, but the unit does not say whether it was "
                          "established on a real unit (R) or a model box (M). Eurovent states this "
                          "minimum as %s%d (%s)."
                          % (declared, m["prefix"], m["worst"], m["prefix"], m["worst"],
                             m["want_basis"]))
        elif m["want_basis"] and row["basis"] != m["want_basis"]:
            row["status"] = BELOW
            row["why"] = ("%s is declared on a %s basis; Eurovent states this minimum as %s%d (%s)."
                          % (declared,
                             "model box" if row["basis"] == MODEL_BOX else "real unit",
                             m["prefix"], m["worst"], m["want_basis"]))
        else:
            row["status"] = MEETS
            row["why"] = "%s meets the recommended minimum." % declared
        out.append(row)
    return out


# ── The filter classification this module still speaks ──────────────────────────────────────────
# EN 1886:2007 sets filter bypass leakage against EN 779 filter classes (F5-F9). EN 779 was
# withdrawn and replaced by EN ISO 16890 in 2018, and Eurovent 6/18 section 1.2.3 says so plainly:
#
#     "EN 1886:2007 sets maximum filter bypass leakage rates related to the filter class but it
#     still refers to the obsolete EN 779 and not to the EN ISO 16890 classification."
#
# It then gives the replacement table, reproduced below. `ahu_route.EN1886_BYPASS` still holds the
# EN 779 F8/F9 figures, because that is what AHU-SOP-MASTER-001 states and this module does not
# rewrite the SOP. The two are reported side by side instead.
ISO16890_BYPASS_MAX_PCT = [
    ("ISO ePM10 50% - 60% and ISO Coarse 30% - 95%", 5.0),
    ("ISO ePM2,5 50% - 60% and ISO ePM10 65% - 95%", 3.0),
    ("ISO ePM1 50% - 65% and ISO ePM2,5 65% - 95%", 2.0),
    ("ISO ePM1 70% - 75%", 1.0),
    ("ISO ePM1 80% - 95%", 0.5),
    ("Gas phase (carbon) filter", 0.5),
]

FILTER_STAGES = [
    "ISO ePM1 50% filter on the outdoor air inlet (first filtration stage)",
    "ISO ePM1 80% filter in the supply air (second filtration stage, if applicable)",
    "ISO ePM10 50% filter on the extract air inlet",
    "Minimum Eurovent filter energy efficiency class: C",
]


# ── Section 12.2: what must be delivered WITH the unit ──────────────────────────────────────────
# Compared against ahu_route.DOSSIER, which encodes the SOP's own list. Anything Eurovent names and
# the SOP does not is reported — not added. Whether the SOP adopts it is the SOP owner's decision.
DELIVERED_WITH_UNIT = [
    {"k": "datasheet", "label": "Technical data sheets and drawings",
     "matches": ("asbuilt", "datasheet", "drawing")},
    {"k": "spares", "label": "Spare parts list", "matches": ("spares", "spare_parts")},
    {"k": "instructions",
     "label": "Instructions for installation, commissioning and maintenance",
     "matches": ("om_manual", "instructions")},
    {"k": "doc", "label": "CE conformity declaration for the concerned directive",
     "matches": ("co_ce", "doc", "conformity")},
    {"k": "ce_mark",
     "label": "CE mark for units defined as machinery (not partly completed machinery)",
     "matches": ("ce_mark",)},
    {"k": "nameplate", "label": "Warnings and name plate on the unit",
     "matches": ("nameplate", "warnings")},
]

# Section 12.3 — the directives the manufacturer must comply with at the time of delivery.
DIRECTIVES = [
    "Machinery Directive (MD)",
    "Ecodesign Directive (ErP)",
    "Electromagnetic Compatibility Directive (EMC)",
    "Low Voltage Directive (LVD)",
    "Pressure Equipment Directive (PED), if applicable",
]

# Section 12.1 — what the manufacturer should do before the unit leaves.
BEFORE_DELIVERY = [
    "Assemble the whole unit or the spare parts (flat pack delivery is not recommended)",
    "Clean the unit and its components",
    "Secure the moving parts of the unit",
    "Check the production quality",
    "Protect the unit and its components against dust, dampness and weather conditions",
]


def document_gaps(dossier):
    """Eurovent 12.2 items the SOP's own dossier list does not appear to cover.

    Matched on the dossier entry's key and on its label, because the two lists were written by
    different people for different purposes and an exact key match would report every line as a gap.
    A loose match can only ever UNDER-report here, which is the safe direction: it will never invent
    a gap that is not there.
    """
    have = set()
    for d in (dossier or []):
        have.add(str(d.get("k") or "").strip().lower())
        for word in str(d.get("label") or "").lower().replace("/", " ").split():
            have.add(word.strip(",.()"))
    gaps = []
    for item in DELIVERED_WITH_UNIT:
        if any(m in have for m in item["matches"]):
            continue
        gaps.append({"label": item["label"], "where": "Eurovent 6/18 section 12.2"})
    return gaps


def summary(decl, dossier):
    """Everything this module can say about one unit, in one call."""
    casing = assess_casing(decl)
    return {
        "citation": CITATION,
        "casing": casing,
        "casingBelow": [c for c in casing if c["status"] == BELOW],
        "documentGaps": document_gaps(dossier),
        "filterStages": FILTER_STAGES,
        "isoBypass": [{"filter": f, "maxPct": p} for f, p in ISO16890_BYPASS_MAX_PCT],
        "directives": DIRECTIVES,
        "beforeDelivery": BEFORE_DELIVERY,
    }
