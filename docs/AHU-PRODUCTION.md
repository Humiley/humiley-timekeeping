# AHU Production

Order to dispatch, against the company's own AHU-SOP-MASTER-001. Seven stages, six gates, nine
workstations, five in-process hold points and a thirteen-item test matrix — encoded so the process
can refuse.

Sidebar: **AHU Production → Production Board · AHU Register · Orders & Contracts · Production
Standard**.

---

## Why it exists

The process was already written down. `AHU Production/00_Master_Documents/AHU-SOP-MASTER-001` is a
careful bilingual procedure, and the factory follows it. What a folder of Word forms cannot do is
*refuse*: nothing stopped a section being foamed before the frame was inspected, a unit being
kitted against a design nobody had released, or a casing leakage test being signed off with the
box left blank.

The questions asked about a delivered AHU a year later are always the same:

* which order was it built against, and at what specification?
* who did each step, and who inspected it?
* what was actually measured, and against what limit?
* what went into it — which fan, which coil, which batch?
* was anything non-conforming, and who accepted the disposition?

This module answers all five, because every controlled act in it is signed rather than typed.

## What it is built against

| Source | What it gives this module |
|---|---|
| **AHU-SOP-MASTER-001** | The backbone: the seven stages, gates G1–G6 with their exit criteria, workstations WS-01…09, hold points IPQC-1…5 and the T1–T13 test matrix. |
| **HML-AHU-DS-MOD / PKG / HYG / OUT-001** | Which steps apply to which product family, the panel construction (PU 45 kg/m³, λ ≤ 0.022 W/mK) and the default EN 1886 class targets per family. |
| **EN 1886** | The published class thresholds — *not* retyped from the SOP. Same tables AeroSelect classifies against, so the class a unit is sold as and the class it is tested against cannot drift apart. |
| **EN 1216 / AHRI 410 · IEC 60204-1 · ISO 14694 · ISO 14644-1 · VDI 6022 · AHRI 260** | The individual test methods. |
| **ISO 9001:2015 §8.5, §8.6, §8.7** | Production control, release of product, control of nonconforming output. |
| **21 CFR Part 11** | The signature itself — the same `/api/esign` path as a payment certificate. |

---

## The screens

| Screen | What it is for |
|---|---|
| **Production Board** | Opens on the process itself: seven stages left to right, the gate that closes each, and how many units sit in each right now. Click a stage to filter the table below it. Then every unit on the floor — its stage, completion, what it is waiting for, what is holding it. Updates within about a second of a sign-off, and still refreshes on a 30 s timer so a dead connection cannot leave it looking live. |
| **AHU Register** | One row per physical unit, by its Production Identification Number. |
| **Orders & Contracts** | Customer POs and contracts, the units built against each, and the contract review that gate G1 checks. |
| **Capacity & Load** | SOP §6.7's rolling 8-week load chart, plus elapsed time against each step's tact. Needs a weekly capacity to give a verdict; without one it reports hours and says so. |
| **Quality Evidence** | Whether the measurements this factory has signed can be defended: the instrument register, who is qualified for what, and the reverse search that answers "which units got this part". |
| **Production Standard** | AHU-SOP-MASTER-001 rendered from the server's own copy — so "what is IPQC-3 supposed to measure?" gets the same answer the gate will enforce. |

## Starting from nothing

The module works the day it is switched on — a unit can be registered, routed and signed with none
of the registers below filled in. What the registers buy is the ability to *defend* what was signed,
and they are worth filling in roughly this order.

**1. Name the people on each order.** Production lead, QC inspector, sales owner. Authority is
checked against these names, so an order with none means a manager has to sign everything, and the
alert for a failed step has nobody to reach.

**2. Set the weekly capacity** (Capacity & Load → *Weekly capacity*). Productive hours the floor
actually has in a week. Until it is set the load chart reports hours with **no verdict**, which is
deliberate: a chart drawn against a guessed capacity looks exactly like one drawn against a real
one, and this is the number a delivery promise rests on.

**3. Register the test instruments** (Quality Evidence → *Register an instrument*). Anything that
produces a number on a test or hold point: manometer, hi-pot tester, anemometer, vibration meter.
The calibration due date is the field everything turns on — leave it blank and the instrument reads
`UNKNOWN`, never valid, because "we have no record" and "it is in calibration" are opposite claims.

Once they are registered, the picker appears on every test and hold-point panel. A step signed
against an instrument the register shows as **out of calibration is refused**, whether or not any
rule is switched on. That one is not a policy setting: signing a measurement to an instrument known
to be out of calibration produces a record the company cannot stand behind.

**4. Record who is qualified** (Quality Evidence → *Record a qualification*). Scope can be a whole
kind — `ipqc`, `test` — or specific codes, `T3, T4`. A kind is how you say "signed off for hold
points" without listing five codes.

**5. Then, and only then, tighten the rules.** Two settings, both off by default:

| Setting | What it does when on |
|---|---|
| `ahu_require_instrument` | A test or hold point cannot be signed without naming the instrument that measured it. |
| `ahu_require_qualification` | A test or hold point cannot be signed by somebody with no current qualification for it. |

They are off by default on purpose. Switching either on against an empty register would stop every
test in the building, and a control that has to be switched off again on its first morning is one
nobody trusts afterwards. Until they are on, the gaps are still **reported** — Quality Evidence
names every signed test that recorded no instrument, by unit and step code.

**What to look at afterwards.** Quality Evidence separates three states that a single red/green
would report identically: expired, none on file, and *on file with no expiry date recorded*. The
third is the one that matters most and the one a report sorted by due date can never show you,
because an instrument with no due date does not appear in it at all.

## The traveller

Open a unit and you get its whole life across seven tabs: **Route & sign-off · Documents &
drawings · Materials · Traceability · Non-conformance · Packing & dispatch · As-built dossier**.

The route tab is the heart. Each step shows the work instruction that governs it, the form it is
recorded on, the standard it is judged against, and its typical cycle time. A step that cannot
start yet says which step it is waiting for. A gate that cannot pass says exactly what is missing.

---

## Where the process lives

Split deliberately across two modules, and the split is what makes it testable:

* **`ahu_route.py`** — the process itself. Pure: no database, no request, no clock. The order of
  the steps, the document governing each one, and the quantity that has to be measured with the
  limit it has to meet. Exercised by `tests/test_ahu_route.py` (51 tests).
* **`ahu.py`** — the part that has to look things up. What this unit declares about itself, which
  steps are signed, whether a gate's exit criteria are actually met, and what goes in the dossier.
  Exercised by `tests/test_ahu_gates.py` (44 tests).
* **`app.py`** — authority and enforcement, exercised by `tests/test_ahu_api.py` (25 tests).

## A limit is never invented

Where the acceptance figure is a property of the **unit** rather than of the process, the check
carries `limit_from` and the limit is resolved from what the unit declares:

| Check | Resolved from |
|---|---|
| Casing deflection (T2) | the declared EN 1886 D class — D1 ≤ 4, D2 ≤ 10 mm/m |
| Casing leakage (T3) | the declared L class — L1 0.15, L2 0.44, L3 1.32 l/(s·m²) at −400 Pa |
| Filter bypass (T4) | the declared F class — F8 ≤ 1 %, F9 ≤ 0.5 % |
| Coil test pressure (T5, IPQC-3) | 1.5 × the declared design pressure, floor 25 bar |
| Hi-pot voltage (T9) | the declared supply voltage — 1500 V for 230 V, 2000 V for 400 V |
| Particle count (T13) | the declared ISO 14644-1 class |

A unit that declared no class **cannot be judged**, and the step reports *undeterminable* — never
*pass*. That distinction is the point: a missing declaration reading as a pass would put a signed
dielectric or leakage test on a CE-facing document with nothing behind it.

A blank class inherits the Design Standard default for its family. Cleanroom class and supply
voltage are **never** defaulted, because an assumed value there would set a test limit nobody chose.

## What refuses, and why

Every one of these is enforced server-side, on the signature, not in the browser:

| Rule | Why |
|---|---|
| A step cannot be signed before its predecessors | The "step by step" promise. A unit cannot be foamed before it is framed. |
| A failed reading cannot be signed off | The server computes pass/fail from the reading against the limit. A fail outranks a blank, so "we haven't finished checking" cannot hide "this one failed". |
| A blank or unresolvable reading cannot be signed off | Incomplete and undeterminable are distinct from pass, and neither is one. |
| A gate cannot pass until its exit criteria are met | Each of the 22 criteria names the specific thing that is missing — *which* BOM line, *which* step, *which* document. |
| A criterion that is unimplemented or raises **blocks** | Silently passing an unknown criterion is how a gate ends up checking nothing. |
| A hold point cannot be signed by whoever did the work | SOP §10.3 puts a hold point after a station so a second pair of eyes sees it. **No manager exemption** — a working supervisor is exactly the person most likely to be both. Checked *before* authority, so somebody who holds QC authority *and* built it is still caught. |
| A non-conformance is closed by somebody other than its raiser, and needs a disposition | ISO 9001 §8.7. |
| A signed step's readings are frozen | The signature attests to the numbers that were there when it was given. Notes and photos stay open — a fact recorded *about* a step is not a change *to* it. |
| A browser can never name the signer | `signedBy` and friends are stripped on create and restored from the stored row on every update. Identity comes from `/api/esign` and nowhere else. |

## Rebuilding a route

A specification change re-reads the route from the standard. It is safe by construction:
every recorded reading and signature is carried forward, and a **signed** step that has left the
route is kept and flagged `orphan` rather than deleted — somebody has to decide what it now means.
An unsigned step that leaves simply goes.

## The as-built dossier

The unit's birth certificate, assembled server-side so the document and the screen cannot tell
different stories: the order it was built against, the design and selection reference, the declared
performance basis, every step with who signed it and what was measured against which limit,
component serials, non-conformances and their dispositions, and the documents travelling with the
unit. Rendered on the Humiley letterhead.

Gate G6 refuses dispatch until every document SOP §12.5 requires is attached.

---

## Integration points

* **AeroSelect** — a unit carries its `selectionRef` and its declared duty and EN 1886 classes, and
  gate G2 requires a selection report. The EN 1886 tables here are kept identical to
  `packages/calculations/src/standards.ts`; `tests/test_ahu_route.py::test_en1886_thresholds_match_aeroselect`
  reads the AeroSelect checkout and asserts they agree (skipped when it is not present).
* **Engineering Design Control** — link a unit to an `eng_projects` commission and an open
  engineering change on that design holds gate G2. A unit with no design link reports no open
  changes rather than inventing a blocker.

## Known divergence

`SOP §11.2` test T2 reads "D2: ≤ 4 mm/m". EN 1886 places 4 mm/m at **D1**; D2 is ≤ 10 mm/m.
Encoding the SOP's figure would make the factory reject D2 casings that pass the standard the unit
is sold against, so the published threshold is applied and the difference is recorded in
`ahu_route.SOP_DISCREPANCIES` — surfaced on the Production Standard screen, so it gets corrected at
the next revision rather than quietly diverging.

## Tools

* `tools/check_index_js.py` — `node --check` over every inline script block in `templates/index.html`.
  A bad splice there fails silently in the browser rather than loudly.
* `tests/vi_duplicate_keys.js` (already on main, in CI) — finds `_VI` keys claimed twice with
  *different* values. Worth running before touching the dictionary: `_VI` is one flat object shared
  by the whole portal, so a bare generic word is a claim on that word in every module and the later
  definition wins silently. Every VN key this module adds is qualified for that reason —
  `Production stage`, not `Stage`.
* `tools/seed_ahu_demo.py` — a small demo order with three units, plus the evidence registers, for
  looking at the module with real data in it. Writes to `TK_DB_PATH`; point it at a throwaway file.
  It is idempotent: re-running adds nothing.

  The seeded examples are deliberately **not** all healthy — one instrument is out of calibration,
  one has no due date at all, one qualification has expired, and two units share a fan batch. Those
  are the states the screens exist to separate, and a demo where everything is green demonstrates
  nothing. An empty screen also cannot be told apart from a broken one, which is why the registers
  are seeded at all.
