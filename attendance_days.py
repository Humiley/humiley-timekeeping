"""What each day WAS for each person — the timesheet, and the only honest way to count absence.

Every screen in this portal that reports absence counted attendance rows whose `status` is
'absent'. Nothing in production has ever written that value: `_checkin` writes 'on-time' or 'late',
and the only two writers of 'absent' are `db.generate_attendance` and `seed_data.py`, both of which
make demo rows. So every absence figure the company has ever looked at was structurally zero — not
"nobody was absent", but "this number cannot be anything else".

The mistake is in the shape, not the value. **An absence is the absence of a record.** Somebody who
does not come to work does not create an attendance row, so no status on a row can ever say so. It
has to be DERIVED, by asking of each day the company expected somebody to work: is there a record?

The inputs all already exist:
  · the attendance rows themselves,
  · the employee's work schedule, which says which weekdays they do not normally work,
  · the company holiday register,
  · approved leave.

Five outcomes, and the difference between the last three is the whole point:

  WORKED     a record exists. `late` when the row says so.
  LEAVE      approved leave covers the day — not an absence, and not a day worked.
  HOLIDAY    a public holiday from the company register.
  REST       a non-working weekday for that person's schedule (Art. 111's weekly rest).
  ABSENT     the company expected them and there is no record and no explanation.

ABSENT is deliberately the last resort. A day is only absent once leave, holidays and rest days have
been ruled out — reporting somebody absent on their own rest day is worse than reporting nothing,
because it is the kind of number that ends up in an appraisal.

This is also the per-employee monthly timesheet: the document Decree 145/2020 requires the employer
to keep and produce on inspection, and the one a payroll clerk and a client auditor both ask for.

Pure — no database, no clock. Exercised by tests/test_attendance_days.py.
"""
from datetime import date, timedelta

WORKED = "worked"
LATE = "late"
LEAVE = "leave"
HOLIDAY = "holiday"
REST = "rest"
ABSENT = "absent"

# What each outcome means, for a screen and for a pack that leaves the building.
OUTCOMES = (
    {"key": WORKED, "label": "Worked", "labelVn": "Có đi làm"},
    {"key": LATE, "label": "Worked, late", "labelVn": "Có đi làm, đi muộn"},
    {"key": LEAVE, "label": "Approved leave", "labelVn": "Nghỉ phép đã duyệt"},
    {"key": HOLIDAY, "label": "Public holiday", "labelVn": "Nghỉ lễ"},
    {"key": REST, "label": "Weekly rest day", "labelVn": "Ngày nghỉ hằng tuần"},
    {"key": ABSENT, "label": "Absent, unexplained", "labelVn": "Vắng không lý do"},
)


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def days_between(frm, to):
    """Every calendar date in the window, inclusive. Empty if the window is backwards or unusable."""
    a, b = _d(frm), _d(to)
    if not a or not b or b < a:
        return []
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def leave_dates(leave_rows, statuses=("approved",)):
    """The set of dates covered by leave in an accepted state.

    A leave request that is still pending is NOT an explanation — it is a question nobody has
    answered, and treating it as one would let an absence be excused by asking.
    """
    ok = {str(s).strip().lower() for s in (statuses or ())}
    out = set()
    for r in (leave_rows or []):
        if _s(r.get("status")).lower() not in ok:
            continue
        a = _d(r.get("start") or r.get("from") or r.get("startDate"))
        b = _d(r.get("end") or r.get("to") or r.get("endDate")) or a
        if not a:
            continue
        if b < a:
            a, b = b, a
        cur = a
        while cur <= b:
            out.add(cur.isoformat())
            cur += timedelta(days=1)
    return out


def classify(day, row=None, on_leave=False, holiday=False, rest=False):
    """What this one day was. The order is the rule: a record beats every explanation.

    Somebody who came in on a public holiday worked; saying "holiday" because the calendar says so
    would erase a day they are owed 300% for.
    """
    if row and (_s(row.get("clock_in")) or _s(row.get("in"))):
        return LATE if _s(row.get("status")).lower() == "late" else WORKED
    if on_leave:
        return LEAVE
    if holiday:
        return HOLIDAY
    if rest:
        return REST
    return ABSENT


def timesheet(emp, rows, frm, to, rest_weekdays=(5, 6), holidays=(), leave_rows=(),
              leave_statuses=("approved",), today=None):
    """One person, one period: every day classified, and the totals a payroll clerk needs.

    `today` is the last day that has actually happened. A day in the future has no record because it
    has not arrived yet, so classifying it would report the rest of the month as absence — asking for
    "August" in the first week would accuse everybody of three weeks off. Future days are left out of
    the record entirely; only a day that somehow already carries a record is kept, because a record
    is evidence and dropping it would hide it.
    """
    by_date = {}
    for r in (rows or []):
        d = _s(r.get("date"))
        if d:
            by_date[d] = r
    hol = {_s(h)[:10] for h in (holidays or ())}
    lv = leave_dates(leave_rows, leave_statuses)
    rest_set = set(rest_weekdays or ())
    cutoff = _s(today)[:10]

    days, counts = [], {o["key"]: 0 for o in OUTCOMES}
    for d in days_between(frm, to):
        iso = d.isoformat()
        row = by_date.get(iso)
        if cutoff and iso > cutoff and not row:
            continue
        kind = classify(d, row=row, on_leave=iso in lv, holiday=iso in hol,
                        rest=d.weekday() in rest_set)
        counts[kind] += 1
        days.append({
            "date": iso,
            "weekday": d.weekday(),
            "outcome": kind,
            "clockIn": _s((row or {}).get("clock_in")),
            "clockOut": _s((row or {}).get("clock_out")),
            "hrs": _s((row or {}).get("hrs")),
            "otHours": (row or {}).get("ot_hours") or 0,
            "otStatus": _s((row or {}).get("ot_status")),
            "location": _s((row or {}).get("loc")),
            "project": _s((row or {}).get("project")),
            # An open row is not a worked day yet, and it is the shape a forgotten check-out leaves.
            "open": bool(row and _s(row.get("clock_in")) and not _s(row.get("clock_out"))),
        })
    worked = counts[WORKED] + counts[LATE]
    expected = worked + counts[ABSENT]
    return {
        "empId": _s((emp or {}).get("id")),
        "name": _s((emp or {}).get("name")),
        "dept": _s((emp or {}).get("dept")),
        "from": _s(frm)[:10], "to": _s(to)[:10],
        # What the record actually covers, once days that have not happened are left out.
        "covers": (days[0]["date"] + " → " + days[-1]["date"]) if days else "",
        "days": days,
        "counts": counts,
        "worked": worked,
        "expected": expected,
        "openRows": len([d for d in days if d["open"]]),
        "statement": _statement(counts, worked, expected),
    }


def _statement(counts, worked, expected):
    parts = ["%d day(s) worked" % worked]
    if counts[LATE]:
        parts.append("%d late" % counts[LATE])
    if counts[LEAVE]:
        parts.append("%d on approved leave" % counts[LEAVE])
    if counts[ABSENT]:
        parts.append("%d absent with no explanation on record" % counts[ABSENT])
    s = ", ".join(parts) + "."
    if expected and counts[ABSENT]:
        s += " That is %d of %d expected working day(s)." % (counts[ABSENT], expected)
    return s


def review(sheets):
    """The company view: the totals the dashboards claimed to show and could not."""
    totals = {o["key"]: 0 for o in OUTCOMES}
    for t in (sheets or []):
        for k, v in (t.get("counts") or {}).items():
            totals[k] = totals.get(k, 0) + v
    absent_people = sorted(
        ({"empId": t["empId"], "name": t["name"], "days": t["counts"][ABSENT]}
         for t in (sheets or []) if t["counts"][ABSENT]),
        key=lambda x: (-x["days"], x["name"]))
    return {
        "totals": totals,
        "worked": totals[WORKED] + totals[LATE],
        "absentDays": totals[ABSENT],
        "absentPeople": absent_people,
        "openRows": sum(t.get("openRows", 0) for t in (sheets or [])),
        "outcomes": [dict(o) for o in OUTCOMES],
        "basis": "An absence is a day the company expected somebody to work with no attendance "
                 "record and no approved leave, public holiday or weekly rest day to explain it. It "
                 "is derived from the register, not stored on it — an absent employee never creates "
                 "a row to store it on.",
        "basisVn": "Vắng mặt là ngày công ty yêu cầu làm việc nhưng không có dữ liệu chấm công và "
                   "cũng không có nghỉ phép đã duyệt, ngày lễ hay ngày nghỉ hằng tuần để giải "
                   "thích. Con số này được suy ra từ sổ chấm công chứ không lưu trên đó — người "
                   "vắng mặt không tạo ra dòng dữ liệu nào để lưu.",
    }
