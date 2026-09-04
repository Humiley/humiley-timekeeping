# Daily Report

The site's daily report to the client, as a portal screen that prints itself.

It reproduces the report the client already receives — the two files it was built against are
`DailyReport_Mega_Taikisha_09.01.2026.pdf` and `DailyReport_Mega_Newtecons_09.02.2026.pdf` — with
the same masthead, the same ten sections, the same column sets and the same footer. What changes is
where the data comes from: instead of somebody refreshing a Power BI file and exporting it by hand,
the site fills in SharePoint forms and the portal assembles the report from them.

- **Daily Report** (`dr-report`) — the report itself, tabbed as ten sections, with **Export PDF**.
- **Report Setup** (`dr-setup`) — set each contractor up once. Manager level and above.

## What is on it

| Page | Section | What it holds |
|---|---|---|
| 1 | Overview | Project header, the two durations, the headcount cards with their day-on-day movement, the site overview photos |
| 2 | Weather & Manpower | Table 1 weather; 2.1 management staff; 2.2 workers; the two seven-day bar charts |
| 3 | Equipment-Materials | 3. Equipment & machinery; 4. Material delivery |
| 4 | Work Progress | 5.1 Work completed today, grouped by category |
| 5 | Progress Gantt | 5.2 The bar chart, with a today line and per-item accumulated progress |
| 6 | Work Plan | 5.3 Next day work plan |
| 7 | Daily Photos | 6. Daily progress photos, numbered per category |
| 8 | Document & Defect | 7. Site document exchange (all four groups, every day); 8. Defect check list |
| 9 | Inspection | 9.1 Daily inspection; 9.2 Next day inspection plan |
| 10 | Safety & Recomm. | 10. Safety control activities; 11. Requests & recommendations |

Sorting, filtering and editing all work on screen: click a column heading to sort, use the
Contractor / Month / Week / Date / Category strip to filter, and edit a row through the register
like any other portal record. The filter strip and the tab strip print on every page, because they
say which contractor and which day the sheet is about — the source report does the same.

## Setting a contractor up (once)

Report Setup → **Contractors**:

1. **Identity** — the contractor's name, its project, and **its logo**. The logo prints in the
   footer of every page of that contractor's report. The Humiley mark in the header is fixed and is
   not editable. The client's logo (the left of the masthead) lives on the project, not here.
2. **The columns its tables count** — each contractor counts different roles and trades, so tables
   2.1 and 2.2 are built from these lists. Taikisha counts Cad Staff and Supervisors; Newtecons
   counts Quantity Surveyors and a Secretary. A headcount that arrives under a name not on the list
   is still shown — listed under the table and left out of the total, never silently added to it.
3. **Work categories** — the order 5.1, 5.2, 5.3 and the photo grid group in.
4. **Safety checklist** — leave empty for the eleven standard checks.
5. **The SharePoint lists** — see below. Then press **Check the lists**.

## The SharePoint side

A SharePoint form writes **one list item per submission**, and this report has eleven repeating
tables on it. There is no form that submits a variable-length table into one item, so the
arrangement the portal is built for is **a list per table**, each row carrying the date and the
contractor it belongs to:

| List | Contributes |
|---|---|
| Daily Report Header | one row per contractor per day: weather, headcount per role |
| Work Progress | many rows: category, item, % today, % overall, start, finish |
| Next Day Work Plan | many rows: item, location |
| Equipment & Machinery | many rows: item, quantity, unit |
| Material Delivery | many rows: item, document code |
| Site Document Exchange | many rows: group (7.1–7.4), item, document code, category |
| Defect Check List | many rows: description, corrective action, dates |
| Daily Inspection | many rows: item, location, document code, status |
| Next Day Inspection Plan | many rows: item, location, time |
| Safety Control Activities | many rows: check, status |
| Requests & Recommendations | many rows: recommendation, location |
| Daily Progress Photos | many rows: a photo, a category, a caption |

Every list needs a **date** column and — unless the list serves only one contractor — a
**contractor** column. Those are what attach a row to a day and a company; a row that cannot say
which day it belongs to is not imported at all, and the sync says how many it skipped.

**Column names are matched, not assumed.** SharePoint internal column names are whatever the person
who built the list typed, then frozen, so `Daily Progress (%)` is internally something like
`Daily_x0020_Progress`. Report Setup's **Check the lists** matches your real columns against the
report's fields and tells you, per list, what it found, what it could not find, and which of your
columns nothing claimed. A list whose essential columns cannot be found is **refused** by the sync
rather than imported blank — an empty section on this report looks the same as a quiet day on site.

### Photos

Two arrangements work with the Graph permission the portal already holds:

1. **A document library folder** — put the day's photos in a folder and give Report Setup its link.
   This is the arrangement to prefer.
2. **A form question that uploads the file** — the list item then holds a sharing link the portal
   follows.

**The paperclip on a classic SharePoint form does not work**, and no extra permission changes that:
Microsoft Graph has no way to reach list-item attachments. Report Setup says so on the page rather
than leaving the photo section quietly empty.

Photo bytes are never copied into the database. A photo row holds its SharePoint reference and the
image is streamed through `/api/dr/photo/<id>`, which is also what lets the photos appear in the
exported PDF — a cross-origin SharePoint URL taints the canvas and the export comes out with blank
frames.

### Ops

The sync uses the app-only Graph token the portal already has (`TK_M365_CLIENT_SECRET`,
`Sites.Read.All` / `Sites.ReadWrite.All`). With no secret configured the screen says so instead of
failing obscurely. **Sync from SharePoint** pulls one day, or a range of at most 31 days; re-syncing
a corrected form replaces that day's rows rather than stacking a second copy underneath, and a photo
somebody uploaded by hand in the portal survives a re-sync.

## The PDF

**Export PDF** builds an A4 portrait file: client logo left, `DAILY REPORT` centre, Humiley mark
right; `Page n/N` and the contractor's logo in the footer. The masthead and footer are drawn
natively so the type is crisp and the page numbers are real; the body of each section is captured
and placed.

- **Auto-fit.** A section a little taller than the page is scaled down to fit — down to 74%, below
  which it is split across sheets instead, because a legible second page beats an illegible first
  one. A 30-row work-progress table and the full Gantt each fit one page this way.
- **Every section is measured before the first page is drawn**, so `Page 1/12` is right on a report
  that turns out to need twelve sheets.
- **The export does not depend on the device.** The off-screen render is pinned to the printed
  layout, so exporting from a phone produces the same document as exporting from a laptop.

## Two things the report says out loud

Both are deliberate, and both exist because the failure they prevent is a report that looks complete
and is not:

- **An unanswered safety check is not a passed check.** The source report shows eleven green ticks;
  defaulting the tick on would produce that page for a day nobody walked the site. An absent answer
  renders as "Not answered" and is listed above the report.
- **A headcount under a column that is not on the table is not in the total.** It is shown under the
  table and named in the warnings, so the number can be found rather than quietly disappearing.

## The two durations are counted differently, on purpose

Measured off both source files:

    Start 2025-11-14, End 2027-04-28   -> "Total Construction Duration (Days): 530"   (exclusive)
    Start 2025-11-14, as-of 2026-09-01 -> "Construction Duration to Date (Days): 292" (inclusive)

That inconsistency is the behaviour of the report the client has been reading every morning, so it
is reproduced rather than tidied — a headline duration that silently moved by a day the week we took
the report over is a report nobody trusts again. `daily_report.INCLUSIVE_ELAPSED` names the choice,
and `tests/test_daily_report.py` fails if either count changes.

## Where the code is

| File | Holds |
|---|---|
| `daily_report.py` | every number on the report and the ten-page structure — pure, no I/O |
| `dr_sharepoint.py` | reading the lists: URL parsing, column matching, row mapping, assembly — pure, the HTTP getter is injected |
| `app.py` | `/api/dr/report`, `/api/dr/photo/<id>`, `/api/dr/detect`, `/api/dr/sync`, and the `dr_*` collection guards |
| `templates/index.html` | the screen, Report Setup and the PDF exporter (`tkDrExportPDF`) |
| `tools/seed_daily_report.py` | seeds the two source reports into a dev database, for comparing against the originals |

Collections: `dr_projects`, `dr_contractors`, `dr_reports`, `dr_photos`. Reports and photos are
readable at staff level — the engineer who submits the form has to be able to read back what they
submitted — and deletable only by whoever raised them, or from management up. Setup rows are
manager-level: the site fills reports in, it does not repoint where reports are read from.
