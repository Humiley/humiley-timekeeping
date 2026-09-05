"""The construction Daily Report — the numbers on it, and the ten pages it is printed as.

The client already receives this report every day. Today it is a Power BI file that somebody
refreshes and exports by hand, and the two we were handed (Newtecons 02/09, Taikisha 01/09) are the
specification: same masthead, same ten sections, same column sets, same footer. This module owns
everything about that report that is ARITHMETIC or STRUCTURE, so the same answer is produced whether
the caller is the screen, the PDF, or a test. No I/O, no Graph, no database — those live in
dr_sharepoint.py and app.py.

Three things here are decisions rather than obvious code, and each one is a place a plausible
implementation would quietly print a different number than the report the client has been reading:

1. THE TWO DURATIONS ARE COUNTED DIFFERENTLY, and that is not a bug we are introducing — it is the
   behaviour of the report in the client's hands, measured off the two PDFs:

       Start 2025-11-14, End 2027-04-28  ->  "Total Construction Duration (Days): 530"
       (end - start).days == 530.  Counting both endpoints would print 531.

       Start 2025-11-14, as-of 2026-09-01 -> "Construction Duration to Date (Days): 292"
       (asof - start).days == 291.  So this one DOES count both endpoints.
       Confirmed against the second file: as-of 2026-09-02 prints 293.

   So the total is an exclusive span and the elapsed is an inclusive one. Reproducing that is the
   whole point — a report whose headline duration silently moved by a day the week we took it over
   is a report nobody trusts again. `INCLUSIVE_ELAPSED` names the choice so it is visible and can
   be turned off for a project that wants both counted the same way, rather than being a constant
   `+ 1` nobody can account for three years from now.

2. THE MANPOWER DELTA IS AGAINST THE PREVIOUS REPORT, NOT THE PREVIOUS CALENDAR DAY. Sites do not
   report on Sundays, and "91 (▲ 17)" after a two-day gap must compare against the last day anybody
   actually counted heads — otherwise Monday always shows a triumphant rise from a day nobody
   worked. `manpower_delta` takes the whole history and walks back to the most recent report BEFORE
   this date, whenever that was, and says how far back it looked.

3. A TOTAL IS THE SUM OF THE COLUMNS THAT ARE ON THE TABLE, and the columns differ per contractor —
   Taikisha counts Cad Staff and Supervisors, Newtecons counts Quantity Surveyors and a Secretary.
   `manpower_row` therefore takes the contractor's own column list and sums THAT, so a role that is
   still in the stored data after somebody removed the column cannot inflate the total shown
   underneath a table it does not appear in. The dropped headcount is returned as `orphans` rather
   than discarded, because a number that vanishes from a total with no trace is how a report starts
   disagreeing with the site.
"""
from datetime import date, timedelta


# ── the ten sections, in the order they are tabbed on screen and printed in the PDF ──────────────
#   key        the tab id and the PDF page
#   tab        the short label on the tab strip (two lines in the source report)
#   heading    the numbered heading(s) that appear inside the page
#
# One page per tab is how the source report paginates (Page 1/10 … Page 10/10). A section whose
# table is longer than the page continues onto a further sheet rather than being cut — see
# `paginate`, which is the only thing that may add pages.
SECTIONS = (
    {"key": "overview",  "tab": "Overview",             "headings": ("Site Overview Photos",)},
    {"key": "manpower",  "tab": "Weather & Manpower",   "headings": ("1. Weather", "2.1 Management Staff", "2.2 Workers")},
    {"key": "equipment", "tab": "Equipment-Materials",  "headings": ("3. Equipment & Machinery", "4. Material Delivery")},
    {"key": "progress",  "tab": "Work Progress",        "headings": ("5.1 Work Completed Today",)},
    {"key": "gantt",     "tab": "Progress Gantt",       "headings": ("5.2 Work Progress Gantt Chart",)},
    {"key": "plan",      "tab": "Work Plan",            "headings": ("5.3 Next Day Work Plan",)},
    {"key": "photos",    "tab": "Daily Photos",         "headings": ("6. Daily Progress Photos",)},
    {"key": "documents", "tab": "Document & Defect",    "headings": ("7. Site Document Exchange", "8. Defect Check List")},
    {"key": "inspection","tab": "Inspection",           "headings": ("9.1 Daily Inspection", "9.2 Next Day Inspection Plan")},
    {"key": "safety",    "tab": "Safety & Recomm.",     "headings": ("10. Safety Control Activities", "11. Requests & Recommendations")},
)
SECTION_KEYS = tuple(s["key"] for s in SECTIONS)

# The four document-exchange groups. They are FIXED headings, not data: the source report prints all
# four every day and writes "None" under an empty one, because "no method statement was issued
# today" and "nobody filled in the method statement question" have to look different on a document
# the consultant signs off against.
DOC_GROUPS = ("7.1- Construction Shop Drawings", "7.2- Method Statements",
              "7.3- Material Submission", "7.4- Other Submissions")

# The work categories 5.1, 5.3 and the photo grid group under. Shipped as the default for the same
# reason as the safety checks below: a contractor set up in a hurry, with none entered, otherwise
# gets a one-option dropdown on the photo section and files every image under whatever that one
# happens to be — which is worse than an unconfigured list, because it looks configured.
#
# Drawn from the two reports this module was built against: the union of Taikisha's six (MEP-led)
# and Newtecons' three (civil-led), which between them cover both kinds of package on this job. A
# contractor edits its own list in Report Setup and the default then stops applying — the same
# contract SAFETY_DEFAULTS has.
CATEGORY_DEFAULTS = (
    "Architectural Finishing Works",
    "Civil Structure Works",
    "Electrical Works",
    "External Works",
    "Fire Fighting Works",
    "HVAC Works",
    "Plumbing Works",
    "Utility Works",
    "Other Works",
)


# The eleven safety checks the report asks about every day. Shipped as the default for a new
# contractor, which may then edit its own list — a site with no hot works should not be answering
# a hot-work question daily, and a site with confined-space entry needs a line the default lacks.
SAFETY_DEFAULTS = (
    "Barricade & Warning Sign Check",
    "Daily Toolbox Talk (15 mins)",
    "Emergency Access & Exit Inspection",
    "Equipment Safety Inspection",
    "Fire Prevention & Hot Work Inspection",
    "First Aid & Emergency Preparedness Check",
    "Housekeeping Inspection",
    "PPE Compliance Inspection",
    "Temporary Electrical Safety Check",
    "Work Permit Verification",
    "Working at Height Safety Check",
)

# The three windows the weather is reported in, exactly as the source report labels them.
WEATHER_SLOTS = (("morning", "Morning (7:00–11:00)"),
                 ("afternoon", "Afternoon (13:00–17:00)"),
                 ("evening", "Evening (17:00–24:00)"))

# Weather words the SharePoint form offers, and the emoji the report draws beside each. Anything
# else the form sends through is still PRINTED — it just gets no icon. A whitelist that silently
# dropped an unrecognised condition would make a rainy day look like a day nobody answered.
WEATHER_ICONS = {
    "sunny": "🌤", "clear up": "🌥", "clear": "🌥", "cloudy": "☁", "overcast": "☁",
    "light rain": "🌦", "rain": "🌧", "heavy rain": "⛈", "storm": "⛈", "thunderstorm": "⛈",
    "windy": "💨", "fog": "🌫", "haze": "🌫",
}

# Set False on a project whose client wants both durations counted the same way. See the module
# docstring: the shipped default reproduces the report the client already receives.
INCLUSIVE_ELAPSED = True

# A4 portrait, in the millimetres the PDF is laid out in. The report is printed portrait with a
# 12 mm margin, a 20 mm masthead and a 14 mm footer, which leaves this much for the section body.
PAGE = {"w": 210.0, "h": 297.0, "margin": 12.0, "header": 20.0, "footer": 14.0}


def body_box():
    """The rectangle a section's content is drawn into, in mm: (x, y, width, height)."""
    x = PAGE["margin"]
    y = PAGE["margin"] + PAGE["header"] + 3.0
    return (x, y, PAGE["w"] - 2 * PAGE["margin"],
            PAGE["h"] - y - PAGE["footer"] - PAGE["margin"])


# Where each masthead field comes from on the PM project record. The daily report is part of the
# Project app, so the project is the PM project — there is no second project register to drift from
# the first. `merge_project` below reads these and lets the report's own settings supply the rest.
PM_FIELDS = (("name", "name"), ("clientName", "client"),
             ("startDate", "startPlanned"), ("endDate", "endPlanned"))


def merge_project(pm_project, settings):
    """The report's masthead, from the PM project plus the daily-report settings for that project.

    Split deliberately. `pm_projects` already knows the project's name, its client and its planned
    dates, and those must not be typed a second time here — two registers holding the same start
    date is two registers that will one day disagree about it, on a document the client reads. What
    `dr_settings` adds is what only this report needs: the investor, the two consultant lines, the
    client's logo and the SharePoint folder the site's submissions land in.

    A setting may still OVERRIDE a PM field, because the report's own wording sometimes differs from
    the register's ("Mega Lifesciences" on the report against a project code in the portfolio) — but
    only when it is actually filled in, so a blank never blanks the project.
    """
    pm = pm_project if isinstance(pm_project, dict) else {}
    st = settings if isinstance(settings, dict) else {}
    out = {}
    for want, pm_key in PM_FIELDS:
        out[want] = st.get(want) or pm.get(pm_key) or ""
    for k in ("location", "investor", "consultant", "pmConsultant", "clientLogo",
              "spFolderUrl", "docCode"):
        out[k] = st.get(k) or ""
    out["projectId"] = str(pm.get("id") or st.get("id") or "")
    out["code"] = pm.get("code") or ""
    return out


# ── dates ────────────────────────────────────────────────────────────────────────────────────────
def to_date(value):
    """'2026-09-01' or a date → date. None for anything that is not one. Accepts the US-order
    strings the SharePoint form emits ('9/1/2026') as well, because that is what Microsoft Forms
    hands back for a date question on an en-US tenant and rejecting it would empty the whole
    report for a reason nobody could see."""
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    s = s.split("T")[0].split(" ")[0]
    try:
        y, m, d = (int(x) for x in s[:10].split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        pass
    try:
        m, d, y = (int(x) for x in s.split("/"))
        if y < 100:
            y += 2000
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def iso(value):
    d = to_date(value)
    return d.isoformat() if d else ""


def total_duration_days(start, end):
    """"Total Construction Duration (Days)" — the exclusive span, which is what the source report
    prints (2025-11-14 → 2027-04-28 = 530). None when either end is missing, so the report can say
    it does not know instead of printing a confident 0."""
    s, e = to_date(start), to_date(end)
    if not (s and e):
        return None
    return (e - s).days


def elapsed_duration_days(start, asof):
    """"Construction Duration to Date (Days)" — inclusive of both ends (2025-11-14 → 2026-09-01 =
    292). Negative spans return 0: a report dated before the project started has not consumed
    minus-forty days of programme, it has a wrong date on it, and `warnings()` says so."""
    s, a = to_date(start), to_date(asof)
    if not (s and a):
        return None
    n = (a - s).days + (1 if INCLUSIVE_ELAPSED else 0)
    return max(0, n)


def week_of(value):
    """ISO week label, e.g. 'W36'. The filter bar offers Month and Week, and a week has to mean the
    same thing on the filter as in any export, so it is the ISO week and not a count from 1 January."""
    d = to_date(value)
    return "W%02d" % d.isocalendar()[1] if d else ""


def month_of(value):
    d = to_date(value)
    return "%04d-%02d" % (d.year, d.month) if d else ""


# ── manpower ─────────────────────────────────────────────────────────────────────────────────────
def _num(v):
    """A headcount. Blank is 0, but a value that is not a number at all is 0 TOO — and both are
    reported by `warnings()` rather than silently priced, because a table cell reading 'tbc' turning
    into a zero is how a total goes wrong without anybody being able to see where."""
    if v is None or v == "":
        return 0
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return 0


def unreadable_counts(counts, columns):
    """Raw headcount values that will silently become something else: text that is not a number, and
    numbers below zero.

    `_num` turns both into a figure — 0 for "tbc", -4 for -4 — and a report cannot refuse to render
    because one cell is wrong. So the figure stands and this names it. The site FORM cannot produce
    either (the server refuses a non-number and anything outside 0..100000 before it is stored); the
    SharePoint sync can, because the column is typed by whoever built the list and read by us.

    Returns [(column, raw, why)] in column order, then orphans, so the report says the same thing
    twice for a value that is both unreadable AND under a name nobody recognises.
    """
    counts = counts if isinstance(counts, dict) else {}
    cols = [str(c).strip() for c in (columns or []) if str(c).strip()]
    lower = {c.lower(): c for c in cols}
    out = []
    seen = set()
    for c in cols:
        raw = counts.get(c)
        seen.add(c)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            n = float(str(raw).replace(",", "").strip())
        except (ValueError, TypeError):
            out.append((c, str(raw)[:40], "is not a number"))
            continue
        if n < 0:
            out.append((c, str(raw)[:40], "is below zero"))
    for k, v in sorted(counts.items()):
        if str(k).strip() in seen or str(k).strip().lower() in lower:
            continue
        if v is None or str(v).strip() == "":
            continue
        try:
            n = float(str(v).replace(",", "").strip())
        except (ValueError, TypeError):
            out.append((str(k), str(v)[:40], "is not a number"))
            continue
        if n < 0:
            out.append((str(k), str(v)[:40], "is below zero"))
    return out


def manpower_row(counts, columns):
    """One row of table 2.1 / 2.2: the per-column figures and the total.

    `columns` is the contractor's own column list — see the module docstring, point 3. A count
    stored under a name no longer on the table is returned in `orphans` rather than added to the
    total, so the total always equals the visible cells and the missing heads are still findable.
    """
    counts = counts if isinstance(counts, dict) else {}
    cols = [str(c).strip() for c in (columns or []) if str(c).strip()]
    cells = [{"col": c, "n": _num(counts.get(c))} for c in cols]
    lower = {c.lower() for c in cols}
    orphans = [{"col": str(k), "n": _num(v)} for k, v in sorted(counts.items())
               if str(k).strip().lower() not in lower and _num(v)]
    return {"cells": cells, "total": sum(c["n"] for c in cells),
            "orphans": orphans, "orphanTotal": sum(o["n"] for o in orphans)}


def manpower_delta(reports, contractor_id, on_date, kind):
    """"13 (▼ 1)" — today's headcount and how it moved since the last day this contractor reported.

    `kind` is 'mgmt' or 'workers'. Returns direction 'up' / 'down' / 'flat', the size of the move,
    and `sinceDays` — how far back the comparison reached. Sunday is why: see point 2 of the module
    docstring. `prevDate` is returned so the screen can say WHICH day it is comparing against, which
    is the difference between a number the site trusts and one it argues with.
    """
    d = to_date(on_date)
    if not d:
        return None
    mine = [r for r in (reports or [])
            if str(r.get("contractorId") or "") == str(contractor_id) and to_date(r.get("date"))]
    today = next((r for r in mine if to_date(r.get("date")) == d), None)
    if today is None:
        return None
    earlier = sorted((r for r in mine if to_date(r.get("date")) < d),
                     key=lambda r: to_date(r.get("date")))
    prev = earlier[-1] if earlier else None
    now = _headcount(today, kind)
    if prev is None:
        # First report on the job. There is no previous day, so there is no movement to state —
        # printing "(▲ 91)" against nothing would claim a rise from an empty site that never
        # happened. dir 'none' renders as the report's own "(- 0)" with no arrow.
        return {"n": now, "dir": "none", "by": 0, "prevDate": "", "sinceDays": 0}
    was = _headcount(prev, kind)
    pd = to_date(prev.get("date"))
    by = now - was
    return {"n": now, "was": was, "by": abs(by),
            "dir": "up" if by > 0 else ("down" if by < 0 else "flat"),
            "prevDate": pd.isoformat(), "sinceDays": (d - pd).days}


def _headcount(report, kind):
    src = (report or {}).get("mgmt" if kind == "mgmt" else "workers")
    if isinstance(src, dict):
        return sum(_num(v) for v in src.values())
    return 0


def manpower_series(reports, contractor_id, on_date, days=7):
    """The two "in the Last 7 Days" bar charts.

    Every day in the window appears, reported or not — a site that shut for Tet must show a gap,
    not a compressed chart in which four working days masquerade as a week. A day with no report
    carries n=None (no bar) rather than 0 (a bar saying nobody came), which are different facts.
    """
    d = to_date(on_date)
    if not d:
        return []
    by_date = {}
    for r in (reports or []):
        if str(r.get("contractorId") or "") != str(contractor_id):
            continue
        rd = to_date(r.get("date"))
        if rd:
            by_date[rd] = r
    out = []
    for i in range(days - 1, -1, -1):
        day = d - timedelta(days=i)
        r = by_date.get(day)
        out.append({"date": day.isoformat(),
                    "mgmt": _headcount(r, "mgmt") if r else None,
                    "workers": _headcount(r, "workers") if r else None,
                    "reported": r is not None})
    return out


# ── the grouped tables (5.1 work done, 5.3 next-day plan, 7 documents) ────────────────────────────
def _pct(v):
    """A percentage cell. Returns None for 'not answered', which prints as a dash — distinct from
    0%, which is a real answer meaning the item did not move today."""
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace("%", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return n


def group_rows(rows, key="category", order=None, sort_key=None):
    """Group flat rows under their category heading, the way 5.1, 5.3 and 6 are grouped.

    `order` is the contractor's own category list, so the groups come out in the order that
    contractor's report has always used rather than alphabetically. A category present in the data
    but not in `order` still appears — after the known ones, alphabetically — because dropping a
    row whose category somebody renamed would delete work from the report silently.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    seen = {}
    for r in rows:
        seen.setdefault(str(r.get(key) or "").strip() or "—", []).append(r)
    known = [str(c).strip() for c in (order or []) if str(c).strip() and str(c).strip() in seen]
    rest = sorted(k for k in seen if k not in known)
    out = []
    for name in known + rest:
        items = seen[name]
        if sort_key:
            items = sorted(items, key=sort_key)
        out.append({"category": name, "rows": items, "count": len(items)})
    return out


def progress_rows(rows, categories=None):
    """5.1 Work Completed Today, grouped and with its percentages parsed once."""
    clean = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        clean.append({
            "category": str(r.get("category") or "").strip(),
            "item": str(r.get("item") or "").strip(),
            "daily": _pct(r.get("daily")),
            "accum": _pct(r.get("accum")),
            "start": iso(r.get("start")),
            "finish": iso(r.get("finish")),
        })
    return group_rows(clean, order=categories, sort_key=lambda r: r["item"].lower())


def plan_rows(rows, categories=None):
    """5.3 Next Day Work Plan."""
    clean = [{"category": str(r.get("category") or "").strip(),
              "item": str(r.get("item") or "").strip(),
              "location": str(r.get("location") or "").strip(),
              "notes": str(r.get("notes") or "").strip()}
             for r in (rows or []) if isinstance(r, dict)]
    return group_rows(clean, order=categories, sort_key=lambda r: r["item"].lower())


def document_rows(rows):
    """7. Site Document Exchange — all four groups, every day, "None" under an empty one.

    See DOC_GROUPS: the empty line is the point. It is the difference between "nothing was issued"
    and "this section was skipped", and the consultant countersigning the report needs to be able
    to tell those apart.
    """
    by_group = {g: [] for g in DOC_GROUPS}
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        g = str(r.get("group") or "").strip()
        match = next((k for k in DOC_GROUPS if k.lower().startswith(g.lower()[:4])), None) if g else None
        if match is None:
            match = next((k for k in DOC_GROUPS if g and g.lower() in k.lower()), DOC_GROUPS[3])
        by_group[match].append({"item": str(r.get("item") or "").strip(),
                                "docCode": str(r.get("docCode") or "").strip(),
                                "category": str(r.get("category") or "").strip(),
                                "notes": str(r.get("notes") or "").strip()})
    return [{"group": g, "rows": by_group[g], "empty": not by_group[g]} for g in DOC_GROUPS]


def safety_rows(answers, checklist=None):
    """10. Safety Control Activities — one line per check the contractor's list carries.

    An UNANSWERED check is not a passed check. The source report shows a green tick against every
    line, and the temptation is to default the tick on; a safety register that reads Yes for a check
    nobody performed is worse than no register, so an absent answer renders as 'not answered' and is
    raised by `warnings()`.
    """
    checks = [str(c).strip() for c in (checklist or SAFETY_DEFAULTS) if str(c).strip()]
    ans = answers if isinstance(answers, dict) else {}
    out = []
    for c in checks:
        out.append(dict(_safety_cell(ans.get(c)), item=c, extra=False))
    # An answer for a check that is NOT on this contractor's list still prints, marked as extra.
    # The site submitted it — a confined-space entry check on the one day there was a confined-space
    # entry — and dropping it would delete a safety record because a configuration list had not
    # caught up. The same rule the orphan headcount follows: surface it, never discard it.
    known = {c.lower() for c in checks}
    for k in sorted(ans):
        if str(k).strip() and str(k).strip().lower() not in known:
            out.append(dict(_safety_cell(ans[k]), item=str(k).strip(), extra=True))
    return out


def _safety_cell(raw):
    if isinstance(raw, dict):
        return {"status": _yesno(raw.get("status")), "notes": str(raw.get("notes") or "").strip()}
    return {"status": _yesno(raw), "notes": ""}


def _yesno(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return "unanswered"
    if isinstance(v, bool):
        return "yes" if v else "no"
    s = str(v).strip().lower()
    if s in ("yes", "y", "true", "1", "ok", "pass", "có", "co", "đạt", "dat"):
        return "yes"
    if s in ("no", "n", "false", "0", "fail", "không", "khong"):
        return "no"
    if s in ("n/a", "na", "not applicable", "n.a."):
        return "na"
    return "unanswered"


# ── the Gantt (5.2) ──────────────────────────────────────────────────────────────────────────────
def gantt(rows, categories=None, asof=None):
    """5.2 Work Progress Gantt Chart: one bar per work item, grouped under a summary bar per
    category, with the same accumulated percentage that 5.1 prints.

    The category summary bar spans the earliest start to the latest finish of its children, and its
    duration is stated in days — which is what the source report prints beside a rolled-up group
    ("34 days", "114 days"). Its percentage is DELIBERATELY not an average of its children: a
    category holding a 200-day pipe run at 98% and a 3-day fixing at 10% is not 54% complete, and
    the source report does not claim one either — it prints the duration there instead.
    """
    items, cats = [], {}
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        s, f = to_date(r.get("start")), to_date(r.get("finish"))
        cat = str(r.get("category") or "").strip() or "—"
        pct = _pct(r.get("accum"))
        it = {"category": cat, "item": str(r.get("item") or "").strip(),
              "start": s.isoformat() if s else "", "finish": f.isoformat() if f else "",
              "pct": pct, "days": ((f - s).days + 1) if (s and f and f >= s) else None}
        items.append(it)
        c = cats.setdefault(cat, {"start": s, "finish": f})
        if s and (c["start"] is None or s < c["start"]):
            c["start"] = s
        if f and (c["finish"] is None or f > c["finish"]):
            c["finish"] = f
    order = [str(c).strip() for c in (categories or []) if str(c).strip() and str(c).strip() in cats]
    order += sorted(k for k in cats if k not in order)
    groups = []
    for name in order:
        c = cats[name]
        kids = sorted((i for i in items if i["category"] == name),
                      key=lambda i: (-(i["pct"] if i["pct"] is not None else -1), i["item"].lower()))
        groups.append({
            "category": name,
            "start": c["start"].isoformat() if c["start"] else "",
            "finish": c["finish"].isoformat() if c["finish"] else "",
            "days": ((c["finish"] - c["start"]).days + 1) if (c["start"] and c["finish"]) else None,
            "rows": kids})
    span = _span(groups)
    return {"groups": groups, "start": span[0], "finish": span[1],
            "today": iso(asof), "quarters": _quarters(span[0], span[1])}


def _span(groups):
    starts = [g["start"] for g in groups if g["start"]]
    ends = [g["finish"] for g in groups if g["finish"]]
    return (min(starts) if starts else "", max(ends) if ends else "")


def _quarters(start, finish):
    """The Q3 / Q4 column headings across the top of the Gantt."""
    s, f = to_date(start), to_date(finish)
    if not (s and f) or f < s:
        return []
    out = []
    y, q = s.year, (s.month - 1) // 3 + 1
    while (y, q) <= (f.year, (f.month - 1) // 3 + 1):
        qs = date(y, (q - 1) * 3 + 1, 1)
        qe = date(y + (q == 4), (q % 4) * 3 + 1, 1) - timedelta(days=1)
        out.append({"label": "Q%d" % q, "year": y, "start": qs.isoformat(), "finish": qe.isoformat()})
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
def photo_caption(category, seq):
    """"HVAC Works - Photo 01" — the caption format the source report uses under every daily photo."""
    n = "%02d" % int(seq or 0) if str(seq or "").strip().isdigit() else str(seq or "")
    cat = str(category or "").strip()
    return ("%s - Photo %s" % (cat, n)) if cat else ("Photo %s" % n)


def number_photos(photos, categories=None):
    """Caption and order the daily photos: numbered from 01 WITHIN each category, categories in the
    contractor's own order. The sequence is assigned here rather than trusted from the form, because
    a phone that uploads out of order, or a re-sync that re-reads the same list, would otherwise
    produce two "Photo 03"s and no "Photo 05" on a document that gets filed."""
    rows = [p for p in (photos or []) if isinstance(p, dict)]
    grouped = group_rows(rows, sort_key=lambda p: (str(p.get("takenAt") or ""), str(p.get("id") or "")))
    known = [str(c).strip() for c in (categories or []) if str(c).strip()]
    grouped.sort(key=lambda g: (known.index(g["category"]) if g["category"] in known else len(known),
                                g["category"].lower()))
    out = []
    for g in grouped:
        for i, p in enumerate(g["rows"], start=1):
            q = dict(p)
            q["seq"] = i
            q["caption"] = str(p.get("caption") or "").strip() or photo_caption(g["category"], i)
            out.append(q)
    return out


# ── sorting and filtering (the screen's controls, applied server-side too) ────────────────────────
def filter_reports(reports, project_id=None, contractor_id=None, month="", week="",
                   on_date="", q=""):
    """The filter bar: Contractor / Month / Week / Date, plus free-text search.

    'All' is the empty string for every one of them, matching the source report's dropdowns. Date
    wins over Month and Week when it is set, because that is what the screen does: picking a date
    shows that day, not that day intersected with a month somebody left set from last week.
    """
    out = []
    ql = str(q or "").strip().lower()
    for r in (reports or []):
        if not isinstance(r, dict):
            continue
        if project_id and str(r.get("projectId") or "") != str(project_id):
            continue
        if contractor_id and str(r.get("contractorId") or "") != str(contractor_id):
            continue
        d = iso(r.get("date"))
        if on_date:
            if d != iso(on_date):
                continue
        else:
            if month and month_of(d) != str(month):
                continue
            if week and week_of(d) != str(week):
                continue
        if ql and ql not in _haystack(r):
            continue
        out.append(r)
    return sorted(out, key=lambda r: iso(r.get("date")), reverse=True)


def _haystack(r):
    parts = [str(r.get("date") or ""), str(r.get("contractor") or ""), str(r.get("notes") or "")]
    for key in ("progress", "plan", "equipment", "materials", "inspections", "recommendations"):
        for row in (r.get(key) or []):
            if isinstance(row, dict):
                parts.extend(str(v) for v in row.values() if isinstance(v, (str, int, float)))
    return " ".join(parts).lower()


# Which column of which table may be sorted, and how its value is read. A named map rather than
# getattr-by-string: the sort key arrives from a query string, and letting a URL choose the
# expression it is sorted by is how a filter becomes an injection.
SORTABLE = {
    "equipment": {"item": lambda r: str(r.get("item") or "").lower(),
                  "qty": lambda r: _num(r.get("qty")),
                  "unit": lambda r: str(r.get("unit") or "").lower(),
                  "notes": lambda r: str(r.get("notes") or "").lower()},
    "materials": {"item": lambda r: str(r.get("item") or "").lower(),
                  "docCode": lambda r: str(r.get("docCode") or "").lower(),
                  "notes": lambda r: str(r.get("notes") or "").lower()},
    "progress":  {"category": lambda r: str(r.get("category") or "").lower(),
                  "item": lambda r: str(r.get("item") or "").lower(),
                  "daily": lambda r: _pct(r.get("daily")) if _pct(r.get("daily")) is not None else -1,
                  "accum": lambda r: _pct(r.get("accum")) if _pct(r.get("accum")) is not None else -1,
                  "start": lambda r: iso(r.get("start")),
                  "finish": lambda r: iso(r.get("finish"))},
    "plan":      {"category": lambda r: str(r.get("category") or "").lower(),
                  "item": lambda r: str(r.get("item") or "").lower(),
                  "location": lambda r: str(r.get("location") or "").lower()},
    "defects":   {"desc": lambda r: str(r.get("desc") or "").lower(),
                  "action": lambda r: str(r.get("action") or "").lower(),
                  "identified": lambda r: iso(r.get("identified")),
                  "due": lambda r: iso(r.get("due"))},
    "inspections": {"item": lambda r: str(r.get("item") or "").lower(),
                    "location": lambda r: str(r.get("location") or "").lower(),
                    "docCode": lambda r: str(r.get("docCode") or "").lower(),
                    "status": lambda r: str(r.get("status") or "").lower()},
    "inspectionPlan": {"item": lambda r: str(r.get("item") or "").lower(),
                       "location": lambda r: str(r.get("location") or "").lower(),
                       "time": lambda r: str(r.get("time") or "")},
    "safety":    {"item": lambda r: str(r.get("item") or "").lower(),
                  "status": lambda r: str(r.get("status") or "").lower()},
    "recommendations": {"item": lambda r: str(r.get("item") or "").lower(),
                        "location": lambda r: str(r.get("location") or "").lower()},
}


def sort_rows(table, rows, column, direction="asc"):
    """Sort one table's rows by one of ITS OWN sortable columns. An unknown table or column leaves
    the order untouched rather than raising — a stale sort saved in a bookmark should show the
    report, not an error page."""
    keys = SORTABLE.get(str(table) or "")
    fn = keys.get(str(column) or "") if keys else None
    if not fn:
        return list(rows or [])
    return sorted((r for r in (rows or []) if isinstance(r, dict)), key=fn,
                  reverse=str(direction).lower() in ("desc", "dsc", "down", "-1"))


# ── what the report itself is unsure about ───────────────────────────────────────────────────────
def warnings(project, contractor, report, photos=None):
    """Everything on this report that a reader should be told rather than left to discover.

    These are stated ON the report, not swallowed. The whole failure mode this module is written
    against is a document that looks complete and is not: a headcount summed from columns that were
    deleted, a safety register showing eleven ticks for a day nobody walked the site, a percentage
    that went backwards. Each of those still renders — and says so.
    """
    out = []
    rep = report or {}
    con = contractor or {}
    d = to_date(rep.get("date"))
    start, end = to_date((project or {}).get("startDate")), to_date((project or {}).get("endDate"))

    if not d:
        out.append({"level": "error", "msg": "This report has no date on it."})
    elif start and d < start:
        out.append({"level": "warn", "msg": "The report date is before the project start date."})
    elif end and d > end:
        out.append({"level": "warn", "msg": "The report date is after the planned completion date."})

    for kind, cols, label in (("mgmt", con.get("mgmtRoles"), "Management Staff"),
                              ("workers", con.get("workerTrades"), "Workers")):
        for col, raw, why in unreadable_counts(rep.get(kind), cols):
            out.append({"level": "warn", "msg":
                        "%s: the figure for %s (%r) %s, so it is counted as %d."
                        % (label, col, raw, why, _num(raw))})
        row = manpower_row(rep.get(kind), cols)
        if row["orphans"]:
            out.append({"level": "warn", "msg":
                        "%s: %d people are recorded under %s, which is not a column on this "
                        "contractor's table, so they are not in the total."
                        % (label, row["orphanTotal"],
                           ", ".join(o["col"] for o in row["orphans"]))})

    for r in (rep.get("progress") or []):
        if not isinstance(r, dict):
            continue
        daily, accum = _pct(r.get("daily")), _pct(r.get("accum"))
        name = str(r.get("item") or "an item")
        if accum is not None and accum > 100:
            out.append({"level": "warn", "msg": "%s is recorded at %g%% complete." % (name, accum)})
        if daily is not None and accum is not None and daily > accum:
            out.append({"level": "warn", "msg":
                        "%s moved %g%% today but stands at %g%% overall." % (name, daily, accum)})
        s, f = to_date(r.get("start")), to_date(r.get("finish"))
        if s and f and f < s:
            out.append({"level": "warn", "msg": "%s finishes before it starts." % name})

    unanswered = [s["item"] for s in safety_rows(rep.get("safety"), con.get("safetyChecklist"))
                  if s["status"] == "unanswered"]
    if unanswered:
        out.append({"level": "warn", "msg":
                    "%d safety check%s not answered today: %s."
                    % (len(unanswered), "" if len(unanswered) == 1 else "s were",
                       ", ".join(unanswered[:4]) + ("…" if len(unanswered) > 4 else ""))})

    if not (photos or []):
        out.append({"level": "info", "msg": "No progress photos were submitted for this day."})
    if not con.get("logo"):
        out.append({"level": "info", "msg":
                    "This contractor has no logo set up yet, so the report footer prints its name "
                    "instead. Set it once in Report Setup."})
    return out


# ── the page model both the screen and the PDF read ──────────────────────────────────────────────
def build(project, contractor, report, photos=None, history=None, asof=None):
    """Assemble one day's report. The ONE place that decides what is on each page.

    The screen renders this and the PDF prints it, so a change to what a section contains cannot
    land in one and miss the other — which is exactly how an exported PDF starts disagreeing with
    the page it was exported from.
    """
    rep = report or {}
    con = contractor or {}
    prj = project or {}
    d = iso(rep.get("date")) or iso(asof)
    cats = con.get("categories") or []
    hist = history or []
    cid = con.get("id") or rep.get("contractorId")
    daily_photos = number_photos([p for p in (photos or [])
                                  if str(p.get("kind") or "daily") == "daily"], cats)
    overview = sorted((p for p in (photos or []) if str(p.get("kind") or "") == "overview"),
                      key=lambda p: _num(p.get("seq")))

    return {
        "date": d,
        "project": {
            "name": prj.get("name") or "", "location": prj.get("location") or "",
            "investor": prj.get("investor") or "", "consultant": prj.get("consultant") or "",
            "pmConsultant": prj.get("pmConsultant") or "",
            "clientName": prj.get("clientName") or "", "clientLogo": prj.get("clientLogo") or "",
            "startDate": iso(prj.get("startDate")), "endDate": iso(prj.get("endDate")),
            "totalDays": total_duration_days(prj.get("startDate"), prj.get("endDate")),
            "elapsedDays": elapsed_duration_days(prj.get("startDate"), d),
        },
        "contractor": {"id": cid, "name": con.get("name") or "", "logo": con.get("logo") or ""},
        "sections": {
            "overview": {
                "mgmt": manpower_delta(hist, cid, d, "mgmt"),
                "workers": manpower_delta(hist, cid, d, "workers"),
                "photos": [dict(p, caption=str(p.get("caption") or "").strip()
                                or ("View %d" % (i + 1))) for i, p in enumerate(overview)],
            },
            "manpower": {
                "weather": weather(rep.get("weather")),
                "mgmt": manpower_row(rep.get("mgmt"), con.get("mgmtRoles")),
                "workers": manpower_row(rep.get("workers"), con.get("workerTrades")),
                "series": manpower_series(hist, cid, d),
            },
            "equipment": {"equipment": list(rep.get("equipment") or []),
                          "materials": list(rep.get("materials") or [])},
            "progress": {"groups": progress_rows(rep.get("progress"), cats)},
            "gantt": gantt(rep.get("progress"), cats, d),
            "plan": {"groups": plan_rows(rep.get("plan"), cats)},
            "photos": {"photos": daily_photos},
            "documents": {"groups": document_rows(rep.get("documents")),
                          "defects": list(rep.get("defects") or [])},
            "inspection": {"today": list(rep.get("inspections") or []),
                           "next": list(rep.get("inspectionPlan") or [])},
            "safety": {"checks": safety_rows(rep.get("safety"), con.get("safetyChecklist")),
                       "recommendations": list(rep.get("recommendations") or [])},
        },
        "warnings": warnings(prj, con, rep, photos),
        "source": rep.get("source") or "manual",
        "syncedAt": rep.get("syncedAt") or "",
        "status": rep.get("status") or "draft",
    }


def weather(w):
    """Table 1, with an icon per slot. Unrecognised conditions still print — see WEATHER_ICONS."""
    w = w if isinstance(w, dict) else {}
    slots = []
    for key, label in WEATHER_SLOTS:
        v = str(w.get(key) or "").strip()
        slots.append({"key": key, "label": label, "value": v,
                      "icon": WEATHER_ICONS.get(v.lower(), "")})
    temp = w.get("avgTemp")
    rain = w.get("rainHours")
    return {"slots": slots,
            "avgTemp": ("%g °C" % float(temp)) if _isnum(temp) else str(temp or ""),
            "rainHours": ("%g Hours" % float(rain)) if _isnum(rain) else str(rain or "")}


def _isnum(v):
    try:
        float(str(v).strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


# ── pagination: how many sheets, and what is on each ──────────────────────────────────────────────
# How many body rows of each table fit on one page, measured against the two reference PDFs rather
# than guessed: 5.1 prints 30 rows on page 4 of the Taikisha report with room to spare, and its
# rows wrap to two lines often enough that 30 is the honest ceiling. A section that exceeds its
# capacity CONTINUES rather than being truncated — the failure this replaces is a report that
# printed the first 30 items of 47 and looked complete.
ROWS_PER_PAGE = {"equipment": 22, "materials": 18, "progress": 30, "plan": 30,
                 "documents": 24, "inspection": 16, "safety": 22, "photos": 9}


def _rows_in(section, model):
    s = (model.get("sections") or {}).get(section) or {}
    if section == "progress" or section == "plan":
        return sum(g["count"] + 1 for g in s.get("groups") or [])
    if section == "equipment":
        return len(s.get("equipment") or []) + len(s.get("materials") or [])
    if section == "documents":
        return sum(len(g["rows"]) + 1 for g in s.get("groups") or []) + len(s.get("defects") or [])
    if section == "inspection":
        return len(s.get("today") or []) + len(s.get("next") or [])
    if section == "safety":
        return len(s.get("checks") or []) + len(s.get("recommendations") or [])
    if section == "photos":
        return len(s.get("photos") or [])
    return 0


def paginate(model):
    """The sheet PLAN: one page per section, plus continuation sheets where a table will not fit.
    Returns [{"section", "part", "parts", "rows": (from, to), "page", "of"}].

    This is an ESTIMATE, from row counts, and it is what the screen previews before anybody clicks
    Export. It is deliberately NOT the authority on the printed page count: the exporter renders
    each section and MEASURES it, then numbers the sheets from what it measured, because a row that
    wraps to three lines makes any row-count estimate wrong and a footer reading "Page 1/10" on a
    twelve-sheet document is worse than no footer at all.

    Keeping both is the reason to say which is which here. The estimate exists so the screen can
    say roughly how long the report will print; the measurement exists so the document is right.
    Nothing shows the two numbers side by side.
    """
    pages = []
    for s in SECTIONS:
        key = s["key"]
        cap = ROWS_PER_PAGE.get(key)
        n = _rows_in(key, model) if cap else 0
        parts = max(1, -(-n // cap)) if cap and n else 1
        for i in range(parts):
            pages.append({"section": key, "tab": s["tab"], "headings": s["headings"],
                          "part": i + 1, "parts": parts,
                          "rows": (i * cap, min(n, (i + 1) * cap)) if cap else (0, 0)})
    for i, p in enumerate(pages, start=1):
        p["page"] = i
        p["of"] = len(pages)
    return pages
