# AHU Production — what is built, what is missing, what to build next

An assessment of the production platform against **the company's own documents**, not against a
generic MES feature list. Every gap below is something AHU-SOP-MASTER-001 or a Design Standard
already asks for, or something the module captures data for but does not use.

Written 21 August 2026, after the module went live.

---

## Where it stands

Order to dispatch is digital and enforced. A unit cannot move to a step whose predecessor is
unsigned, a reading that fails its limit cannot be signed off, a gate cannot pass until its exit
criteria are met, and nobody can sign off a hold point on work they did. Every controlled act goes
through the same Part 11 signature path as a payment certificate, and the as-built dossier assembles
from records that were signed when the work happened.

That is the spine. What follows is what it is missing to be a production *management* platform
rather than a production *record*.

---

## Just added: the SOP's own KPIs

**SOP §1.4 defines eight KPIs with a target and an owning function.** None of them had ever been
computed — they were a table in a Word file. They are now arithmetic over signed records, on the
Production Board.

Five are computed: First-Pass Yield, On-Time Delivery, Casing Leakage Class, Casing Strength Class,
and Lost-Time Incident Rate (when the exposure hours are supplied).

**Three say `NOT MEASURED`, with the reason.** Thermal bridging and thermal transmittance are
established on a test rig with a thermal camera and a calibrated chamber — no step on the production
line measures either, so the class a unit is *sold* as is recorded and the class *achieved* is not
something this factory can report. Customer complaints are captured nowhere in the portal.

Showing 100% for a class nobody tests would have been the worst possible version of this feature.

One subtlety worth keeping: the KPI asks for the class **achieved**, which is not pass/fail. A
casing sold as L1 and measured at 0.30 l/(s·m²) *fails its contract* and *achieves L2*. The unit is
a warranty problem; the casing line is performing to L2. Both facts matter and a pass rate reports
neither, so the reading is classified rather than judged.

---

## The gaps, in the order I would close them

### 1. Capacity and load — the SOP asks for this by name

> *SOP §6.7: "Capacity check by PMO using rolling 8-week load chart."*

This is named as the **control** against the risk "delivery date shorter than feasible", and it does
not exist. Sales can still promise a date the floor cannot meet, which is the single most expensive
mistake in the whole process and the one the document already identifies.

What it needs: each unit's route carries SOP tact times per workstation, so the hours a unit will
consume are already known. Sum by week across live units, against a stated capacity per station,
and the answer to *"can we take this order for September?"* becomes a screen rather than an opinion.

**This is the highest-value item on the list.** The data is captured; nothing reads it.

### 2. Actual versus tact — the data is already there and unused

Every step row records `startedOn` and `signedOn`, and `ahu_route` carries the SOP's typical cycle
for each workstation. Nothing compares them.

Comparing them gives, for free: which station is the bottleneck, which unit is running long *right
now* rather than at the end, and whether the SOP's tact times are actually true — they were written
before the line ran.

Wire it into the board as an on-track / running-long flag per unit, and into the KPI band as average
cycle by station.

### 3. Nobody is told anything

The board shows a failed step and a held gate. **Nothing pushes.** A hold point fails at 16:00 and
QA/QC finds out when somebody next opens the screen.

The portal already has Web Push and an approval-notification path. Failed steps, held gates, open
NCRs past an age, and units at risk of their delivery date should reach the owning function the way
an approval does. This is small, and it is the difference between a dashboard and a system that runs
a factory.

### 4. The shop floor is still using a desktop screen

Signing a step means navigating to the unit, the tab, the step. At a workstation, with gloves, that
is friction, and friction is what makes people batch their sign-offs to the end of the shift —
at which point the timestamps are fiction and the "real time" board is hours stale.

What it needs: a **scan-to-step** mode. The traveller card already carries the PIN; add a QR code,
scan it on a tablet, and land directly on that unit's next actionable step with the readings keyboard
open. Large touch targets, no chrome, offline-tolerant.

The evidential value of the whole module depends on people signing *at the point of work*. This is
the item that most affects whether they do.

### 5. Materials are typed twice

`ahu_bom` kitting, shortages and IQC status are entered by hand, while Procurement is a full app in
the same portal with purchase orders and receipts. A BOM line and a purchase order line are the same
fact recorded twice, which is how a shortage stays invisible until the kitting gate refuses.

Link them. Gate G3's "no shortage" criterion should read from what was actually received.

### 6. The board polls; it does not push

`ahuRenderBoard` re-fetches every 30 seconds. That is adequate and it is not real time. With push
already in the portal, the board could update when a step is signed rather than up to 30 seconds
later — and on a wall display that difference is visible.

Lower priority than it sounds: 30 seconds is fine for a board. Do 3, then 6, then this.

### 7. Two documented figures still disagree with each other

Not code — but they will bite production:

* **Panel foam density is stated four ways**: DS-COMP `45`, SOP `38–45`, IPQC-2 `42–48`, product
  catalogue `42`. The portal follows IPQC-2, because that is the inspection criterion. The set
  should agree with itself.
* **DS-PKG-001 specifies 38 kg/m³** where the module applies one band to every family. A packaged
  unit built to its own Design Standard would **fail** IPQC-2 in the portal. One of those documents
  is wrong and I have not guessed which.
* **The catalogue says PIR where the Design Standards say PU** — different materials, different fire
  behaviour, and the catalogue is what customers are shown.
* **SOP §11.2 D-class** — corrected in source, still unapproved, PDFs still stale. See
  `DOCUMENT-CHANGE-RECORD_EN1886-D-class.md`.

---

## Deliberately not recommended

**A single "production health score."** Averaging first-pass yield, on-time delivery and a casing
class produces a number the SOP does not define, that moves for reasons nobody can trace, and that
nobody can act on. Eight KPIs with owners is more useful than one number with none.

**Predicting completion dates from historical cycle times.** Tempting, and it would be a guess
dressed as a forecast until there is a year of real cycle data. Build item 2 first, let it collect,
then revisit.

**A customer-facing portal for FAT witnessing.** Real value, but it puts the company's production
record in front of a client — an access-control and commercial-terms decision, not an engineering
one. Worth doing after the internal items, deliberately.

---

## Suggested order

| | Item | Why first |
|---|---|---|
| 1 | Capacity and load chart | The SOP names it as a control; it prevents the most expensive mistake |
| 2 | Actual vs tact | Data already captured, nothing reads it — cheapest real insight available |
| 3 | Push notifications | Turns a dashboard into something that runs a factory |
| 4 | Scan-to-step shop-floor mode | Determines whether sign-offs happen at the point of work |
| 5 | Procurement ↔ BOM link | Removes a double entry and makes G3 truthful |
| 6 | Live push for the board | Genuine real time, but 30s was never the problem |
| 7 | Document reconciliation | Not code — but a wrong figure in a controlled document outlives any of this |
