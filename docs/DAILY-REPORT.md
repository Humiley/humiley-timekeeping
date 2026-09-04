# Daily Report

The site's daily report to the client — a tab of the **Project workspace**, fed from the SharePoint
forms the site fills in, printed on the Humiley letterhead.

It reproduces the report the client already receives (the two files it was built against are
`DailyReport_Mega_Taikisha_09.01.2026.pdf` and `DailyReport_Mega_Newtecons_09.02.2026.pdf`) with the
same ten sections, the same column sets and the same figures. What changes is where the data comes
from: instead of somebody refreshing a Power BI file and exporting it by hand, the site fills forms
and the portal assembles the report.

**Where it is:** Projects → open a project → **Daily Report**. It is part of the Project app, so the
Projects switch governs it and the project's own team scope decides who can see it. Report Setup is
a panel of the same tab (manager level and above); there is no separate screen for it.

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

On screen this is the portal's own furniture — cards, tabs, the standard tables with sortable
headings and the filter bar — so it reads like every other PMC register. The **PDF** is the document:
Humiley letterhead, the client's logo top-left, the contractor's bottom-right.

## The project comes from the project

The name, the client and the planned dates are read from `pm_projects`. They are not typed again
here, because two registers holding the same start date is two registers that will one day disagree
about it on a document the client reads every morning. Rename the project in PMC and the report's
masthead changes with it.

Report Setup → **This project's report header** holds only what the report adds: the location, the
investor, the two consultant lines, the client's logo, and the project's SharePoint folder.

## Setting a contractor up (once)

1. **Identity** — its name and **its logo**, which prints bottom-right on every page of that
   contractor's report. The Humiley mark is fixed.
2. **The columns its tables count** — each contractor counts different roles and trades, so tables
   2.1 and 2.2 are built from these lists. Taikisha counts Cad Staff and Supervisors; Newtecons
   counts Quantity Surveyors and a Secretary. A headcount arriving under a name not on the list is
   still shown — listed under the table and left out of the total, never silently added to it.
3. **Work categories** — the order 5.1, 5.2, 5.3 and the photo grid group in.
4. **Safety checklist** — leave empty for the eleven standard checks.
5. **The SharePoint lists**, then press **Check the lists**.

## The SharePoint side, for contractors with no Microsoft account

This is the constraint that shapes the whole setup: **the contractors do not have accounts in the
tenant.** Two consequences, and the second one is the awkward part.

### Report Setup builds the sheet for you

**Report Setup → Build the forms** generates the whole package from this contractor's own roles,
trades, categories and safety checks:

- **the build sheet for each of the twelve forms** — every question in order, its exact title, its
  answer type and its choices verbatim. Microsoft Forms has no creation API at any licence level, so
  a form is still built by a person in the Forms UI; this makes it a few minutes of typing rather
  than a guessing game.
- **the SharePoint lists** — one button, or a **PnP PowerShell script** if the tenant has not granted
  `Sites.Manage.All` (which is broader than the `Sites.ReadWrite.All` the portal holds). The panel
  says which of the two applies, read from the token's own roles claim, so it never offers a button
  that will 403. Created lists have their URLs written straight back into Report Setup.
- **the three-step Power Automate flow** per form.

The point of generating all three from one table (`dr_forms.py`) is that the form question title,
the SharePoint column and the name the sync looks for **cannot disagree**. `tests/test_dr_forms.py`
proves it: build the columns this spec describes, run them through the sync's own mapper, and every
field is found. A list built to the sheet cannot then fail "Check the lists".

Do it in the order the panel gives, because it matters: the forms are generated *from* the
contractor's configuration, so building forms before finishing that configuration means building
them twice.

### 1. The form must accept anonymous responses, so a flow moves the answers

Build a **Microsoft Form** per table and set it to *Anyone can respond*. An anonymous form writes its
responses to a workbook, not to a list, so a **Power Automate** flow does the last step:

```
Microsoft Forms  "When a new response is submitted"
   → Forms       "Get response details"
   → SharePoint  "Create item"   (the list the portal reads)
```

The flow runs as whoever owns it — a Humiley account — so the contractor needs no permission on the
list and no account anywhere. Give every list a **date** column and, unless the list serves one
contractor only, a **contractor** column: those are what attach a row to a day and a company. A row
that cannot say which day it belongs to is not imported at all, and the sync reports how many it
skipped.

One list per table, because no form submits a variable-length table into a single item:

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

**Column names are matched, not assumed.** SharePoint freezes whatever the list builder typed, so
`Daily Progress (%)` is internally something like `Daily_x0020_Progress`. **Check the lists** matches
your real columns against the report's fields and says, per list, what it found, what it could not
find, and which of your columns nothing claimed. A list whose essential columns cannot be matched is
**refused** by the sync rather than imported blank — an empty section on this report looks the same
as a quiet day on site.

### 2. Photos cannot come through the form at all

**Microsoft Forms offers a file-upload question only when responses are restricted to your
organisation.** An anonymous form cannot accept one, and no permission changes that. Neither can the
paperclip on a classic SharePoint form be read back — Microsoft Graph has no attachments
relationship on a list item at any consent level.

So photos take a different route, and it is the one that needs no account:

1. In Report Setup, give the project its **SharePoint folder**.
2. In SharePoint, use **Request files** on that folder to create an upload-only link, and give the
   link to the site. Anyone can upload through it; nobody can see what else is in there.
3. The portal reads the folder on every sync. Files are expected under
   `Daily Report / <contractor> / <YYYY-MM> / <YYYY-MM-DD>`, and a photo's **work category is read
   from its file name** (`HVAC Works - 03.jpg`) because a folder cannot carry a column. A name that
   matches no category still appears, under the contractor's first one — a wrong heading is
   recoverable, a missing photo is not.

If you would rather have one form do everything, the alternative is to add each contractor as a
**guest (B2B) user** in the tenant; file-upload questions then work, at the cost of every contractor
accepting an invitation and signing in. The portal supports both — it reads photos from the folder
*and* from a link column a form question stores.

Everything the site submits — every photo, every file — is stored under **that project's SharePoint
folder**, not in the portal. A photo row holds only its reference; the image streams through
`/api/dr/photo/<id>`, which is also what lets photos appear in the exported PDF (a cross-origin
SharePoint URL taints the canvas and the export comes out with blank frames).

### Ops

The sync uses the app-only Graph token the portal already holds (`TK_M365_CLIENT_SECRET`,
`Sites.Read.All` / `Sites.ReadWrite.All`). With no secret configured the screen says so instead of
failing obscurely. **Sync from SharePoint** pulls one day, or a range of at most 31 days; re-syncing
a corrected form replaces that day's rows rather than stacking a second copy underneath, and a photo
somebody uploaded by hand in the portal survives a re-sync.

## The PDF

**Export PDF** builds A4 portrait on the Humiley letterhead: the two-tone brand bar, the navy
company block, the emerald document title, the hairline footer with its page count and document
code — plus **the client's logo top-left** and **the contractor's logo bottom-right**. The letterhead
puts its company block top-left and its page count bottom-right, which is exactly where those two
logos go, so the block moves right of the client's mark and the page count left of the contractor's.

- **Auto-fit.** A section a little taller than the page is scaled down to fit — down to 74%, below
  which it is split across sheets, because a legible second page beats an illegible first one. The
  letterhead takes more of the sheet than a bare masthead did, so a 30-row work-progress table now
  prints across two pages rather than being crushed onto one.
- **Every section is measured before the first page is drawn**, so `Page 1/11` is right.
- **The export does not depend on the device or the theme.** The print renderer carries its own
  styles rather than the screen's, so it cannot inherit a reader's dark mode or a global rule meant
  for on-screen registers.
- **It cannot hang.** The build has a deadline; if it stalls it says so rather than leaving
  "Building…" on screen forever.

## Three things the report says out loud

Each because the alternative is a document that looks complete and is not:

- **An unanswered safety check is not a passed check.** The source report shows eleven green ticks;
  defaulting the tick on would produce that page for a day nobody walked the site. An absent answer
  renders as "Not answered" and is listed above the report.
- **A headcount under a column that is not on the table is not in the total.** It is shown under the
  table and named in the warnings, so the number can be found rather than quietly disappearing.
- **The manpower delta compares against the last day this contractor reported**, not against
  yesterday — so a site that does not work Sundays does not show every Monday as a rise from nothing.

## The two durations are counted differently, on purpose

Measured off both source files:

    Start 2025-11-14, End 2027-04-28   -> "Total Construction Duration (Days): 530"   (exclusive)
    Start 2025-11-14, as-of 2026-09-01 -> "Construction Duration to Date (Days): 292" (inclusive)

That inconsistency is the behaviour of the report the client has been reading every morning, so it is
reproduced rather than tidied — a headline duration that silently moved by a day the week we took the
report over is a report nobody trusts again. `daily_report.INCLUSIVE_ELAPSED` names the choice, and
`tests/test_daily_report.py` fails if either count changes.

## Where the code is

| File | Holds |
|---|---|
| `daily_report.py` | every number on the report, the ten-page structure, and the PM-project merge — pure, no I/O |
| `dr_sharepoint.py` | reading the lists and the folder: URL parsing, column matching, row mapping, assembly — pure, the HTTP getter is injected |
| `dr_forms.py` | the lists and forms the report is filled in WITH — one table generating the form questions, the SharePoint columns and the flow mapping, so the three cannot drift |
| `app.py` | `/api/dr/report`, `/api/dr/photo/<id>`, `/api/dr/detect`, `/api/dr/sync`, and the `dr_*` project scoping |
| `templates/index.html` | the `pmRenderDailyReport` tab, Report Setup, and the letterhead exporter |
| `tools/seed_daily_report.py` | seeds both source reports into a dev database, for comparing against the originals |

Collections: `dr_settings` (one per project, keyed by its id), `dr_contractors`, `dr_reports`,
`dr_photos`. All four are **project data**: readable at staff level for anyone on the project's team
— the engineer who submits the form has to be able to read back what they submitted — writable and
deletable by anyone on that team, and out of reach of everyone else. Scoped by project rather than by
author on purpose: a day's report is filed by whoever ran the sync, so creator-ownership would leave
the engineers who produced it unable to remove a duplicate.
