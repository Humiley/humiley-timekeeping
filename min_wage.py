"""The statutory wage floor, effective-dated — and the one question every social audit asks first.

"Is anybody paid below the regional minimum wage?" is the commonest line on a client's labour-
compliance checklist, and nothing in this portal could answer it. `statutory.py` held one minimum-
wage figure and used it solely as the BHTN contribution ceiling; `payroll_calc.compute()` has no
floor at all; `contract_doc` accepted any wage above zero. A contract stating ₫3,000,000 a month in
Ho Chi Minh City was issuable, payable and invisible.

**The table is effective-dated, not a constant.** Vietnam revises these by decree every year or two.
A single set of numbers overwritten each January silently rewrites history: a statutory return or a
contract check for a 2025 month would be measured against 2026 figures and report a breach that did
not exist, or miss one that did. `at(region, on_date)` picks the decree that was in force on the
day in question, and every answer says which decree it used.

Figures below are the published decrees:

  · **Decree 293/2025/NĐ-CP**, signed 10 November 2025, in force **1 January 2026**, replacing
    Decree 74/2024. Region I ₫5,310,000 · II ₫4,730,000 · III ₫4,140,000 · IV ₫3,700,000 monthly;
    ₫25,500 · ₫22,700 · ₫20,000 · ₫17,800 hourly.
  · **Decree 74/2024/NĐ-CP**, in force **1 July 2024** to 31 December 2025. Region I ₫4,960,000 ·
    II ₫4,410,000 · III ₫3,860,000 · IV ₫3,450,000 monthly; ₫23,800 · ₫21,200 · ₫18,600 · ₫16,600
    hourly.

**What is deliberately NOT asserted here.** A +7% uplift for vocationally-trained workers was an
express requirement under Decree 90/2019 and was not carried into the decrees that replaced it; how
far it survives as a binding term now depends on the company's own collective agreement and
contracts. It is therefore offered as an OPTIONAL company-policy check (`trained_uplift`), never as
a statutory floor, and the answer says which of the two it is. Encoding a contested figure as law
would be worse than leaving it out — it is the kind of number an auditor checks.

Which REGION a workplace is in is a question about its district, set by the decree's own schedule.
This module does not guess it: `at()` refuses an unrecognised region rather than defaulting to the
cheapest or the dearest one.

Pure — no database, no clock. Exercised by tests/test_min_wage.py.
"""
from datetime import date

REGIONS = ("I", "II", "III", "IV")

# (in force from, decree, {region: (monthly, hourly)}). Newest first is not required; `at` sorts.
SCHEDULE = (
    ("2026-01-01", "Decree 293/2025/NĐ-CP", {
        "I": (5_310_000, 25_500), "II": (4_730_000, 22_700),
        "III": (4_140_000, 20_000), "IV": (3_700_000, 17_800)}),
    ("2024-07-01", "Decree 74/2024/NĐ-CP", {
        "I": (4_960_000, 23_800), "II": (4_410_000, 21_200),
        "III": (3_860_000, 18_600), "IV": (3_450_000, 16_600)}),
)

# Offered as a company-policy option, never as law. See the module docstring.
TRAINED_UPLIFT_PCT = 7.0
TRAINED_UPLIFT_NOTE = (
    "A 7% uplift over the regional minimum for employees who have completed certified vocational "
    "training was an express requirement under Decree 90/2019 and was not carried into the decrees "
    "that replaced it. Whether it still binds this company depends on its collective agreement and "
    "its labour contracts, so it is applied only if the company turns it on — it is not asserted "
    "here as a statutory floor.")
TRAINED_UPLIFT_NOTE_VN = (
    "Mức cao hơn 7% so với lương tối thiểu vùng đối với người đã qua đào tạo nghề là quy định rõ "
    "trong Nghị định 90/2019 và không được đưa vào các nghị định thay thế. Việc có còn ràng buộc "
    "công ty hay không phụ thuộc vào thỏa ước lao động tập thể và hợp đồng lao động, nên chỉ áp "
    "dụng khi công ty bật tùy chọn này.")


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def _n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def region_key(region):
    """The region as the decrees name it, or None. Accepts 'I', 'i', 'vung I', 1, '1'."""
    r = _s(region).upper().replace("VÙNG", "").replace("VUNG", "").strip()
    if r in REGIONS:
        return r
    return {"1": "I", "2": "II", "3": "III", "4": "IV"}.get(r)


def at(region, on_date):
    """The floor in force for that region on that day, or None if either is unusable.

    Refuses rather than defaulting. Guessing the region would put a whole workforce against the
    wrong floor, and guessing the date would measure a 2025 payslip against a 2026 decree.
    """
    key = region_key(region)
    d = _d(on_date)
    if not key or not d:
        return None
    for frm, decree, table in sorted(SCHEDULE, reverse=True):
        f = _d(frm)
        if f and d >= f:
            monthly, hourly = table[key]
            return {"region": key, "monthly": monthly, "hourly": hourly,
                    "decree": decree, "inForceFrom": f.isoformat(),
                    "basis": "%s — Region %s minimum wage, in force from %s."
                             % (decree, key, f.isoformat())}
    return None


def trained_uplift(floor_monthly, apply_it):
    """The company-policy floor, if the company has elected to apply the 7%. Never assumed."""
    base = _n(floor_monthly) or 0
    if not apply_it or base <= 0:
        return None
    return int(round(base * (1 + TRAINED_UPLIFT_PCT / 100.0)))


def check(wage, region, on_date, trained=False, apply_trained_uplift=False):
    """Whether a monthly wage meets the floor, and by how much it falls short.

    `ok` is None — not False — when the check cannot be made. A wage that was never checked and a
    wage that passed are different facts, and reporting the first as the second is how a register
    comes to say a company is compliant when nobody looked.
    """
    floor = at(region, on_date)
    w = _n(wage)
    if not floor:
        return {"ok": None, "shortfall": 0, "floor": None, "wage": w,
                "why": "The workplace region or the date is not recorded, so the statutory minimum "
                       "for this employee cannot be established. Both come from the decree's own "
                       "schedule of districts — they are not something to estimate.",
                "whyVn": "Chưa ghi vùng nơi làm việc hoặc chưa có ngày, nên không xác định được "
                         "mức lương tối thiểu áp dụng. Cả hai đều theo danh mục địa bàn của nghị "
                         "định — không phải thứ để ước lượng."}
    if w is None or w <= 0:
        return {"ok": None, "shortfall": 0, "floor": floor, "wage": w,
                "why": "No monthly wage on record, so it cannot be compared with the %s floor of "
                       "₫%s." % (floor["decree"], "{:,}".format(floor["monthly"])),
                "whyVn": "Chưa có mức lương tháng trên hồ sơ nên không đối chiếu được với mức sàn "
                         "₫%s theo %s." % ("{:,}".format(floor["monthly"]), floor["decree"])}
    applies = floor["monthly"]
    policy = trained_uplift(floor["monthly"], trained and apply_trained_uplift)
    if policy:
        applies = policy
    short = max(0, applies - int(w))
    return {
        "ok": short == 0,
        "wage": int(w),
        "floor": floor,
        "applies": applies,
        "policyFloor": policy,
        "shortfall": short,
        "why": (("Meets" if short == 0 else "BELOW") + " the applicable floor of ₫%s. %s%s"
                % ("{:,}".format(applies), floor["basis"],
                   (" Company policy adds the %g%% trained-worker uplift." % TRAINED_UPLIFT_PCT)
                   if policy else "")),
        "whyVn": (("Đạt" if short == 0 else "THẤP HƠN") + " mức sàn áp dụng ₫%s. %s%s"
                  % ("{:,}".format(applies), floor["basis"],
                     (" Chính sách công ty cộng thêm %g%% cho người đã qua đào tạo nghề."
                      % TRAINED_UPLIFT_PCT) if policy else "")),
    }


def review(employees, on_date, default_region=None, apply_trained_uplift=False):
    """Every employee against their floor — the answer to the audit's first question.

    An employee whose region or wage is not recorded is listed as UNCHECKED, separately from those
    who passed. The two are different findings and merging them would let a company report full
    compliance on a roster nobody could measure.
    """
    d = _d(on_date) or date.today()
    rows, below, unchecked = [], [], []
    for e in (employees or []):
        reg = _s(e.get("wageRegion")) or _s(default_region)
        r = check(e.get("salary"), reg, d,
                  trained=bool(e.get("trained")),
                  apply_trained_uplift=apply_trained_uplift)
        row = {"empId": _s(e.get("id")), "name": _s(e.get("name")),
               "dept": _s(e.get("dept")), "title": _s(e.get("title")),
               "region": (r.get("floor") or {}).get("region") or reg,
               "wage": r.get("wage"), "floor": (r.get("floor") or {}).get("monthly"),
               "applies": r.get("applies"), "shortfall": r.get("shortfall", 0),
               "ok": r["ok"], "why": r["why"], "whyVn": r.get("whyVn", "")}
        rows.append(row)
        if r["ok"] is None:
            unchecked.append(row)
        elif not r["ok"]:
            below.append(row)
    rows.sort(key=lambda x: (0 if x["ok"] is False else (1 if x["ok"] is None else 2),
                             -int(x["shortfall"] or 0), x["name"]))
    decree = at(default_region or "I", d) or {}
    return {
        "asOf": d.isoformat(),
        "rows": rows, "checked": len(rows) - len(unchecked),
        "below": len(below), "unchecked": len(unchecked),
        "totalShortfall": sum(int(x["shortfall"] or 0) for x in below),
        "decree": decree.get("decree", ""),
        "schedule": [{"from": f, "decree": dec,
                      "rates": {k: {"monthly": v[0], "hourly": v[1]} for k, v in t.items()}}
                     for f, dec, t in sorted(SCHEDULE, reverse=True)],
        "trainedUpliftApplied": bool(apply_trained_uplift),
        "trainedUpliftNote": TRAINED_UPLIFT_NOTE,
        "trainedUpliftNoteVn": TRAINED_UPLIFT_NOTE_VN,
        "statement": _statement(len(rows) - len(unchecked), len(below), len(unchecked)),
        "statementVn": _statement_vn(len(rows) - len(unchecked), len(below), len(unchecked)),
    }


def _statement_vn(checked, below, unchecked):
    if below:
        s = "%d người lao động đang được trả thấp hơn mức lương tối thiểu vùng." % below
    elif checked:
        s = ("Cả %d người lao động đã đối chiếu đều được trả bằng hoặc cao hơn mức lương tối thiểu "
             "vùng." % checked)
    else:
        s = "Chưa đối chiếu được người lao động nào."
    if unchecked:
        s += (" %d người chưa đối chiếu được — chưa có vùng nơi làm việc hoặc chưa có mức lương "
              "tháng trên hồ sơ, nên không kết luận gì về họ theo hướng nào." % unchecked)
    return s


def _statement(checked, below, unchecked):
    if below:
        s = "%d employee(s) are paid below the statutory regional minimum." % below
    elif checked:
        s = "All %d employee(s) checked are paid at or above the statutory regional minimum." % checked
    else:
        s = "No employee could be checked."
    if unchecked:
        s += (" %d could not be checked — their workplace region or monthly wage is not on record, "
              "so nothing is asserted about them either way." % unchecked)
    return s
