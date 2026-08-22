# Engineering Design Control

Conceptual → Basic → Detailed design, the drawings that come out of it, and the control around them.

Sidebar: **Engineering Design → Design Portfolio · Design Control**.

---

## Why it exists

A design consultancy's product is documents. The questions asked about a document a year later are
always the same:

* which revision was issued, and for what purpose?
* who prepared it, who checked it, who approved it?
* which design input does it answer?
* under whose authority did it change afterwards?

A folder of PDFs cannot answer any of that. This module can, and it is the reason every controlled
act in it is signed rather than typed.

## What it is built against

| Standard | What it gives this module |
|---|---|
| **ISO 9001:2015 §8.3** | The backbone. 8.3.2 planning (the Design Plan and the stage/gate structure), 8.3.3 inputs (the Design Input register), 8.3.4 controls (Reviews & Verification), 8.3.5 outputs (the MDR and revisions), 8.3.6 changes (the ECR/ECN register). |
| **ISO 19650-1/-2** | Information management. The CDE states (WIP → Shared → Published → Archived), suitability codes S0–S7 / A1 / B1, revision codes P01 / C01, and the fielded document-numbering format. |
| **ISO 10007** | Configuration management — identification, change control, status accounting, configuration audit. |
| **ASME Y14.35 / Y14.100** | Revision practice: a released drawing is changed by issuing a new revision with a recorded reason, never by editing the released one. |
| **FEL / IPA · RIBA · AIA** | The stage equivalents, so the same commission reads correctly to an EPC, UK or US client. |
| **Luật Xây dựng 2014/2020 + NĐ 15/2021** | *Thiết kế cơ sở / thiết kế kỹ thuật / thiết kế bản vẽ thi công*, and the *thẩm định → phê duyệt* sequence recorded on the stage gate. |

---

## The twelve tabs

| Tab | Register | What it is for |
|---|---|---|
| **Overview** | — | Earned vs planned progress, design SPI, what needs attention, progress by discipline, the SharePoint link. |
| **Stages & Gates** | `eng_stages` | Feasibility → Concept → Basic/FEED → Detail → IFC → As-built, each with entry/exit criteria and a **signed** gate decision. |
| **Design Inputs** | `eng_inputs` | One row per requirement, traceable to its source clause and allocated to the deliverable that answers it. Includes the **Requirements Traceability Matrix**. |
| **Deliverables (MDR)** | `eng_deliverables` | The Master Deliverable Register — every document this commission will produce, weighted for progress measurement. |
| **Drawing Control** | `eng_revisions` | The same register filtered to drawings, with the revision history opened up: revision, issue status, suitability, who signed. |
| **Reviews & Verification** | `eng_reviews` | Design reviews, IDC/squad checks, HAZOP, constructability, DQ, statutory appraisal — with findings and actions. |
| **Comments (CRS)** | `eng_comments` | The Comment Resolution Sheet. One row per comment, review codes 1–4, closed one at a time and signed. |
| **Change Control** | `eng_changes` | ECR/ECN. Classified, impact-assessed, **signed** by somebody other than the originator. |
| **Technical Queries** | `eng_tq` | Formal questions with a clock on them, to client / vendor / site. |
| **Transmittals** | `eng_transmittals` | Proof a document left, when, to whom, at which revision, and for what purpose. Generates a transmittal note on the letterhead. |
| **Team & Authority** | `eng_team` | Prepared / checked / approved authority, practising certificates (*chứng chỉ hành nghề*) and their expiry, and allocated workload. |
| **Document Structure** | — | The SharePoint folder tree, and where each register files its attachments. |

---

## How progress is measured

Counting documents measures nothing — the last 20% of a drawing is most of the work. Progress uses
the standard EPC **rule of credit**, weighted by each deliverable's own `weight` (manhours, or any
consistent points):

| Status | Credit |
|---|---|
| Not started | 0% |
| In progress | 15% |
| Drafted | 30% |
| IDC / squad check | 40% |
| Checked | 55% |
| Issued for review | 65% |
| Issued for approval | 80% |
| Approved with comments | 90% |
| Approved / IFC | 100% |

**Earned progress** = Σ(weight × credit) / Σ(weight). **Planned progress** comes from each
deliverable's own planned issue date, so no separate baseline is needed — the planned dates *are*
the plan. **Design SPI** = earned ÷ planned.

Cancelled deliverables leave the denominator; held ones stay in it at whatever credit they reached,
because the hold is exactly what the figure should be showing.

Issuing a revision advances the credit status automatically (IFR → *Issued for review*, IFA → *Issued
for approval*, IFC → *Approved / IFC*), so nobody has to keep two fields in step.

---

## Document numbering

Per-commission format string, tokens substituted at creation. Leave the document number blank and
the next free number in that (discipline, type) family is allocated. Numbers are never reused, so
gaps after a deletion are correct.

| Token | Source |
|---|---|
| `{PRJ}` | Project code | 
| `{ORG}` | Originator code (ISO 19650) |
| `{DISC}` | Two-letter discipline code |
| `{TYPE}` | Three-letter document-type code |
| `{STAGE}` | Stage code (CD / BD / DD …) |
| `{VOL}` `{LVL}` `{ROLE}` | ISO 19650 volume / level / role |
| `{NNN}` | Sequence, per family |

Presets: `Humiley standard` (`{PRJ}-{DISC}-{TYPE}-{NNN}`), `ISO 19650 (full)`, `EPC classic`,
`Stage-coded`.

**Revisions** follow the commission's scheme: ISO 19650 (`P01…` while preliminary, `C01…` once
contractual), numeric (`0, 1, 2`), or alpha (`A, B, C`). The next code is proposed from the issue
purpose and stays editable — plenty of drawings arrive from a client already at Rev 3.

---

## What is signed, and what freezes

Every controlled act goes through `/api/esign`, the same 21 CFR Part 11 path as a payment
certificate: the server re-authenticates the signer and stamps their identity. A browser can never
name the signer, and a POST carrying `issuedBy` has it stripped.

| Act | Sets | Frozen afterwards, except |
|---|---|---|
| Issue a revision | `issuedBy`, `issuedOn` | marking it **Superseded** when the next revision is issued |
| Stage gate decision | `gateDecision`, `gateSignedBy`, `gateSignedOn` | closing out gate actions |
| Authorise a change | `decision`, `decidedBy`, `decidedOn` | recording it **Implemented / Closed** |
| Issue a transmittal | `issuedBy`, `issuedOn` | recording the **acknowledgement** |
| Approve review minutes | `approvedBy`, `approvedOn` | (record stays editable; the signature does not) |
| Close a comment | `closedBy`, `closedOn` | (record stays editable; the signature does not) |

Issuing revision B automatically marks revision A superseded, so two revisions can never both read
as current.

### Who may sign

**Not** the portal access level. The person entitled to approve a general-arrangement drawing is the
discipline lead named on that drawing, and in a design office they are usually an ordinary staff
account. Authority is: a portal manager, **or** the commission's Design Manager / Lead Engineer /
QA Approver, **or** the person named as **Approver on that deliverable**.

Two segregation rules, with **no admin exemption** — an exemption would aim itself at the one person
most likely to be both the only preparer and the only approver:

* **Nobody approves their own external issue.** Applies to IFA / IFC / IFT / IFP / AB and to any
  A-series suitability. An **IFR** internal review copy stays self-serviceable, so a one-engineer
  discipline can still circulate a check print.
* **The originator of a change does not authorise it.**

And one content rule: a comment cannot be closed with nothing written against it.

---

## Files and SharePoint

Link the commission to a SharePoint folder on the **Overview** tab, then **Create in SharePoint**
(Graph) or download the PnP PowerShell script. Every file attached anywhere in the module is then
uploaded straight into the right folder and only a link is kept in the database.

The design tree is organised by **stage**, then by **what the document is** — not by the PMC project
tree, whose `03_Design_Engineering` node points here. Superseded revisions are retained in
`07_Issued_Transmittals/02_Superseded`, never deleted: the earlier revision is what the contractor
built from, and it is the first thing asked for if anything goes wrong.

Attachment routing lives in `_PM_UPLOAD_DIR` (shared with PMC) and is shown on the Document
Structure tab.

---

## Documents it produces

All on the Humiley letterhead, via `_brandHeader` / `_brandFooter`:

| Document | Code | Where |
|---|---|---|
| Design & Development Plan | `HML-ENG-DDP` | workspace header |
| Master Deliverable Register | `HML-ENG-MDR` | header, MDR tab (also CSV) |
| Design Status Report | `HML-ENG-STA` | workspace header |
| Drawing Register | `HML-ENG-DRG` | Drawing Control tab |
| Document Revision History | `HML-ENG-REV` | revision panel |
| Document Transmittal | `HML-ENG-TRN` | Transmittals tab |
| Comment Resolution Sheet | `HML-ENG-CRS` | Comments tab |
| Stage Gate Certificate | `HML-ENG-GAT` | Stages tab, after signing |

---

## Access

`eng` is an **opt-out** app, like CRM and Projects: everyone has it until an admin unticks *Design*
in **Access & Permissions**. Visibility is per commission — manager level and above see the whole
book of work; everyone else sees commissions where they are the Design Manager, Lead Engineer,
QA Approver, listed in `members`, or hold a row in the design team register.

Creating a **commission** is manager level. Every other register is staff-writable, because design
engineers are who fill them in.

---

## Getting started on a new commission

1. **Design Control → New Commission.** Set the project code (it prefixes every document number) and
   name a Lead Engineer — that is the design authority the portal looks for when a drawing is signed.
2. **Overview** → paste the SharePoint folder link → **Save & build folders**.
3. **Team & Authority** → add the team. This also gives them access.
4. **Design Inputs** → capture the client brief, the statutory requirements and the governing codes,
   one row each, with an acceptance criterion.
5. **Deliverables (MDR)** → **Seed from stage template**, then edit. Set a `weight` on each row.
6. **Stages & Gates** → plan the stages and set planned dates.
7. Work the registers. Raise revisions, issue and sign them, transmit them, close the comments.

---

## Holds, assumptions, and the interdisciplinary check

Three things the module described but did not enforce.

**The check now has to exist, and has to be somebody else.** `checkedBy` was a stamped field: a
drawing could reach IFC with it blank, or naming the person who drew it, provided one other name
appeared as the approver. Checking and approving are separate acts — the checker confirms the
content, the approver authorises the release — and ISO 9001 §8.3.4 asks for the verification, not
only the authorisation. An external issue (IFA / IFC / IFT / IFP / as-built) is now refused unless
a checker is recorded and differs from the preparer. IFR is untouched: a one-engineer discipline
must still be able to circulate a check print.

**Holds and assumptions are a register, not a text box.** They are different in kind and the
module now treats them differently:

| | what it is | what it does |
|---|---|---|
| **Assumption** | a number the design proceeded on because nobody had the real one | declared, listed, carried on the face of the document — does **not** block |
| **Hold** | an open question the design cannot answer | **blocks every external issue** of the deliverable it sits on |

A hold may sit on a drawing through every internal circulation. It must not reach somebody who
will build from it — an assumption that shipped and was never revisited is how a consultancy
inherits a liability it never priced. Closing a hold releases documents, so it is an e-signed act,
and the engineer who raised it does not close it alone.

**IDC is a matrix of signatures.** "IDC complete on every discipline" was a line on the Detail gate
checklist with nothing behind it. Each `eng_idc` row is one discipline signing that it checked its
own interfaces on one deliverable, and the engineer who prepared that deliverable cannot sign its
IDC. The matrix shows a cell per deliverable × discipline; a blank cell is not missing paperwork,
it is a check nobody has done.

## Codes and standards — at which edition

The question an auditor asks is never "did you follow the code". It is **which code, at which
edition, and show me the drawings were checked against that text**. A design basis that says
"designed to TCVN 5687" answers none of it: the 2010 and the 2024 differ, and so does what a
reviewer should have been looking for.

`eng_standards` holds the codes a commission is designed to, each with its **governing edition**,
its issuing body, its force (statutory / contractual / client standard / guidance), what it governs
here, and the clauses relied on. Adopting an edition is an e-signed act of the Design Manager or
Lead Engineer — it decides what every deliverable is verified against, so it is not a line anybody
can edit into the register.

**The edition cannot drift.** Once adopted, every deliverable has been designed and checked against
that text; moving the register to a newer edition silently re-bases the whole design and leaves the
drawings claiming compliance with something nobody verified. ISO 9001 §8.3.6 calls that a change to
a design input and wants the review, the authorisation and the record. So the edition may still
move — codes really are reissued mid-project — but only carrying the change reference that says who
looked at what it broke. Before adoption the register is still being assembled and moves freely.

A newer edition being published is **not** automatically a problem: a commission is designed to the
edition in force when it was fixed. Record it in *A newer edition exists* and the register will
carry the flag without pretending a decision has been made.

## Deviations and concessions

A **deviation** is asked for before the fact: the design cannot meet a clause and proposes
something else, with the reasoning that makes it acceptable. A **concession** is the same
conversation afterwards — what was built does not match what was specified, and somebody has to
decide whether to accept it.

Neither is a failure. What fails an audit is a departure nobody wrote down, or one agreed by the
same office that wanted it. So:

- a departure is agreed by somebody **other than** the engineer who asked for it;
- until it is agreed, the deliverable it sits on **will not issue externally** — an unaccepted
  departure is a non-compliance until somebody accepts it, and issuing it publishes that
  non-compliance as though it were the design. Internal circulation (IFR) stays open, because that
  is where the argument happens;
- a departure from a **statutory** code cannot be agreed inside the office at all. Internal
  agreement records that we find it acceptable; it cannot make a building lawful. The authority's
  or client's written agreement must be referenced on the record before it can be approved here.
  Rejecting one needs no external paper — saying no is always ours to do.

The register links each departure to the code and clause in the standards register, so the force of
that code (statutory / contractual / client / guidance) decides which rule applies.

## Design risk and safety in design

A designer's duty runs in an order: **eliminate** the hazard, then **reduce** it, then **control**
it, and only then **inform** the people who will inherit what is left. `eng_risks` is worth having
only if it records which of those actually happened.

- Signing a risk off as **Controlled** requires the action written down. "Controlled" with an empty
  action column is an opinion, and it is the register that gets produced after an accident and
  proves nothing.
- Marking one **Transferred** requires the record of how the people carrying it were told — the
  drawing note, the H&S file entry, the residual-risk schedule that went out with a transmittal. A
  residual risk passed to somebody who was never told stays ours.
- A drawing carrying an **uninformed** residual risk will not issue for construction. The duty to
  inform is discharged by the issue itself, so that is the last moment it can be caught.
- Scores are **computed** from likelihood × severity, initial and residual. A rating somebody typed
  is a number that can disagree with its own inputs.

An open risk blocks nothing — it is still being worked. Only one being passed on needs the telling.

## Register check — auditing the numbers and revisions

Document numbers and revision codes are generated for you, but only when somebody uses the
generator. A register accumulates drawings typed in by hand, imported from a client, renumbered
mid-project and superseded out of sequence, and none of that announces itself. A drawing office
finds out when two drawings share a number on site, or when the revision on the wall is not the
revision in the register.

The **Register Check** tab reads the whole commission and reports what does not line up:

| | |
|---|---|
| `DUPLICATE` | two deliverables on one number |
| `NO-NUMBER` / `SHAPE` | missing, or not the commission's format |
| `DISC-CODE` / `TYPE-CODE` | the discipline or type is not in its own number |
| `REV-PRELIM-EXTERNAL` | an IFC issued on a `P` code — ISO 19650 runs `P__` while preliminary, `C__` once contractual |
| `REV-DUPLICATE` | the same revision code twice on one drawing |
| `TWO-CURRENT` | two revisions issued with neither superseded |
| `NO-REASON` / `NO-FILE` | issued with no description of change, or nothing attached |
| `ORPHAN-REV` | a revision pointing at a deliverable that is not in the register |

**Warnings are not failures.** A client's drawings keep the client's prefix; a drawing with no
revision yet is simply new. The list separates what must be fixed from what is worth a look, and
every finding says what to do about it.

`_engCheckRegister` is a pure function — no DOM, no globals beyond the code tables — so
`tests/eng_register_check.js` runs **the code that ships** rather than a copy that would keep
passing after the real thing drifted. CI runs it on every PR.

## Awaiting response — the clock on everybody else

A design programme slips because approvals arrive late far more often than because drawings do, and
the evidence for that is contemporaneous or it is nothing. At the time it is one line; a year later
it is inbox archaeology, and by then the claim is a matter of opinion.

Every transmittal that asked for something carries a clock. The **Awaiting Response** tab shows what
is still running, how long it has been running, how often it has been chased and by whom — because
"we chased them three times" is worth exactly what its record is worth, which is why a chase is
e-signed and the server names the chaser.

Two refusals keep the record honest:

- **Responded** requires the date the answer actually arrived. Without it the register cannot say
  how long anything took.
- **Closed**, on a transmittal that asked for a response and never got one, requires somebody to
  write what happened. Closing it silently deletes the single fact an extension-of-time claim rests
  on: that we asked, on a date, and waited.

Transmittals issued for information ask for nothing and close freely — most do, and making those a
fight would empty the register.

## Effort and earned value

The MDR already carried a weight and a rule-of-credit status per deliverable — that is earned
value. Nothing recorded the hours that bought it, so the two halves never met and the only answer
to "are we over?" was somebody's feel for it. `eng_timelogs` books design hours against a
deliverable, and the **Effort & Earned Value** tab puts them together.

**SPI** is earned over planned: a ratio of weight to weight, so it is honest whatever the weights
mean.

**CPI** is earned over hours spent — and that is a cost index *only if the weights are hours*. A
weight of 40 might be forty manhours or forty points of relative size, and dividing points by hours
produces a confident number that means nothing. So the commission declares its weight unit, and
until it does the screen reports **Not measured** with the reason rather than showing an index. Same
for a CPI that would be infinite (nothing booked) or zero (nothing earned).

Planned value **steps** at the planned issue date. Nothing pretends to know the shape of the curve
in between; a smooth S-curve nobody agreed to is a number nobody can check.

Two things it surfaces that a total would hide: hours booked to the commission but to no
deliverable — they count as cost and earn nothing — and deliverables that have spent well past what
they have earned and are not finished yet.

## Recovering a chargeable change

A chargeable change that was built and never billed is the quietest way a design office funds a
client's change out of its own fee. It does not look like anything at the time: the ECN is approved,
the drawings are revised, the work is recorded as done, and the variation that was going to recover
it is still a conversation somebody meant to have.

Two points where it can still be caught.

**Approval** refuses a change whose chargeability is *"To be agreed"*. That is a deliberate
deferral, and it settles itself once the hours are spent — against us. A **blank** field is not
refused: it is a record made before anybody asked the question, and older changes are full of them.

**Implementation** refuses a change agreed as chargeable that has nothing to bill it against. The
variation does not have to exist at approval — usually it cannot, the scope is still being argued —
but by the time the work is recorded as done, the thing that recovers it has to be pointed at.
Absorbing the cost stays available; it just has to be a decision somebody is seen to make, which is
why the refusal offers both exits.

The Change Control tab totals what is unrecovered: each change looks handled on its own row, and
the sum is the only place the money shows.

## Tests

`tests/test_eng_design_control.py` — twelve tests over the five things that would destroy the value
of the register if they broke: signature provenance, the freeze, both segregation rules, the
comment-response rule, and staff engineers being able to do their job.
