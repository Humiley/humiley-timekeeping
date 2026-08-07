"""Occupational accidents: the register, the clock, and the call that has to be made today.

The portal has a health-and-safety certificate register, a quality module with NCRs, and one
free-text `safetyIncidents` line on the site daily report. None of them is an accident register.
Vietnam's Law on OSH 2015 and Decree 39/2016 impose duties that start the moment somebody is hurt,
and a company that finds out about them afterwards has already missed them.

What is encoded, and where it comes from:

  · **Three classes** — nhẹ / nặng / chết người (minor / serious / fatal). Everything else follows
    from the class and the number of people hurt.
  · **Immediate declaration** (Decree 39/2016 Art. 10). A FATAL accident, or a serious one injuring
    TWO OR MORE people, must be declared *at once, by the fastest means* to the labour inspectorate
    of the provincial Department of Labour — and a fatal one to the district police as well. This is
    the duty that is missed, because it is measured in hours and nobody is looking at a register.
  · **The investigation clock** (Law on OSH 2015 Art. 35(4)), counted from the day notice of the
    accident was received to the day the investigation report is published: 4 days minor, 7 serious
    injuring one, 20 serious injuring two or more, 30 fatal, 60 where technical or forensic
    examination is required. It may be extended ONCE, by no more than the original period.
  · **The periodic returns** (Decree 39/2016 Art. 24) — before 5 July for the first half, before
    10 January for the year just ended.

Also a lost-time injury frequency rate, because that is the number a client's safety audit asks for
and it is meaningless without the hours worked. `lost_time_rate` REFUSES to produce one when the
hours are not supplied rather than quoting a rate against a denominator it guessed.

Pure — no database, no clock. Exercised by tests/test_osh_incident.py.
"""
from datetime import date, timedelta

MINOR = "minor"
SERIOUS = "serious"
FATAL = "fatal"

CLASSES = (
    {"key": MINOR, "label": "Minor injury", "labelVn": "Tai nạn lao động nhẹ",
     "help": "Treated and back at work without a serious injury as defined by the Ministry's list."},
    {"key": SERIOUS, "label": "Serious injury", "labelVn": "Tai nạn lao động nặng",
     "help": "An injury on the list at Appendix II of Decree 39/2016 — fractures, amputations, "
             "burns over a threshold, injuries to the skull, spine or internal organs."},
    {"key": FATAL, "label": "Fatal", "labelVn": "Tai nạn lao động chết người",
     "help": "Death at the scene, on the way to hospital, during treatment, or later from the same "
             "injury; also an employee declared dead whose body was not found."},
)
_CLASS = {c["key"]: c for c in CLASSES}

# Law on OSH 2015 Art. 35(4). Days from receiving notice of the accident to publishing the report.
INVESTIGATION_DAYS = {MINOR: 4, SERIOUS: 7, "serious_multi": 20, FATAL: 30}
INVESTIGATION_DAYS_FORENSIC = 60
# Decree 39/2016 Art. 24 — the two filings, as (month, day, what it covers, and the same in VN).
REPORT_PERIODS = ((7, 5, "first half — before 5 July", "sáu tháng đầu năm — trước ngày 5 tháng 7"),
                  (1, 10, "the year just ended — before 10 January",
                   "cả năm vừa kết thúc — trước ngày 10 tháng 1"))
_REPORT_BASIS = ("Decree 39/2016 Art. 24 — occupational-accident report to the provincial "
                 "Department of Labour, Invalids and Social Affairs.")
_REPORT_BASIS_VN = ("Nghị định 39/2016 Điều 24 — báo cáo tai nạn lao động gửi Sở Lao động – "
                    "Thương binh và Xã hội cấp tỉnh.")


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def _n(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def klass(key):
    return _CLASS.get(_s(key).lower())


_INSPECTORATE = ("The labour inspectorate of the provincial Department of Labour, Invalids and "
                 "Social Affairs where the accident happened")
_INSPECTORATE_VN = ("Thanh tra lao động thuộc Sở Lao động – Thương binh và Xã hội cấp tỉnh nơi xảy "
                    "ra tai nạn")
_POLICE = "The district police"
_POLICE_VN = "Công an cấp huyện nơi xảy ra tai nạn"


def declare_immediately(incident):
    """Decree 39/2016 Art. 10. Whether this must be declared AT ONCE, and to whom.

    This is the finding the register exists to surface. It is measured in hours, so it is returned
    as an instruction with the recipients named — not as a flag somebody has to interpret.

    Every string comes back in Vietnamese too. This one instruction is read under time pressure, by
    a site manager, on a Vietnamese-language site — leaving it in English would be leaving it in the
    one language the reader might not have. The frontend picks by the user's language; the wording
    stays here, next to the article it comes from.
    """
    c = incident or {}
    kind = _s(c.get("class")).lower()
    hurt = _n(c.get("injuredCount"), 1)
    if kind == FATAL:
        return {
            "required": True,
            "to": [_INSPECTORATE, _POLICE],
            "toVn": [_INSPECTORATE_VN, _POLICE_VN],
            "how": "At once, by the fastest means available — in person, telephone, fax or email. "
                   "Not a letter, and not at the end of the week.",
            "howVn": "Ngay lập tức, bằng phương tiện nhanh nhất — trực tiếp, điện thoại, fax hoặc "
                     "thư điện tử. Không gửi công văn, và không để đến cuối tuần.",
            "basis": "Decree 39/2016 Art. 10 — a fatal occupational accident.",
            "basisVn": "Nghị định 39/2016 Điều 10 — tai nạn lao động chết người.",
        }
    if kind == SERIOUS and hurt >= 2:
        return {
            "required": True,
            "to": [_INSPECTORATE],
            "toVn": [_INSPECTORATE_VN],
            "how": "At once, by the fastest means available.",
            "howVn": "Ngay lập tức, bằng phương tiện nhanh nhất.",
            "basis": "Decree 39/2016 Art. 10 — a serious accident injuring two or more people.",
            "basisVn": "Nghị định 39/2016 Điều 10 — tai nạn lao động nặng làm bị thương từ hai "
                       "người trở lên.",
        }
    return {
        "required": False, "to": [], "toVn": [], "how": "", "howVn": "",
        "basis": ("Immediate declaration applies to a fatal accident, or a serious one injuring two "
                  "or more. This one is investigated and recorded, and reaches the authority in the "
                  "periodic return."),
        "basisVn": ("Nghĩa vụ khai báo ngay chỉ áp dụng với tai nạn chết người hoặc tai nạn nặng "
                    "làm bị thương từ hai người trở lên. Vụ này được điều tra, ghi nhận và báo cáo "
                    "với cơ quan có thẩm quyền trong báo cáo định kỳ."),
    }


def investigation_deadline(incident, as_of=None):
    """Law on OSH 2015 Art. 35(4) — when the investigation report is due, and whether it is late.

    Counted from the day notice was RECEIVED, not the day of the accident: they are usually the same
    and occasionally are not, and the statute names the notice.
    """
    c = incident or {}
    start = _d(c.get("notifiedOn")) or _d(c.get("occurredOn"))
    if not start:
        return None
    kind = _s(c.get("class")).lower()
    hurt = _n(c.get("injuredCount"), 1)
    forensic = bool(c.get("forensic"))
    if forensic:
        days, why = INVESTIGATION_DAYS_FORENSIC, "technical or forensic examination is required"
        why_vn = "phải giám định kỹ thuật hoặc pháp y"
    elif kind == FATAL:
        days, why = INVESTIGATION_DAYS[FATAL], "a fatal accident"
        why_vn = "tai nạn chết người"
    elif kind == SERIOUS and hurt >= 2:
        days, why = INVESTIGATION_DAYS["serious_multi"], "a serious accident injuring two or more"
        why_vn = "tai nạn nặng làm bị thương từ hai người trở lên"
    elif kind == SERIOUS:
        days, why = INVESTIGATION_DAYS[SERIOUS], "a serious accident injuring one person"
        why_vn = "tai nạn nặng làm bị thương một người"
    elif kind == MINOR:
        days, why = INVESTIGATION_DAYS[MINOR], "a minor accident"
        why_vn = "tai nạn nhẹ"
    else:
        return None
    base = start + timedelta(days=days)
    # Art. 35(4): extended ONCE, by no more than the original period for that class.
    extended = bool(c.get("extended"))
    due = base + timedelta(days=days) if extended else base
    reported = _d(c.get("reportPublishedOn"))
    today = _d(as_of) or date.today()
    return {
        "days": days, "why": why, "whyVn": why_vn,
        "from": start.isoformat(),
        "baseDue": base.isoformat(), "due": due.isoformat(),
        "extended": extended,
        "extensionLimit": (base + timedelta(days=days)).isoformat(),
        "published": bool(reported),
        "late": bool(reported and reported > due) or (not reported and today > due),
        "basis": ("Law on OSH 2015 Art. 35(4) — no more than %d days from receiving notice, for %s. "
                  "It may be extended once, by no more than the same period again." % (days, why)),
        "basisVn": ("Luật An toàn, vệ sinh lao động 2015 Điều 35(4) — không quá %d ngày kể từ ngày "
                    "nhận được tin báo, đối với %s. Được gia hạn một lần và không quá thời hạn "
                    "ban đầu." % (days, why_vn)),
    }


def next_report_due(as_of):
    """Decree 39/2016 Art. 24 — the next periodic return to the Department of Labour."""
    today = _d(as_of) or date.today()
    for m, d, what, what_vn in sorted(REPORT_PERIODS):
        due = date(today.year, m, d)
        if due >= today:
            return {"due": due.isoformat(), "covers": what, "coversVn": what_vn,
                    "basis": _REPORT_BASIS, "basisVn": _REPORT_BASIS_VN}
    # Past both this year's dates → the January filing, next year.
    jan = [p for p in REPORT_PERIODS if p[0] == 1][0]
    return {"due": date(today.year + 1, jan[0], jan[1]).isoformat(),
            "covers": jan[2], "coversVn": jan[3],
            "basis": _REPORT_BASIS, "basisVn": _REPORT_BASIS_VN}


def lost_time_rate(incidents, hours_worked):
    """Lost-time injury frequency per million hours worked.

    Refuses to produce a number when the hours are not supplied. A frequency rate against a guessed
    denominator is worse than no rate: it is the single figure a client's safety audit compares
    across contractors, and it would be compared.
    """
    hrs = 0
    try:
        hrs = float(hours_worked or 0)
    except (TypeError, ValueError):
        hrs = 0
    lti = sum(1 for c in (incidents or []) if _n((c or {}).get("daysLost")) > 0
              or _s((c or {}).get("class")).lower() in (SERIOUS, FATAL))
    if hrs <= 0:
        return {"rate": None, "lostTimeInjuries": lti, "hours": 0,
                "why": "No hours worked were supplied, so a frequency rate cannot be computed. A "
                       "rate against a guessed denominator would be compared with other "
                       "contractors' real ones.",
                "whyVn": "Chưa có số giờ làm việc nên không tính được tần suất. Một tỷ lệ dựa trên "
                         "mẫu số phỏng đoán sẽ bị đem so sánh với số liệu thật của nhà thầu khác."}
    return {"rate": round(lti * 1000000.0 / hrs, 2), "lostTimeInjuries": lti, "hours": int(hrs),
            "why": "Lost-time injuries per 1,000,000 hours worked. A lost-time injury is one with "
                   "days lost recorded, or any serious or fatal accident.",
            "whyVn": "Số vụ tai nạn phải nghỉ việc trên 1.000.000 giờ làm việc. Tai nạn phải nghỉ "
                     "việc là vụ có ghi nhận ngày nghỉ, hoặc bất kỳ tai nạn nặng hay chết người."}


def blockers(incident):
    """What stops this from being a usable record."""
    c = incident or {}
    out = []
    if not klass(c.get("class")):
        out.append("Say how serious it was — it decides whether this has to be declared today and "
                   "how long the investigation may take.")
    if not _d(c.get("occurredOn")):
        out.append("The date it happened is what every deadline is counted from.")
    if not _s(c.get("empId")) and not _s(c.get("personName")):
        out.append("Say who was hurt. A contractor or visitor who is not on the payroll can be "
                   "named instead of chosen.")
    if len(_s(c.get("what"))) < 20:
        out.append("Describe what happened, in enough detail that somebody investigating it a month "
                   "later can follow it.")
    if _n(c.get("injuredCount"), 1) < 1:
        out.append("At least one person was hurt, or this is not an accident record.")
    return out


def review(incidents, as_of, hours_worked=None):
    """The register: what is outstanding, what is late, and the figures an audit asks for."""
    today = _d(as_of) or date.today()
    rows, undeclared, late, open_ = [], [], 0, 0
    by_class = {}
    days_lost = 0
    for c in (incidents or []):
        dec = declare_immediately(c)
        dl = investigation_deadline(c, today)
        k = _s(c.get("class")).lower() or "unknown"
        by_class[k] = by_class.get(k, 0) + 1
        days_lost += max(0, _n(c.get("daysLost")))
        if dec["required"] and not _d(c.get("declaredOn")):
            # Both languages. Copying only the English keys here left the one banner that is read
            # under time pressure in English, on a Vietnamese site — even though the instruction
            # itself had a Vietnamese wording all along.
            undeclared.append({"id": c.get("id"), "ref": c.get("ref"),
                               "occurredOn": c.get("occurredOn"),
                               "to": dec["to"], "toVn": dec["toVn"],
                               "how": dec["how"], "howVn": dec["howVn"],
                               "basis": dec["basis"], "basisVn": dec["basisVn"]})
        if dl and dl["late"]:
            late += 1
        if not _d(c.get("reportPublishedOn")):
            open_ += 1
        rows.append(dict(c, declare=dec, deadline=dl))
    rows.sort(key=lambda r: (not (r["declare"]["required"] and not _d(r.get("declaredOn"))),
                             not ((r.get("deadline") or {}).get("late")),
                             str(r.get("occurredOn") or "")), reverse=False)
    return {
        "asOf": today.isoformat(),
        "rows": rows, "total": len(rows), "open": open_,
        "undeclared": undeclared, "lateInvestigations": late,
        "daysLost": days_lost,
        "byClass": sorted(({"class": k, "label": (klass(k) or {}).get("label", k), "count": v}
                           for k, v in by_class.items()), key=lambda r: (-r["count"], r["class"])),
        "nextReport": next_report_due(today),
        "frequency": lost_time_rate(incidents, hours_worked),
        "statement": ("%d accident(s) recorded, %d still under investigation, %d day(s) lost."
                      % (len(rows), open_, days_lost)),
    }
