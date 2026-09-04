"""Building the SharePoint lists and the Microsoft Forms the site fills the Daily Report in with.

THE PROBLEM THIS SOLVES. Three artefacts have to agree, exactly, or the report comes out blank:

    the Microsoft Form question title
        -> the SharePoint list column it is written into
            -> the column name dr_sharepoint.automap looks for

They are built by different people at different times in different tools, and nothing connects them
but a string. Get one wrong and the sync reports success while a section prints empty — the failure
this whole module is written against. So all three are generated HERE, from one table, and
`tests/test_dr_forms.py` proves the loop closes: build the columns this module specifies, run them
through `automap`, and every required field must be found. A generated list cannot fail "Check the
lists", by construction rather than by care.

WHAT CANNOT BE AUTOMATED, said plainly. **Microsoft Forms has no creation API** — none, at any
licence level. A form is built in the Forms UI by a person. So this module produces a build sheet
precise enough to type from in a few minutes per form (exact title, question order, question type,
the choices verbatim), and the parts that CAN be automated — the lists and the flow mapping — it
emits as machine-readable definitions and as a runnable PowerShell script.

THE ANONYMOUS CONSTRAINT drives two decisions that look odd until you know it. The contractors have
no accounts in the tenant:

  * The form must be set to "Anyone can respond", and an anonymous response is written to a workbook
    rather than to a list — so a Power Automate flow does the last hop, running as a Humiley account.
    That is why `flow_mapping` exists at all.
  * **Microsoft Forms only offers a file-upload question when responses are restricted to the
    organisation.** An anonymous form therefore cannot carry photos, whatever else it carries. The
    photos form below is emitted with `signed_in_only` set, and the build sheet says so, because the
    alternative — an admin building a form whose photo question silently is not there — is exactly
    the kind of half-configured setup this module exists to prevent.

NO I/O. This module only produces definitions; app.py does the Graph calls.
"""
import json
import re

import daily_report
import dr_sharepoint as sp


# ── the field table: one row per question, and the source of all three artefacts ──────────────────
# (field, display title, kind of answer, required?, help text)
#
# `field` is the canonical name dr_sharepoint.FIELD_SPECS uses; the display TITLE is what both the
# form question and the SharePoint column are called. The title is chosen to be one that `automap`
# already matches — test_dr_forms.py is what holds that true rather than this comment.
#
# Answer kinds map to both tools:
#   text  -> SP "Text",   Forms short answer          note -> SP "Note",   Forms long answer
#   num   -> SP "Number", Forms short answer          date -> SP "DateTime", Forms date
#   time  -> SP "Text",   Forms short answer (hh:mm — a real time column would force a date too)
#   pick  -> SP "Choice", Forms choice (choices below)
TEXT, NOTE, NUM, DATE, TIME, PICK = "text", "note", "num", "date", "time", "pick"

# On every list. `date` is what attaches a row to a day and `contractor` to a company; a row missing
# the first cannot be filed at all, which is why it is required everywhere.
COMMON_FIELDS = [
    ("date", "ReportDate", DATE, True, "The day this report is for."),
    ("contractor", "Contractor", PICK, True, "Your company."),
]

WEATHER_CHOICES = ["Sunny", "Clear up", "Cloudy", "Overcast", "Light rain", "Rain",
                   "Heavy rain", "Storm", "Windy", "Fog"]
YES_NO = ["Yes", "No", "N/A"]

# The four submission groups of section 7, verbatim from daily_report.DOC_GROUPS so the choice list
# and the printed headings cannot drift.
DOC_GROUP_CHOICES = list(daily_report.DOC_GROUPS)

FORMS = [
    {
        "kind": "header", "list": "Daily Report Header",
        "title": "Daily Report — Weather & Manpower",
        "intro": ("One submission per day. Fill this in even on a quiet day: a day with no header "
                  "row shows on the report as a day whose weather and headcount are unknown."),
        "fields": [
            ("weatherMorning", "Morning (7:00-11:00)", PICK, True, "Weather in the morning."),
            ("weatherAfternoon", "Afternoon (13:00-17:00)", PICK, True, "Weather in the afternoon."),
            ("weatherEvening", "Evening (17:00-24:00)", PICK, True, "Weather in the evening."),
            ("avgTemp", "Average Temperature", NUM, False, "Degrees Celsius, e.g. 30."),
            ("rainHours", "Total Rainfall Duration", NUM, False, "Hours of rain, e.g. 1. Enter 0 for none."),
            ("notes", "Notes", NOTE, False, "Anything about the day that is not covered elsewhere."),
        ],
        "choices": {"weatherMorning": WEATHER_CHOICES, "weatherAfternoon": WEATHER_CHOICES,
                    "weatherEvening": WEATHER_CHOICES},
        # Plus one NUMBER question per role and per trade — those differ per contractor, so they are
        # added by `build` from the contractor's own configuration.
        "roles": True,
    },
    {
        "kind": "progress", "list": "Daily Work Progress",
        "title": "Daily Report — Work Completed Today",
        "intro": "One submission per work item completed or advanced today.",
        "fields": [
            ("category", "Category", PICK, True, "Which trade this item belongs to."),
            ("item", "Report Items", TEXT, True, "What was worked on, as it should read on the report."),
            ("daily", "Daily Progress (%)", NUM, False,
             "How much this item advanced TODAY. Enter 0 if it did not move — leave blank only if "
             "you do not know."),
            ("accum", "Accumulated Progress (%)", NUM, False, "How complete the item is overall."),
            ("start", "Start Date", DATE, False, "When the item started."),
            ("finish", "Finish Date", DATE, False, "When the item is planned to finish."),
        ],
    },
    {
        "kind": "plan", "list": "Daily Work Plan",
        "title": "Daily Report — Next Day Work Plan",
        "intro": "One submission per item planned for tomorrow.",
        "fields": [
            ("category", "Category", PICK, True, "Which trade this item belongs to."),
            ("item", "Report Items", TEXT, True, "What will be worked on tomorrow."),
            ("location", "Location", TEXT, False, "Zone, floor or block."),
            ("notes", "Notes", NOTE, False, ""),
        ],
    },
    {
        "kind": "equipment", "list": "Daily Equipment",
        "title": "Daily Report — Equipment & Machinery",
        "intro": "One submission per type of plant on site today.",
        "fields": [
            ("item", "Report Items", TEXT, True, "The equipment, e.g. Excavator."),
            ("qty", "Quantity", NUM, True, "How many on site today."),
            ("unit", "Unit", TEXT, False, "Usually pcs."),
            ("notes", "Notes", NOTE, False, ""),
        ],
    },
    {
        "kind": "materials", "list": "Daily Material Delivery",
        "title": "Daily Report — Material Delivery",
        "intro": "One submission per material delivery received today.",
        "fields": [
            ("item", "Report Items", TEXT, True, "What was delivered."),
            ("docCode", "Document Code", TEXT, False, "Delivery note or submission reference."),
            ("notes", "Notes", NOTE, False, ""),
        ],
    },
    {
        "kind": "documents", "list": "Daily Document Exchange",
        "title": "Daily Report — Site Document Exchange",
        "intro": "One submission per document issued or submitted today.",
        "fields": [
            ("group", "Group", PICK, True, "Which of the four submission groups this belongs to."),
            ("item", "Report Items", TEXT, True, "The document's title."),
            ("docCode", "Document Code", TEXT, False, ""),
            ("category", "Category", PICK, False, "Which trade it relates to."),
            ("notes", "Notes", NOTE, False, ""),
        ],
        "choices": {"group": DOC_GROUP_CHOICES},
    },
    {
        "kind": "defects", "list": "Daily Defects",
        "title": "Daily Report — Defect Check List",
        "intro": "One submission per defect raised today.",
        "fields": [
            ("desc", "Defect Description", NOTE, True, "What is wrong, and where."),
            ("action", "Corrective Action", NOTE, False, "What will be done about it."),
            ("identified", "Date Identified", DATE, False, ""),
            ("due", "Expected Completion Date", DATE, False, ""),
        ],
    },
    {
        "kind": "inspections", "list": "Daily Inspection",
        "title": "Daily Report — Daily Inspection",
        "intro": "One submission per inspection carried out today.",
        "fields": [
            ("item", "Inspection Item", TEXT, True, "What was inspected."),
            ("location", "Location", TEXT, False, ""),
            ("docCode", "Document Code", TEXT, False, "ITP or checklist reference."),
            ("status", "Status", PICK, False, "The outcome."),
            ("notes", "Notes", NOTE, False, ""),
        ],
        "choices": {"status": ["Passed", "Failed", "Passed with comments", "Postponed"]},
    },
    {
        "kind": "inspectionPlan", "list": "Daily Inspection Plan",
        "title": "Daily Report — Next Day Inspection Plan",
        "intro": "One submission per inspection requested for tomorrow.",
        "fields": [
            ("item", "Work Item", TEXT, True, "What needs inspecting."),
            ("location", "Location", TEXT, False, ""),
            ("time", "Time", TIME, False, "Requested time, e.g. 14h00."),
            ("notes", "Notes", NOTE, False, ""),
        ],
    },
    {
        "kind": "safety", "list": "Daily Safety",
        "title": "Daily Report — Safety Control Activities",
        "intro": ("One submission per safety check. A check nobody submits shows on the report as "
                  "NOT ANSWERED, never as passed — so submit every one, including the ones that "
                  "did not apply."),
        "fields": [
            ("item", "Report Items", PICK, True, "Which check this is."),
            ("status", "Status", PICK, True, "Was it done?"),
            ("notes", "Notes", NOTE, False, ""),
        ],
        "choices": {"status": YES_NO},
        # The check list differs per contractor, so the choices come from its configuration.
        "checklist": True,
    },
    {
        "kind": "recommendations", "list": "Daily Recommendations",
        "title": "Daily Report — Requests & Recommendations",
        "intro": "One submission per request or recommendation to the consultant.",
        "fields": [
            ("item", "Recommendation", NOTE, True, "What you are asking for."),
            ("location", "Location", TEXT, False, ""),
            ("notes", "Notes", NOTE, False, ""),
        ],
    },
    {
        "kind": "photos", "list": "Daily Photos",
        "title": "Daily Report — Progress Photos",
        "intro": "One submission per photo.",
        "fields": [
            ("category", "Category", PICK, True, "Which trade the photo shows."),
            ("caption", "Caption", TEXT, False, "Leave blank to have the report number it."),
            ("photo", "Photo", TEXT, True, "The photograph."),
        ],
        # THE ONE FORM AN ANONYMOUS RESPONDER CANNOT COMPLETE. Microsoft Forms offers a file-upload
        # question only when responses are restricted to the organisation, so on an anonymous form
        # this question cannot exist. Flagged rather than quietly emitted: an admin who builds this
        # form without knowing gets a photo section that is permanently empty and no reason why.
        "signed_in_only": "photo",
    },
]

BY_KIND = {f["kind"]: f for f in FORMS}

# How an answer kind becomes a SharePoint column. `text` is deliberately used for `time`: a real
# DateTime column would force the responder to give a date as well as a time.
SP_COLUMN = {
    TEXT: {"text": {}},
    NOTE: {"text": {"allowMultipleLines": True}},
    NUM: {"number": {}},
    DATE: {"dateTime": {"format": "dateOnly"}},
    TIME: {"text": {}},
    PICK: {"choice": {"allowTextEntry": True}},
}
FORMS_QUESTION = {TEXT: "Text", NOTE: "Text (long answer)", NUM: "Text (number)",
                  DATE: "Date", TIME: "Text", PICK: "Choice"}


def _fields_for(spec, contractor):
    """Every question on one form, in order, with the per-contractor ones filled in."""
    con = contractor or {}
    out = list(COMMON_FIELDS) + [tuple(f) for f in spec["fields"]]
    choices = dict(spec.get("choices") or {})
    choices["contractor"] = [str(con.get("name") or "")] if con.get("name") else []
    cats = [str(c) for c in (con.get("categories") or []) if str(c).strip()]
    for f, _t, kind, _r, _h in out:
        if f in ("category",) and kind == PICK:
            choices["category"] = cats
    if spec.get("checklist"):
        checks = [str(c) for c in (con.get("safetyChecklist") or daily_report.SAFETY_DEFAULTS)
                  if str(c).strip()]
        choices["item"] = checks
    if spec.get("roles"):
        # One NUMBER question per role and per trade, named exactly as the contractor's own tables
        # name them — which is also how `automap` finds them (it matches header columns against the
        # contractor's role/trade lists, not against a fixed table).
        for name in ([str(r) for r in (con.get("mgmtRoles") or [])] +
                     [str(t) for t in (con.get("workerTrades") or [])]):
            if name.strip():
                out.append(("role:" + name, name, NUM, False,
                            "How many " + name + " on site today. Enter 0 if none."))
    return out, choices


def build(contractor):
    """The whole build package for one contractor: its forms, its lists, its flow mappings.

    Everything below is derived from the table above plus this contractor's own configuration, so
    the three artefacts cannot disagree with each other or with what the reader looks for.
    """
    con = contractor or {}
    forms = []
    for spec in FORMS:
        fields, choices = _fields_for(spec, con)
        questions, columns, mapping = [], [], []
        for field, title, kind, required, help_text in fields:
            blocked = spec.get("signed_in_only") == field
            questions.append({
                "field": field, "title": title, "type": FORMS_QUESTION[kind],
                "required": bool(required), "help": help_text,
                "choices": list(choices.get(field) or []),
                "signedInOnly": blocked,
                # A choice question with nothing to choose from is a question nobody can answer.
                # Reported so setup can say WHICH configuration is missing.
                "needsConfig": kind == PICK and not (choices.get(field) or []),
            })
            columns.append({"name": title, "type": kind,
                            "definition": SP_COLUMN[kind],
                            "choices": list(choices.get(field) or [])})
            mapping.append({"question": title, "column": title, "field": field})
        forms.append({
            "kind": spec["kind"], "listName": spec["list"], "formTitle": spec["title"],
            "intro": spec["intro"], "questions": questions, "columns": columns,
            "flow": mapping,
            "anonymousBlocked": bool(spec.get("signed_in_only")),
        })
    return {"contractor": con.get("name") or "", "contractorId": con.get("id") or "",
            "forms": forms, "notes": _notes(con)}


def _notes(con):
    """What is not ready, in the words of the thing that is missing. An empty choice list is the
    common one: a Category question with no categories configured is a question with no answers."""
    out = []
    if not (con.get("categories") or []):
        out.append({"level": "warn", "msg":
                    "This contractor has no work categories set up, so the Category questions would "
                    "have nothing to choose from. Set them in Report Setup first."})
    if not (con.get("mgmtRoles") or []) and not (con.get("workerTrades") or []):
        out.append({"level": "warn", "msg":
                    "No management roles or worker trades are set up, so the header form would ask "
                    "for no headcounts at all and tables 2.1 and 2.2 would print empty."})
    if not (con.get("name") or "").strip():
        out.append({"level": "warn", "msg": "This contractor has no name, so the Contractor "
                                            "question would have nothing to choose from."})
    out.append({"level": "info", "msg":
                "Set every form to \"Anyone can respond\" — the site has no Microsoft accounts. "
                "Microsoft Forms will then not offer a file-upload question, which is why photos "
                "come through the SharePoint upload link instead of through the Progress Photos "
                "form."})
    return out


# ── the artefacts, in the shapes the people building them need ────────────────────────────────────
def graph_list_body(form):
    """The JSON for Graph's POST /sites/{id}/lists — one list, with its columns."""
    cols = []
    for c in form["columns"]:
        d = dict(c["definition"])
        if "choice" in d:
            d = {"choice": dict(d["choice"], choices=list(c["choices"]))}
        cols.append(dict({"name": c["name"]}, **d))
    return {"displayName": form["listName"], "columns": cols, "list": {"template": "genericList"}}


def powershell(pkg, site_url):
    """A PnP PowerShell script that creates every list. The fallback that always works.

    Graph's list-creation call needs Sites.Manage.All, which is BROADER than the Sites.ReadWrite.All
    this portal holds — so an admin may not be able to click a button in the portal and have it
    happen. Rather than tell them to hand-build seventy columns, they get this. It is idempotent:
    re-running it adds what is missing and leaves what is there.
    """
    esc = lambda s: str(s or "").replace("`", "``").replace('"', '`"')
    out = ["# Daily Report — create the SharePoint lists for " + esc(pkg.get("contractor")),
           "# Generated by dr_forms.py. Idempotent: safe to re-run.",
           "#",
           "#   Install-Module PnP.PowerShell -Scope CurrentUser",
           '#   Connect-PnPOnline -Url "' + esc(site_url) + '" -Interactive',
           "",
           '$site = "' + esc(site_url) + '"',
           "Connect-PnPOnline -Url $site -Interactive",
           ""]
    for f in pkg["forms"]:
        ln = esc(f["listName"])
        out += ['Write-Host "== ' + ln + '"',
                '$l = Get-PnPList -Identity "' + ln + '" -ErrorAction SilentlyContinue',
                'if ($null -eq $l) { $l = New-PnPList -Title "' + ln +
                '" -Template GenericList -OnQuickLaunch }']
        for c in f["columns"]:
            t = {TEXT: "Text", NOTE: "Note", NUM: "Number", DATE: "DateTime",
                 TIME: "Text", PICK: "Choice"}[c["type"]]
            name = esc(c["name"])
            line = ('Add-PnPField -List "' + ln + '" -DisplayName "' + name + '" -InternalName "' +
                    re.sub(r"[^A-Za-z0-9]", "", c["name"])[:32] + '" -Type ' + t +
                    ' -AddToDefaultView -ErrorAction SilentlyContinue')
            if c["type"] == PICK and c["choices"]:
                line += " -Choices " + ",".join('"' + esc(x) + '"' for x in c["choices"])
            out.append(line)
        out.append("")
    out += ['Write-Host "Done. Now paste each list URL into Report Setup and press Check the lists."']
    return "\n".join(out)


def flow_steps(form):
    """The Power Automate flow for one form, as the three steps an admin builds in the designer.

    Named explicitly rather than shipped as an importable package: a flow's exported ZIP embeds the
    environment and connection ids of the tenant it came from, so one generated here would not
    import into theirs — it would fail in a way that looks like a broken file rather than a
    mismatch. Three steps is a two-minute build.
    """
    return [
        {"step": 1, "action": "Microsoft Forms — When a new response is submitted",
         "detail": "Form Id: " + form["formTitle"]},
        {"step": 2, "action": "Microsoft Forms — Get response details",
         "detail": "Response Id: from step 1"},
        {"step": 3, "action": "SharePoint — Create item",
         "detail": "List Name: " + form["listName"],
         "fields": [{"column": m["column"], "value": m["question"]} for m in form["flow"]]},
    ]


def checklist(pkg):
    """The order to do it in, because the order matters: the list has to exist before the flow can
    point at it, and the form has to exist before the flow can trigger on it."""
    return [
        "In Report Setup, finish this contractor's roles, trades, categories and safety checks — "
        "the forms are generated FROM them, so building forms first means building them twice.",
        "Create the SharePoint lists (the button here, or the PowerShell script).",
        "Build each Microsoft Form from its build sheet. Set each one to \"Anyone can respond\".",
        "Build one Power Automate flow per form: Forms trigger, Get response details, "
        "SharePoint Create item.",
        "Paste each list's URL into Report Setup and press \"Check the lists\" — it reports, per "
        "list, every column it matched and every one it could not find.",
        "Use SharePoint's \"Request files\" on the project folder for photos, and give the site "
        "that link.",
        "Submit one test response per form, then press \"Sync from SharePoint\" and read the day "
        "back on the report.",
    ]


def as_json(pkg):
    return json.dumps(pkg, ensure_ascii=False, indent=2, sort_keys=True)
