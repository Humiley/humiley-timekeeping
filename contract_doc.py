"""The labour contract itself: what Art. 21 requires it to say, and whether we can actually say it.

`contracts.py` already knows what a contract's TERM means — when it expires, when it turns indefinite
by operation of law, when another fixed term is no longer lawful. What has never existed is the
document. The register was a reader with no writer: the collection had no UI that could create a row,
so the expiry warnings were watching a list nobody could add to.

This module is the drafting half. Article 21(1) of the Labour Code 2019 lists ten particulars a
labour contract must contain, and Circular 10/2020 gives the model form. The useful work here is not
formatting — it is refusing to produce a document with a silent gap in it:

  · a particular the portal can supply from a record is filled from that record;
  · a particular that is a matter of agreement is required from the drafter, by name;
  · a particular that is statutory is stated as the statute, not invented;
  · and anything still missing is returned as a BLOCKER, with whose record has to change.

The distinction that matters is between "the company has not been set up yet" and "this person's
record is incomplete". They are fixed by different people in different screens, so they are reported
separately rather than as one list of red text.

Pure — no database, no clock. Exercised by tests/test_contract_doc.py.
"""
from datetime import date

import company
import contracts
import datespan
import vn_amount

# Art. 21(1)(a)–(k). `source` says where the content comes from, which is what lets the caller
# distinguish a missing setting from a missing employee field from a missing agreement.
#   company    — the employer's legal identity (company.py)
#   employee   — the employee master record
#   terms      — agreed between the parties, so the drafter must supply it
#   statutory  — fixed by law; stated, not chosen
PARTICULARS = (
    {"code": "a", "key": "employer", "source": "company",
     "label": "The employer, and who signs for it",
     "labelVn": "Tên, địa chỉ người sử dụng lao động và người giao kết"},
    {"code": "b", "key": "employee", "source": "employee",
     "label": "The employee's identity",
     "labelVn": "Họ tên, ngày sinh, giới tính, nơi cư trú, số CCCD/hộ chiếu"},
    {"code": "c", "key": "job", "source": "terms",
     "label": "The job and the place of work", "labelVn": "Công việc và địa điểm làm việc"},
    {"code": "d", "key": "term", "source": "terms",
     "label": "The term of the contract", "labelVn": "Thời hạn của hợp đồng lao động"},
    {"code": "đ", "key": "wage", "source": "terms",
     "label": "Wage, how and when it is paid, allowances",
     "labelVn": "Mức lương, hình thức trả lương, thời hạn trả lương, phụ cấp"},
    {"code": "e", "key": "raise", "source": "terms",
     "label": "Promotion and wage-rise arrangements", "labelVn": "Chế độ nâng bậc, nâng lương"},
    {"code": "g", "key": "hours", "source": "terms",
     "label": "Working time and rest time", "labelVn": "Thời giờ làm việc, thời giờ nghỉ ngơi"},
    {"code": "h", "key": "ppe", "source": "terms",
     "label": "Personal protective equipment", "labelVn": "Trang bị bảo hộ lao động"},
    {"code": "i", "key": "insurance", "source": "statutory",
     "label": "Social, health and unemployment insurance",
     "labelVn": "Bảo hiểm xã hội, bảo hiểm y tế và bảo hiểm thất nghiệp"},
    {"code": "k", "key": "training", "source": "terms",
     "label": "Training and skill improvement", "labelVn": "Đào tạo, bồi dưỡng, nâng cao trình độ"},
)

# The employee fields Art. 21(1)(b) names. `personalId` is the citizen ID (CCCD) — for a foreign
# employee it holds the passport number, which the article treats as equivalent.
EMPLOYEE_REQUIRED = (
    ("name", "Full name", "Họ và tên"),
    ("dob", "Date of birth", "Ngày sinh"),
    ("gender", "Gender", "Giới tính"),
    ("address", "Place of residence", "Nơi cư trú"),
    ("personalId", "Citizen ID or passport number", "Số CCCD hoặc hộ chiếu"),
)

# Terms the drafter must state, because they are agreed rather than derived. Anything the portal can
# default from a record is NOT here — it is filled in and shown for correction.
TERMS_REQUIRED = (
    ("jobTitle", "Job title", "Chức danh công việc"),
    ("workplace", "Place of work", "Địa điểm làm việc"),
    ("contractType", "Contract type", "Loại hợp đồng"),
    ("startDate", "Effective from", "Ngày có hiệu lực"),
    ("wage", "Wage", "Mức lương"),
)

# Art. 168(1) + the Law on Social Insurance: the split is fixed, so the contract states it rather
# than negotiating it. These are the employee-side rates that appear on the model form.
INSURANCE_TEXT = (
    "The employee participates in compulsory social insurance, health insurance and unemployment "
    "insurance under the Law on Social Insurance, the Law on Health Insurance and the Law on "
    "Employment. Contributions are withheld and paid at the statutory rates.")
INSURANCE_TEXT_VN = (
    "Người lao động tham gia bảo hiểm xã hội bắt buộc, bảo hiểm y tế và bảo hiểm thất nghiệp theo "
    "quy định của Luật Bảo hiểm xã hội, Luật Bảo hiểm y tế và Luật Việc làm. Các khoản đóng góp "
    "được khấu trừ và nộp theo tỷ lệ luật định.")

# Art. 25: the longest probation allowed, by the kind of post. Stated so a drafter cannot exceed it
# by accident; the portal does not decide which band somebody is in, it asks.
PROBATION_MAX_DAYS = {
    "manager": (180, "an enterprise manager as defined by the Law on Enterprises"),
    "degree": (60, "a post requiring a college degree or above"),
    "intermediate": (30, "a post requiring intermediate or technical-worker training"),
    "other": (6, "any other work — six WORKING days"),
}


def _s(v):
    return "" if v is None else str(v).strip()


def _d(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(_s(v)[:10])
    except (TypeError, ValueError):
        return None


def _money(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _term_missing(terms, key):
    # The wage is checked as a NUMBER. _s(0) is "0", which is truthy, so a string test would have
    # let a contract through with no wage on it — the one term nobody can afford to leave blank.
    if key == "wage":
        return _money(terms.get("wage")) <= 0
    return not _s(terms.get(key))


def probation_cap(band):
    """The Art. 25 ceiling for a band, or None if the band is not one of the four."""
    hit = PROBATION_MAX_DAYS.get(_s(band).lower())
    return None if not hit else {"days": hit[0], "basis": "Labour Code 2019 Art. 25 — %s." % hit[1]}


def term_check(terms):
    """What Art. 20 says about the term as drafted. Returns problems, not a verdict."""
    out = []
    kind = _s(terms.get("contractType")).lower()
    start, end = _d(terms.get("startDate")), _d(terms.get("endDate"))
    # A date the parser cannot read used to fall through every branch below, so a drafter who typed
    # 30/01/2026 in the Vietnamese format got the Art. 20 ceiling switched off entirely and a
    # 15-year fixed term issued without a word. The one check this module exists to perform.
    for label, raw in (("start", terms.get("startDate")), ("end", terms.get("endDate"))):
        if _s(raw) and not _d(raw):
            out.append("The %s date '%s' is not a date the term can be checked against. Use "
                       "YYYY-MM-DD." % (label, raw))
    if kind == contracts.DEFINITE:
        if not end:
            out.append("A definite-term contract needs an end date — that is what makes it definite.")
        elif start and end < start:
            out.append("The contract ends before it starts.")
        elif start and contracts.exceeds_max_term(start, end):
            out.append("Art. 20(1)(b) caps a definite term at %d months. As drafted it runs to %s; "
                       "the latest lawful end date from this start is %s."
                       % (contracts.MAX_DEFINITE_MONTHS, end.isoformat(),
                          contracts.last_lawful_end(start).isoformat()))
    elif kind == contracts.INDEFINITE:
        if end:
            out.append("An indefinite-term contract has no end date. Remove it, or make the "
                       "contract definite-term.")
    elif kind:
        out.append("'%s' is not a contract type. Art. 20 allows only indefinite or definite term."
                   % terms.get("contractType"))
    prob = terms.get("probationDays")
    band = terms.get("probationBand")
    # Art. 24(3): NO probation at all on a contract of under one month. The term and the probation
    # were validated as two independent facts and never related to each other, so a two-week
    # contract with a 60-day probation passed both checks — the probation outlasting the contract
    # it was attached to.
    if prob and kind == contracts.DEFINITE and start and end:
        try:
            short = datespan.whole_months(start.isoformat(), end.isoformat()) < 1
        except Exception:
            short = (end - start).days < 30
        if short:
            out.append("Art. 24(3) does not allow a probation period at all on a contract of under "
                       "one month. This one runs %s to %s. Remove the probation, or make the "
                       "contract longer." % (start.isoformat(), end.isoformat()))
            prob = None
    if prob:
        cap = probation_cap(band)
        if not cap:
            out.append("A probation period needs the kind of post it is for, because Art. 25 sets a "
                       "different ceiling for each.")
        else:
            try:
                days = int(prob)
            except (TypeError, ValueError):
                days = -1
            if days < 0:
                out.append("The probation period is not a number of days.")
            elif days > cap["days"]:
                out.append("Probation of %d days exceeds the %d-day ceiling. %s"
                           % (days, cap["days"], cap["basis"]))
    return out


def blockers(company_settings, employee, terms):
    """Everything standing between this draft and a signable document, grouped by whose record it is.

    Grouped rather than flattened because the company identity is fixed once by an administrator in
    settings, the employee fields by HR on the person's record, and the terms by whoever is drafting
    — three different screens, and a single red list sends everybody to the wrong one.
    """
    emp = employee or {}
    t = terms or {}
    return {
        "company": company.missing_for("labour_contract", company_settings),
        "employee": [{"key": k, "label": lbl, "labelVn": vn}
                     for k, lbl, vn in EMPLOYEE_REQUIRED if not _s(emp.get(k))],
        "terms": [{"key": k, "label": lbl, "labelVn": vn}
                  for k, lbl, vn in TERMS_REQUIRED if _term_missing(t, k)],
        "term": term_check(t),
    }


def can_issue(company_settings, employee, terms):
    b = blockers(company_settings, employee, terms)
    return not any(b.values())


def defaults_from(employee, portal=None):
    """What the portal already knows, offered as a starting point rather than silently adopted.

    These are pre-filled for correction, never treated as agreed: a job title on an HR record is
    what somebody is called day to day, and a contract states what they were hired to do.
    """
    e = employee or {}
    p = portal or {}
    return {
        "jobTitle": _s(e.get("title")),
        "workplace": _s(p.get("addressVn")),
        "startDate": _s(e.get("startDate")),
        "wage": e.get("salary") or 0,
        "dept": _s(e.get("dept")),
        "schedule": _s(e.get("schedule")),
        "contractType": contracts.DEFINITE,
    }


def assemble(company_settings, employee, terms, as_of=None, doc_no=""):
    """The finished content of a labour contract, particular by particular.

    Returns the content AND its blockers. It never refuses to assemble — a draft that shows its own
    gaps is more useful than an error message, and the caller decides whether it may be signed.
    """
    ident = company.identity(company_settings)
    emp = employee or {}
    t = dict(terms or {})
    today = _d(as_of) or date.today()
    start, end = _d(t.get("startDate")), _d(t.get("endDate"))
    kind = _s(t.get("contractType")).lower() or contracts.DEFINITE

    wage = _money(t.get("wage"))

    if kind == contracts.INDEFINITE:
        term_line = "Indefinite term, effective from %s." % (start.isoformat() if start else "—")
        term_line_vn = ("Hợp đồng lao động không xác định thời hạn, có hiệu lực từ ngày %s."
                        % (start.isoformat() if start else "—"))
    else:
        months = datespan.whole_months(start, end) if (start and end) else None
        term_line = "Definite term%s, from %s to %s." % (
            " of %d months" % months if months else "",
            start.isoformat() if start else "—", end.isoformat() if end else "—")
        term_line_vn = "Hợp đồng lao động xác định thời hạn%s, từ ngày %s đến ngày %s." % (
            " %d tháng" % months if months else "",
            start.isoformat() if start else "—", end.isoformat() if end else "—")

    content = {
        "a": {"employer": ident["legalNameVn"], "employerEn": ident["displayNameEn"],
              "regNo": ident["regNo"], "address": ident["addressVn"], "phone": ident["phone"],
              "signatory": ident["signatory"], "repName": ident["repName"],
              "repTitle": ident["repTitle"]},
        "b": {"name": _s(emp.get("name")), "dob": _s(emp.get("dob")),
              "gender": _s(emp.get("gender")), "residence": _s(emp.get("address")),
              "personalId": _s(emp.get("personalId")), "empId": _s(emp.get("id")),
              "taxId": _s(emp.get("taxId"))},
        "c": {"jobTitle": _s(t.get("jobTitle")), "dept": _s(t.get("dept")),
              "workplace": _s(t.get("workplace")), "duties": _s(t.get("duties"))},
        "d": {"type": kind, "startDate": start.isoformat() if start else "",
              "endDate": end.isoformat() if end else "", "text": term_line, "textVn": term_line_vn,
              "probationDays": t.get("probationDays") or 0,
              "probationBand": _s(t.get("probationBand")),
              "probationCap": probation_cap(t.get("probationBand"))},
        "đ": {"wage": wage, "wageInWords": vn_amount.in_words(wage),
              "payForm": _s(t.get("payForm")) or "Bank transfer",
              "payDay": _s(t.get("payDay")),
              "allowances": [a for a in (t.get("allowances") or []) if _s(a.get("label"))]},
        "e": {"text": _s(t.get("raiseTerms"))},
        "g": {"text": _s(t.get("hours")), "schedule": _s(t.get("schedule"))},
        "h": {"text": _s(t.get("ppe"))},
        "i": {"text": INSURANCE_TEXT, "textVn": INSURANCE_TEXT_VN},
        "k": {"text": _s(t.get("training"))},
    }

    return {
        "docNo": _s(doc_no),
        "issuedOn": today.isoformat(),
        "particulars": [dict(p) for p in PARTICULARS],
        "content": content,
        "blockers": blockers(company_settings, emp, t),
        "canIssue": can_issue(company_settings, emp, t),
        "basis": ("Labour Code 2019 Art. 21(1) sets the required contents; Art. 20 the term; "
                  "Art. 25 the probation ceiling; Circular 10/2020 gives the model form."),
        # Art. 14(1)/(3) and Art. 13(1): in writing, two copies, one of which is the employee's.
        "copies": ("Made in two copies of equal effect — one held by the employer, one given to the "
                   "employee (Labour Code 2019 Art. 13(1) and Art. 14)."),
        "copiesVn": ("Hợp đồng được lập thành hai bản có giá trị như nhau, người sử dụng lao động "
                     "giữ một bản, người lao động giữ một bản."),
    }
