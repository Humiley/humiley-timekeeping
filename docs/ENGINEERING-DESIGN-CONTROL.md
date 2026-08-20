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

## Tests

`tests/test_eng_design_control.py` — twelve tests over the five things that would destroy the value
of the register if they broke: signature provenance, the freeze, both segregation rules, the
comment-response rule, and staff engineers being able to do their job.
