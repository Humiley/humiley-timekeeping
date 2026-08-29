"""Who the employer is, in the terms a document has to state it.

The portal has always known the company as a display name in a header. That is enough to brand a
report and nowhere near enough to sign a contract: Art. 21(1)(a) of the Labour Code 2019 requires a
labour contract to state the employer's NAME and ADDRESS and the FULL NAME AND TITLE of the person
concluding it, and Circular 10/2020 adds the enterprise registration number to the model form. A
document that guesses any of those is not a document — it is a draft with the company's logo on it.

So the identity is data, held once in settings, and every document that needs it asks here. The two
useful things this module does are:

  · say what is MISSING for a particular document, by name and by reason, so somebody can go and
    fill it in rather than discovering a blank line after printing;
  · refuse to pretend. `identity()` never invents a fallback. An absent field comes back empty and
    `missing_for()` names it.

Vietnamese first, because the contract is governed by Vietnamese law and filed in Vietnamese; the
English line is a courtesy for the bilingual copy and never stands alone.

Pure — no database, no clock. Exercised by tests/test_company.py.
"""

# Every field a document can ask for. `why` is the sentence shown to whoever has to fill it in — it
# says what breaks if it is blank, because "required" on its own has never persuaded anybody.
FIELDS = (
    {"key": "legalNameVn", "label": "Legal name (Vietnamese)", "labelVn": "Tên công ty (tiếng Việt)",
     "why": "The name on the business registration certificate. This is the party to the contract; "
            "a trading name has no standing if the two differ."},
    {"key": "legalNameEn", "label": "Legal name (English)", "labelVn": "Tên công ty (tiếng Anh)",
     "why": "Used on the English half of a bilingual document. Optional — if it is blank the "
            "Vietnamese name is used on both sides rather than a guess."},
    {"key": "regNo", "label": "Enterprise registration number", "labelVn": "Mã số doanh nghiệp",
     "why": "The MSDN / tax code. Circular 10/2020 puts it on the model contract form, and it is "
            "how the labour authority identifies the employer on any filing."},
    {"key": "addressVn", "label": "Registered address", "labelVn": "Địa chỉ trụ sở",
     "why": "The head-office address as registered. Art. 21(1)(a) requires the employer's address "
            "on the contract."},
    {"key": "phone", "label": "Telephone", "labelVn": "Điện thoại",
     "why": "Printed in the parties block. Not required by law, but a contract with no way to "
            "contact the employer is a poor document."},
    {"key": "repName", "label": "Legal representative", "labelVn": "Người đại diện theo pháp luật",
     "why": "The person who signs on the company's side. Art. 21(1)(a) requires their full name; "
            "an unnamed signature block is the single most common reason a contract is sent back."},
    {"key": "repTitle", "label": "Representative's title", "labelVn": "Chức vụ",
     "why": "Art. 21(1)(a) requires the title as well as the name — it is what shows the signatory "
            "had authority to bind the company."},
    {"key": "repAuthority", "label": "Basis of authority", "labelVn": "Căn cứ ủy quyền",
     "why": "Only needed when somebody signs by delegation rather than as the registered "
            "representative: the power of attorney or decision number they act under."},
    {"key": "siCode", "label": "Social insurance unit code", "labelVn": "Mã đơn vị BHXH",
     "why": "The employer's code with the social insurance agency. Appears on insurance filings; "
            "not part of the contract itself."},
    # WHERE CUSTOMERS PAY US. Previously typed onto every quotation, which meant three retyped
    # fields per quote and no single place to change when the bank changed — so a quotation could
    # go out with last year's account on it and nothing would notice.
    {"key": "bankName", "label": "Bank", "labelVn": "Ngân hàng",
     "why": "The bank a customer transfers to. Printed on every quotation and invoice; a wrong or "
            "stale one delays payment and looks careless on a document a customer files."},
    {"key": "bankAccount", "label": "Account number", "labelVn": "Số tài khoản",
     "why": "The company's own receiving account. One place to hold it, so a quotation cannot "
            "carry a copy that was correct when somebody last typed it."},
    {"key": "bankSwift", "label": "SWIFT / BIC", "labelVn": "Mã SWIFT",
     "why": "Needed for an inbound international transfer. Blank is fine for a domestic-only "
            "company — it simply does not print."},
    {"key": "bankBeneficiary", "label": "Beneficiary name", "labelVn": "Tên thụ hưởng",
     "why": "Only when the account is not held in the company's own legal name. Blank means the "
            "legal name is used, which is the normal case."},
)

FIELD_KEYS = tuple(f["key"] for f in FIELDS)
_BY_KEY = {f["key"]: f for f in FIELDS}

# What each document cannot be produced without. Deliberately narrow: a field belongs here only if
# its absence leaves a legal blank, not merely an untidy one.
DOCUMENTS = {
    "labour_contract": {
        "title": "Labour contract",
        "titleVn": "Hợp đồng lao động",
        "needs": ("legalNameVn", "regNo", "addressVn", "repName", "repTitle"),
        "basis": "Labour Code 2019 Art. 21(1)(a); Circular 10/2020 model form.",
    },
    "employment_letter": {
        "title": "Employment confirmation letter",
        "titleVn": "Giấy xác nhận công tác",
        "needs": ("legalNameVn", "addressVn", "repName", "repTitle"),
        "basis": "No statutory form — it is a company statement, so it must at least say which "
                 "company is making it and who signed.",
    },
    "decision": {
        "title": "Decision letter",
        "titleVn": "Quyết định",
        "needs": ("legalNameVn", "repName", "repTitle"),
        "basis": "A decision binds the company, so the signatory and their authority have to appear.",
    },
}


def _s(v):
    return "" if v is None else str(v).strip()


def identity(settings):
    """The employer as a document sees it. Absent fields come back empty — never invented."""
    src = settings or {}
    out = {k: _s(src.get(k)) for k in FIELD_KEYS}
    # The English name is a courtesy line. Where it is blank the Vietnamese name carries both halves
    # of a bilingual document, which is correct — the Vietnamese name is the legal one either way.
    out["displayNameEn"] = out["legalNameEn"] or out["legalNameVn"]
    # Who signs, and on what authority. Stated as one line so a document does not have to assemble it
    # and get the delegated case wrong.
    if out["repName"]:
        line = "%s — %s" % (out["repName"], out["repTitle"]) if out["repTitle"] else out["repName"]
        if out["repAuthority"]:
            line += " (%s)" % out["repAuthority"]
        out["signatory"] = line
    else:
        out["signatory"] = ""
    return out


def missing_for(document, settings):
    """Which required fields are blank for this document, with the reason each one matters."""
    doc = DOCUMENTS.get(document)
    if not doc:
        raise ValueError("unknown document type: %r" % (document,))
    ident = identity(settings)
    return [{"key": k, "label": _BY_KEY[k]["label"], "labelVn": _BY_KEY[k]["labelVn"],
             "why": _BY_KEY[k]["why"]}
            for k in doc["needs"] if not ident.get(k)]


def can_issue(document, settings):
    return not missing_for(document, settings)


def review(settings):
    """The whole picture: the identity, and which documents it is not yet good enough to produce."""
    ident = identity(settings)
    docs = []
    for key in sorted(DOCUMENTS):
        d = DOCUMENTS[key]
        miss = missing_for(key, settings)
        docs.append({"document": key, "title": d["title"], "titleVn": d["titleVn"],
                     "basis": d["basis"], "ready": not miss, "missing": miss})
    filled = [k for k in FIELD_KEYS if ident.get(k)]
    return {
        "identity": ident,
        "fields": [dict(f) for f in FIELDS],
        "documents": docs,
        "filled": len(filled), "total": len(FIELD_KEYS),
        "blocked": [d["title"] for d in docs if not d["ready"]],
    }
