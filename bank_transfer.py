"""The salary payment file the bank actually accepts.

The last manual step in the payroll month: somebody reads the net pay off a screen and types thirty
account numbers into the bank's upload template. A transposed digit pays a stranger, a missed row
means somebody quietly does not get paid on the 5th, and neither is visible until the person says so.

This builds the file from the run a Director signed, and refuses to build a partial one.

Two things it will not do, both deliberate:

  It will not omit anybody. If an employee in the run has no usable bank details, the whole file is
  refused and they are named. A file that silently drops one row looks exactly like a correct file,
  and the failure surfaces as somebody with no rent money.

  It will not quietly regenerate. Producing the file a second time is how salaries get paid twice,
  so a re-export has to be asked for explicitly and is recorded.

COLUMN LAYOUT. Vietnamese banks each publish their own bulk-payment template — Techcombank's F@st
EBank differs from Vietcombank's and from ACB's, in column order and in the exact header text. The
layout here is therefore DATA, not code: `COLUMNS` is a default shaped like a typical Techcombank
salary upload, and `portal_bankTemplate` overrides it. Confirm the headers against the template the
bank gives you and set them once; nothing else has to change.

Everything is folded to unaccented ASCII, because bank upload files reject Vietnamese diacritics and
most reject anything outside a narrow character set in the remittance narrative.
"""
import re
import unicodedata

# A typical Vietnamese bulk salary upload. `key` is what this module computes; `header` is what the
# bank's template calls it, and is the part that changes per bank.
COLUMNS = [
    {"key": "no", "header": "STT"},
    {"key": "account", "header": "So tai khoan"},
    {"key": "name", "header": "Ten nguoi huong"},
    {"key": "amount", "header": "So tien"},
    {"key": "narrative", "header": "Noi dung"},
    {"key": "bank", "header": "Ngan hang huong"},
    {"key": "branch", "header": "Chi nhanh"},
]

# The remittance narrative. Kept short and unaccented: most banks truncate hard and some reject the
# whole file on an unexpected character.
NARRATIVE_MAX = 90
_SAFE = re.compile(r"[^A-Za-z0-9 ./-]")


def fold(s):
    """Vietnamese text to unaccented ASCII — 'Nguyễn Đức Huy' becomes 'Nguyen Duc Huy'."""
    out = "".join(ch for ch in unicodedata.normalize("NFD", str(s or ""))
                  if unicodedata.category(ch) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


def safe_text(s, limit=NARRATIVE_MAX):
    """Unaccented, stripped of anything a bank file is likely to reject, and length-bounded."""
    return _SAFE.sub(" ", fold(s)).replace("  ", " ").strip()[:limit]


def narrative(company, period, name):
    """'HUMILEY LUONG T08/2026 NGUYEN VAN A' — the form a Vietnamese payroll credit usually takes,
    so the employee can recognise it on their statement without ringing HR."""
    return safe_text("%s LUONG %s %s" % (fold(company or "HUMILEY").upper(),
                                         _period_short(period), fold(name or "").upper()))


def _period_short(period):
    """'August 2026' → 'T08/2026'. Falls back to whatever was given rather than inventing a date."""
    months = ["january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"]
    parts = str(period or "").strip().split()
    if len(parts) == 2 and parts[0].lower() in months:
        return "T%02d/%s" % (months.index(parts[0].lower()) + 1, parts[1])
    return safe_text(period, 20)


def account_of(emp):
    """The account to credit. Digits only — a space or a dash typed into the field is a formatting
    habit, not part of the number, and every bank template wants it bare."""
    raw = str((emp or {}).get("bankAcc") or "")
    return re.sub(r"\D", "", raw)


def problems(emp, amount):
    """Why this employee cannot be paid by file. Empty means they can."""
    out = []
    if not account_of(emp):
        out.append("no bank account number on record")
    if not str((emp or {}).get("bankName") or "").strip():
        out.append("no bank name on record")
    if not str((emp or {}).get("name") or "").strip():
        out.append("no name on record")
    try:
        if float(amount or 0) <= 0:
            out.append("net pay is not a positive amount")
    except (TypeError, ValueError):
        out.append("net pay is not a number")
    return out


def build(run, employees, company="HUMILEY", columns=None):
    """Rows for one finalised pay run, or the reason none can be produced.

    Returns {"rows", "total", "count", "blocked"}. `blocked` lists everybody who cannot be paid by
    file and why; when it is non-empty the caller must refuse to produce anything, because a file
    missing a row is indistinguishable from a complete one.
    """
    by_id = {e.get("id"): e for e in (employees or []) if isinstance(e, dict)}
    period = run.get("period") or ""
    rows, blocked, total = [], [], 0.0

    for ln in (run.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        emp = by_id.get(ln.get("empId")) or {}
        calc = ln.get("calc") if isinstance(ln.get("calc"), dict) else {}
        try:
            amount = float(calc.get("net", ln.get("net")) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        name = emp.get("name") or ln.get("name") or ""

        why = problems(dict(emp, name=name), amount)
        if why:
            blocked.append({"empId": ln.get("empId"), "name": name or ln.get("empId") or "?",
                            "why": why})
            continue

        rows.append({
            "no": len(rows) + 1,
            "account": account_of(emp),
            # The BENEFICIARY name is folded but not otherwise stripped: it is matched against the
            # account holder, and dropping a character there is what makes a transfer bounce.
            "name": fold(emp.get("bankHolder") or name).upper().strip(),
            "amount": int(round(amount)),
            "narrative": narrative(company, period, name),
            "bank": safe_text(emp.get("bankName"), 60),
            "branch": safe_text(emp.get("bankBranch"), 60),
        })
        total += round(amount)

    return {"rows": rows, "total": total, "count": len(rows), "blocked": blocked,
            "period": period, "columns": columns or COLUMNS}


def to_csv(built, columns=None):
    """The upload file. A control row at the end carries the count and the total, so whoever
    approves the batch in the bank's portal can check it against the pay run before releasing it —
    which is the one moment the whole month can still be caught."""
    cols = columns or built.get("columns") or COLUMNS
    q = lambda v: '"%s"' % str(v).replace('"', '""')
    out = [",".join(q(c["header"]) for c in cols)]
    for r in built["rows"]:
        out.append(",".join(q(r.get(c["key"], "")) for c in cols))

    # The control row is built to the SHAPE OF THE TEMPLATE, not to a fixed four fields. The previous
    # version wrote TOTAL / n rows / blank / total and then padded to len(cols), which broke twice on
    # a custom layout: with fewer than four columns the trailer came out WIDER than the header (a
    # malformed CSV), and the total always landed in the fourth column whatever that column actually
    # was — so with the amount last, the batch total sat under the account-number heading. For a file
    # a bank reads back to check a month's payroll, a total under the wrong heading is worse than no
    # total at all.
    keys = [c.get("key") for c in cols]
    trailer = [""] * len(cols)
    if trailer:
        trailer[0] = "TOTAL"
    _amount = keys.index("amount") if "amount" in keys else None
    if _amount is not None:
        trailer[_amount] = "%d" % int(built["total"])
    # The count goes in the first free cell that is not the total, so it never overwrites it.
    for i in range(1, len(cols)):
        if i != _amount:
            trailer[i] = "%d rows" % built["count"]
            break
    out.append(",".join(q(v) for v in trailer))
    return "\n".join(out)
