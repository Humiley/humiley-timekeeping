"""Young workers: the register Art. 144 requires, and the hours Art. 146 allows.

A client's social-compliance audit opens with young workers. It is the first section of an
SMETA/RBA-style labour audit and a standing Vietnamese statutory duty, and this portal could
produce nothing for it — while holding, on every employee record, the one fact the whole section
turns on.

Labour Code 2019:

  · **Art. 143** — a minor employee is anybody under full 18. Three bands, each with its own rule:
    under 13 (arts, physical training and sport only, and only with the provincial labour agency's
    written approval); 13 to under 15 (light work on the Ministry's list); 15 to under 18 (any work
    except those forbidden to under-18s and the workplaces forbidden to them).
  · **Art. 144** — when a company employs minors it must keep a SEPARATE monitoring book recording
    each one's full name, date of birth, the work being done, and the results of their periodic
    health examinations, and produce it to a competent authority on request. Those four columns are
    exactly what `register()` returns.
  · **Art. 146** — hours. Under 15: no more than 4 hours a day and 20 a week, and **no overtime and
    no night work at all**. From 15 to under 18: no more than 8 hours a day and 40 a week, with
    overtime and night work only in occupations the Ministry lists.

The Art. 146(1) prohibition is a REFUSAL, not a ceiling. Art. 107's monthly overtime limit is a cap
the company may exceed with a stated reason, because the Code itself contemplates the cases; Art.
146(1) admits no exception, so `overtime_allowed` returns a refusal for an under-15 and the caller
must not offer an override.

Nothing here guesses an age. An employee with no date of birth on record is `UNKNOWN`, reported as
a gap in the register rather than resolved to "adult" — see leave_entitlement.dob_known.

Pure — no database, no clock. Exercised by tests/test_minors.py.
"""
from datetime import date

MINOR_AGE = 18

# Art. 143 bands, youngest first. `maxDaily`/`maxWeekly` are Art. 146.
UNDER_13 = "under13"
BAND_13_15 = "13to15"
BAND_15_18 = "15to18"
ADULT = "adult"
UNKNOWN = "unknown"

BANDS = (
    {"key": UNDER_13, "from": 0, "to": 13,
     "label": "Under 13", "labelVn": "Dưới 13 tuổi",
     "maxDaily": 4, "maxWeekly": 20, "overtime": False, "night": False,
     "work": "Arts, physical training and sport only, and only with the written approval of the "
             "provincial labour agency.",
     "workVn": "Chỉ được làm các công việc nghệ thuật, thể dục, thể thao và phải được cơ quan lao "
               "động cấp tỉnh chấp thuận bằng văn bản.",
     "basis": "Labour Code 2019 Art. 143(3) and Art. 145(1); hours under Art. 146(1)."},
    {"key": BAND_13_15, "from": 13, "to": 15,
     "label": "13 to under 15", "labelVn": "Từ đủ 13 đến dưới 15 tuổi",
     "maxDaily": 4, "maxWeekly": 20, "overtime": False, "night": False,
     "work": "Light work on the list issued by the Ministry of Labour, Invalids and Social Affairs.",
     "workVn": "Công việc nhẹ theo danh mục do Bộ Lao động – Thương binh và Xã hội ban hành.",
     "basis": "Labour Code 2019 Art. 143(3); hours under Art. 146(1)."},
    {"key": BAND_15_18, "from": 15, "to": 18,
     "label": "15 to under 18", "labelVn": "Từ đủ 15 đến dưới 18 tuổi",
     "maxDaily": 8, "maxWeekly": 40, "overtime": "listed", "night": "listed",
     "work": "Any work except those forbidden to employees under 18 and the workplaces forbidden "
             "to them.",
     "workVn": "Mọi công việc trừ công việc và nơi làm việc cấm sử dụng người lao động dưới 18 tuổi.",
     "basis": "Labour Code 2019 Art. 143 and Art. 147; hours and overtime under Art. 146(2)."},
)
_BAND = {b["key"]: b for b in BANDS}

# Art. 146(2): overtime and night work for a 15-to-under-18 are allowed only in occupations the
# Ministry lists — art performers, certain sports, and a light-trade list. Nothing on that list
# resembles HVAC or cleanroom installation, so this company has no lawful case for it, and the
# module says so rather than leaving a blank the caller has to interpret.
LISTED_OCCUPATIONS_NOTE = (
    "Only in the occupations the Ministry lists for Art. 146(2) — art performance, certain sports, "
    "and a short light-trade list. Mechanical, electrical, cleanroom and construction work is not "
    "among them.")
LISTED_OCCUPATIONS_NOTE_VN = (
    "Chỉ trong các nghề, công việc được Bộ Lao động – Thương binh và Xã hội quy định theo Điều "
    "146(2) — biểu diễn nghệ thuật, một số môn thể thao và một số nghề thủ công nhẹ. Công việc cơ "
    "khí, điện, phòng sạch và xây dựng không thuộc danh mục này.")


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def completed_years(born, as_of):
    """Whole years lived. Birthday-aware — somebody turns 18 ON their birthday, not in January."""
    b, a = _d(born), _d(as_of)
    if not b or not a or a < b:
        return None
    years = a.year - b.year
    if (a.month, a.day) < (b.month, b.day):
        years -= 1
    return years


def band(dob, as_of):
    """Which Art. 143 band somebody is in on a given date, or UNKNOWN.

    UNKNOWN is a real answer and never collapses to ADULT: the whole point of the register is to
    show that a date of birth is missing, because that is the gap an auditor finds.
    """
    yrs = completed_years(dob, as_of)
    if yrs is None:
        return UNKNOWN
    if yrs >= MINOR_AGE:
        return ADULT
    for b in BANDS:
        if b["from"] <= yrs < b["to"]:
            return b["key"]
    return UNKNOWN


def limits(dob, as_of):
    """The Art. 146 ceilings that apply to this person, with the article they come from."""
    k = band(dob, as_of)
    if k == ADULT:
        return {"band": ADULT, "minor": False, "maxDaily": None, "maxWeekly": None,
                "overtime": True, "night": True,
                "basis": "Not a minor employee — the ordinary Art. 105 and Art. 107 limits apply."}
    if k == UNKNOWN:
        return {"band": UNKNOWN, "minor": None, "maxDaily": None, "maxWeekly": None,
                "overtime": None, "night": None,
                "basis": "No date of birth on record, so the Art. 146 limits cannot be applied. "
                         "Record the date of birth."}
    b = _BAND[k]
    return {"band": k, "minor": True, "label": b["label"], "labelVn": b["labelVn"],
            "maxDaily": b["maxDaily"], "maxWeekly": b["maxWeekly"],
            "overtime": b["overtime"], "night": b["night"],
            "work": b["work"], "workVn": b["workVn"], "basis": b["basis"]}


def overtime_allowed(dob, as_of):
    """Whether this person may work overtime at all, and on what authority.

    Three different answers, and the difference between them is the whole point:

      · a MINOR is refused and `overridable` is False. Art. 146(1) admits no exception, unlike the
        Art. 107 monthly limit which the Code itself contemplates exceeding, so this must never be
        offered as a cap somebody can buy past with a reason.
      · an UNKNOWN age is refused but `overridable` is True. That is a gap in the RECORD, not a
        prohibition in the law — the approver knows the person and can attest they are an adult, and
        that attestation goes into the audit chain under their name. Refusing outright would stop a
        company approving any overtime at all until every date of birth was typed in, which is how
        a correct check gets switched off.
      · an ADULT is allowed, and the Art. 107 ceilings still apply on top.
    """
    k = band(dob, as_of)
    if k == ADULT:
        return {"allowed": True, "band": ADULT, "refuse": False, "overridable": False,
                "basis": "Not a minor employee. The Art. 107 limits still apply."}
    if k == UNKNOWN:
        return {"allowed": None, "band": UNKNOWN, "refuse": True, "overridable": True,
                "reason": "No date of birth on record, so it cannot be established that this "
                          "employee is old enough to work overtime at all (Art. 146). Record the "
                          "date of birth — or confirm below that you know this employee is over 18, "
                          "which is recorded against your name.",
                "reasonVn": "Chưa có ngày sinh trên hồ sơ nên không thể xác định người lao động có "
                            "đủ tuổi làm thêm giờ hay không (Điều 146). Hãy ghi nhận ngày sinh.",
                "basis": "Labour Code 2019 Art. 146."}
    if k in (UNDER_13, BAND_13_15):
        return {"allowed": False, "band": k, "refuse": True, "overridable": False,
                "reason": "An employee under 15 may not work overtime or at night in any "
                          "occupation. This is a prohibition, not a limit that can be exceeded "
                          "with a reason.",
                "reasonVn": "Người lao động chưa đủ 15 tuổi không được làm thêm giờ hoặc làm việc "
                            "ban đêm trong bất kỳ nghề nào. Đây là điều cấm, không phải giới hạn "
                            "có thể vượt qua kèm lý do.",
                "basis": "Labour Code 2019 Art. 146(1)."}
    return {"allowed": False, "band": BAND_15_18, "refuse": True, "overridable": False,
            "reason": "An employee aged 15 to under 18 may work overtime or at night ONLY in the "
                      "occupations the Ministry lists. " + LISTED_OCCUPATIONS_NOTE,
            "reasonVn": "Người lao động từ đủ 15 đến dưới 18 tuổi chỉ được làm thêm giờ hoặc làm "
                        "ban đêm trong các nghề được Bộ quy định. " + LISTED_OCCUPATIONS_NOTE_VN,
            "basis": "Labour Code 2019 Art. 146(2)."}


def daily_hours_ok(dob, as_of, hours):
    """Whether a day of that length is within this person's Art. 146 ceiling."""
    lim = limits(dob, as_of)
    cap = lim.get("maxDaily")
    try:
        h = float(hours or 0)
    except (TypeError, ValueError):
        h = 0.0
    if cap is None:
        return {"ok": lim["band"] != UNKNOWN, "cap": None, "hours": h, "basis": lim["basis"]}
    return {"ok": h <= cap, "cap": cap, "hours": h,
            "basis": "%s No more than %d hours in a day." % (lim["basis"], cap)}


def register(employees, as_of, health_by_emp=None):
    """The Art. 144 monitoring book: every minor, with the four columns the article names.

    Returns the gaps too. A minor with no health examination on file and a person with no date of
    birth are both findings an auditor would raise, and the register that hides them is worse than
    no register.
    """
    today = _d(as_of) or date.today()
    health = health_by_emp or {}
    rows, unknown, gaps = [], [], []
    for e in (employees or []):
        eid = _s(e.get("id"))
        k = band(e.get("dob"), today)
        if k == ADULT:
            continue
        checks = list(health.get(eid) or [])
        row = {
            # The four Art. 144 columns, in the article's own order.
            "empId": eid,
            "name": _s(e.get("name")),
            "dob": _s(e.get("dob")),
            "work": _s(e.get("title")),
            "healthChecks": checks,
            # Everything else is context for the person reading it.
            "dept": _s(e.get("dept")),
            "age": completed_years(e.get("dob"), today),
            "band": k,
            "limits": limits(e.get("dob"), today),
            "issues": [], "issuesVn": [],
        }
        # Findings carry their Vietnamese wording. The register is read by a Vietnamese HR officer
        # who has to act on it — an English-only finding on a translated screen is a finding nobody
        # acts on, and the screen has no business restating the law in its own words.
        def _issue(en, vn):
            row["issues"].append(en)
            row["issuesVn"].append(vn)

        if k == UNKNOWN:
            _issue("No date of birth on record. Until it is, this employee cannot be shown to be "
                   "over 18, and the Art. 146 hour limits cannot be applied.",
                   "Chưa có ngày sinh trên hồ sơ. Khi chưa có, không thể chứng minh người này đã "
                   "đủ 18 tuổi và không áp dụng được giới hạn giờ làm theo Điều 146.")
            unknown.append(row)
        else:
            if not checks:
                _issue("No periodic health examination on file. Art. 144 requires the result to be "
                       "recorded in the monitoring book for every minor employee.",
                       "Chưa có kết quả khám sức khỏe định kỳ. Điều 144 yêu cầu ghi kết quả này "
                       "vào sổ theo dõi đối với mọi người lao động chưa thành niên.")
            if not row["work"]:
                _issue("The work being done is not recorded, and Art. 144 requires it by name.",
                       "Chưa ghi công việc đang làm, trong khi Điều 144 yêu cầu ghi rõ tên công việc.")
            if k == UNDER_13:
                _issue("An employee under 13 may only do arts, physical training or sport, and "
                       "only with the provincial labour agency's written approval (Art. 143(3)).",
                       "Người chưa đủ 13 tuổi chỉ được làm công việc nghệ thuật, thể dục, thể thao "
                       "và phải được cơ quan lao động cấp tỉnh chấp thuận bằng văn bản "
                       "(Điều 143(3)).")
        if row["issues"]:
            gaps.append(row)
        rows.append(row)
    minors = [r for r in rows if r["band"] not in (UNKNOWN,)]
    rows.sort(key=lambda r: (r["band"] == UNKNOWN, r.get("age") if r.get("age") is not None else 99,
                             r["name"]))
    return {
        "asOf": today.isoformat(),
        "rows": rows,
        "minors": len(minors),
        "unknownDob": len(unknown),
        "gaps": len(gaps),
        "bands": [dict(b) for b in BANDS],
        "basis": "Labour Code 2019 Art. 144 — a separate monitoring book recording the full name, "
                 "date of birth, work being done and periodic health examination results of every "
                 "minor employee, produced to a competent authority on request.",
        "basisVn": "Bộ luật Lao động 2019 Điều 144 — lập sổ theo dõi riêng ghi họ tên, ngày sinh, "
                   "công việc đang làm và kết quả khám sức khỏe định kỳ của người lao động chưa "
                   "thành niên, xuất trình khi cơ quan có thẩm quyền yêu cầu.",
        "statement": _statement(len(minors), len(unknown)),
        "statementVn": _statement_vn(len(minors), len(unknown)),
    }


def _statement_vn(n_minors, n_unknown):
    if not n_minors and not n_unknown:
        return ("Không có người lao động nào dưới 18 tuổi và mọi người đều đã có ngày sinh trên hồ "
                "sơ. Điều 144 không yêu cầu lập sổ theo dõi.")
    parts = []
    if n_minors:
        parts.append("%d người lao động dưới 18 tuổi, thuộc diện phải lập sổ theo dõi theo Điều 144"
                     % n_minors)
    if n_unknown:
        parts.append("%d người chưa có ngày sinh trên hồ sơ, không thể xác định tuổi theo hướng nào"
                     % n_unknown)
    return "; ".join(parts) + "."


def _statement(n_minors, n_unknown):
    """The sentence an auditor is actually asking for."""
    if not n_minors and not n_unknown:
        return ("No employee on the register is under 18, and every employee has a date of birth on "
                "record. Art. 144 requires no monitoring book.")
    parts = []
    if n_minors:
        parts.append("%d employee(s) under 18, for whom Art. 144 requires a monitoring book" % n_minors)
    if n_unknown:
        parts.append("%d employee(s) with no date of birth on record, whose age cannot be shown "
                     "either way" % n_unknown)
    return "; ".join(parts) + "."
