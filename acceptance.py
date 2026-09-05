"""Hồ sơ nghiệm thu — the acceptance dossier, written as rules you can test.

A Vietnamese construction project does not hand over a building; it hands over a *dossier*. Every
piece of work is inspected, minuted and signed as it is covered up, those minutes roll up into stage
and completion acceptances, and the bound set is what the client, the supervision consultant and —
for the classes of works that need it — the state construction authority actually check. If the
paperwork is not there, the work is not accepted, whatever was built.

The portal already held the two ends of that chain and nothing in between. `pm_quality_itp` plans an
inspection; `pm_quality` records that one happened. Neither produces the document anyone signs, and
neither knows that a completion acceptance may not be signed while a work acceptance underneath it
is still open. This module is that middle: the acceptance TYPES, what each one proves, who has to
sign it, what must already be true before it may be signed, and the standards it is judged against.

THE LEGAL CHAIN (Nghị định 06/2021/NĐ-CP — quản lý chất lượng, thi công xây dựng và bảo trì):

  Điều 12   nghiệm thu vật liệu, sản phẩm, cấu kiện, thiết bị trước khi sử dụng vào công trình.
  Điều 21   nghiệm thu CÔNG VIỆC xây dựng. Signed by the contractor's person directly in charge of
            the technical execution and the client's person directly supervising it. The minute
            states the work, the time and place, who attended, and a conclusion — accepted, or not
            accepted with what must be put right.
  Điều 23   nghiệm thu GIAI ĐOẠN thi công hoặc BỘ PHẬN công trình, where the client and contractor
            agree it is needed, or where the work will be covered up.
  Điều 24   nghiệm thu HOÀN THÀNH hạng mục / công trình đưa vào sử dụng. Conditional on the
            underlying work having been accepted, on the tests, trials and commissioning results
            meeting requirement, and on the external clearances (fire safety, environment, and
            whatever else the works class attracts) being in hand. Khoản 3 permits acceptance with
            an outstanding punch list PROVIDED the remaining items do not affect load-bearing
            capacity, safety in use, or the function of the works.
  Điều 25   the state construction authority's check of the acceptance, for the classes of works
            that attract it.
  Điều 26   retention of the completed-works dossier.

  Luật Xây dựng 50/2014/QH13 (sđ, bs 62/2020/QH14) Điều 123 nghiệm thu, Điều 124 bàn giao.
  Thông tư 10/2021/TT-BXD hướng dẫn một số điều và biện pháp thi hành Nghị định 06/2021/NĐ-CP.

PMBOK, for the same chain in the other vocabulary. The mapping is not decorative — it is why the
gate below refuses what it refuses:

  Control Quality (PMBOK 6 §8.3)      an inspection produces a VERIFIED deliverable.
  Validate Scope  (PMBOK 6 §5.5)      the customer signs a verified deliverable and it becomes an
                                      ACCEPTED deliverable. You cannot validate what was never
                                      verified — which is Điều 24's precondition, stated twice in
                                      two languages.
  Close Project or Phase (§4.7)       handover, and the dossier is the closure record.
  PMBOK 7 Delivery / Measurement performance domains carry the same idea without the process names.

WHAT THIS MODULE DELIBERATELY DOES NOT DECIDE

The TCVN/QCVN catalogue below is a STARTING LIST, not an authority. Vietnamese standards are
reissued — TCVN 7957, TCVN 3890 and QCVN 06 have all moved within a few years — and a dossier that
cites a withdrawn edition is a finding at audit. So:

  * a standard is a SUGGESTION offered to whoever is filling the form; the field itself is free text
    and the project's own form library overrides this list;
  * every entry carries the edition it was seeded with, so a wrong one is visible rather than
    implied;
  * nothing in this module refuses anything on the basis of a standard's edition. That judgement
    belongs to the project's QA/QC manager against the current list, and encoding it here would
    only make the app confidently wrong on the day an edition changes.

Pure module: no database, no request, no clock. Everything below is exercised by
tests/test_acceptance.py.
"""

# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Disciplines — the "bộ môn" a dossier belongs to
# ═══════════════════════════════════════════════════════════════════════════════════════════════

DISCIPLINES = [
    {"code": "OSM", "vi": "Nghiệm thu vật tư đầu vào", "en": "Incoming materials & equipment"},
    {"code": "CIV", "vi": "Xây dựng / Kết cấu", "en": "Civil & structural"},
    {"code": "ARC", "vi": "Kiến trúc / Hoàn thiện", "en": "Architectural & finishes"},
    {"code": "ELE", "vi": "Hệ thống điện", "en": "Electrical system"},
    {"code": "LTN", "vi": "Hệ thống chống sét", "en": "Lightning protection"},
    {"code": "ELV", "vi": "Hệ thống điện nhẹ", "en": "Extra-low voltage / ELV"},
    {"code": "FF", "vi": "Hệ thống chữa cháy", "en": "Fire protection"},
    {"code": "HVAC", "vi": "Hệ thống HVAC", "en": "HVAC"},
    {"code": "PLU", "vi": "Hệ thống cấp thoát nước", "en": "Plumbing & drainage"},
    {"code": "GEN", "vi": "Chung / Liên bộ môn", "en": "General / multi-discipline"},
]

DISCIPLINE_CODES = [d["code"] for d in DISCIPLINES]


def discipline(code):
    """The discipline record, or None. Unknown codes are not an error — an imported register may
    carry a code this list has never heard of, and losing the row would be worse than showing it."""
    c = str(code or "").strip().upper()
    return next((d for d in DISCIPLINES if d["code"] == c), None)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Acceptance types — what each minute proves, who signs it, and what must precede it
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  `requires`  BLOCKING. The dossier may not be accepted until every named type has at least one
#              accepted dossier on the same project. This is Điều 24(2) and Validate Scope's
#              "verified deliverables" input, and it is the whole reason this module exists.
#  `expects`   ADVISORY. Shown as a warning, never a refusal — the drafting says "where the client
#              and contractor agree it is needed", and a rule that turns an agreement into a
#              requirement stops real work for no legal reason.
#
#  `parties`   the roles whose signature the minute must carry. These are PROJECT roles, not portal
#              access levels: the person who signs for the contractor is very often an ordinary
#              staff account, and gating on `manager` would mean either the wrong person signs or
#              every site engineer is handed manager access. See _acc_appr_check in app.py.

PARTY_CONTRACTOR = "contractor"
PARTY_SUPERVISOR = "supervisor"
PARTY_CLIENT = "client"
PARTY_DESIGNER = "designer"

PARTIES = [
    {"key": PARTY_CONTRACTOR, "vi": "Nhà thầu thi công", "en": "Contractor",
     "role_vi": "Người phụ trách kỹ thuật thi công trực tiếp",
     "role_en": "Person directly in charge of technical execution"},
    {"key": PARTY_SUPERVISOR, "vi": "Tư vấn QLXD & giám sát", "en": "Construction management & supervision consultant",
     "role_vi": "Người giám sát thi công xây dựng trực tiếp",
     "role_en": "Person directly supervising the construction"},
    {"key": PARTY_CLIENT, "vi": "Chủ đầu tư / BQLDA", "en": "Client / Project Management Unit",
     "role_vi": "Đại diện Ban quản lý dự án của chủ đầu tư",
     "role_en": "Representative of the client's project management unit"},
    {"key": PARTY_DESIGNER, "vi": "Nhà thầu thiết kế", "en": "Design contractor",
     "role_vi": "Người giám sát tác giả",
     "role_en": "Design supervision representative"},
]

PARTY_KEYS = [p["key"] for p in PARTIES]

# Which field on the dossier holds each party's signatory.
#
# Only ONE of the four parties has a portal account. The supervision consultant and the client sign
# the minute on paper, at the point of inspection, and the contractor's own signature on a Vietnamese
# acceptance minute is a wet one too — that sheet with three signature blocks IS the legal artefact.
# So the portal does two different things and must not confuse them:
#
#   * it records WHO signs for each party, prints their name and position on the form, and refuses
#     to mark a dossier accepted while a required party has nobody named — which is the check that
#     catches the real mistake, a minute issued with an empty signature block;
#   * it applies a Part 11 e-signature to the INTERNAL act — compiled, checked, filed — because that
#     is the act a portal account genuinely performs.
#
# Pretending a client's project manager e-signs in our portal would produce a signature manifestation
# naming somebody who never touched the system. That is worse than no signature at all.

SIGNATORY_FIELDS = {
    PARTY_CONTRACTOR: "signContractor",
    PARTY_SUPERVISOR: "signSupervisor",
    PARTY_CLIENT: "signClient",
    PARTY_DESIGNER: "signDesigner",
}


def party(key):
    k = str(key or "").strip().lower()
    return next((p for p in PARTIES if p["key"] == k), None)


def signed_parties(dossier):
    """The parties whose signature block on this minute has a name in it."""
    d = dossier or {}
    return [k for k, f in SIGNATORY_FIELDS.items() if str(d.get(f) or "").strip()]


ACCEPTANCE_TYPES = [
    {
        "key": "material",
        "vi": "Nghiệm thu vật liệu, cấu kiện, thiết bị đầu vào",
        "en": "Acceptance of incoming materials, components and equipment",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 12",
        "pmbok": "Control Quality (§8.3) — inspection of procured inputs",
        "proves_vi": "Vật liệu, cấu kiện và thiết bị đưa vào công trình đúng chủng loại, có chứng "
                     "chỉ xuất xứ và kết quả thí nghiệm phù hợp thiết kế và tiêu chuẩn áp dụng.",
        "proves_en": "The materials, components and equipment brought to site are of the specified "
                     "type and carry origin certificates and test results conforming to the design.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR],
        "requires": [],
        "expects": [],
    },
    {
        "key": "work",
        "vi": "Nghiệm thu công việc xây dựng",
        "en": "Acceptance of construction work",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 21",
        "pmbok": "Control Quality (§8.3) — produces a verified deliverable",
        "proves_vi": "Công việc xây dựng đã thực hiện đúng thiết kế, biện pháp thi công và tiêu "
                     "chuẩn áp dụng; đủ điều kiện để chuyển bước hoặc che khuất.",
        "proves_en": "The work was executed to the design, the method statement and the applicable "
                     "standard, and may proceed to the next step or be covered up.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR],
        "requires": [],
        "expects": ["material"],
    },
    {
        "key": "commission",
        "vi": "Nghiệm thu chạy thử, thí nghiệm, vận hành thử",
        "en": "Testing, trial run and commissioning acceptance",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 21 và Điều 24 khoản 2",
        "pmbok": "Control Quality (§8.3) — system-level verification before validation",
        "proves_vi": "Hệ thống đã được thí nghiệm, chạy thử không tải và có tải; kết quả đạt yêu "
                     "cầu của thiết kế và tiêu chuẩn áp dụng.",
        "proves_en": "The system has been tested and trial-run under no load and load, with results "
                     "meeting the design and the applicable standard.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR, PARTY_CLIENT],
        "requires": ["work"],
        "expects": [],
    },
    {
        "key": "stage",
        "vi": "Nghiệm thu giai đoạn thi công hoặc bộ phận công trình",
        "en": "Acceptance of a construction stage or part of the works",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 23",
        "pmbok": "Validate Scope (§5.5) at a phase boundary",
        "proves_vi": "Một giai đoạn thi công hoặc một bộ phận công trình đã hoàn thành trên cơ sở "
                     "các công việc thành phần đã được nghiệm thu.",
        "proves_en": "A construction stage or a part of the works is complete, on the basis of the "
                     "component works already accepted.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR, PARTY_CLIENT],
        "requires": ["work"],
        "expects": [],
    },
    {
        "key": "handover_part",
        "vi": "Nghiệm thu hoàn thành hạng mục công trình",
        "en": "Completion acceptance of a work item",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 24",
        "pmbok": "Validate Scope (§5.5) — accepted deliverable",
        "proves_vi": "Hạng mục công trình đã hoàn thành, các công việc đã được nghiệm thu, kết quả "
                     "thí nghiệm và chạy thử đạt yêu cầu; đủ điều kiện đưa vào sử dụng.",
        "proves_en": "The work item is complete, its works accepted and its test and trial results "
                     "compliant; it may be put into use.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR, PARTY_CLIENT],
        "requires": ["work"],
        "expects": ["stage", "commission"],
        "clearances": True,
    },
    {
        "key": "handover_all",
        "vi": "Nghiệm thu hoàn thành công trình đưa vào sử dụng",
        "en": "Completion acceptance of the works for use",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 24; Luật Xây dựng, Điều 123",
        "pmbok": "Validate Scope (§5.5) → Close Project or Phase (§4.7)",
        "proves_vi": "Toàn bộ công trình đã hoàn thành theo thiết kế được phê duyệt, đủ điều kiện "
                     "đưa vào khai thác sử dụng.",
        "proves_en": "The whole works is complete to the approved design and may be brought into "
                     "operation.",
        "parties": [PARTY_CONTRACTOR, PARTY_SUPERVISOR, PARTY_CLIENT, PARTY_DESIGNER],
        "requires": ["handover_part"],
        "expects": ["stage", "commission"],
        "clearances": True,
    },
    {
        "key": "handover_deed",
        "vi": "Bàn giao công trình đưa vào sử dụng",
        "en": "Handover of the works into use",
        "law": "Luật Xây dựng, Điều 124; Nghị định 06/2021/NĐ-CP, Điều 27",
        "pmbok": "Close Project or Phase (§4.7)",
        "proves_vi": "Công trình được bàn giao cho chủ quản lý sử dụng cùng hồ sơ hoàn thành, quy "
                     "trình vận hành bảo trì và thời hạn bảo hành.",
        "proves_en": "The works is handed to the operator together with the completion dossier, the "
                     "operation and maintenance procedure, and the warranty period.",
        "parties": [PARTY_CONTRACTOR, PARTY_CLIENT],
        "requires": ["handover_all"],
        "expects": [],
        "clearances": True,
    },
]

TYPE_KEYS = [t["key"] for t in ACCEPTANCE_TYPES]


def acceptance_type(key):
    k = str(key or "").strip().lower()
    return next((t for t in ACCEPTANCE_TYPES if t["key"] == k), None)


def required_parties(type_key):
    """The signatures this kind of minute has to carry. An unknown type falls back to the two
    signatures Điều 21 always requires rather than to none — a dossier that demands nothing is a
    worse answer than one that demands the minimum."""
    t = acceptance_type(type_key)
    return list(t["parties"]) if t else [PARTY_CONTRACTOR, PARTY_SUPERVISOR]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  External clearances — Điều 24 khoản 2
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  A completion acceptance is conditional on written acceptance from the authorities the works class
#  attracts. WHICH ones is a project fact, not a code fact: fire safety applies to most buildings,
#  environment to some, lifts and pressure equipment only where they are installed. So this is a
#  CHECKLIST the project ticks and evidences, and `applies` is the default the form is seeded with —
#  every one of them can be turned off on a project with a recorded reason.

CLEARANCES = [
    {"key": "fire", "vi": "Văn bản chấp thuận kết quả nghiệm thu về phòng cháy chữa cháy",
     "en": "Written acceptance of the fire-safety acceptance result", "applies": True,
     "note_vi": "Do cơ quan Cảnh sát PCCC cấp theo pháp luật về PCCC hiện hành.",
     "note_en": "Issued by the fire authority under the fire-safety law in force."},
    {"key": "environment", "vi": "Văn bản về bảo vệ môi trường / giấy phép môi trường",
     "en": "Environmental clearance or environmental licence", "applies": True,
     "note_vi": "Theo pháp luật về bảo vệ môi trường áp dụng cho loại và cấp công trình.",
     "note_en": "Under the environmental law applicable to the class of works."},
    {"key": "authority_check", "vi": "Thông báo kết quả kiểm tra công tác nghiệm thu của cơ quan "
     "chuyên môn về xây dựng", "en": "Notice of the construction authority's check of the acceptance",
     "applies": True, "note_vi": "Nghị định 06/2021/NĐ-CP, Điều 24 khoản 2 và Điều 25 — áp dụng cho "
     "các công trình thuộc đối tượng phải kiểm tra.",
     "note_en": "Decree 06/2021 Arts. 24(2) and 25 — for the classes of works that attract it."},
    {"key": "lift", "vi": "Kiểm định an toàn thang máy, thiết bị nâng",
     "en": "Safety inspection of lifts and lifting equipment", "applies": False,
     "note_vi": "Chỉ áp dụng khi công trình có lắp đặt.", "note_en": "Only where installed."},
    {"key": "pressure", "vi": "Kiểm định thiết bị áp lực, nồi hơi",
     "en": "Inspection of pressure vessels and boilers", "applies": False,
     "note_vi": "Chỉ áp dụng khi công trình có lắp đặt.", "note_en": "Only where installed."},
    {"key": "water", "vi": "Kết quả thử nghiệm chất lượng nước sinh hoạt",
     "en": "Potable-water quality test result", "applies": False,
     "note_vi": "Khi công trình cấp nước sinh hoạt cho người sử dụng.",
     "note_en": "Where the works supplies potable water to occupants."},
]

CLEARANCE_KEYS = [c["key"] for c in CLEARANCES]


def default_clearances():
    """The clearance checklist a new completion dossier starts from."""
    return [{"key": c["key"], "applies": bool(c["applies"]), "ref": "", "date": "", "reason": ""}
            for c in CLEARANCES]


def clearance(key):
    k = str(key or "").strip().lower()
    return next((c for c in CLEARANCES if c["key"] == k), None)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Tài liệu căn cứ — the basis documents every minute cites
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  Điều 21(3) requires the minute to identify what the work was judged against. These five rows are
#  the ones a Vietnamese acceptance form carries; the project fills the number and the date.

#  `prefill` is the difference between a standing statement and a placeholder. "Theo bản vẽ thi công
#  được phê duyệt" is what the row actually SAYS on every Vietnamese acceptance form — it is content.
#  "Tiêu chuẩn áp dụng cho công tác này" is an instruction to the person filling it in, and printing
#  it on a signed minute produces a document that appears to cite a standard and cites nothing. So
#  the standing statements are prefilled and the rest arrive empty, with the instruction offered as
#  the field's placeholder instead.

BASIS_ROWS = [
    {"key": "drawing", "vi": "Bản vẽ tham chiếu", "en": "Reference drawing", "prefill": True,
     "hint_vi": "Theo bản vẽ thi công được phê duyệt",
     "hint_en": "Following approved shop drawing"},
    {"key": "spec", "vi": "Tiêu chí kỹ thuật", "en": "Specification", "prefill": False,
     "hint_vi": "Theo chỉ dẫn kỹ thuật của dự án", "hint_en": "Following the project specification"},
    {"key": "standard", "vi": "Quy chuẩn, tiêu chuẩn", "en": "Code, standard", "prefill": False,
     "hint_vi": "Tiêu chuẩn áp dụng cho công tác này",
     "hint_en": "The standard applicable to this work"},
    {"key": "method", "vi": "Biện pháp thi công", "en": "Method statement", "prefill": True,
     "hint_vi": "Theo biện pháp thi công được phê duyệt",
     "hint_en": "Following approved method statement"},
    {"key": "procedure", "vi": "Quy trình", "en": "Procedure", "prefill": False,
     "hint_vi": "Quy trình kiểm tra, thí nghiệm áp dụng",
     "hint_en": "The applicable inspection or test procedure"},
]

BASIS_KEYS = [b["key"] for b in BASIS_ROWS]


def default_basis():
    return [{"key": b["key"], "docNo": "",
             "title": b["hint_vi"] if b.get("prefill") else "", "date": ""}
            for b in BASIS_ROWS]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  TCVN / QCVN — a SUGGESTION list, per discipline
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  Read the module docstring before adding to this. Nothing here refuses anything; it fills a
#  dropdown so a site engineer types "TCVN 4453:1995" rather than "TCVN 4453-95" and the register
#  can be searched. `edition` is the edition this list was seeded with — shown next to the code so
#  a superseded one is visible rather than silently cited.

STANDARDS = [
    # ── Chung / cross-discipline ──────────────────────────────────────────────────────────────
    {"code": "TCVN 4055", "edition": "2012", "disc": ["GEN", "CIV"],
     "vi": "Công trình xây dựng — Tổ chức thi công", "en": "Construction works — Organisation of construction"},
    {"code": "TCVN 5637", "edition": "1991", "disc": ["GEN"],
     "vi": "Quản lý chất lượng xây lắp công trình xây dựng — Nguyên tắc cơ bản",
     "en": "Quality management of construction and installation — Basic principles"},
    {"code": "QCVN 18", "edition": "2021/BXD", "disc": ["GEN"],
     "vi": "Quy chuẩn kỹ thuật quốc gia về An toàn trong thi công xây dựng",
     "en": "National technical regulation on safety in construction"},
    {"code": "TCVN 9398", "edition": "2012", "disc": ["GEN", "CIV"],
     "vi": "Công tác trắc địa trong xây dựng công trình — Yêu cầu chung",
     "en": "Surveying in construction — General requirements"},

    # ── Xây dựng / kết cấu ────────────────────────────────────────────────────────────────────
    {"code": "TCVN 4453", "edition": "1995", "disc": ["CIV"],
     "vi": "Kết cấu bê tông và bê tông cốt thép toàn khối — Quy phạm thi công và nghiệm thu",
     "en": "Monolithic concrete and reinforced concrete structures — Code for execution and acceptance"},
    {"code": "TCVN 9361", "edition": "2012", "disc": ["CIV"],
     "vi": "Công tác nền móng — Thi công và nghiệm thu",
     "en": "Foundation works — Execution and acceptance"},
    {"code": "TCVN 5574", "edition": "2018", "disc": ["CIV"],
     "vi": "Thiết kế kết cấu bê tông và bê tông cốt thép",
     "en": "Design of concrete and reinforced concrete structures"},
    {"code": "TCVN 5575", "edition": "2012", "disc": ["CIV"],
     "vi": "Thiết kế kết cấu thép", "en": "Design of steel structures"},
    {"code": "TCVN 1651", "edition": "bộ / series", "disc": ["CIV", "OSM"],
     "vi": "Thép cốt bê tông", "en": "Steel for the reinforcement of concrete"},
    {"code": "TCVN 3118", "edition": "2022", "disc": ["CIV", "OSM"],
     "vi": "Bê tông — Phương pháp xác định cường độ chịu nén",
     "en": "Concrete — Method for determination of compressive strength"},

    # ── Điện ──────────────────────────────────────────────────────────────────────────────────
    {"code": "QCVN 12", "edition": "2014/BXD", "disc": ["ELE"],
     "vi": "Quy chuẩn kỹ thuật quốc gia về Hệ thống điện của nhà ở và nhà công cộng",
     "en": "National technical regulation on electrical installations of dwellings and public buildings"},
    {"code": "TCVN 9206", "edition": "2012", "disc": ["ELE"],
     "vi": "Đặt thiết bị điện trong nhà ở và công trình công cộng — Tiêu chuẩn thiết kế",
     "en": "Installation of electrical equipment in dwellings and public buildings — Design standard"},
    {"code": "TCVN 9207", "edition": "2012", "disc": ["ELE"],
     "vi": "Đặt đường dẫn điện trong nhà ở và công trình công cộng — Tiêu chuẩn thiết kế",
     "en": "Installation of electrical wiring in dwellings and public buildings — Design standard"},
    {"code": "TCVN 7447", "edition": "bộ / series (IEC 60364)", "disc": ["ELE"],
     "vi": "Hệ thống lắp đặt điện hạ áp", "en": "Low-voltage electrical installations"},
    {"code": "TCVN 9358", "edition": "2012", "disc": ["ELE", "LTN"],
     "vi": "Lắp đặt hệ thống nối đất thiết bị cho các công trình công nghiệp — Yêu cầu chung",
     "en": "Installation of earthing systems for industrial works — General requirements"},

    # ── Chống sét ─────────────────────────────────────────────────────────────────────────────
    {"code": "TCVN 9385", "edition": "2012", "disc": ["LTN"],
     "vi": "Chống sét cho công trình xây dựng — Hướng dẫn thiết kế, kiểm tra và bảo trì hệ thống",
     "en": "Lightning protection for buildings — Design, inspection and maintenance guide"},
    {"code": "TCVN 9888", "edition": "bộ / series (IEC 62305)", "disc": ["LTN"],
     "vi": "Bảo vệ chống sét", "en": "Protection against lightning"},

    # ── Điện nhẹ ──────────────────────────────────────────────────────────────────────────────
    {"code": "TCVN 9250", "edition": "2021", "disc": ["ELV"],
     "vi": "Trung tâm dữ liệu — Yêu cầu về hạ tầng kỹ thuật viễn thông",
     "en": "Data centres — Telecommunication infrastructure requirements"},
    {"code": "ISO/IEC 11801", "edition": "series", "disc": ["ELV"],
     "vi": "Hệ thống cáp cấu trúc cho khuôn viên người dùng",
     "en": "Generic cabling for customer premises"},

    # ── PCCC ──────────────────────────────────────────────────────────────────────────────────
    {"code": "QCVN 06", "edition": "2022/BXD", "disc": ["FF", "GEN", "ARC"],
     "vi": "Quy chuẩn kỹ thuật quốc gia về An toàn cháy cho nhà và công trình",
     "en": "National technical regulation on fire safety of buildings and constructions"},
    {"code": "TCVN 3890", "edition": "2023", "disc": ["FF"],
     "vi": "Phòng cháy chữa cháy — Phương tiện PCCC cho nhà và công trình — Trang bị, bố trí",
     "en": "Fire protection — Fire-fighting equipment for buildings — Provision and arrangement"},
    {"code": "TCVN 5738", "edition": "2021", "disc": ["FF", "ELV"],
     "vi": "PCCC — Hệ thống báo cháy tự động — Yêu cầu kỹ thuật",
     "en": "Fire protection — Automatic fire alarm systems — Technical requirements"},
    {"code": "TCVN 7336", "edition": "2021", "disc": ["FF"],
     "vi": "PCCC — Hệ thống chữa cháy tự động bằng nước, bọt — Yêu cầu thiết kế và lắp đặt",
     "en": "Fire protection — Automatic water and foam sprinkler systems — Design and installation"},

    # ── HVAC ──────────────────────────────────────────────────────────────────────────────────
    {"code": "TCVN 5687", "edition": "2010", "disc": ["HVAC"],
     "vi": "Thông gió — Điều hòa không khí — Tiêu chuẩn thiết kế",
     "en": "Ventilation and air conditioning — Design standard"},
    {"code": "QCVN 09", "edition": "2017/BXD", "disc": ["HVAC", "ELE", "ARC"],
     "vi": "Quy chuẩn kỹ thuật quốc gia về Các công trình xây dựng sử dụng năng lượng hiệu quả",
     "en": "National technical regulation on energy-efficient buildings"},

    # ── Cấp thoát nước ────────────────────────────────────────────────────────────────────────
    {"code": "TCVN 4513", "edition": "1988", "disc": ["PLU"],
     "vi": "Cấp nước bên trong — Tiêu chuẩn thiết kế",
     "en": "Internal water supply — Design standard"},
    {"code": "TCVN 4474", "edition": "1987", "disc": ["PLU"],
     "vi": "Thoát nước bên trong — Tiêu chuẩn thiết kế",
     "en": "Internal drainage — Design standard"},
    {"code": "TCVN 7957", "edition": "2023", "disc": ["PLU"],
     "vi": "Thoát nước — Mạng lưới và công trình bên ngoài — Yêu cầu thiết kế",
     "en": "Drainage — External networks and facilities — Design requirements"},
    {"code": "QCVN 01-1", "edition": "2018/BYT", "disc": ["PLU"],
     "vi": "Quy chuẩn kỹ thuật quốc gia về Chất lượng nước sạch sử dụng cho mục đích sinh hoạt",
     "en": "National technical regulation on domestic water quality"},
]


def standards_for(disc_code):
    """The suggestion list for one discipline, with the GEN entries always included — a work
    acceptance cites its discipline standard and the organisation-of-works one together."""
    c = str(disc_code or "").strip().upper()
    # An unknown code — an imported register, a discipline this app has not been taught — gets the
    # WHOLE catalogue. Narrowing it to the GEN entries would look like a filtered answer while
    # hiding the standard the person is actually looking for.
    if not discipline(c):
        return list(STANDARDS)
    out = [s for s in STANDARDS if c in s["disc"]]
    if c != "GEN":
        seen = {id(s) for s in out}
        out += [s for s in STANDARDS if "GEN" in s["disc"] and id(s) not in seen]
    return out


def standard_label(s):
    """`TCVN 4453:1995`, `QCVN 06:2022/BXD`, `TCVN 1651 bộ / series` — how the code is written on
    the form. A year-like edition is joined with a colon (that is the convention); a word-like one
    reads as a note and is joined with a space."""
    ed = str((s or {}).get("edition") or "").strip()
    if not ed:
        return (s or {}).get("code") or ""
    return s["code"] + (":" if ed[0].isdigit() else " ") + ed


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Numbering — the two independent series a Vietnamese dossier runs
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  A project runs TWO series that must not be confused, because they count different things:
#    the ARF  — one number per acceptance CALLED (the invitation), including the ones that fail and
#               are called again;
#    the ref  — one number per DOSSIER compiled, which may bind several ARFs together.
#  Merging them loses the count of failed inspections, which is exactly the number a client asks for.

NUMBER_TOKENS = [
    {"token": "{PREFIX}", "vi": "Mã dự án", "en": "Project code"},
    {"token": "{DISC}", "vi": "Mã bộ môn (ELE, HVAC…)", "en": "Discipline code"},
    {"token": "{CODE}", "vi": "Mã biểu mẫu (PP-EL-205)", "en": "Form code"},
    {"token": "{TYPE}", "vi": "Mã loại nghiệm thu (ARF, BBNT…)", "en": "Acceptance type tag"},
    {"token": "{SEQ}", "vi": "Số thứ tự 3 chữ số", "en": "3-digit sequence"},
    {"token": "{YY}", "vi": "Năm 2 chữ số", "en": "2-digit year"},
]

DEFAULT_ARF_TEMPLATE = "{PREFIX}-ARF-{DISC}-{SEQ}"
DEFAULT_REF_TEMPLATE = "{PREFIX}-{DISC}-{SEQ}"


def render_number(template, prefix="", disc="", code="", type_tag="", seq=1, year=""):
    """Substitute the tokens. An unknown token is left alone rather than blanked: a template with a
    typo should read `{DISK}` on the screen, which somebody will fix, not vanish into a number that
    looks right and is missing a field."""
    n = str(template or DEFAULT_REF_TEMPLATE)
    try:
        s = int(seq)
    except (TypeError, ValueError):
        s = 1
    yy = str(year or "")[-2:]
    for tok, val in (("{PREFIX}", prefix), ("{DISC}", disc), ("{CODE}", code),
                     ("{TYPE}", type_tag), ("{SEQ}", _pad3(s)), ("{YY}", yy)):
        n = n.replace(tok, str(val or ""))
    # A template that used no separator around an empty token leaves a double dash behind.
    while "--" in n:
        n = n.replace("--", "-")
    return n.strip("-")


def _pad3(n):
    t = str(int(n))
    return t if len(t) >= 3 else ("000" + t)[-3:]


def next_seq(existing, field):
    """One past the HIGHEST trailing number already in the register — not the count. A register
    holding 1, 2 and 7 goes on to 8, and deleting the last record must not hand its number to the
    next one."""
    top = 0
    for row in existing or []:
        v = str((row or {}).get(field) or "").strip()
        i = len(v)
        while i and v[i - 1].isdigit():
            i -= 1
        if i < len(v):
            try:
                n = int(v[i:])
            except ValueError:
                continue
            if n > top:
                top = n
    return top + 1


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Results
# ═══════════════════════════════════════════════════════════════════════════════════════════════

RESULT_PASS = "pass"          # Đạt
RESULT_FAIL = "fail"          # Không đạt
RESULT_NA = "na"              # Không áp dụng
RESULT_PENDING = "pending"    # Chưa kiểm tra

RESULTS = [
    {"key": RESULT_PASS, "vi": "Đạt", "en": "Pass", "hex": "#00B060"},
    {"key": RESULT_FAIL, "vi": "Không đạt", "en": "Fail", "hex": "#DC2626"},
    {"key": RESULT_NA, "vi": "Không áp dụng", "en": "N/A", "hex": "#94a3b8"},
    {"key": RESULT_PENDING, "vi": "Chưa kiểm tra", "en": "Not checked", "hex": "#F59E0B"},
]


def _res(v):
    """Normalise whatever the row carries. The register is filled in two languages and imported from
    spreadsheets, so `Đạt`, `Pass`, `pass`, `OK` and `P` all arrive meaning the same thing. Anything
    unrecognised is PENDING, never PASS — an unreadable result must not close a checklist line."""
    s = str(v or "").strip().lower()
    if not s:
        return RESULT_PENDING
    if s in ("pass", "p", "ok", "đạt", "dat", "yes", "y", "accepted", "conform"):
        return RESULT_PASS
    if s in ("fail", "f", "không đạt", "khong dat", "kđ", "kd", "k.đạt", "k.dat", "no", "n",
             "rejected", "nonconform"):
        return RESULT_FAIL
    if s in ("na", "n/a", "n.a", "không áp dụng", "khong ap dung", "kap"):
        return RESULT_NA
    return RESULT_PENDING


def checklist_progress(items):
    """How the checklist stands: counts by result, plus the two numbers a form header prints."""
    out = {RESULT_PASS: 0, RESULT_FAIL: 0, RESULT_NA: 0, RESULT_PENDING: 0}
    for it in items or []:
        out[_res((it or {}).get("result"))] += 1
    total = sum(out.values())
    judged = total - out[RESULT_PENDING]
    applicable = total - out[RESULT_NA]
    return {
        "total": total, "judged": judged, "applicable": applicable,
        "pass": out[RESULT_PASS], "fail": out[RESULT_FAIL],
        "na": out[RESULT_NA], "pending": out[RESULT_PENDING],
        # Percentage of the APPLICABLE lines that have passed. Not of `total`: a form with ten lines
        # of which six are N/A on this unit is 100% done when the other four pass, and showing 40%
        # there teaches people to ignore the number.
        "pct": (0 if not applicable else int(round(out[RESULT_PASS] * 100.0 / applicable))),
    }


def dossier_result(items):
    """The single word the minute's conclusion carries.

    FAIL wins over PENDING: a checklist with one failed line and three unchecked ones has already
    established that the work is not acceptable, and reporting "not checked" there would let a
    failure hide behind an incomplete form. An empty checklist is PENDING, never PASS."""
    p = checklist_progress(items)
    if p["fail"]:
        return RESULT_FAIL
    if p["pending"] or not p["applicable"]:
        return RESULT_PENDING
    return RESULT_PASS


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Defects — Điều 24 khoản 3, the punch list
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  Completion acceptance may carry outstanding items PROVIDED they do not affect load-bearing
#  capacity, safety in use, or the function of the works. That is not a severity scale — it is three
#  named consequences — so the register asks which of the three an open defect touches, and any one
#  of them blocks. A "Minor / Major / Critical" dropdown would have let somebody call a structural
#  crack "Major" and sign it off.

DEFECT_IMPACTS = [
    {"key": "structural", "vi": "Ảnh hưởng khả năng chịu lực", "en": "Affects load-bearing capacity",
     "blocks": True},
    {"key": "safety", "vi": "Ảnh hưởng an toàn sử dụng", "en": "Affects safety in use",
     "blocks": True},
    {"key": "function", "vi": "Ảnh hưởng công năng công trình", "en": "Affects the function of the works",
     "blocks": True},
    {"key": "cosmetic", "vi": "Hoàn thiện, mỹ quan — không ảnh hưởng ba yếu tố trên",
     "en": "Finish or appearance — none of the three above", "blocks": False},
]

BLOCKING_IMPACTS = {d["key"] for d in DEFECT_IMPACTS if d["blocks"]}


def defect_is_open(d):
    return str((d or {}).get("status") or "Open").strip().lower() not in ("closed", "đã đóng", "da dong")


def blocking_defects(defects):
    """Open defects that Điều 24(3) will not let you sign around."""
    return [d for d in defects or []
            if defect_is_open(d) and str((d or {}).get("impact") or "").strip().lower() in BLOCKING_IMPACTS]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  The gate
# ═══════════════════════════════════════════════════════════════════════════════════════════════

STATUS_DRAFT = "Draft"
STATUS_SUBMITTED = "Submitted"
STATUS_REVIEWED = "Reviewed"
STATUS_ACCEPTED = "Accepted"
STATUS_REJECTED = "Rejected"

STATUSES = [
    {"key": STATUS_DRAFT, "vi": "Đang lập", "en": "Draft", "hex": "#94a3b8"},
    {"key": STATUS_SUBMITTED, "vi": "Đã trình", "en": "Submitted", "hex": "#F59E0B"},
    {"key": STATUS_REVIEWED, "vi": "Đã kiểm tra", "en": "Reviewed", "hex": "#3168A8"},
    {"key": STATUS_ACCEPTED, "vi": "Đã nghiệm thu", "en": "Accepted", "hex": "#00B060"},
    {"key": STATUS_REJECTED, "vi": "Không đạt", "en": "Rejected", "hex": "#DC2626"},
]


def readiness(dossier, items, defects, accepted_types=(), signed_parties=()):
    """Everything standing between this dossier and an acceptance signature.

    Returns a list of {code, blocks, vi, en}. `blocks` False is a warning the screen shows and the
    signature ignores — the drafting genuinely says "where agreed", and a rule that hardens an
    agreement into a requirement stops real work for no legal reason.

      dossier         the header row
      items           its checklist lines
      defects         its punch list
      accepted_types  the type keys that ALREADY have an accepted dossier on this project
      signed_parties  the party keys already signed on this dossier

    Nothing here reads a clock or a database, so every branch is reachable from a test."""
    out = []
    t = acceptance_type(dossier.get("accType") if dossier else None)
    prog = checklist_progress(items)
    accepted = {str(k or "").strip().lower() for k in (accepted_types or ())}
    signed = {str(k or "").strip().lower() for k in (signed_parties or ())}

    def add(code, blocks, vi, en):
        out.append({"code": code, "blocks": blocks, "vi": vi, "en": en})

    # ── the checklist itself ──────────────────────────────────────────────────────────────────
    if not prog["total"]:
        add("no_checklist", True,
            "Hồ sơ chưa có mục kiểm tra nào — chọn biểu mẫu checklist trước khi nghiệm thu.",
            "The dossier has no checklist lines — attach a checklist form before accepting.")
    elif prog["pending"]:
        add("checklist_pending", True,
            "Còn %d mục chưa kiểm tra." % prog["pending"],
            "%d checklist line(s) have no result yet." % prog["pending"])
    if prog["fail"]:
        add("checklist_failed", True,
            "Có %d mục KHÔNG ĐẠT — không thể ký nghiệm thu đạt." % prog["fail"],
            "%d checklist line(s) FAILED — this cannot be signed as accepted." % prog["fail"])
    if prog["total"] and prog["applicable"] == 0:
        add("all_na", True,
            "Toàn bộ mục kiểm tra đều ghi Không áp dụng — biên bản không chứng minh điều gì.",
            "Every checklist line is marked N/A — the minute proves nothing.")

    # ── the punch list — Điều 24(3) ───────────────────────────────────────────────────────────
    # Split by INDEX, not by `d not in blocked`. Two punch-list rows can be equal dicts (same
    # description typed twice on two floors), and `in` compares by value — so the second copy of a
    # blocking defect would have been counted as an ordinary one and shown as a warning.
    _blocking_ix = {i for i, d in enumerate(defects or [])
                    if defect_is_open(d)
                    and str((d or {}).get("impact") or "").strip().lower() in BLOCKING_IMPACTS}
    blocked = [d for i, d in enumerate(defects or []) if i in _blocking_ix]
    if blocked:
        add("defects_blocking", True,
            "Còn %d tồn tại ảnh hưởng chịu lực, an toàn hoặc công năng (Điều 24 khoản 3)." % len(blocked),
            "%d open defect(s) affect load-bearing capacity, safety or function (Art. 24(3))." % len(blocked))
    open_other = [d for i, d in enumerate(defects or [])
                  if defect_is_open(d) and i not in _blocking_ix]
    if open_other:
        add("defects_open", False,
            "Còn %d tồn tại phải ghi vào phụ lục và ấn định thời hạn khắc phục." % len(open_other),
            "%d open defect(s) must be listed in the annex with a rectification date." % len(open_other))

    # ── the chain — Điều 24(2) / Validate Scope needs verified deliverables ───────────────────
    for req in (t or {}).get("requires", []):
        if req not in accepted:
            rt = acceptance_type(req) or {}
            add("requires_" + req, True,
                "Chưa có hồ sơ %s nào được nghiệm thu trên dự án này (%s)."
                % (str(rt.get("vi") or req).lower(), rt.get("law") or ""),
                "No %s has been accepted on this project yet (%s)."
                % (str(rt.get("en") or req).lower(), rt.get("law") or ""))
    for exp in (t or {}).get("expects", []):
        if exp not in accepted:
            et = acceptance_type(exp) or {}
            add("expects_" + exp, False,
                "Thường phải có %s trước bước này — xác nhận nếu dự án không áp dụng."
                % str(et.get("vi") or exp).lower(),
                "%s normally precedes this step — confirm if the project does not use one."
                % str(et.get("en") or exp))

    # ── external clearances — Điều 24(2) ──────────────────────────────────────────────────────
    #
    # Driven from the TYPE, never from the record's own array. Reading the list off the dossier
    # meant an empty `clearances: []` — an import, a stale row, or a browser that simply sent one —
    # satisfied the whole of Điều 24(2) by having nothing in it to check. The record supplies
    # EVIDENCE, not the list of what has to be evidenced.
    #
    # Turning one off is allowed and is often right: there are no lifts, so the lift inspection does
    # not apply. But a clearance that is ON by default is on because it applies to most works, so
    # switching it off is a decision and has to say why. One that is OFF by default ("only where
    # installed") needs no explanation for staying off.
    if (t or {}).get("clearances"):
        have = {str((c or {}).get("key") or ""): (c or {})
                for c in ((dossier or {}).get("clearances") or [])}
        for meta in CLEARANCES:
            c = have.get(meta["key"], {"applies": meta["applies"]})
            if not c.get("applies"):
                if meta["applies"] and not str(c.get("reason") or "").strip():
                    add("clearance_off_" + meta["key"], True,
                        "Đã bỏ %s — phải ghi lý do không áp dụng." % str(meta["vi"]).lower(),
                        "%s is switched off — record why it does not apply." % meta["en"])
                continue
            if not str(c.get("ref") or "").strip():
                add("clearance_" + meta["key"], True,
                    "Chưa có %s." % str(meta["vi"]).lower(),
                    "Missing: %s." % str(meta["en"]).lower())

    # ── the signature blocks ──────────────────────────────────────────────────────────────────
    # A minute issued with an empty signature block is the mistake this catches. The signature
    # itself is wet ink on the printed sheet; what the portal can check is that somebody is NAMED
    # to give it, before the form is printed and taken to site.
    for pk in required_parties((dossier or {}).get("accType")):
        if pk not in signed:
            pm = party(pk) or {}
            add("sign_" + pk, True,
                "Chưa ghi người ký của %s." % str(pm.get("vi") or pk),
                "No signatory named for the %s." % str(pm.get("en") or pk).lower())

    # ── the signed sheet itself ───────────────────────────────────────────────────────────────
    # An acceptance the register calls Accepted, with no scan of the minute everyone actually
    # signed, is a claim rather than a record. It is the first thing an audit asks for and the
    # commonest thing missing from a dossier assembled at the end of a job instead of as it went.
    if not str((dossier or {}).get("minuteFile") or (dossier or {}).get("minuteUrl") or "").strip():
        add("no_minute", True,
            "Chưa đính kèm bản scan biên bản đã ký.",
            "The scan of the signed minute has not been attached.")

    return out


def blockers(*a, **kw):
    """Just the refusals."""
    return [r for r in readiness(*a, **kw) if r["blocks"]]


def can_accept(*a, **kw):
    return not blockers(*a, **kw)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Seed checklist library
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  A STARTER set, not a complete one. A real MEP contractor's library runs to a hundred-odd forms
#  (PP-EL-201 … PP-HV-4xx) written against that contractor's ITP, and inventing them here would be
#  producing plausible checklists nobody wrote — which is worse than an empty library, because
#  somebody would sign one. So this seeds the shapes and the disciplines; the library screen imports
#  the project's own forms from CSV or JSON, and every form is editable in the app.
#
#  Each item: vi | en | method (how it is checked) | criteria (what it is judged against).

def _it(vi, en, method="", criteria=""):
    return {"vi": vi, "en": en, "method": method, "criteria": criteria}


FORM_LIBRARY = [
    {
        "code": "HML-OSM-001", "disc": "OSM",
        "vi": "Nghiệm thu vật tư, thiết bị đầu vào",
        "en": "Incoming material and equipment acceptance",
        "standard": "TCVN 4055:2012",
        "items": [
            _it("Chủng loại, quy cách đúng với vật tư được phê duyệt",
                "Type and specification match the approved material submittal",
                "Đối chiếu / Compare", "Material approval / submittal"),
            _it("Số lượng nhận đúng theo phiếu giao hàng",
                "Quantity received matches the delivery note", "Đếm / Count", "Delivery note"),
            _it("Có chứng chỉ xuất xứ (CO) và chứng nhận chất lượng (CQ)",
                "Certificate of origin and certificate of quality provided",
                "Kiểm tra hồ sơ / Document check", "NĐ 06/2021 Điều 12"),
            _it("Có kết quả thí nghiệm phù hợp tiêu chuẩn áp dụng",
                "Test results provided and conform to the applicable standard",
                "Kiểm tra hồ sơ / Document check", "Project specification"),
            _it("Tình trạng bao bì, nhãn mác nguyên vẹn, không hư hỏng khi vận chuyển",
                "Packaging and labelling intact, no transport damage", "Quan sát / Visual", "—"),
            _it("Hạn sử dụng còn hiệu lực (với vật tư có hạn dùng)",
                "Shelf life still valid (for materials that have one)", "Quan sát / Visual", "—"),
            _it("Điều kiện lưu kho tại công trường đáp ứng yêu cầu của nhà sản xuất",
                "Site storage conditions meet the manufacturer's requirement",
                "Quan sát / Visual", "Manufacturer's instruction"),
        ],
    },
    {
        "code": "HML-EL-201", "disc": "ELE",
        "vi": "Lắp đặt lỗ chờ, ống chờ sàn vách",
        "en": "Installation of slab / wall openings and sleeves",
        "standard": "TCVN 9207:2012",
        "items": [
            _it("Vị trí lỗ chờ, ống chờ đúng bản vẽ thi công được phê duyệt",
                "Opening and sleeve positions follow the approved shop drawing",
                "Đo / Measure", "Approved shop drawing"),
            _it("Cao độ và kích thước trong dung sai cho phép",
                "Level and dimensions within the permitted tolerance", "Đo / Measure", "±10 mm"),
            _it("Chủng loại và đường kính ống chờ đúng thiết kế",
                "Sleeve type and diameter as designed", "Đối chiếu / Compare", "Design"),
            _it("Ống chờ được cố định chắc chắn, không xê dịch khi đổ bê tông",
                "Sleeves fixed securely and will not move during the concrete pour",
                "Quan sát / Visual", "Method statement"),
            _it("Bịt đầu ống chống lọt vữa, bê tông",
                "Sleeve ends capped against mortar and concrete ingress", "Quan sát / Visual", "—"),
            _it("Không xung đột với cốt thép chịu lực; đã được kỹ sư kết cấu chấp thuận nếu có cắt thép",
                "No clash with structural reinforcement; structural engineer's approval where bars are cut",
                "Quan sát / Visual", "TCVN 4453:1995"),
            _it("Khoảng cách tới các hệ thống khác đáp ứng yêu cầu phối hợp",
                "Clearance to other services meets the coordination requirement",
                "Đo / Measure", "Coordinated drawing"),
            _it("Đã đánh dấu, ghi nhãn nhận biết tuyến",
                "Marked and labelled for route identification", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-EL-205", "disc": "ELE",
        "vi": "Lắp đặt thang cáp, máng cáp",
        "en": "Installation of cable tray and trunking",
        "standard": "TCVN 9207:2012",
        "items": [
            _it("Tuyến đi đúng bản vẽ thi công được phê duyệt",
                "Route as per the approved shop drawing", "Đối chiếu / Compare", "Approved shop drawing"),
            _it("Cao độ lắp đặt và độ thẳng, độ phẳng đạt yêu cầu",
                "Installation level, straightness and flatness acceptable", "Đo / Measure", "±5 mm / 3 m"),
            _it("Khoảng cách giá đỡ đúng chỉ dẫn của nhà sản xuất",
                "Support spacing follows the manufacturer's instruction", "Đo / Measure",
                "Manufacturer's instruction"),
            _it("Chủng loại, kích thước, lớp mạ đúng thiết kế",
                "Type, size and finish as designed", "Đối chiếu / Compare", "Design"),
            _it("Liên kết cơ khí chắc chắn, đủ bu lông, không biến dạng",
                "Mechanical joints sound, fully bolted, no distortion", "Quan sát / Visual", "—"),
            _it("Liên kết đẳng thế (nối đất) liên tục trên toàn tuyến",
                "Earth bonding continuous along the whole route",
                "Đo điện trở / Resistance test", "TCVN 9358:2012"),
            _it("Không có cạnh sắc gây hư hỏng vỏ cáp",
                "No sharp edges that could damage cable sheathing", "Quan sát / Visual", "—"),
            _it("Khoảng cách tới hệ thống khác và tới kết cấu đáp ứng yêu cầu",
                "Clearance to other services and to structure acceptable", "Đo / Measure",
                "Coordinated drawing"),
            _it("Xuyên tường, xuyên sàn đã chèn bịt chống cháy đúng cấp",
                "Wall and floor penetrations fire-stopped to the correct rating",
                "Quan sát / Visual", "QCVN 06:2022/BXD"),
            _it("Đã dán nhãn tuyến và mã hiệu",
                "Route labels and identification codes applied", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-EL-203", "disc": "ELE",
        "vi": "Lắp đặt dây, cáp điện",
        "en": "Installation of cables and wires",
        "standard": "TCVN 7447 / TCVN 9207:2012",
        "items": [
            _it("Chủng loại, tiết diện cáp đúng thiết kế",
                "Cable type and cross-section as designed", "Đối chiếu / Compare", "Design"),
            _it("Bán kính uốn không nhỏ hơn giá trị nhà sản xuất quy định",
                "Bending radius not less than the manufacturer's minimum", "Đo / Measure",
                "Manufacturer's instruction"),
            _it("Cáp được đỡ, buộc gọn, không chịu lực kéo tại đầu nối",
                "Cables supported and tied, no tension at terminations", "Quan sát / Visual", "—"),
            _it("Đầu cốt, đầu nối đúng chủng loại và được ép đúng dụng cụ",
                "Lugs and terminations of the correct type, crimped with the correct tool",
                "Quan sát / Visual", "Manufacturer's instruction"),
            _it("Đo điện trở cách điện đạt yêu cầu",
                "Insulation resistance test passed", "Thí nghiệm / Test", "TCVN 7447"),
            _it("Đo điện trở vòng lặp sự cố và thông mạch bảo vệ",
                "Earth-fault loop impedance and protective-conductor continuity verified",
                "Thí nghiệm / Test", "TCVN 7447"),
            _it("Thứ tự pha đúng và thống nhất toàn hệ thống",
                "Phase sequence correct and consistent across the system", "Thí nghiệm / Test", "—"),
            _it("Đánh số lõi, dán nhãn hai đầu cáp",
                "Cores numbered and both cable ends labelled", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-LT-101", "disc": "LTN",
        "vi": "Hệ thống nối đất và chống sét",
        "en": "Earthing and lightning protection system",
        "standard": "TCVN 9385:2012 / TCVN 9358:2012",
        "items": [
            _it("Vị trí kim thu sét, dây dẫn sét đúng thiết kế",
                "Air terminal and down-conductor positions as designed",
                "Đối chiếu / Compare", "Design"),
            _it("Số lượng và khoảng cách dây xuống đạt yêu cầu tiêu chuẩn",
                "Number and spacing of down conductors meet the standard",
                "Đo / Measure", "TCVN 9385:2012"),
            _it("Cọc tiếp địa đủ số lượng, đủ độ sâu",
                "Earth rods to the required number and depth", "Đo / Measure", "Design"),
            _it("Mối nối hàn hoá nhiệt / ép đạt yêu cầu, được bảo vệ chống ăn mòn",
                "Exothermic or compression joints sound and corrosion-protected",
                "Quan sát / Visual", "—"),
            _it("Điện trở nối đất đo được đạt giá trị thiết kế",
                "Measured earth resistance meets the design value", "Thí nghiệm / Test", "Design value"),
            _it("Có hộp kiểm tra tiếp địa, tiếp cận được để đo định kỳ",
                "Test box provided and accessible for periodic measurement",
                "Quan sát / Visual", "TCVN 9385:2012"),
            _it("Liên kết đẳng thế với kết cấu và các hệ thống kim loại",
                "Equipotential bonding to structure and metallic services",
                "Quan sát / Visual", "TCVN 9358:2012"),
        ],
    },
    {
        "code": "HML-FF-101", "disc": "FF",
        "vi": "Lắp đặt hệ thống chữa cháy tự động (sprinkler)",
        "en": "Installation of the automatic sprinkler system",
        "standard": "TCVN 7336:2021",
        "items": [
            _it("Tuyến ống, đường kính đúng bản vẽ được phê duyệt và được thẩm duyệt PCCC",
                "Pipe routes and diameters as per the approved and fire-authority-appraised drawing",
                "Đối chiếu / Compare", "Approved drawing"),
            _it("Chủng loại đầu phun, hệ số K và nhiệt độ tác động đúng thiết kế",
                "Sprinkler head type, K-factor and operating temperature as designed",
                "Đối chiếu / Compare", "TCVN 7336:2021"),
            _it("Khoảng cách đầu phun tới trần, tới tường và giữa các đầu đạt yêu cầu",
                "Head clearance to ceiling, to walls and between heads within limits",
                "Đo / Measure", "TCVN 7336:2021"),
            _it("Giá treo, gối đỡ đủ số lượng, đúng khoảng cách",
                "Hangers and supports to the required number and spacing", "Đo / Measure",
                "TCVN 7336:2021"),
            _it("Thử áp lực đường ống đạt yêu cầu, giữ áp đủ thời gian quy định",
                "Pipework pressure test passed and held for the specified duration",
                "Thí nghiệm / Test", "TCVN 7336:2021"),
            _it("Súc rửa đường ống trước khi đấu nối đầu phun",
                "Pipework flushed before sprinkler heads are fitted", "Quan sát / Visual", "—"),
            _it("Van chặn, van báo động, công tắc dòng chảy lắp đúng vị trí và hoạt động",
                "Control valves, alarm valves and flow switches correctly located and functional",
                "Thí nghiệm / Test", "TCVN 7336:2021"),
            _it("Chèn bịt chống cháy tại vị trí xuyên tường, xuyên sàn đúng cấp",
                "Fire-stopping at wall and floor penetrations to the correct rating",
                "Quan sát / Visual", "QCVN 06:2022/BXD"),
            _it("Sơn, nhãn nhận biết đường ống theo quy định",
                "Pipework painted and labelled as required", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-HV-101", "disc": "HVAC",
        "vi": "Lắp đặt ống gió và phụ kiện",
        "en": "Installation of ductwork and accessories",
        "standard": "TCVN 5687:2010",
        "items": [
            _it("Tuyến ống gió, kích thước đúng bản vẽ được phê duyệt",
                "Duct routes and sizes as per the approved drawing", "Đối chiếu / Compare",
                "Approved shop drawing"),
            _it("Vật liệu, chiều dày tôn đúng thiết kế",
                "Material and sheet thickness as designed", "Đo / Measure", "Design"),
            _it("Mối nối kín, gioăng đầy đủ, không rò rỉ nhìn thấy",
                "Joints sealed, gaskets complete, no visible leakage", "Quan sát / Visual", "—"),
            _it("Thử rò rỉ đường ống đạt cấp kín theo yêu cầu",
                "Duct leakage test achieves the required tightness class",
                "Thí nghiệm / Test", "Specification"),
            _it("Giá treo đủ số lượng, đúng khoảng cách, có đệm chống rung",
                "Hangers to the required number and spacing, with anti-vibration pads",
                "Đo / Measure", "Manufacturer's instruction"),
            _it("Bảo ôn đúng chủng loại, chiều dày, kín mạch hơi",
                "Insulation of the correct type and thickness, vapour barrier continuous",
                "Quan sát / Visual", "QCVN 09:2017/BXD"),
            _it("Van gió, van chặn lửa lắp đúng vị trí và thao tác được",
                "Dampers and fire dampers correctly located and operable",
                "Thí nghiệm / Test", "QCVN 06:2022/BXD"),
            _it("Cửa thăm vệ sinh bố trí tại các vị trí cần thiết",
                "Access doors provided where cleaning access is needed", "Quan sát / Visual", "—"),
            _it("Đã vệ sinh bên trong ống trước khi đóng trần",
                "Duct interior cleaned before the ceiling is closed", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-PL-101", "disc": "PLU",
        "vi": "Lắp đặt đường ống cấp nước bên trong",
        "en": "Installation of internal water supply pipework",
        "standard": "TCVN 4513:1988",
        "items": [
            _it("Tuyến ống, đường kính đúng bản vẽ được phê duyệt",
                "Pipe routes and diameters as per the approved drawing",
                "Đối chiếu / Compare", "Approved shop drawing"),
            _it("Vật liệu ống và phụ kiện đúng chủng loại được duyệt",
                "Pipe and fitting materials as approved", "Đối chiếu / Compare", "Material approval"),
            _it("Độ dốc, cao độ lắp đặt đạt yêu cầu",
                "Gradient and installation level acceptable", "Đo / Measure", "Design"),
            _it("Mối nối thực hiện đúng quy trình của nhà sản xuất",
                "Joints made to the manufacturer's procedure", "Quan sát / Visual",
                "Manufacturer's instruction"),
            _it("Giá đỡ đủ số lượng, đúng khoảng cách",
                "Supports to the required number and spacing", "Đo / Measure",
                "Manufacturer's instruction"),
            _it("Thử áp lực đạt yêu cầu và giữ áp đủ thời gian quy định",
                "Pressure test passed and held for the specified duration",
                "Thí nghiệm / Test", "Specification"),
            _it("Súc xả, khử trùng đường ống trước khi đưa vào sử dụng",
                "Pipework flushed and disinfected before use", "Thí nghiệm / Test",
                "QCVN 01-1:2018/BYT"),
            _it("Bảo ôn, chống đọng sương nơi yêu cầu",
                "Insulation and condensation control where required", "Quan sát / Visual", "—"),
            _it("Dán nhãn, đánh dấu hướng dòng chảy",
                "Labels applied and flow direction marked", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-CIV-101", "disc": "CIV",
        "vi": "Nghiệm thu cốt thép trước khi đổ bê tông",
        "en": "Reinforcement acceptance before concrete pour",
        "standard": "TCVN 4453:1995",
        "items": [
            _it("Chủng loại, đường kính thép đúng thiết kế",
                "Bar type and diameter as designed", "Đo / Measure", "Design"),
            _it("Số lượng, khoảng cách thanh thép đúng bản vẽ",
                "Bar count and spacing as per drawing", "Đo / Measure", "Design"),
            _it("Chiều dài neo, nối chồng đạt yêu cầu",
                "Anchorage and lap lengths acceptable", "Đo / Measure", "TCVN 4453:1995"),
            _it("Lớp bê tông bảo vệ đủ, con kê đủ số lượng và đúng chủng loại",
                "Concrete cover achieved; spacers of the correct type and number",
                "Đo / Measure", "TCVN 4453:1995"),
            _it("Thép sạch, không dính dầu mỡ, không rỉ vảy",
                "Bars clean, free of oil and loose rust scale", "Quan sát / Visual", "—"),
            _it("Ván khuôn kín khít, đúng kích thước, chống phình",
                "Formwork tight, to size, and braced against bulging", "Đo / Measure", "TCVN 4453:1995"),
            _it("Các chi tiết đặt sẵn, ống chờ MEP đã lắp và được nghiệm thu",
                "Cast-in items and MEP sleeves installed and already accepted",
                "Đối chiếu / Compare", "NĐ 06/2021 Điều 21"),
            _it("Vệ sinh trong ván khuôn trước khi đổ",
                "Formwork cleaned out before the pour", "Quan sát / Visual", "—"),
        ],
    },
    {
        "code": "HML-GEN-001", "disc": "GEN",
        "vi": "Biểu mẫu trống — tự soạn danh mục kiểm tra",
        "en": "Blank form — write your own checklist",
        "standard": "",
        "items": [
            _it("", "", "", ""),
        ],
    },
]


def form(code):
    c = str(code or "").strip().upper()
    return next((f for f in FORM_LIBRARY if f["code"].upper() == c), None)


def forms_for(disc_code):
    c = str(disc_code or "").strip().upper()
    return [f for f in FORM_LIBRARY if not c or f["disc"] == c]


def snapshot_items(form_row):
    """Copy a form's lines onto a dossier.

    A COPY, deliberately. The library is edited — a line is reworded, one is added when a standard
    changes — and a dossier signed last month must go on saying what was actually signed. Same
    reasoning as the estimating module's snapshot rates: the register is a live document, the
    signed record is not."""
    src = (form_row or {}).get("items") or []
    out = []
    for i, it in enumerate(src):
        out.append({
            "seq": i + 1,
            "textVi": (it or {}).get("vi") or "",
            "textEn": (it or {}).get("en") or "",
            "method": (it or {}).get("method") or "",
            "criteria": (it or {}).get("criteria") or "",
            "result": "",
            "note": "",
        })
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  The catalogue the browser asks for
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def catalogue():
    """Everything the acceptance screens need in order to render, in one payload. The law lives here
    and is served; it is not duplicated into the browser, where a second copy would drift."""
    return {
        "disciplines": DISCIPLINES,
        "types": ACCEPTANCE_TYPES,
        "parties": PARTIES,
        "statuses": STATUSES,
        "results": RESULTS,
        "clearances": CLEARANCES,
        "basis": BASIS_ROWS,
        "defectImpacts": DEFECT_IMPACTS,
        "standards": STANDARDS,
        "forms": [{k: v for k, v in f.items()} for f in FORM_LIBRARY],
        "numberTokens": NUMBER_TOKENS,
        "defaults": {"arf": DEFAULT_ARF_TEMPLATE, "ref": DEFAULT_REF_TEMPLATE},
        "note": {
            "vi": "Danh mục tiêu chuẩn dưới đây là gợi ý để điền nhanh, không phải căn cứ pháp lý. "
                  "Phiên bản tiêu chuẩn phải được QA/QC của dự án đối chiếu với danh mục hiện hành "
                  "trước khi ghi lên biên bản đã ký.",
            "en": "The standards list below is a fill-in suggestion, not an authority. The edition "
                  "must be checked by the project's QA/QC against the current list before it is "
                  "written on a signed minute.",
        },
    }
