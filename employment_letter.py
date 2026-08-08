"""The employment confirmation letter — giấy xác nhận công tác.

Somebody asks HR to confirm in writing that they work here. It is the most-requested HR document
there is and it has no statutory form at all, which is exactly why it needs thought: with no form to
follow, the easy implementation prints everything it knows, and "everything it knows" includes the
person's salary.

So the letter has a PURPOSE, and the purpose decides what it discloses:

  · a bank assessing a loan needs the income, and that is the whole point of the letter;
  · an embassy assessing a visa needs the dates, the position, and that leave has been approved —
    not the salary;
  · a prospective employer needs the dates and the position, and has no business knowing the pay;
  · a general confirmation states the least that answers the question.

The employee chooses the purpose when they ask. That is not a formality: it is the difference
between disclosing a salary because somebody needed it and disclosing it because the template had a
field for it. Every letter records the purpose it was issued for, so if a salary was disclosed there
is a reason on file for why.

Pure — no database, no clock. Exercised by tests/test_employment_letter.py.
"""
from datetime import date

import company
import datespan

# What every letter says, whatever it is for. Anything beyond this has to be justified by a purpose.
#
# personalId is deliberately NOT here. The whole design of PURPOSES is that the purpose decides
# disclosure, and the CCCD was the one field that ignored it — a reference to a prospective
# employer and a general confirmation for a landlord both carried the number Vietnamese banks and
# telcos use for e-KYC, to a party who had asked only whether the person works here.
BASE_FIELDS = ("name", "title", "dept", "startDate", "status")

FIELD_LABELS = {
    "name": ("Full name", "Họ và tên"),
    "personalId": ("Citizen ID / passport", "Số CCCD / hộ chiếu"),
    "dob": ("Date of birth", "Ngày sinh"),
    "title": ("Position", "Chức danh"),
    "dept": ("Department", "Bộ phận"),
    "startDate": ("Employed since", "Công tác từ ngày"),
    "status": ("Current status", "Tình trạng hiện tại"),
    "contractType": ("Contract type", "Loại hợp đồng"),
    "salary": ("Gross monthly salary", "Mức lương hàng tháng"),
    "leaveApproved": ("Approved leave", "Nghỉ phép đã được duyệt"),
    "taxId": ("Personal tax code", "Mã số thuế cá nhân"),
}

PURPOSES = {
    "bank": {
        "label": "Bank / loan application", "labelVn": "Vay vốn ngân hàng",
        "discloses": ("personalId", "contractType", "salary", "taxId"),
        "why": "A lender is assessing income, so the salary is the point of the letter rather than "
               "an incidental disclosure. The lender must also identify the borrower, so the "
               "citizen ID belongs on this one.",
    },
    "visa": {
        "label": "Visa / travel", "labelVn": "Xin thị thực / đi công tác",
        "discloses": ("personalId", "dob", "contractType", "leaveApproved"),
        "why": "A consulate wants to know the employment is real and that the trip is agreed, and it "
               "matches the letter to the travel document. It does not need the salary, so this "
               "letter does not print it.",
    },
    "new_employer": {
        "label": "Prospective employer / reference", "labelVn": "Xác nhận cho nơi làm việc mới",
        "discloses": ("contractType",),
        "why": "Dates and position answer the question. What somebody is paid here is not the next "
               "employer's business.",
    },
    "general": {
        "label": "General confirmation", "labelVn": "Xác nhận chung",
        "discloses": (),
        "why": "States the least that answers the question. Choose a more specific purpose if the "
               "recipient needs more.",
    },
}

def has_left(employee, as_of=None):
    """Whether they had already gone by the date on the letter."""
    e = employee or {}
    end = _d(e.get("endDate"))
    today = _d(as_of) or date.today()
    if end and end < today:
        return True
    return _s(e.get("status")).lower() == "inactive"


STATUS_VN = {"active": "Đang làm việc", "inactive": "Đã nghỉ việc",
             "probation": "Đang thử việc", "on leave": "Đang nghỉ phép"}

# A letter without one of these is not evidence of anything.
REQUIRED_EMPLOYEE = (
    ("name", "Full name", "Họ và tên"),
    ("startDate", "Employment start date", "Ngày bắt đầu công tác"),
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


def fields_for(purpose):
    """Which fields this purpose puts on the letter, base first, in a stable printing order."""
    spec = PURPOSES.get(_s(purpose))
    if not spec:
        raise ValueError("unknown purpose: %r" % (purpose,))
    order = list(BASE_FIELDS)
    for f in spec["discloses"]:
        if f not in order:
            order.append(f)
    return order


def discloses_salary(purpose):
    return "salary" in PURPOSES.get(_s(purpose), {}).get("discloses", ())


def service(start_date, as_of):
    """How long they have been here, as the letter states it."""
    s, a = _d(start_date), _d(as_of)
    if not s or not a or a < s:
        return None
    months = datespan.whole_months(s, a)
    years, rem = divmod(months, 12)
    parts = []
    if years:
        parts.append("%d năm" % years)
    if rem or not years:
        parts.append("%d tháng" % rem)
    return {"months": months, "textVn": " ".join(parts),
            # Joined rather than concatenated: the old form left "1 year " with a trailing
            # space, printing "a service of 1 year ." on the anniversaries people ask on.
            "text": " ".join(
                ([("%d year%s" % (years, "" if years == 1 else "s"))] if years else []) +
                ([("%d month%s" % (rem, "" if rem == 1 else "s"))] if (rem or not years) else []))}


def blockers(company_settings, employee, request):
    """What stands between this request and a signable letter."""
    emp = employee or {}
    req = request or {}
    purpose = _s(req.get("purpose"))
    terms = []
    if purpose not in PURPOSES:
        terms.append({"key": "purpose", "label": "What the letter is for",
                      "labelVn": "Mục đích sử dụng"})
    return {
        "company": company.missing_for("employment_letter", company_settings),
        "employee": [{"key": k, "label": lbl, "labelVn": vn}
                     for k, lbl, vn in REQUIRED_EMPLOYEE if not _s(emp.get(k))],
        "terms": terms,
    }


def can_issue(company_settings, employee, request):
    return not any(blockers(company_settings, employee, request).values())


def assemble(company_settings, employee, request, as_of=None, doc_no=""):
    """The finished letter: what it says, and — on the record — why it said that much."""
    ident = company.identity(company_settings)
    emp = employee or {}
    req = request or {}
    today = _d(as_of) or date.today()
    purpose = _s(req.get("purpose"))
    spec = PURPOSES.get(purpose)

    shown, withheld = [], []
    order = fields_for(purpose) if spec else list(BASE_FIELDS)
    for key in order:
        val = emp.get(key)
        if key == "status":
            # The stored value is an English enum; this is a Vietnamese document that somebody signs.
            val = STATUS_VN.get((_s(emp.get("status")) or "Active").lower(),
                                _s(emp.get("status")) or "Active")
        if key == "leaveApproved":
            val = _s(req.get("leaveApproved"))
        label, label_vn = FIELD_LABELS.get(key, (key, key))
        if _s(val):
            shown.append({"key": key, "label": label, "labelVn": label_vn, "value": _s(val)})
    # Named explicitly rather than silently omitted, so the employee can see the letter did not say
    # what they were hoping it would say and ask for a different purpose.
    if spec:
        for key in ("personalId", "salary", "taxId", "dob", "leaveApproved", "contractType"):
            if key not in order and _s(emp.get(key) or req.get(key)):
                label, label_vn = FIELD_LABELS[key]
                withheld.append({"key": key, "label": label, "labelVn": label_vn})

    # A letter for somebody who has LEFT must say so. The first version asserted current employment
    # in the signed sentence while the rows underneath printed "Đã nghỉ việc" — a document that
    # contradicts itself on one page, addressed to a bank or a consulate. Their service also stops
    # on their last day rather than counting on after they left.
    left = has_left(emp, today)
    end = _d(emp.get("endDate"))
    svc = service(emp.get("startDate"), end if (left and end) else today)
    # No "Công ty" prefix: the registered name already carries its own legal form, and prefixing it
    # produced "Công ty Công ty TNHH ..." on the first letter that printed.
    if left:
        body_vn = ("%s xác nhận ông/bà %s đã công tác tại Công ty%s%s, chức danh %s%s."
                   % (ident["legalNameVn"] or "…", _s(emp.get("name")) or "…",
                      " từ ngày %s" % _s(emp.get("startDate")) if _s(emp.get("startDate")) else "",
                      " đến ngày %s" % end.isoformat() if end else "",
                      _s(emp.get("title")) or "…",
                      ", thời gian công tác %s" % svc["textVn"] if svc else ""))
        body_en = ("%s confirms that %s was employed by the company%s%s as %s%s."
                   % (ident["displayNameEn"] or "…", _s(emp.get("name")) or "…",
                      " from %s" % _s(emp.get("startDate")) if _s(emp.get("startDate")) else "",
                      " until %s" % end.isoformat() if end else "",
                      _s(emp.get("title")) or "…",
                      ", a service of %s" % svc["text"] if svc else ""))
    else:
        body_vn = ("%s xác nhận ông/bà %s hiện đang công tác tại Công ty%s, chức danh %s%s."
                   % (ident["legalNameVn"] or "…", _s(emp.get("name")) or "…",
                      " từ ngày %s" % _s(emp.get("startDate")) if _s(emp.get("startDate")) else "",
                      _s(emp.get("title")) or "…",
                      ", thời gian công tác %s" % svc["textVn"] if svc else ""))
        body_en = ("%s confirms that %s is employed by the company%s as %s%s."
                   % (ident["displayNameEn"] or "…", _s(emp.get("name")) or "…",
                      " since %s" % _s(emp.get("startDate")) if _s(emp.get("startDate")) else "",
                      _s(emp.get("title")) or "…",
                      ", a service of %s" % svc["text"] if svc else ""))

    return {
        "docNo": _s(doc_no),
        "issuedOn": today.isoformat(),
        "purpose": purpose,
        "purposeLabel": spec["label"] if spec else "",
        "purposeLabelVn": spec["labelVn"] if spec else "",
        "purposeWhy": spec["why"] if spec else "",
        "addressedTo": _s(req.get("addressedTo")),
        "employer": {"name": ident["legalNameVn"], "nameEn": ident["displayNameEn"],
                     "regNo": ident["regNo"], "address": ident["addressVn"],
                     "phone": ident["phone"], "signatory": ident["signatory"],
                     "repName": ident["repName"], "repTitle": ident["repTitle"]},
        "bodyVn": body_vn, "body": body_en,
        "rows": shown,
        "withheld": withheld,
        "disclosesSalary": discloses_salary(purpose),
        "hasLeft": left,
        "service": svc,
        "purposes": [dict(v, key=k) for k, v in sorted(PURPOSES.items())],
        "blockers": blockers(company_settings, emp, req),
        "canIssue": can_issue(company_settings, emp, req),
        "basis": ("No statutory form — Art. 21 governs the contract, not this. What the letter "
                  "states is decided by what it is for, so a purpose is recorded with every one."),
    }
