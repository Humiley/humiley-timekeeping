# How this module compares with the European AHU industry

An assessment of the AHU Production module against **Eurovent 6/18 – 2022, "Quality criteria for
Air Handling Units"**, First Edition, published 13 October 2022.

Written 21 August 2026.

## Why this document and not a survey of manufacturers

Individual manufacturers — Systemair, TROX, FläktGroup, Swegon, Robatherm, Menerga, Clivet, VTS,
Daikin, Carrier, Trane — do not publish their production routings, and what they do publish is
marketing. What they *do* publish, collectively, is Eurovent 6/18: their own product group, which
represents most manufacturers active on the European market, stating what distinguishes a good air
handling unit. That is a far better benchmark than a dozen brochures, and it is checkable.

Everything below cites a section of it. Where this module differs, the difference is reported and
**not** silently resolved — the same discipline `ahu_route.SOP_DISCREPANCIES` already applies to the
one place where AHU-SOP-MASTER-001 and EN 1886 disagree.

---

## What already matches

The EN 1886 class tables in `ahu_route.py` agree with Eurovent 6/18 exactly, figure for figure:

| Indicator | Our table | Eurovent 6/18 |
|---|---|---|
| Strength (±1000 Pa) | D1 ≤ 4, D2 ≤ 10, D3 > 10 mm/m | Table 2 — identical |
| Leakage at −400 Pa | L1 0,15 · L2 0,44 · L3 1,32 l/(s·m²) | Table 3 — identical |
| Leakage at +700 Pa | L1 0,22 · L2 0,63 · L3 1,90 l/(s·m²) | Table 4 — identical |
| Transmittance | T1 ≤0,5 · T2 ≤1,0 · T3 ≤1,4 · T4 ≤2,0 · T5 >2 W/m²K | Table 5 — identical |
| Thermal bridging | TB1 0,75–1 · TB2 0,6–0,75 · TB3 0,45–0,6 · TB4 0,3–0,45 · TB5 <0,3 | Table 7 — identical |

The gate-and-hold-point structure, the refusal to sign a failed reading, the segregation of duty at
a hold point and the as-built dossier are all consistent with §12.1's "check the production quality"
— and are considerably more rigorous than that sentence asks for.

The module's refusal to report an *achieved* thermal transmittance or thermal bridging class also
turns out to be exactly right for a reason the KPI work reached independently: Eurovent states those
two minimums on a **model box** basis (T4 (M), T3 (M)), because they are established on a test rig
and not on the production line.

---

## Finding 1 — casing classes do not say what they were measured on

**This is the most significant gap, and it is now visible in the app.**

> Eurovent 6/18 §1.2: *"Casing indicator values must be identified with the extension (R) for real
> units and (M) for model box according to EN 1886:2007."*

A model box, per EN 1886, is a two-section assembly of frame, doors, panels and filter frame — no
windows, hoses, piping or dampers. It exists to compare casing *constructions*. It is not the unit
that ships.

Eurovent's minimums are stated in exactly those terms and they are **not interchangeable**:

- **D2 (R)** and **L2 (R)** — demanded of a real unit
- **T4 (M)** / **T3 (M)** — model-box figures

Today a unit in this module declares `classD: "D1"` with no basis. Numerically that beats D2. As a
claim it is incomplete, and a D1 established on a model box does not satisfy a D2 (R) recommendation.
Every seeded demonstration unit has this gap.

**Done:** `ahu_eurovent.py` reads the basis where a declaration carries one (`D2 (R)`, `L2 (M)`) and
reports `Basis not stated` where it does not — rather than assuming either way. The traveller shows
it next to the AeroSelect selection.

**Still to decide (not code):** whether `classD`/`classL` should *require* the suffix at entry, and
whether AeroSelect should carry it through the selection handoff. Both are cheap once somebody
decides that a class without a basis is an incomplete declaration.

---

## Finding 2 — the filter classification is one standard out of date

`ahu_route.EN1886_BYPASS` is `{"F8": 1.0, "F9": 0.5}`. F8 and F9 are **EN 779** classes. EN 779 was
withdrawn and replaced by **EN ISO 16890** in 2018. Eurovent says so directly:

> §1.2.3: *"EN 1886:2007 sets maximum filter bypass leakage rates related to the filter class but it
> still refers to the obsolete EN 779 and not to the EN ISO 16890 classification."*

So this is not a mistake in our SOP so much as an inheritance from EN 1886 itself — but the industry
has moved, and a customer specification written today will say ePM1, not F9. Eurovent gives the
replacement table, now carried in `ahu_eurovent.ISO16890_BYPASS_MAX_PCT`:

| Filter | Max bypass |
|---|---|
| ISO ePM10 50–60% and ISO Coarse 30–95% | 5,0 % |
| ISO ePM2,5 50–60% and ISO ePM10 65–95% | 3,0 % |
| ISO ePM1 50–65% and ISO ePM2,5 65–95% | 2,0 % |
| ISO ePM1 70–75% | 1,0 % |
| ISO ePM1 80–95% | 0,5 % |
| Gas phase (carbon) filter | 0,5 % |

Eurovent §13 also names the filtration stages a unit should have: **ISO ePM1 50%** on the outdoor
air inlet, **ISO ePM1 80%** in the supply air where there is a second stage, **ISO ePM10 50%** on the
extract air inlet, minimum Eurovent filter energy class **C**.

**Deliberately not changed:** the acceptance limit test T4 applies. Swapping the SOP's stated figure
for a different standard's without the QA/QC Manager is precisely the mistake that put an invented
foam-density band into this module. Both tables are now carried, side by side, so the difference is
visible.

**Recommended:** add an ISO 16890 filter class to the unit declaration and let T4's limit resolve
from it, the same way the L and F limits already resolve from the declared class. That is a small
change to `ahu_route.resolve_limit` once the SOP names the classes.

---

## Finding 3 — three documents Eurovent requires are not on the dispatch list

Eurovent §12.2, what the manufacturer must deliver **with** the unit, against `ahu_route.DOSSIER`:

| Eurovent §12.2 | On our list? |
|---|---|
| Technical data sheets and drawings | Yes — as-built electrical drawings |
| Instructions for installation, commissioning and maintenance | Yes — O&M manual |
| CE conformity declaration | Yes, but **conditional** on "Export or CE-marked supply" |
| **Spare parts list** | **No** |
| **CE mark for units defined as machinery** | **No** |
| **Warnings and name plate on the unit** | **No** |

The name plate is the one that would embarrass the company first: it is what an inspector looks for,
and G6 currently releases a unit for dispatch without any record that one was fitted.

The conditional CE declaration is worth a second look too. §12.3 lists the directives that apply **at
the time of delivery** — Machinery, Ecodesign (ErP), EMC, Low Voltage, and Pressure Equipment where
applicable — and notes that location and configuration inside the EU do not affect whether MD, LVD,
ErP and EMC apply.

**Reported, not added.** `ahu_eurovent.document_gaps()` computes this against the live `DOSSIER`, so
it stays true if the SOP list changes. Adding a G6 criterion changes what the factory is refused for,
which is the SOP owner's decision, not a module's.

---

## Finding 4 — properties global practice specifies that this module does not record

None of these is wrong today; they are simply absent, and each is something a European customer
specification routinely names.

- **Corrosivity category** — EN ISO 12944 C1…CX decides the casing material. Eurovent §1.1.3 gives a
  material table per category and a default: *C3* for indoor and outdoor units, *C4* in a corrosive
  atmosphere, where nothing is specified. A coastal pharmaceutical site is C5.
- **Flammability class** — EN 13501-1. Eurovent recommends **A1 or A2 – s1 d0** for insulation, and
  notes national minimums differ (France B s3 d1, Germany A2 s1 d0, Sweden A2-s1 d0).
- **Damper leakage class** — EN 1751 class 2 for dampers closed during operation, **class 3** for
  supply and exhaust dampers in high-hygiene applications; air velocity across a damper max 8 m/s.
- **Heat recovery** — EATR ≤ 5 %, OACF 0,90–1,1, efficiency class **H2** per EN 13053.
- **Energy** — SFP<sub>int</sub> below the Regulation (EU) 1253/2014 limit, SFP<sub>v</sub> 1300–1800
  W/(m³/s), minimum Eurovent AHU Energy Efficiency Class **B**.
- **Hygiene** — VDI 6022 generally, **DIN 1946-4** for hospitals, EN ISO 846:2019 for microbial
  resistance of materials, and Eurovent's separate HAHU certification programme. This module has a
  `hygienic` family but does not record which hygiene standard a unit was built to.

The cheapest of these to add is corrosivity category: it is a single declared field, it changes what
material the BOM should call for, and it is the one most likely to be wrong on a Vietnamese coastal
project.

---

## What was built alongside this document

- `ahu_eurovent.py` — the recommendations, with citations, as reference data; a per-unit casing
  assessment; and the document-gap computation. Pure: no database, no network, nothing that refuses.
- `tests/test_ahu_eurovent.py` — 19 tests, most of them about what the module declines to conclude.
- `/api/ahu/process` now carries a `eurovent` block; `/api/ahu/unit/<id>` carries the per-unit
  assessment.
- "Against the industry recommendation" panel on the traveller, next to the declaration.

## What was deliberately not built

No gate criterion changed and no acceptance limit moved. Every finding above is reported next to
what this factory's own SOP says, for a person to decide. AHU-SOP-MASTER-001 is what the company has
agreed to build to; Eurovent 6/18 is what the industry recommends. Those are different kinds of
document and the difference between them is information, not a defect to be auto-corrected.

## Sources

- [Eurovent 6/18 – 2022, Quality criteria for Air Handling Units](https://www.eurovent.eu/wp-content/uploads/eurovent-rec-6-18-quality-criteria-for-air-handling-units-2022-en-2.pdf)
- [Eurovent Certita Certification — Air Handling Units programme](https://www.eurovent-certification.com/en/cms/news/programme-focus-air-handling-units-ahus)
- [FläktGroup — EN standards and the expectations of AHUs](https://www.flaktgroup.com/en/flaktgroup-insights-driving-innovation/the-en-standards-and-the-expectations-of-ahus/)
- EN 13053:2019, EN 1886:2007, EN 308:2022, EN 16798-3:2017, EN ISO 16890, EN 1751, EN 13501-1,
  EN ISO 12944, EN ISO 846:2019, VDI 6022, DIN 1946-4, Regulation (EU) 1253/2014, Regulation (EU)
  2019/1781 — as cited by Eurovent 6/18 §"Key referred standards and regulations".
