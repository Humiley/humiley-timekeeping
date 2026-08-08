"""Company decisions about staff — the quyết định — and the parts of them the law actually governs.

A Vietnamese company records what it decides about a person in a *quyết định*: an appointment, a pay
rise, a disciplinary measure, the end of an employment. Most of the form is convention. Some of it is
not, and the difference is the whole point of this module: an appointment letter that is badly laid
out is untidy, while a dismissal issued eight months after the incident is void, and a "fine"
deducted from wages is an act the Labour Code forbids outright.

So the conventional shell is data, and the four rules below are code:

  · **Art. 45(1)** — the employer must give WRITTEN notice of termination, except where the ground
    is one of Art. 34(4)–(8). That exception list is exact, and it is why some exits produce a
    decision and some do not.
  · **Art. 36(2)/(3)** — how much advance notice the employer owes, by contract type. With two
    traps: grounds (d) and (e) need none at all, and ground (b) — the long-illness case — is always
    03 WORKING days whatever the contract says, which a naive reading of the ladder gets wrong.
  · **Art. 123** — a disciplinary decision must be ISSUED within 6 months of the violation (12 for
    finance, assets or trade secrets), extendable by 60 days. After that the company has lost the
    right, and a decision issued anyway is worse than none.
  · **Art. 124 / 127** — there are exactly four lawful measures, and monetary fines or deductions
    from wages are not among them. Art. 127(2) prohibits them by name.

The module states the law and refuses; it does not decide anything. Whether somebody should be
disciplined is not a question a portal is entitled to answer.

Sources are the official English translation of Labour Code 45/2019/QH14. Pure — no database, no
clock. Exercised by tests/test_hr_decision.py.
"""
import math
from datetime import date, timedelta

import company
import contracts
import datespan

INDEFINITE = contracts.INDEFINITE
DEFINITE = contracts.DEFINITE


# ── Art. 34: how an employment contract ends ─────────────────────────────────────────────────────
# `notice` is Art. 45(1): the employer must notify in writing EXCEPT for clauses 4, 5, 6, 7 and 8.
# `by` says whose act it is, which decides whose notice ladder applies (Art. 35 vs Art. 36).
TERMINATION_GROUNDS = (
    {"clause": 1, "key": "expiry", "by": "operation", "notice": True,
     "label": "The contract expired", "labelVn": "Hết hạn hợp đồng lao động"},
    {"clause": 2, "key": "task_done", "by": "operation", "notice": True,
     "label": "The agreed task was completed", "labelVn": "Đã hoàn thành công việc theo hợp đồng"},
    {"clause": 3, "key": "mutual", "by": "both", "notice": True,
     "label": "Both parties agreed to end it", "labelVn": "Hai bên thỏa thuận chấm dứt"},
    {"clause": 4, "key": "imprisoned", "by": "operation", "notice": False,
     "label": "The employee was imprisoned or barred from the work by a court",
     "labelVn": "Người lao động bị kết án tù, tử hình hoặc bị cấm làm công việc"},
    {"clause": 5, "key": "expelled", "by": "operation", "notice": False,
     "label": "A foreign employee was expelled",
     "labelVn": "Người lao động nước ngoài bị trục xuất"},
    {"clause": 6, "key": "employee_dead", "by": "operation", "notice": False,
     "label": "The employee died, or was declared missing or incapacitated",
     "labelVn": "Người lao động chết, mất tích hoặc mất năng lực hành vi dân sự"},
    {"clause": 7, "key": "employer_gone", "by": "operation", "notice": False,
     "label": "The employer ceased to exist or to operate",
     "labelVn": "Người sử dụng lao động chết, chấm dứt hoạt động"},
    {"clause": 8, "key": "dismissal", "by": "employer", "notice": False,
     "label": "The employee was dismissed as a disciplinary measure",
     "labelVn": "Người lao động bị xử lý kỷ luật sa thải"},
    {"clause": 9, "key": "employee_unilateral", "by": "employee", "notice": True,
     "label": "The employee resigned (Art. 35)",
     "labelVn": "Người lao động đơn phương chấm dứt hợp đồng (Điều 35)"},
    {"clause": 10, "key": "employer_unilateral", "by": "employer", "notice": True,
     "label": "The employer terminated it unilaterally (Art. 36)",
     "labelVn": "Người sử dụng lao động đơn phương chấm dứt hợp đồng (Điều 36)"},
    {"clause": 11, "key": "redundancy", "by": "employer", "notice": True,
     "label": "Redundancy on restructuring or transfer (Art. 42–43)",
     "labelVn": "Cho thôi việc do thay đổi cơ cấu, công nghệ (Điều 42, 43)"},
    {"clause": 12, "key": "work_permit", "by": "operation", "notice": True,
     "label": "A foreign employee's work permit expired",
     "labelVn": "Giấy phép lao động của người lao động nước ngoài hết hiệu lực"},
    {"clause": 13, "key": "probation_failed", "by": "either", "notice": True,
     "label": "The agreed probation was not passed, or was cancelled",
     "labelVn": "Thỏa thuận thử việc không đạt hoặc bị hủy bỏ"},
)
_GROUND = {g["key"]: g for g in TERMINATION_GROUNDS}

# Art. 36(1)(a)–(g): when the EMPLOYER may terminate unilaterally, and what notice each carries.
#   `notice`: "ladder"  → the Art. 36(2) ladder by contract type
#             "three"   → always 03 working days, whatever the contract (Art. 36(2)(c))
#             "none"    → no advance notice at all (Art. 36(3))
EMPLOYER_GROUNDS = (
    {"point": "a", "key": "underperformance", "notice": "ladder",
     "label": "Repeated failure to perform the work against the employer's published criteria",
     "labelVn": "Thường xuyên không hoàn thành công việc theo tiêu chí đánh giá"},
    {"point": "b", "key": "long_illness", "notice": "three",
     "label": "Still unable to work after 12 months' treatment (6 on a 12–36 month contract, or "
              "more than half the term on a shorter one)",
     "labelVn": "Ốm đau, tai nạn đã điều trị 12 tháng liên tục mà khả năng lao động chưa hồi phục"},
    {"point": "c", "key": "force_majeure", "notice": "ladder",
     "label": "Natural disaster, fire, epidemic, hostility, relocation or downsizing required by a "
              "competent authority, after every alternative was exhausted",
     "labelVn": "Thiên tai, hỏa hoạn, dịch bệnh nguy hiểm, di dời, thu hẹp sản xuất"},
    {"point": "d", "key": "absent_after_suspension", "notice": "none",
     "label": "Not present at the workplace after the Art. 31 time limit",
     "labelVn": "Không có mặt tại nơi làm việc sau thời hạn quy định tại Điều 31"},
    {"point": "đ", "key": "retirement", "notice": "ladder",
     "label": "Reached the Art. 169 retirement age, unless the parties agreed otherwise",
     "labelVn": "Đủ tuổi nghỉ hưu theo Điều 169, trừ trường hợp có thỏa thuận khác"},
    {"point": "e", "key": "absent_five_days", "notice": "none",
     "label": "Absent without acceptable excuse for at least 5 consecutive working days",
     "labelVn": "Tự ý bỏ việc 05 ngày làm việc liên tục không có lý do chính đáng"},
    {"point": "g", "key": "untruthful", "notice": "ladder",
     "label": "Gave untruthful information at conclusion (Art. 16(2)) in a way that affected the "
              "recruitment",
     "labelVn": "Cung cấp thông tin không trung thực khi giao kết hợp đồng"},
)
_EMP_GROUND = {g["key"]: g for g in EMPLOYER_GROUNDS}

# Decree 145/2020 Art. 7 — the fourth rung the ladder never had.
#
# Art. 36(2)(d) and Art. 35(1)(d) do not state a period; they hand it to the Government, and the
# Government set it in Decree 145/2020 Art. 7 for a short list of occupations: an enterprise manager
# as defined by the Law on Enterprises, aircrew and aircraft technical staff, and the master and
# crew of a Vietnamese vessel working abroad. For them the notice is AT LEAST 120 days on an
# indefinite contract or a fixed term of 12 months or more, and at least a QUARTER of the term on a
# shorter one. It binds both sides.
#
# This company has enterprise managers. Without this branch the portal certified 45 days as
# compliant for its own Director and printed a Vietnamese quyết định reciting Art. 36 to say so —
# a signed document that is evidence of the breach it describes.
SPECIAL_NOTICE_DAYS = 120
SPECIAL_JOBS = {
    "label": "Enterprise manager, aircrew or seagoing crew",
    "labelVn": "Người quản lý doanh nghiệp, thành viên tổ bay hoặc thuyền viên",
    "help": "An enterprise manager as defined by the Law on Enterprises (the owner, company "
            "chairman, chairman or members of the Members' Council or the Board, the Director or "
            "General Director, and any other managerial title named in the company charter); "
            "aircrew and aircraft technical staff; and the master or crew of a Vietnamese vessel "
            "working abroad. A head of department is NOT one of these unless the charter names "
            "the role.",
    "helpVn": "Người quản lý doanh nghiệp theo Luật Doanh nghiệp; thành viên tổ lái, nhân viên kỹ "
              "thuật bảo dưỡng tàu bay; thuyền trưởng, thuyền viên tàu biển Việt Nam làm việc ở "
              "nước ngoài. Trưởng phòng KHÔNG thuộc nhóm này trừ khi điều lệ công ty quy định.",
    "basis": "Decree 145/2020 Art. 7, made under Labour Code Art. 35(1)(d) and Art. 36(2)(d).",
}

# Art. 36(2)(a)–(c) and Art. 35(1)(a)–(c): the same ladder for both sides.
NOTICE_LADDER = (
    {"contractType": INDEFINITE, "days": 45, "working": False},
    {"contractType": DEFINITE, "minMonths": 12, "days": 30, "working": False},
    {"contractType": DEFINITE, "minMonths": 0, "days": 3, "working": True},
)

# Art. 124. Exactly four, in order of severity. Nothing else is a disciplinary measure.
MEASURES = (
    {"key": "reprimand", "clause": 1, "label": "Reprimand", "labelVn": "Khiển trách"},
    {"key": "defer_raise", "clause": 2, "label": "Deferment of pay rise, up to 6 months",
     "labelVn": "Kéo dài thời hạn nâng lương không quá 06 tháng", "maxMonths": 6},
    {"key": "demotion", "clause": 3, "label": "Demotion", "labelVn": "Cách chức"},
    {"key": "dismissal", "clause": 4, "label": "Dismissal", "labelVn": "Sa thải"},
)
_MEASURE = {m["key"]: m for m in MEASURES}

# Art. 127. Named prohibitions — the portal refuses these rather than rendering them.
FORBIDDEN_MEASURES = {
    "fine": "Art. 127(2) prohibits monetary fines as a disciplinary measure.",
    "salary_deduction": "Art. 127(2) prohibits deducting the employee's wages as a disciplinary "
                        "measure. A lawful deduction for damage to property is a different thing, "
                        "governed by Art. 129, and is not a disciplinary decision.",
    "suspension_unpaid": "Unpaid suspension is not one of the four measures in Art. 124. Art. 128 "
                         "allows suspension only during an investigation, and it is paid in "
                         "advance at 50%.",
}

# Art. 123(1)/(2). The clock on a disciplinary decision.
LIMIT_MONTHS = 6
LIMIT_MONTHS_SERIOUS = 12          # finance, assets, technological or business secrets
LIMIT_EXTENSION_DAYS = 60

# The decision types this company issues. `governed` says whether the Labour Code constrains it —
# an appointment is pure convention, a dismissal is not, and telling them apart is the point.
DECISIONS = {
    "appointment": {
        "title": "Appointment / assignment", "titleVn": "Quyết định bổ nhiệm / điều động",
        "governed": False, "prefix": "QĐ-BN",
        "basis": "No statutory form. Art. 29 governs a temporary transfer to different work; a "
                 "permanent change to the job stated in the contract is an amendment under "
                 "Art. 33, not a decision the employer takes alone.",
    },
    "salary": {
        "title": "Salary adjustment", "titleVn": "Quyết định nâng lương / điều chỉnh lương",
        "governed": False, "prefix": "QĐ-NL",
        "basis": "Art. 21(1)(e) requires the contract to state the wage-rise arrangements; a rise "
                 "given under them is a decision. A cut is an amendment needing agreement "
                 "(Art. 33), not a decision.",
    },
    "termination": {
        "title": "Termination of employment", "titleVn": "Quyết định chấm dứt hợp đồng lao động",
        "governed": True, "prefix": "QĐ-CDHĐ",
        "basis": "Art. 34 sets the grounds; Art. 45(1) requires written notice for all but "
                 "clauses 4–8; Art. 36(2)/(3) and Art. 35(1) set the notice period.",
    },
    "discipline": {
        "title": "Disciplinary measure", "titleVn": "Quyết định xử lý kỷ luật lao động",
        "governed": True, "prefix": "QĐ-KL",
        "basis": "Art. 124 lists the four measures; Art. 122 the principles and procedure; "
                 "Art. 123 the time limit; Art. 125 the grounds for dismissal; Art. 127 what is "
                 "forbidden.",
    },
    "reward": {
        "title": "Reward / commendation", "titleVn": "Quyết định khen thưởng",
        "governed": False, "prefix": "QĐ-KT",
        "basis": "No statutory form. Art. 104 leaves rewards to the employer's own regulations.",
    },
}

# How the offboarding module's exit types map onto Art. 34. `_EXIT_TYPES` in the frontend is
# ('Resignation', 'End of contract', 'Termination', 'Retirement', 'Mutual agreement').
EXIT_TYPE_GROUND = {
    "resignation": "employee_unilateral",
    "end of contract": "expiry",
    "termination": "employer_unilateral",
    "retirement": "employer_unilateral",     # Art. 36(1)(đ) — still the employer's act
    "mutual agreement": "mutual",
}


def _s(v):
    return "" if v is None else str(v).strip()


# JSON from a form arrives as strings. bool("false") is True, and these two flags decide whether the
# Art. 123 limit is 6 months or 12 — so a typo'd "false" doubled the limit and let a time-barred
# dismissal through. Anything that reads as a negative is a negative.
_FALSEY = {"", "0", "false", "no", "n", "off", "none", "null", "undefined"}


def _flag(v):
    if isinstance(v, str):
        return v.strip().lower() not in _FALSEY
    return bool(v)


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


# ── notice ───────────────────────────────────────────────────────────────────────────────────────

def notice_required(contract_type, term_months=None, special_job=False):
    """The Art. 36(2) / Art. 35(1) ladder, from the contract alone.

    `special_job` selects the Decree 145/2020 Art. 7 rung — see SPECIAL_JOBS. It is a separate
    argument rather than something inferred from a job title, because the Law on Enterprises
    definition turns on the company charter and no regex over "Giám đốc" can read a charter.

    `days` is None when the contract is not known well enough to place somebody on the ladder. The
    first version returned the 30-day middle rung for a blank contract type, which invented an
    obligation from missing data and got it wrong in both directions — an indefinite employee owed
    45 and a short-contract one owed 3 working days. Refusing to pretend is the same rule
    company.py follows.
    """
    kind = _s(contract_type).lower()
    special = _flag(special_job)
    if special and kind == INDEFINITE:
        return {"days": SPECIAL_NOTICE_DAYS, "working": False, "special": True,
                "basis": "120 days — indefinite-term contract for %s. %s"
                         % (SPECIAL_JOBS["label"].lower(), SPECIAL_JOBS["basis"])}
    if kind == INDEFINITE:
        return {"days": 45, "working": False,
                "basis": "45 days — indefinite-term contract (Art. 36(2)(a) / Art. 35(1)(a))."}
    if kind != DEFINITE:
        return {"days": None, "working": False,
                "basis": "The contract type is not recorded, so the Art. 36(2) / Art. 35(1) notice "
                         "period cannot be worked out. Record the contract first."}
    months = term_months if isinstance(term_months, (int, float)) else None
    if months is None:
        return {"days": None, "working": False,
                "basis": "A fixed-term contract with no recorded length could owe 30 days or 03 "
                         "working days (Art. 36(2)(b) vs (c)). Record the term first."}
    if special and months >= 12:
        return {"days": SPECIAL_NOTICE_DAYS, "working": False, "special": True,
                "basis": "120 days — fixed term of 12 months or more for %s. %s"
                         % (SPECIAL_JOBS["label"].lower(), SPECIAL_JOBS["basis"])}
    if special:
        # "At least one quarter of the term." The term is held in whole months here, so the day
        # count is derived from it and the basis says so rather than implying a precision the
        # record does not have. Rounded UP: the decree sets a floor, not a target.
        days = int(math.ceil(months * 30 / 4.0))
        return {"days": days, "working": False, "special": True,
                "basis": "%d days — at least a quarter of a %d-month term, for %s. %s"
                         % (days, months, SPECIAL_JOBS["label"].lower(), SPECIAL_JOBS["basis"])}
    if months < 12:
        return {"days": 3, "working": True,
                "basis": "03 working days — fixed term under 12 months "
                         "(Art. 36(2)(c) / Art. 35(1)(c))."}
    return {"days": 30, "working": False,
            "basis": "30 days — fixed term of 12 to 36 months (Art. 36(2)(b) / Art. 35(1)(b))."}


def employer_notice(ground_key, contract_type, term_months=None, special_job=False):
    """What Art. 36 requires for THIS ground. None if it is not an employer-unilateral ground.

    Two things a straight reading of the ladder gets wrong, both encoded here: grounds (d) and (e)
    carry no advance notice at all (Art. 36(3)), and ground (b) is always 03 working days whatever
    the contract type, because Art. 36(2)(c) names it explicitly alongside the short contracts.
    """
    g = _EMP_GROUND.get(_s(ground_key).lower())
    if not g:
        return None
    if g["notice"] == "none":
        return {"days": 0, "working": False, "point": g["point"],
                "basis": "No advance notice is required for Art. 36(1)(%s) — Art. 36(3)."
                         % g["point"]}
    if g["notice"] == "three":
        return {"days": 3, "working": True, "point": g["point"],
                "basis": "03 working days — Art. 36(2)(c) names Art. 36(1)(b) alongside contracts "
                         "of under 12 months, so the contract type does not change it."}
    out = dict(notice_required(contract_type, term_months, special_job))
    out["point"] = g["point"]
    return out


def working_days_between(a, b):
    """Working days from `a` to `b`, counting Sunday as the weekly rest day.

    Art. 111 guarantees at least one day off a week and Sunday is the statutory default. A company
    on a five-day week gives MORE rest, so counting only Sundays is the conservative direction: it
    can overstate the notice given, never understate the notice required... which is why the caller
    below compares it against the requirement rather than the other way round.
    """
    if not a or not b or b < a:
        return 0
    days = 0
    cur = a
    while cur < b:
        cur = cur + timedelta(days=1)
        if cur.weekday() != 6:          # 6 = Sunday
            days += 1
    return days


def notice_given(notice_date, last_day, working=False):
    """Days of notice actually given, in the unit the requirement is expressed in.

    Art. 36(2)(c) and Art. 35(1)(c) say "03 WORKING days". Comparing that against calendar days
    passed a Friday-to-Monday termination as compliant — three calendar days, but only two working
    ones — so an unlawfully short notice was certified lawful.
    """
    a, b = _d(notice_date), _d(last_day)
    if not a or not b:
        return None
    return working_days_between(a, b) if working else (b - a).days


# ── discipline ───────────────────────────────────────────────────────────────────────────────────

def discipline_deadline(violation_date, serious=False, suspended_until=None):
    """Art. 123. The last day a disciplinary decision may lawfully be ISSUED.

    `serious` is Art. 123(1)'s second limb — finance, assets, technological or business secrets —
    which doubles the limit to 12 months.

    `suspended_until` is the day an Art. 122(4) period ends: the employee's sick leave, custody,
    pending verification, pregnancy or maternity leave, during which no disciplinary measure may be
    taken at all. Art. 123(2) then reads: where the limit has ALREADY EXPIRED by that day, or has
    less than 60 days left, it may be extended by up to 60 days — **from the end of that period**,
    not from the old deadline. The first version added 60 days to the deadline, which refuses a
    lawful dismissal whenever the suspension outlasts the 6- or 12-month limit — which is precisely
    the case the clause exists for. A maternity leave running past the limit is the ordinary case.
    """
    v = _d(violation_date)
    if not v:
        return None
    months = LIMIT_MONTHS_SERIOUS if serious else LIMIT_MONTHS
    end = datespan.add_months(v, months)
    base = end
    sus = _d(suspended_until)
    extended = False
    if sus and (end - sus).days < LIMIT_EXTENSION_DAYS:
        end = sus + timedelta(days=LIMIT_EXTENSION_DAYS)
        extended = end > base
    return {
        "deadline": end.isoformat(), "months": months,
        "baseDeadline": base.isoformat(),
        "extended": extended,
        "suspendedUntil": sus.isoformat() if sus else "",
        "basis": ("Art. 123(1) — %d months from the violation%s.%s"
                  % (months,
                     " (finance, assets or trade secrets)" if serious else "",
                     (" The Art. 122(4) period ran to %s, leaving under 60 days, so Art. 123(2) "
                      "extends it to 60 days from then." % sus.isoformat()) if extended else "")),
    }


def discipline_check(measure, violation_date, issued_on, serious=False, suspended_until=None,
                     defer_months=None):
    """Whether this disciplinary decision may lawfully be issued. Problems, not a verdict."""
    out = []
    key = _s(measure).lower()
    if key in FORBIDDEN_MEASURES:
        out.append(FORBIDDEN_MEASURES[key])
        return out                       # nothing else matters; this one is not a measure at all
    if key not in _MEASURE:
        out.append("'%s' is not a disciplinary measure. Art. 124 allows exactly four: %s."
                   % (measure, ", ".join(m["label"] for m in MEASURES)))
        return out
    if key == "defer_raise":
        # Required, not optional: without it the Art. 124(2) cap has nothing to police AND the
        # decision cannot state the penalty, so Điều 1 would say "not more than 06 months", which
        # imposes nothing an employee could plan around.
        try:
            months = float(defer_months)
        except (TypeError, ValueError):
            months = -1
        if defer_months in (None, "") or months < 0:
            out.append("A deferment of pay rise has to say for how many months — otherwise the "
                       "decision imposes nothing determinate and Art. 124(2) has no figure to cap.")
        elif months == 0:
            out.append("A deferment of zero months is not a penalty.")
        elif months > _MEASURE["defer_raise"]["maxMonths"]:
            out.append("A pay rise may be deferred by at most %d months — Art. 124(2). "
                       "This decision defers it by %g."
                       % (_MEASURE["defer_raise"]["maxMonths"], months))
    dl = discipline_deadline(violation_date, serious=serious, suspended_until=suspended_until)
    if not dl:
        out.append("A disciplinary decision needs the date of the violation — Art. 123 runs the "
                   "time limit from it, so without it nobody can say whether this is in time.")
    else:
        iss = _d(issued_on)
        if not iss:
            out.append("A disciplinary decision needs its own date of issue.")
        elif iss.isoformat() > dl["deadline"]:
            out.append("Out of time. %s The last lawful date to issue this was %s; it is dated %s."
                       % (dl["basis"], dl["deadline"], iss.isoformat()))
        elif _d(violation_date) and iss < _d(violation_date):
            out.append("The decision is dated before the violation it is about.")
    return out


# ── termination ──────────────────────────────────────────────────────────────────────────────────

def ground_for_exit(exit_type):
    """The Art. 34 ground an offboarding record's type corresponds to, or ''."""
    return EXIT_TYPE_GROUND.get(_s(exit_type).lower(), "")


def termination_check(ground_key, contract_type, term_months=None, employer_ground="",
                      notice_date="", last_day="", violation_date="", issued_on="",
                      serious=False, suspended_until=None, special_job=False):
    """What Art. 34/36/45 say about this termination as recorded. Problems, not a verdict."""
    out = []
    g = _GROUND.get(_s(ground_key).lower())
    if not g:
        out.append("'%s' is not one of the Art. 34 grounds for ending an employment contract."
                   % (ground_key or "—"))
        return out
    if g["key"] == "employer_unilateral":
        eg = _EMP_GROUND.get(_s(employer_ground).lower())
        if not eg:
            out.append("A termination under Art. 36 has to say WHICH of the seven grounds in "
                       "Art. 36(1) it rests on — the notice owed depends on it, and a termination "
                       "on no stated ground is unlawful.")
        else:
            need = employer_notice(eg["key"], contract_type, term_months, special_job)
            # In the unit the requirement is expressed in. Art. 36(2)(c) says WORKING days, and
            # comparing that against calendar days passed a Friday-to-Monday termination as
            # compliant — three calendar days but only two working ones.
            given = notice_given(notice_date, last_day, working=need["working"])
            unit = "working day" if need["working"] else "day"
            if need["days"] is None:
                out.append(need["basis"])
            elif need["days"] and given is None:
                out.append("%s The record does not say when the employee was told, so the notice "
                           "cannot be checked." % need["basis"])
            elif need["days"] and given < need["days"]:
                out.append("Short notice: %s Only %d %s(s) were given."
                           % (need["basis"], given, unit))
    # Art. 34(8): a dismissal is a disciplinary measure, so the Art. 123 clock and the Art. 124/127
    # rules apply to it whether it is recorded as a discipline decision or as a termination. Without
    # this, the one refusal the module exists to enforce was optional — the caller chose the kind.
    if g["key"] == "dismissal":
        out += discipline_check("dismissal", violation_date, issued_on,
                                serious=serious, suspended_until=suspended_until)
    return out


def termination_notes(ground_key, contract_type, term_months=None, notice_date="", last_day="",
                      special_job=False):
    """Observations that are NOT reasons to refuse the decision.

    An employee who resigns on short notice has not stopped the company from recording that they
    left; it changes what they are entitled to. Putting it in the blocker list stopped the
    commonest exit there is from being recorded at all, and Art. 35(2) lists seven grounds on which
    they owe no notice whatever — so this is stated as a fact with that caveat, not as a bar.
    """
    notes = []
    if _s(ground_key).lower() != "employee_unilateral":
        return notes
    need = notice_required(contract_type, term_months, special_job)
    if need["days"] is None:
        return notes
    given = notice_given(notice_date, last_day, working=need["working"])
    if given is not None and given < need["days"]:
        notes.append("The employee gave %d day(s) where Art. 35(1) asks for %d. %s Art. 35(2) "
                     "lists seven grounds — unpaid wages, harassment, mistreatment, pregnancy and "
                     "others — on which no notice is owed at all, so check which applies before "
                     "treating this as a shortfall."
                     % (given, need["days"], need["basis"]))
    return notes


def needs_written_notice(ground_key):
    """Art. 45(1). Whether the employer must serve a written notice of termination at all."""
    g = _GROUND.get(_s(ground_key).lower())
    if not g:
        return None
    return {
        "required": bool(g["notice"]),
        "basis": ("Art. 45(1) requires written notice of termination, except where the ground is "
                  "Art. 34(4)–(8)." if g["notice"] else
                  "Art. 45(1) exempts Art. 34(%d) from the written-notice requirement."
                  % g["clause"]),
    }


# ── the document ─────────────────────────────────────────────────────────────────────────────────

NATIONAL_HEADING = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
NATIONAL_MOTTO = "Độc lập - Tự do - Hạnh phúc"


def blockers(kind, company_settings, employee, decision):
    """What stands between this draft and a signable decision, grouped by whose record it is."""
    d = decision or {}
    emp = employee or {}
    spec = DECISIONS.get(_s(kind))
    if not spec:
        raise ValueError("unknown decision type: %r" % (kind,))
    terms = []
    if not _s(d.get("subject")):
        terms.append({"key": "subject", "label": "What is being decided",
                      "labelVn": "Về việc"})
    if not _d(d.get("effectiveFrom")):
        terms.append({"key": "effectiveFrom", "label": "Effective from",
                      "labelVn": "Có hiệu lực từ ngày"})
    law = []
    if kind == "discipline":
        law = discipline_check(d.get("measure"), d.get("violationDate"),
                               d.get("issuedOn") or d.get("effectiveFrom"),
                               serious=_flag(d.get("serious")),
                               suspended_until=d.get("suspendedUntil"),
                               defer_months=d.get("deferMonths"))
    elif kind == "termination":
        law = termination_check(d.get("ground"), d.get("contractType"), d.get("termMonths"),
                                employer_ground=d.get("employerGround"),
                                notice_date=d.get("noticeDate"), last_day=d.get("effectiveFrom"),
                                violation_date=d.get("violationDate"),
                                issued_on=d.get("issuedOn") or d.get("effectiveFrom"),
                                serious=_flag(d.get("serious")),
                                suspended_until=d.get("suspendedUntil"),
                                special_job=_flag(d.get("specialJob")))
    return {
        "company": company.missing_for("decision", company_settings),
        "employee": ([] if _s(emp.get("name")) else
                     [{"key": "name", "label": "Full name", "labelVn": "Họ và tên"}]),
        "terms": terms,
        "law": law,
    }


# The catalogue label spells out the statutory ceiling ("không quá 06 tháng"), which is right for a
# menu and wrong in Điều 1: a decision that says "not more than 6 months" imposes nothing an
# employee could plan around. The operative article states the measure, then the actual period.
_MEASURE_SHORT_VN = {"defer_raise": "kéo dài thời hạn nâng lương"}


def _defer_text(measure, decision):
    if not measure or measure.get("key") != "defer_raise":
        return ("", "")
    try:
        months = float((decision or {}).get("deferMonths"))
    except (TypeError, ValueError):
        return ("", "")
    if months <= 0:
        return ("", "")
    n = int(months) if float(months).is_integer() else months
    return (" Thời hạn kéo dài: %s tháng." % n, " Deferred by %s month(s)." % n)


def notes(kind, decision):
    """Things worth saying about a decision that are NOT reasons to refuse it."""
    d = decision or {}
    if _s(kind) != "termination":
        return []
    return termination_notes(d.get("ground"), d.get("contractType"), d.get("termMonths"),
                             notice_date=d.get("noticeDate"), last_day=d.get("effectiveFrom"),
                             special_job=_flag(d.get("specialJob")))


def can_issue(kind, company_settings, employee, decision):
    return not any(blockers(kind, company_settings, employee, decision).values())


def assemble(kind, company_settings, employee, decision, doc_no="", as_of=None):
    """The finished content of a decision, in the conventional Vietnamese shape.

    Recitals ("Căn cứ …") then operative articles ("Điều 1/2/3"), because that is the form a
    Vietnamese reader — and a labour inspector — expects. The recitals are ASSEMBLED from the rules
    that actually apply rather than typed, so a decision cannot cite an article it does not rest on.
    """
    spec = DECISIONS.get(_s(kind))
    if not spec:
        raise ValueError("unknown decision type: %r" % (kind,))
    ident = company.identity(company_settings)
    emp = employee or {}
    d = decision or {}
    today = _d(as_of) or date.today()
    eff = _d(d.get("effectiveFrom"))

    recitals = [
        "Căn cứ Bộ luật Lao động số 45/2019/QH14 ngày 20 tháng 11 năm 2019;",
        "Căn cứ Điều lệ và Nội quy lao động của %s;" % (ident["legalNameVn"] or "Công ty"),
    ]
    if _s(emp.get("id")):
        recitals.append("Căn cứ hợp đồng lao động đã giao kết với ông/bà %s;"
                        % (_s(emp.get("name")) or _s(emp.get("id"))))

    articles = []
    if kind == "termination":
        g = _GROUND.get(_s(d.get("ground")).lower())
        if g:
            recitals.insert(1, "Căn cứ khoản %d Điều 34 Bộ luật Lao động 2019;" % g["clause"])
        # Only when the termination IS under Art. 36. A consensual exit reciting the 5-day-absence
        # clause misstates the ground on the face of a signed document, and the module's whole
        # claim is that a decision cannot cite an article it does not rest on.
        eg = (_EMP_GROUND.get(_s(d.get("employerGround")).lower())
              if (g and g["key"] == "employer_unilateral") else None)
        if eg:
            recitals.insert(2, "Căn cứ điểm %s khoản 1 Điều 36 Bộ luật Lao động 2019;" % eg["point"])
        articles = [
            {"no": 1, "textVn": "Chấm dứt hợp đồng lao động với ông/bà %s%s kể từ ngày %s."
                                % (_s(emp.get("name")),
                                   ", chức danh %s" % _s(emp.get("title")) if _s(emp.get("title")) else "",
                                   eff.isoformat() if eff else "…"),
             "text": "The employment of %s ends on %s."
                     % (_s(emp.get("name")), eff.isoformat() if eff else "…")},
            {"no": 2, "textVn": "Người lao động bàn giao công việc, tài sản và hoàn tất thủ tục "
                                "trước ngày chấm dứt. Công ty thanh toán đầy đủ các khoản theo "
                                "Điều 48 Bộ luật Lao động trong thời hạn luật định.",
             "text": "Handover to be completed before the last day; the company settles everything "
                     "owed within the Art. 48 deadline."},
        ]
    elif kind == "discipline":
        m = _MEASURE.get(_s(d.get("measure")).lower())
        recitals.insert(1, "Căn cứ Điều 122, Điều 123 và Điều 124 Bộ luật Lao động 2019;")
        articles = [
            {"no": 1, "textVn": "Thi hành hình thức kỷ luật lao động %s đối với ông/bà %s.%s"
                                % ((_MEASURE_SHORT_VN.get((m or {}).get("key"), (m or {}).get("labelVn", "…"))).lower(),
                                   _s(emp.get("name")), _defer_text(m, d)[0]),
             "text": "The disciplinary measure of %s is imposed on %s.%s"
                     % ((m["label"].lower() if m else "…"), _s(emp.get("name")),
                        _defer_text(m, d)[1])},
            {"no": 2, "textVn": "Quyết định có hiệu lực kể từ ngày %s."
                                % (eff.isoformat() if eff else "…"),
             "text": "Effective from %s." % (eff.isoformat() if eff else "…")},
        ]
    else:
        articles = [
            {"no": 1, "textVn": "%s kể từ ngày %s."
                                % (_s(d.get("subjectVn")) or _s(d.get("subject")),
                                   eff.isoformat() if eff else "…"),
             "text": "%s with effect from %s."
                     % (_s(d.get("subject")), eff.isoformat() if eff else "…")},
        ]
    articles.append({
        "no": len(articles) + 1,
        "textVn": "Các bộ phận liên quan và ông/bà %s chịu trách nhiệm thi hành Quyết định này."
                  % _s(emp.get("name")),
        "text": "The departments concerned and %s are responsible for giving effect to this "
                "decision." % _s(emp.get("name")),
    })

    return {
        "kind": kind, "title": spec["title"], "titleVn": spec["titleVn"],
        "governed": spec["governed"], "basis": spec["basis"],
        "docNo": _s(doc_no), "prefix": spec["prefix"],
        "issuedOn": today.isoformat(),
        "nationalHeading": NATIONAL_HEADING, "nationalMotto": NATIONAL_MOTTO,
        "employer": {"name": ident["legalNameVn"], "regNo": ident["regNo"],
                     "address": ident["addressVn"], "signatory": ident["signatory"],
                     "repName": ident["repName"], "repTitle": ident["repTitle"]},
        "employee": {"id": _s(emp.get("id")), "name": _s(emp.get("name")),
                     "title": _s(emp.get("title")), "dept": _s(emp.get("dept"))},
        "subject": _s(d.get("subject")), "subjectVn": _s(d.get("subjectVn")),
        "effectiveFrom": eff.isoformat() if eff else "",
        "recitals": recitals,
        "articles": articles,
        # "Nơi nhận" — who gets a copy. The employee is always on it: a decision about somebody
        # that they are not given is not a decision they can answer.
        "recipients": ["Như Điều %d;" % len(articles),
                       "Người lao động;", "Phòng Nhân sự;", "Lưu: VT."],
        "blockers": blockers(kind, company_settings, emp, d),
        "notes": notes(kind, d),
        "canIssue": can_issue(kind, company_settings, emp, d),
    }
