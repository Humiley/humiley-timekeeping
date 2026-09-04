"""Reading the Daily Report out of the SharePoint forms the site actually fills in.

The site does not type into this portal. It fills a SharePoint form on a phone, standing in a
half-built plant room, and that submission is the report — so this module's whole job is to turn
list items into the shapes `daily_report.build` expects, and to be honest about the parts it could
not read.

HOW THE FORMS ARE SHAPED. A SharePoint form writes ONE list item per submission, and a daily report
has eleven repeating tables on it. There is no form that submits a variable-length table into one
item, so the arrangement that actually works — and the one this module is built for — is a list per
table, each row carrying the date and the contractor it belongs to:

    Daily Report Header      one row per contractor per day: weather, headcount per role
    Daily Work Progress      many rows per day: category, item, % today, % overall, dates
    Daily Work Plan          many rows: tomorrow's items
    Daily Equipment          many rows          Daily Materials       many rows
    Daily Documents          many rows          Daily Defects         many rows
    Daily Inspection         many rows          Daily Inspection Plan many rows
    Daily Safety             many rows          Daily Recommendations many rows
    Daily Photos             many rows: a photo, a category, a caption

`LIST_KINDS` names those twelve, and a contractor is set up once with the URL of each list it uses.
A list left unconfigured is not an error — plenty of days have no defects list at all — it simply
contributes nothing, and `sync_report` says which kinds it read from so a section that is empty
because nobody configured its list does not look like a section that is empty because nothing
happened.

WHY THE COLUMN NAMES ARE MAPPED RATHER THAN ASSUMED. SharePoint internal column names are whatever
the person who built the list happened to type, and then frozen forever: a column displayed as
"Daily Progress (%)" is internally `Daily_x0020_Progress_x0020__x002…`. Assuming a name would mean
the sync worked on our test list and silently read blanks on theirs — the worst possible outcome,
because a report full of empty cells looks like a quiet site. So `automap` matches the list's real
columns against candidate titles and returns BOTH what it matched and what it could not, and
`sync_report` refuses a kind whose essential fields are unmapped instead of importing zeroes.

WHERE THE PHOTOS COME FROM. Three arrangements exist in the wild and two of them are reachable with
the Graph app-only token this portal already has consented:

  1. A DOCUMENT LIBRARY FOLDER (`photoFolder`). Graph reads it directly. This is the arrangement to
     prefer and the one Report Setup recommends.
  2. A LINK COLUMN — what a Microsoft Forms file-upload question produces: the list item holds a
     sharing URL into OneDrive/SharePoint. Graph resolves it through /shares/{encoded}/driveItem.
  3. LIST-ITEM ATTACHMENTS — the paperclip on a classic SharePoint form. Microsoft Graph v1.0 has
     NO attachments relationship on a listItem; they are reachable only through the SharePoint REST
     API, which needs a token for the SharePoint resource rather than for Graph, and therefore a
     SEPARATE application consent (SharePoint › Sites.Read.All). `attachments_available` reports
     whether that consent exists and `attachment_help` explains it. We do not pretend to read them:
     the failure mode of pretending is a photo section that is permanently empty with no reason
     given, which is the exact shape of bug this codebase has been bitten by most.

Bytes are never copied into the database. A photo is stored as its Graph reference and streamed
through the portal's own endpoint, which keeps the report rows small and — because the endpoint is
same-origin — lets html2canvas draw the photos into the exported PDF at all.

NO NETWORK CALL IS MADE BY THIS MODULE. Every function that needs one takes a `get` callable and
the caller supplies it (app.py passes a Graph-authenticated fetch, tests pass a dict). That is not
decoration: it is the only way the mapping and assembly logic — where all the real bugs live — can
be tested at all.
"""
import json
import re
import urllib.parse

import daily_report as dr

GRAPH = "https://graph.microsoft.com/v1.0"

# The twelve lists a fully-configured contractor has, and what each one contributes to the report.
#   key       -> (human label, the report field it fills, "one row per day" or "many rows per day")
LIST_KINDS = {
    "header":         ("Daily Report Header", None, "one"),
    "progress":       ("Work Progress", "progress", "many"),
    "plan":           ("Next Day Work Plan", "plan", "many"),
    "equipment":      ("Equipment & Machinery", "equipment", "many"),
    "materials":      ("Material Delivery", "materials", "many"),
    "documents":      ("Site Document Exchange", "documents", "many"),
    "defects":        ("Defect Check List", "defects", "many"),
    "inspections":    ("Daily Inspection", "inspections", "many"),
    "inspectionPlan": ("Next Day Inspection Plan", "inspectionPlan", "many"),
    "safety":         ("Safety Control Activities", "safety", "many"),
    "recommendations": ("Requests & Recommendations", "recommendations", "many"),
    "photos":         ("Daily Progress Photos", None, "many"),
}

# Candidate column titles per canonical field, most specific first. Matching is on a normalised form
# (lower-cased, non-alphanumerics stripped) so "Daily Progress (%)", "daily_progress" and
# "DailyProgress%" all land on the same field.
#
# `date` and `contractor` are on EVERY list: they are how a row is attached to a day and a company.
# Both are in the required set for every kind, because a row that cannot say which day it belongs to
# cannot be filed at all — importing it against today would put last Tuesday's work on this
# afternoon's report.
COMMON = {
    "date": ("reportdate", "date", "ngay", "ngaybaocao", "reportingdate", "workdate", "day"),
    "contractor": ("contractor", "nhathau", "subcontractor", "company", "contractorname"),
}
FIELD_SPECS = {
    "header": {
        "weatherMorning":   ("morning", "morning7001100", "weathermorning", "buoisang"),
        "weatherAfternoon": ("afternoon", "afternoon13001700", "weatherafternoon", "buoichieu"),
        "weatherEvening":   ("evening", "evening17002400", "weatherevening", "buoitoi"),
        "avgTemp":          ("averagetemperature", "avgtemperature", "temperature", "temp", "nhietdo"),
        "rainHours":        ("totalrainfallduration", "rainfallduration", "rainhours", "rainfall", "giomua"),
        "notes":            ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "progress": {
        "category": ("category", "workcategory", "discipline", "trade", "hangmuc", "loaicongviec"),
        "item":     ("reportitems", "reportitem", "workitem", "item", "description", "congviec"),
        "daily":    ("dailyprogress", "dailyprogress%", "progresstoday", "todayprogress", "tienDoNgay"),
        "accum":    ("accumulatedprogress", "accumulatedprogress%", "totalprogress",
                     "cumulativeprogress", "overallprogress"),
        "start":    ("startdate", "start", "plannedstart", "ngaybatdau"),
        "finish":   ("finishdate", "finish", "enddate", "plannedfinish", "ngayketthuc"),
    },
    "plan": {
        "category": ("category", "workcategory", "discipline", "trade", "hangmuc"),
        "item":     ("reportitems", "reportitem", "workitem", "item", "description", "congviec"),
        "location": ("location", "zone", "area", "viTri", "vitri"),
        "notes":    ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "equipment": {
        "item":  ("reportitems", "reportitem", "equipment", "machinery", "item", "thietbi"),
        "qty":   ("quantity", "qty", "soluong", "count"),
        "unit":  ("unit", "uom", "donvi"),
        "notes": ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "materials": {
        "item":    ("reportitems", "reportitem", "material", "item", "vattu"),
        "docCode": ("documentcode", "doccode", "code", "reference", "sohieu"),
        "notes":   ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "documents": {
        "group":    ("group", "submissiontype", "documentgroup", "type", "nhom"),
        "item":     ("reportitems", "reportitem", "document", "item", "title", "tailieu"),
        "docCode":  ("documentcode", "doccode", "code", "reference", "sohieu"),
        "category": ("category", "discipline", "trade", "hangmuc"),
        "notes":    ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "defects": {
        "desc":       ("defectdescription", "defect", "description", "issue", "moTa", "mota"),
        "action":     ("correctiveaction", "action", "correction", "bienphap"),
        "identified": ("dateidentified", "identified", "raiseddate", "ngayphathien"),
        "due":        ("expectedcompletiondate", "expectedcompletion", "duedate", "targetdate", "ngayhoanthanh"),
    },
    "inspections": {
        "item":     ("inspectionitem", "inspection", "item", "workitem", "noidungkiemtra"),
        "location": ("location", "zone", "area", "vitri"),
        "docCode":  ("documentcode", "doccode", "code", "reference", "sohieu"),
        "status":   ("status", "result", "outcome", "ketqua"),
        "notes":    ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "inspectionPlan": {
        "item":     ("workitem", "inspectionitem", "item", "noidung"),
        "location": ("location", "zone", "area", "vitri"),
        "time":     ("time", "plannedtime", "gio", "thoigian"),
        "notes":    ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "safety": {
        "item":   ("reportitems", "reportitem", "safetyitem", "check", "item", "noidung"),
        "status": ("status", "result", "done", "completed", "ketqua"),
        "notes":  ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "recommendations": {
        "item":     ("recommendation", "request", "reportitems", "item", "kiennghi"),
        "location": ("location", "zone", "area", "vitri"),
        "notes":    ("notes", "note", "remark", "remarks", "ghichu"),
    },
    "photos": {
        "category": ("category", "workcategory", "discipline", "trade", "hangmuc"),
        "caption":  ("caption", "title", "description", "photocaption", "chuthich"),
        "photo":    ("photo", "photos", "image", "picture", "attachment", "file", "fileurl",
                     "photolink", "hinhanh"),
        "takenAt":  ("takenat", "time", "phototime", "created", "thoigian"),
        "kind":     ("kind", "phototype", "type", "loai"),
    },
}

# The fields without which a row cannot be filed. Everything else may legitimately be blank on a
# given day; these are what make the row a row. A kind whose required fields are not all mapped is
# REFUSED by `sync_report` rather than imported — see the module docstring.
REQUIRED = {
    "header": ("date",),
    "progress": ("date", "item"),
    "plan": ("date", "item"),
    "equipment": ("date", "item"),
    "materials": ("date", "item"),
    "documents": ("date", "item"),
    "defects": ("date", "desc"),
    "inspections": ("date", "item"),
    "inspectionPlan": ("date", "item"),
    "safety": ("date", "item"),
    "recommendations": ("date", "item"),
    "photos": ("date", "photo"),
}


# ── names and URLs ───────────────────────────────────────────────────────────────────────────────
def norm(s):
    """'Daily Progress (%)' → 'dailyprogress%'. Keeps % because it distinguishes a percentage
    column from an identically-named text one, and SharePoint list builders really do ship both."""
    s = str(s or "")
    s = re.sub(r"_x[0-9a-fA-F]{4}_", "", s)          # SharePoint's encoded spaces and punctuation
    return re.sub(r"[^a-z0-9%]", "", s.lower())


def parse_list_url(url):
    """A pasted SharePoint list URL → (host, site_path, list_hint).

    Accepts every form an admin actually copies out of the address bar:
        …/sites/Mega/Lists/Daily Work Progress/AllItems.aspx
        …/sites/Mega/Lists/DailyWorkProgress
        …/sites/Mega/_layouts/15/listedit.aspx?List=%7Bguid%7D
        …/sites/Mega/Lists/X/AllItems.aspx?viewid=…
    `list_hint` is a title or a GUID; `resolve_list` copes with either. Raises ValueError with a
    sentence an admin can act on — "Expected a link like …" beats "invalid URL", because the person
    reading it is holding the thing that produced the URL.
    """
    pu = urllib.parse.urlparse(str(url or "").strip())
    if not pu.netloc:
        raise ValueError("Expected a full https://<tenant>.sharepoint.com/sites/… link to the list.")
    qs = urllib.parse.parse_qs(pu.query or "")
    guid = ""
    for k in ("list", "listid"):
        for qk in qs:
            if qk.lower() == k and qs[qk]:
                guid = qs[qk][0].strip().strip("{}")
                break
    parts = [urllib.parse.unquote(p) for p in pu.path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() != "sites":
        raise ValueError("Expected a link like "
                         "https://<tenant>.sharepoint.com/sites/<Site>/Lists/<List Name>")
    site_path = "/sites/" + parts[1]
    rest = parts[2:]
    hint = guid
    if not hint:
        for i, p in enumerate(rest):
            if p.lower() == "lists" and i + 1 < len(rest):
                hint = rest[i + 1]
                break
        else:
            # A library-style link (…/sites/X/Daily Photos/Forms/AllItems.aspx) names the list
            # directly. Strip the view page and the Forms folder the same way the folder parser does.
            trimmed = [p for p in rest if not p.lower().endswith(".aspx") and p.lower() != "forms"
                       and p.lower() != "_layouts" and p != "15"]
            hint = trimmed[0] if trimmed else ""
    if not hint:
        raise ValueError("That link does not name a list. Open the list and copy the URL from the "
                         "address bar, or use its Settings page.")
    return pu.netloc, site_path, hint


def resolve_list(get, url):
    """(host, site, list_hint) → {"site", "list", "listName", "host"}.

    `get(url)` must return the parsed JSON of an authenticated Graph GET. Resolution is by GUID when
    the URL carried one, else by display name, else by the list's internal name — in that order,
    because a list renamed after the form was built keeps its old internal name and its GUID, and
    matching on display name alone would break the day somebody tidied a title.
    """
    host, site_path, hint = parse_list_url(url)
    site = get(GRAPH + "/sites/" + host + ":" + site_path)
    site_id = (site or {}).get("id")
    if not site_id:
        raise ValueError("Could not open that SharePoint site. Check the link and that the portal "
                         "has been granted access to it.")
    if re.fullmatch(r"[0-9a-fA-F-]{36}", hint or ""):
        lst = get(GRAPH + "/sites/" + site_id + "/lists/" + hint)
        if not (lst or {}).get("id"):
            raise ValueError("That site has no list with id %s." % hint)
        return {"host": host, "site": site_id, "list": lst["id"],
                "listName": lst.get("displayName") or lst.get("name") or hint}
    want = norm(hint)
    page = get(GRAPH + "/sites/" + site_id + "/lists?$select=id,name,displayName&$top=200")
    lists = (page or {}).get("value") or []
    for key in ("displayName", "name"):
        for l in lists:
            if norm(l.get(key)) == want:
                return {"host": host, "site": site_id, "list": l.get("id"),
                        "listName": l.get("displayName") or l.get("name") or hint}
    raise ValueError("No list called %r on that site. Its lists are: %s"
                     % (hint, ", ".join(sorted(str(l.get("displayName") or l.get("name"))
                                               for l in lists)[:20]) or "(none visible)"))


def list_columns(get, site_id, list_id):
    """[{"name": internal, "title": display}] for one list. `name` is what item fields are keyed by;
    `title` is what the person who built the form sees, and what `automap` matches against."""
    page = get(GRAPH + "/sites/" + site_id + "/lists/" + list_id
               + "/columns?$select=name,displayName,readOnly,hidden")
    out = []
    for c in (page or {}).get("value") or []:
        if c.get("hidden"):
            continue
        out.append({"name": c.get("name") or "", "title": c.get("displayName") or c.get("name") or ""})
    return out


# ── mapping ──────────────────────────────────────────────────────────────────────────────────────
def automap(kind, columns, roles=None, trades=None):
    """Match a list's real columns onto canonical field names.

    Returns {"map": {field: internalName}, "missing": [required fields not found],
             "roles": {roleName: internalName}, "unused": [columns nothing claimed]}.

    `roles`/`trades` are the CONTRACTOR'S OWN column lists (see daily_report.manpower_row): a header
    list's headcount columns are named after that contractor's roles, which differ per company — so
    they are matched from the setup rather than from a fixed table, and a contractor who adds a
    "Storage man" column tomorrow needs no code change.

    `unused` is returned, and shown in Report Setup, because the useful diagnostic when a field
    imports blank is not "we could not find Daily Progress" — it is "we could not find it, and here
    are the twelve columns that are actually on your list".
    """
    spec = FIELD_SPECS.get(kind) or {}
    by_norm = {}
    for c in (columns or []):
        for k in (c.get("title"), c.get("name")):
            n = norm(k)
            if n and n not in by_norm:
                by_norm[n] = c.get("name")
    got, claimed = {}, set()
    for field, cands in list(COMMON.items()) + list(spec.items()):
        for cand in cands:
            hit = by_norm.get(norm(cand))
            if hit and hit not in claimed:
                got[field] = hit
                claimed.add(hit)
                break
    role_map = {}
    if kind == "header":
        for name in list(roles or []) + list(trades or []):
            hit = by_norm.get(norm(name))
            if hit and hit not in claimed:
                role_map[str(name)] = hit
                claimed.add(hit)
    missing = [f for f in REQUIRED.get(kind, ()) if f not in got]
    unused = sorted({c.get("title") or c.get("name") for c in (columns or [])
                     if c.get("name") not in claimed and c.get("name")})
    return {"map": got, "missing": missing, "roles": role_map, "unused": unused}


def merge_map(auto, manual):
    """An admin's hand-corrections win over the automatic match. Both are stored, so re-running
    detection after somebody adds a column cannot silently undo a correction they made."""
    out = dict((auto or {}).get("map") or {})
    for k, v in ((manual or {}).get("map") or {}).items():
        if str(v or "").strip():
            out[k] = v
    roles = dict((auto or {}).get("roles") or {})
    roles.update({k: v for k, v in ((manual or {}).get("roles") or {}).items() if str(v or "").strip()})
    return {"map": out, "roles": roles,
            "missing": [f for f in (auto or {}).get("missing") or [] if f not in out],
            "unused": (auto or {}).get("unused") or []}


def _field(fields, mapping, name):
    key = (mapping or {}).get(name)
    if not key:
        return None
    v = (fields or {}).get(key)
    if isinstance(v, dict):
        # A SharePoint lookup / person / hyperlink column arrives as an object. Take the label a
        # human would read, never the raw dict — which would render as "{'Url': …}" in a table cell.
        for k in ("LookupValue", "Label", "DisplayName", "Title", "Description", "Url", "Email"):
            if v.get(k):
                return v[k]
        return ""
    if isinstance(v, list):
        return ", ".join(str(_field({"x": x}, {"x": "x"}, "x") or "") for x in v)
    return v


def _text(fields, mapping, name):
    v = _field(fields, mapping, name)
    return "" if v is None else str(v).strip()


def map_row(kind, fields, mapping):
    """One list item → the canonical row shape. Unmapped fields come back blank, never invented."""
    m = (mapping or {}).get("map") if "map" in (mapping or {}) else mapping
    spec = FIELD_SPECS.get(kind) or {}
    row = {}
    for field in list(COMMON) + list(spec):
        row[field] = _text(fields, m, field)
    row["date"] = dr.iso(row.get("date"))
    if kind == "header":
        roles = (mapping or {}).get("roles") or {}
        counts = {}
        for role, col in roles.items():
            raw = (fields or {}).get(col)
            if raw is not None and str(raw).strip() != "":
                counts[role] = raw
        row["counts"] = counts
    if kind in ("progress",):
        for k in ("start", "finish"):
            row[k] = dr.iso(row.get(k))
    if kind == "defects":
        for k in ("identified", "due"):
            row[k] = dr.iso(row.get(k))
    if kind == "photos":
        row["ref"] = photo_ref(fields, m)
    return row


def fetch_items(get, site_id, list_id, top=500, date_field=None, since="", until=""):
    """Every item of one list as a fields dict, following Graph's paging.

    Filtering by date is done SERVER-SIDE when the list's date column is known, because a project
    that has been running eighteen months has thousands of progress rows and pulling all of them to
    keep three is how a sync starts timing out in month six. When the column is not known the filter
    is applied here instead — slower, but it still returns the right answer rather than refusing.
    """
    url = (GRAPH + "/sites/" + site_id + "/lists/" + list_id
           + "/items?expand=fields&$top=" + str(min(int(top or 500), 999)))
    if date_field and (since or until):
        clauses = []
        if since:
            clauses.append("fields/%s ge '%s'" % (date_field, dr.iso(since)))
        if until:
            clauses.append("fields/%s le '%sT23:59:59Z'" % (date_field, dr.iso(until)))
        url += "&$filter=" + urllib.parse.quote(" and ".join(clauses))
    out, seen = [], 0
    while url and seen < 20000:                      # a hard stop: a runaway page loop is not a sync
        page = get(url) or {}
        for it in page.get("value") or []:
            f = dict(it.get("fields") or {})
            f.setdefault("_spItemId", it.get("id"))
            out.append(f)
            seen += 1
        url = page.get("@odata.nextLink")
    return out


# ── photos ───────────────────────────────────────────────────────────────────────────────────────
def photo_ref(fields, mapping):
    """Where one photo actually lives, from whatever the form put in the column.

    Returns {"kind": "share"|"drive"|"none", "url", "driveId", "itemId", "name"}. `kind` "none" is a
    real answer and is reported: a photo row whose file column is empty is a row somebody submitted
    without attaching anything, and the report should say the photo is missing rather than render a
    broken image frame.
    """
    raw = _field(fields, mapping, "photo")
    if isinstance(raw, dict):
        url = raw.get("Url") or raw.get("url") or ""
        name = raw.get("Description") or raw.get("fileName") or ""
    else:
        url, name = str(raw or "").strip(), ""
    if not url:
        return {"kind": "none", "url": "", "driveId": "", "itemId": "", "name": ""}
    # A Forms upload answer is a JSON array of {name, link}. Parse it rather than storing the JSON
    # as a URL, which is what makes the photo pane show a broken frame with no explanation.
    if url.startswith("[") or url.startswith("{"):
        try:
            j = json.loads(url)
            first = (j[0] if isinstance(j, list) and j else j) or {}
            url = str(first.get("link") or first.get("url") or "").strip()
            name = str(first.get("name") or name).strip()
        except (ValueError, TypeError, KeyError, IndexError):
            return {"kind": "none", "url": "", "driveId": "", "itemId": "", "name": name}
    if not url:
        return {"kind": "none", "url": "", "driveId": "", "itemId": "", "name": name}
    return {"kind": "share", "url": url, "driveId": "", "itemId": "",
            "name": name or url.rsplit("/", 1)[-1].split("?")[0]}


def share_id(url):
    """A sharing URL → Graph's /shares/{id} token. Base64url of 'u!' + the URL, unpadded, which is
    the encoding Graph documents for this call."""
    import base64
    b = base64.urlsafe_b64encode(str(url or "").encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b


def folder_photos(get, drive_id, rel_path):
    """The photo files in a document-library folder — arrangement 1 in the module docstring.

    Only image files come back. A folder that also holds a method statement PDF should not put it in
    the photo grid, and filtering by the MIME type Graph reports is more reliable than by extension
    (a phone uploads .HEIC, .jpeg and .jpg for the same picture).
    """
    base = GRAPH + "/drives/" + drive_id + "/root"
    if rel_path:
        base += ":/" + "/".join(urllib.parse.quote(p) for p in rel_path.split("/") if p) + ":"
    url = base + "/children?$top=200&$select=id,name,file,photo,createdDateTime,size"
    out = []
    while url:
        page = get(url) or {}
        for it in page.get("value") or []:
            f = it.get("file") or {}
            if not str(f.get("mimeType") or "").startswith("image/"):
                continue
            out.append({"driveId": drive_id, "itemId": it.get("id"), "name": it.get("name") or "",
                        "takenAt": ((it.get("photo") or {}).get("takenDateTime")
                                    or it.get("createdDateTime") or ""),
                        "size": it.get("size") or 0, "mime": f.get("mimeType")})
        url = page.get("@odata.nextLink")
    return out


# Where a day's submissions live under the project's own SharePoint folder. One folder per
# contractor per month per day, because that is the shape somebody looking for "Taikisha, 1
# September" actually browses — and because a single flat folder with a year of site photos in it
# is a folder nobody opens twice.
FOLDER_ROOT = "Daily Report"


def folder_for(contractor_name, on_date, root=FOLDER_ROOT):
    """'Daily Report/Taikisha/2026-09/2026-09-01' — the path a day's photos and files are filed at,
    relative to the project's SharePoint folder. Returns '' for a date that cannot be read, so a
    caller never creates a folder called 'None'."""
    d = dr.iso(on_date)
    if not d:
        return ""
    who = _safe_segment(contractor_name) or "Unassigned"
    return "/".join([str(root or FOLDER_ROOT).strip("/"), who, d[:7], d])


def _safe_segment(name):
    """A folder name SharePoint will accept. It rejects " * : < > ? / \\ | and leading/trailing dots,
    and a contractor called 'Newtecons JSC / Taikisha' would otherwise create two nested folders."""
    s = re.sub(r'[\\/:*?"<>|#%{}~&]+', " ", str(name or ""))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:120]


def attachment_help():
    """Why the paperclip does not work, in words an admin can act on.

    This is a flat NO rather than a permission check, and deliberately so. Microsoft Graph v1.0 has
    no attachments relationship on a listItem at ANY consent level — granting more permission does
    not open this door — so a function that inspected the token's roles and answered "maybe" would
    send an admin to Azure to grant something that cannot help. The two arrangements that DO work
    are named here because that is the actual next step.
    """
    return ("Photos attached with the paperclip on a classic SharePoint form cannot be read by this "
            "portal: Microsoft Graph has no way to reach list attachments, and no extra permission "
            "changes that. Two arrangements do work — put the photos in a document library folder "
            "and give Report Setup that folder's link, or use a form question that UPLOADS the file, "
            "which stores a link the portal can follow.")


# ── assembly ─────────────────────────────────────────────────────────────────────────────────────
def _matches(row, contractor_name, on_date):
    if on_date and dr.iso(row.get("date")) != dr.iso(on_date):
        return False
    want = norm(contractor_name)
    got = norm(row.get("contractor"))
    # A list dedicated to one contractor legitimately has no contractor column at all, and a blank
    # there must NOT exclude the row — that would silently import nothing from the most common
    # single-contractor setup. A value that is present and different does exclude it.
    return (not got) or (not want) or got == want


def assemble(rows_by_kind, contractor, on_date):
    """The rows pulled from every list → one report dict plus its photo rows.

    Returns (report, photos, notes). `notes` carries what was skipped and why — a row whose date
    could not be read, a row belonging to another contractor — because a sync that quietly drops
    nine rows of forty is indistinguishable from a quiet day on site.
    """
    con = contractor or {}
    cid = con.get("id") or ""
    cname = con.get("name") or ""
    notes, report = [], {
        "contractorId": cid, "projectId": con.get("projectId") or "",
        "date": dr.iso(on_date), "source": "sharepoint", "status": "submitted",
    }
    # EVERY kind is walked, including ones the caller pulled nothing for. Iterating only the keys
    # present meant a day whose header list was unconfigured — or returned nothing — produced a
    # report with no weather and no headcount and NOT ONE WORD saying so, which on this document
    # reads as a site that recorded no people. An absent kind is a fact about the report and has to
    # be stated by the same code path that states a present one.
    pulled = rows_by_kind or {}
    for kind in LIST_KINDS:
        rows = pulled.get(kind)
        if rows is None and kind != "header":
            continue
        rows = rows or []
        keep, dropped_date, dropped_con = [], 0, 0
        for r in (rows or []):
            if not dr.iso(r.get("date")):
                dropped_date += 1
                continue
            if not _matches(r, cname, on_date):
                if dr.iso(r.get("date")) == dr.iso(on_date):
                    dropped_con += 1
                continue
            keep.append(r)
        if dropped_date:
            notes.append({"level": "warn", "kind": kind, "msg":
                          "%d row%s in %s had no readable date and were not imported."
                          % (dropped_date, "" if dropped_date == 1 else "s",
                             LIST_KINDS.get(kind, (kind,))[0])})
        if dropped_con:
            notes.append({"level": "info", "kind": kind, "msg":
                          "%d row%s in %s belong to another contractor."
                          % (dropped_con, "" if dropped_con == 1 else "s",
                             LIST_KINDS.get(kind, (kind,))[0])})
        if kind == "header":
            _apply_header(report, keep, notes)
        elif kind == "photos":
            report.setdefault("_photos", []).extend(keep)
        elif kind == "safety":
            report["safety"] = {r["item"]: {"status": r.get("status"), "notes": r.get("notes")}
                                for r in keep if r.get("item")}
        else:
            field = LIST_KINDS.get(kind, (None, None))[1]
            if field:
                report[field] = [{k: v for k, v in r.items()
                                  if k not in ("contractor", "ref", "counts")} for r in keep]
    photos = _photo_rows(report.pop("_photos", []), report, cid)
    return report, photos, notes


def _item_order(row):
    raw = str((row or {}).get("_spItemId") or "")
    return (0, int(raw), "") if raw.isdigit() else (1, 0, raw)


def _apply_header(report, rows, notes):
    if not rows:
        notes.append({"level": "warn", "kind": "header", "msg":
                      "No header row for this day, so the weather and the headcount are unknown."})
        return
    if len(rows) > 1:
        # Two submissions for one day is a real thing (a correction, or two people filling it in).
        # The LAST one wins because that is the correction, and the fact is stated rather than
        # silently resolved — a headcount that changed with no explanation is a headcount that gets
        # argued about at the site meeting.
        notes.append({"level": "warn", "kind": "header", "msg":
                      "%d header rows were submitted for this day; the most recently created one "
                      "is used." % len(rows)})
    # Ordered NUMERICALLY. SharePoint item ids are numeric strings, and a string sort puts item 9
    # after item 10 — so the "most recently created" row would be the OLDER one exactly once every
    # ten submissions, silently reinstating the figures a correction was filed to replace.
    h = sorted(rows, key=_item_order)[-1]
    report["weather"] = {"morning": h.get("weatherMorning") or "",
                         "afternoon": h.get("weatherAfternoon") or "",
                         "evening": h.get("weatherEvening") or "",
                         "avgTemp": h.get("avgTemp") or "", "rainHours": h.get("rainHours") or ""}
    report["notes"] = h.get("notes") or ""
    report["spItemId"] = h.get("_spItemId") or ""
    counts = h.get("counts") or {}
    report["mgmt"], report["workers"] = {}, {}
    report["_counts"] = counts


def split_counts(report, roles, trades):
    """Put each headcount column on the right table. The header list has one column per role and no
    idea which table it belongs to; the CONTRACTOR knows, so the split is driven from its setup.
    A count matching neither list stays in the report untouched and is surfaced by
    daily_report.warnings as an orphan — never dropped, never added to a total it is not under."""
    counts = report.pop("_counts", None)
    if counts is None:
        return report
    rl = {norm(r): r for r in (roles or []) if str(r).strip()}
    tl = {norm(t): t for t in (trades or []) if str(t).strip()}
    mgmt, workers, other = {}, {}, {}
    for k, v in counts.items():
        n = norm(k)
        if n in rl:
            mgmt[rl[n]] = v
        elif n in tl:
            workers[tl[n]] = v
        else:
            other[k] = v
    report["mgmt"] = mgmt
    report["workers"] = dict(workers)
    # An unrecognised column goes onto the WORKERS table, which is the one whose trades change most
    # and the one an orphan is most likely to belong to — and daily_report.warnings then names it in
    # print. Discarding it would remove people from the report with no trace at all.
    report["workers"].update(other)
    return report


def _photo_rows(rows, report, contractor_id):
    out = []
    for i, r in enumerate(rows or []):
        ref = r.get("ref") or {}
        out.append({
            "contractorId": contractor_id, "projectId": report.get("projectId") or "",
            "date": dr.iso(r.get("date")), "kind": (r.get("kind") or "daily").strip().lower() or "daily",
            "category": r.get("category") or "", "caption": r.get("caption") or "",
            "takenAt": r.get("takenAt") or "", "src": "sharepoint",
            "spKind": ref.get("kind") or "none", "spUrl": ref.get("url") or "",
            "spDriveId": ref.get("driveId") or "", "spItemId": ref.get("itemId") or "",
            "fileName": ref.get("name") or "", "seq": i + 1,
        })
    return out
