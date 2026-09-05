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

The checklist CONTENT lives in acceptance_forms.py. This file is the law and stays small enough to
read in one sitting; that one is 97 forms and grows.
"""

import acceptance_forms

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
        # Every stage of the build takes materials, so naming one here would be wrong most of the
        # time. The DOSSIER carries the stage; the type does not presume it.
        "stage": "",
        "notice_days": 1,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Phiếu giao hàng', 'Chứng chỉ xuất xứ (CO)', 'Chứng nhận chất lượng (CQ)', 'Kết quả thí nghiệm của lô', 'Phiếu duyệt vật tư'],
        "evidence_en": ['Delivery note', 'Certificate of origin', 'Certificate of quality', 'Batch test results', 'Approved material submittal'],
        "attends_vi": 'Cán bộ kỹ thuật nhà thầu, tư vấn giám sát; đại diện chủ đầu tư khi vật tư chính.',
        "attends_en": 'Contractor engineer and supervision consultant; the client for principal materials.',
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
        # Likewise: work happens in every stage. Điều 21 does not care which one.
        "stage": "",
        "notice_days": 1,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Bản vẽ thi công được duyệt', 'Biện pháp thi công được duyệt', 'Biên bản nghiệm thu vật tư đầu vào liên quan', 'Kết quả thí nghiệm hiện trường', 'Ảnh chụp hiện trạng trước khi che khuất'],
        "evidence_en": ['Approved shop drawing', 'Approved method statement', 'Related incoming-material acceptance', 'Site test results', 'Photographs before covering up'],
        "attends_vi": 'Người phụ trách kỹ thuật thi công trực tiếp và người giám sát trực tiếp của chủ đầu tư.',
        "attends_en": "The contractor's person directly in charge and the client's direct supervisor.",
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
        "stage": "test_commission",
        "notice_days": 3,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Quy trình chạy thử được duyệt', 'Biên bản thí nghiệm từng hạng mục', 'Chứng chỉ hiệu chuẩn thiết bị đo', 'Bảng số liệu cân chỉnh (TAB)', 'Ma trận nguyên nhân — hệ quả đã thử'],
        "evidence_en": ['Approved commissioning procedure', 'Component test records', 'Instrument calibration certificates', 'Balancing (TAB) data sheets', 'Tested cause-and-effect matrix'],
        "attends_vi": 'Nhà thầu, tư vấn giám sát, chủ đầu tư; nhà sản xuất khi thiết bị chính.',
        "attends_en": 'Contractor, supervision consultant and client; the manufacturer for principal plant.',
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
        "stage": "structure",
        "notice_days": 3,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Danh mục biên bản nghiệm thu công việc thuộc giai đoạn', 'Kết quả thí nghiệm của giai đoạn', 'Bản vẽ hoàn công giai đoạn', 'Danh mục tồn tại chuyển tiếp'],
        "evidence_en": ['Schedule of work acceptances in the stage', 'Stage test results', 'Stage as-built drawings', 'Carried-forward punch list'],
        "attends_vi": 'Chỉ huy trưởng nhà thầu, tư vấn giám sát, đại diện BQLDA; giám sát tác giả khi cần.',
        "attends_en": "Contractor's site manager, supervision consultant, PMU; design supervision where needed.",
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
        "stage": "completion",
        "notice_days": 7,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Toàn bộ biên bản nghiệm thu công việc và giai đoạn', 'Kết quả thí nghiệm, chạy thử', 'Văn bản chấp thuận PCCC', 'Văn bản về bảo vệ môi trường', 'Bản vẽ hoàn công hạng mục', 'Quy trình vận hành và bảo trì', 'Danh mục tồn tại và thời hạn khắc phục'],
        "evidence_en": ['All work and stage acceptance minutes', 'Test and commissioning results', 'Fire-safety written acceptance', 'Environmental clearance', 'As-built drawings for the item', 'Operation and maintenance procedures', 'Punch list with rectification dates'],
        "attends_vi": 'Chủ đầu tư, tư vấn QLXD & giám sát, nhà thầu chính và các nhà thầu phụ liên quan.',
        "attends_en": 'Client, construction management and supervision consultant, main and relevant subcontractors.',
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
        "stage": "completion",
        "notice_days": 15,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Hồ sơ hoàn thành công trình theo danh mục', 'Toàn bộ biên bản nghiệm thu hạng mục', 'Thông báo kết quả kiểm tra công tác nghiệm thu của cơ quan chuyên môn', 'Văn bản chấp thuận PCCC và môi trường', 'Bản vẽ hoàn công toàn công trình', 'Kết quả quan trắc, kiểm định (nếu có)'],
        "evidence_en": ['The completion dossier per its schedule', 'All work-item acceptance minutes', "Construction authority's notice on the acceptance check", 'Fire-safety and environmental clearances', 'Complete as-built drawings', 'Monitoring and third-party inspection results where applicable'],
        "attends_vi": 'Chủ đầu tư, tư vấn QLXD & giám sát, nhà thầu thiết kế, nhà thầu thi công.',
        "attends_en": 'Client, construction management and supervision consultant, designer, contractor.',
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
        "stage": "handover",
        "notice_days": 15,   # convention, not law — a project agrees its own notice period
        "evidence_vi": ['Biên bản nghiệm thu hoàn thành công trình', 'Hồ sơ hoàn thành công trình', 'Quy trình vận hành, bảo trì và định mức bảo trì', 'Biên bản đào tạo vận hành', 'Danh mục vật tư dự phòng, dụng cụ chuyên dụng', 'Chỉ số công tơ, đồng hồ tại thời điểm bàn giao'],
        "evidence_en": ['Completion acceptance minute', 'The completion dossier', 'Operation, maintenance procedures and schedules', 'Operator training record', 'Spare parts and special tools schedule', 'Meter readings at handover'],
        "attends_vi": 'Chủ đầu tư, chủ quản lý sử dụng, nhà thầu thi công.',
        "attends_en": 'Client, the operating owner and the contractor.',
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
{
        "key": "warranty_end",
        "stage": "warranty",
        "notice_days": 30,   # convention, not law — a project agrees its own notice period
        "vi": "Nghiệm thu hết thời hạn bảo hành",
        "en": "End-of-warranty acceptance",
        "law": "Nghị định 06/2021/NĐ-CP, Điều 28",
        "pmbok": "Close Project or Phase (§4.7) — the last obligation to close",
        "proves_vi": "Hết thời hạn bảo hành, các tồn tại phát sinh đã được khắc phục và các bên "
                     "xác nhận để giải tỏa bảo đảm bảo hành.",
        "proves_en": "The warranty period has expired, defects arising have been rectified, and the "
                     "parties confirm so the warranty security can be released.",
        "evidence_vi": ["Biên bản bàn giao công trình", "Danh mục lỗi phát sinh trong thời gian bảo hành",
                        "Biên bản khắc phục từng lỗi", "Bảo lãnh bảo hành còn hiệu lực"],
        "evidence_en": ["Handover minute", "Schedule of defects arising during the warranty period",
                        "Rectification records for each", "The warranty security"],
        "attends_vi": "Chủ đầu tư, chủ quản lý sử dụng, nhà thầu thi công.",
        "attends_en": "Client, the operating owner and the contractor.",
        "parties": [PARTY_CONTRACTOR, PARTY_CLIENT],
        "requires": ["handover_deed"],
        "expects": [],
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
#  Giai đoạn thi công — the construction stages an acceptance belongs to
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  Điều 23 says stage acceptance happens "where the client and contractor agree it is needed, or
#  where the work will be covered up" — and then names no stages, because the stages of a warehouse
#  are not the stages of a hospital. So this is a DEFAULT SEQUENCE, not a rule: it is what the app
#  offers, what it groups the register by, and what it measures coverage against. A project renames,
#  merges or drops any of it.
#
#  What earns each stage its place is the second field, `covered`: whether work in it gets BUILT
#  OVER. That is the one thing about a stage the app can be firm on, because a concealed work
#  acceptance is the only kind that cannot be redone later — the alternative is opening the building
#  up. It is why the stage list exists at all rather than being a free-text label.
#
#  `types` is which acceptance types normally arise in the stage; `after` is the stage that normally
#  precedes it. Both advisory — see stage_warnings, which warns and never refuses. The refusals in
#  this module come from the ARTICLE, not from a sequence somebody drew.

STAGES = [
    {"key": "site", "no": 1, "covered": False,
     "vi": "Chuẩn bị mặt bằng, định vị công trình", "en": "Site preparation and setting out",
     "disc": ["CIV", "GEN"], "types": ["work"], "after": None,
     "note_vi": "Mốc chuẩn, tim trục và cao độ gốc — sai ở đây thì sai suốt công trình.",
     "note_en": "Benchmarks, grid lines and datum — an error here runs through the whole works."},

    {"key": "foundation", "no": 2, "covered": True,
     "vi": "Móng và phần ngầm", "en": "Foundations and substructure",
     "disc": ["CIV", "OSM"], "types": ["material", "work", "stage"], "after": "site",
     "note_vi": "Cọc, đài, giằng và chống thấm phần ngầm bị lấp — nghiệm thu trước khi che khuất.",
     "note_en": "Piles, caps, beams and tanking are buried — accept before they are covered."},

    {"key": "structure", "no": 3, "covered": True,
     "vi": "Kết cấu phần thân", "en": "Superstructure",
     "disc": ["CIV", "OSM"], "types": ["material", "work", "stage"], "after": "foundation",
     "note_vi": "Cốt thép và chi tiết đặt sẵn bị bê tông phủ kín; ảnh chụp trước khi đổ là bắt buộc.",
     "note_en": "Reinforcement and cast-ins vanish under concrete; photographs before the pour are not optional."},

    {"key": "mep_rough", "no": 4, "covered": True,
     "vi": "Cơ điện đi ngầm, trong kết cấu", "en": "MEP first fix / rough-in",
     "disc": ["ELE", "ELV", "FF", "HVAC", "PLU", "LTN"], "types": ["work"], "after": "structure",
     "note_vi": "Ống chờ, ống luồn và tuyến ngầm bị trát, đổ hoặc lấp — đây là giai đoạn dễ mất "
                "bằng chứng nhất của cả dự án.",
     "note_en": "Sleeves, conduits and buried runs are plastered, poured or backfilled over — the "
                "stage where evidence is most easily lost on any project."},

    {"key": "envelope", "no": 5, "covered": True,
     "vi": "Bao che, mái và chống thấm", "en": "Envelope, roofing and waterproofing",
     "disc": ["CIV", "ARC"], "types": ["work", "stage"], "after": "structure",
     "note_vi": "Chống thấm bị lát, ốp hoặc đắp phủ; ngâm nước thử phải xong trước lớp bảo vệ.",
     "note_en": "Waterproofing is tiled, clad or screeded over; flood testing must finish before the protection layer."},

    {"key": "mep_plant", "no": 6, "covered": False,
     "vi": "Lắp đặt thiết bị chính", "en": "Main plant installation",
     "disc": ["ELE", "HVAC", "PLU", "FF"], "types": ["material", "work"], "after": "mep_rough",
     "note_vi": "Máy phát, chiller, bơm, tủ điện — nghiệm thu lắp đặt trước khi chạy thử.",
     "note_en": "Generators, chillers, pumps, switchboards — installation accepted before commissioning."},

    {"key": "finishes", "no": 7, "covered": False,
     "vi": "Hoàn thiện kiến trúc", "en": "Architectural finishes",
     "disc": ["ARC"], "types": ["work", "stage"], "after": "envelope",
     "note_vi": "Trát, ốp lát, sơn, trần, cửa — phần lớn tồn tại của dự án phát sinh ở đây.",
     "note_en": "Plaster, tiling, paint, ceilings, doors — where most of a project's punch list comes from."},

    {"key": "mep_terminal", "no": 8, "covered": False,
     "vi": "Cơ điện thiết bị đầu cuối", "en": "MEP second fix / terminals",
     "disc": ["ELE", "ELV", "FF", "HVAC", "PLU"], "types": ["work"], "after": "finishes",
     "note_vi": "Đèn, ổ cắm, miệng gió, đầu phun, thiết bị vệ sinh — phối hợp với trần và hoàn thiện.",
     "note_en": "Lights, outlets, diffusers, sprinkler heads, sanitaryware — coordinated with ceilings and finishes."},

    {"key": "external", "no": 9, "covered": True,
     "vi": "Hạ tầng ngoài nhà, sân đường", "en": "External works and infrastructure",
     "disc": ["CIV", "ELE", "PLU"], "types": ["work", "stage"], "after": "structure",
     "note_vi": "Cống, tuyến cáp ngầm và các lớp kết cấu áo đường bị lấp trước khi hoàn thiện mặt.",
     "note_en": "Drains, buried cable routes and pavement layers are covered before the surface goes on."},

    {"key": "test_commission", "no": 10, "covered": False,
     "vi": "Thí nghiệm, chạy thử và cân chỉnh", "en": "Testing, commissioning and balancing",
     "disc": ["ELE", "ELV", "FF", "HVAC", "PLU", "LTN"], "types": ["commission"], "after": "mep_terminal",
     "note_vi": "Chạy thử không tải rồi có tải, cân chỉnh TAB, thử liên động — điều kiện của Điều 24.",
     "note_en": "No-load then on-load runs, TAB balancing, interlock testing — Điều 24's precondition."},

    {"key": "authority", "no": 11, "covered": False,
     "vi": "Nghiệm thu của cơ quan quản lý nhà nước", "en": "Statutory and authority acceptance",
     "disc": ["FF", "GEN"], "types": ["commission", "handover_part"], "after": "test_commission",
     "note_vi": "PCCC, môi trường và kiểm tra công tác nghiệm thu của cơ quan chuyên môn về xây dựng. "
                "Thời gian chờ văn bản thường dài hơn dự kiến — bắt đầu sớm.",
     "note_en": "Fire safety, environment and the construction authority's check. The wait for the "
                "written acceptance is routinely longer than planned — start early."},

    {"key": "completion", "no": 12, "covered": False,
     "vi": "Nghiệm thu hoàn thành", "en": "Completion acceptance",
     "disc": ["GEN"], "types": ["handover_part", "handover_all"], "after": "authority",
     "note_vi": "Hạng mục rồi toàn công trình. Tồn tại còn lại phải không ảnh hưởng chịu lực, "
                "an toàn và công năng.",
     "note_en": "Work items, then the whole works. Remaining items must affect neither strength, "
                "safety nor function."},

    {"key": "handover", "no": 13, "covered": False,
     "vi": "Bàn giao đưa vào sử dụng", "en": "Handover into use",
     "disc": ["GEN"], "types": ["handover_deed"], "after": "completion",
     "note_vi": "Hồ sơ hoàn thành, quy trình vận hành bảo trì, đào tạo và thời hạn bảo hành.",
     "note_en": "The completion dossier, O&M procedures, training and the warranty period."},

    {"key": "warranty", "no": 14, "covered": False,
     "vi": "Bảo hành và hết hạn bảo hành", "en": "Warranty and end of warranty",
     "disc": ["GEN"], "types": ["warranty_end"], "after": "handover",
     "note_vi": "Nghị định 06/2021 Điều 28. Hết thời hạn, các bên xác nhận và giải tỏa bảo lãnh.",
     "note_en": "Decree 06/2021 Art. 28. At the end of the period the parties confirm and the "
                "warranty security is released."},
]

STAGE_KEYS = [s["key"] for s in STAGES]


def stage(key):
    k = str(key or "").strip().lower()
    return next((s for s in STAGES if s["key"] == k), None)


def stages_for(disc_code):
    """The stages a discipline actually appears in. What the plan screen offers an electrician, so
    they are not scrolling past foundations and finishes to find first fix."""
    c = str(disc_code or "").strip().upper()
    if not c:
        return list(STAGES)
    return [s for s in STAGES if c in s["disc"]] or list(STAGES)


def is_covered_stage(key):
    """Does work in this stage get built over?

    The one fact about a stage the app is firm on. A concealed work acceptance is the only kind that
    cannot be redone — the alternative is opening the building up — so the screen says so, loudly,
    while there is still something to look at."""
    s = stage(key)
    return bool(s and s["covered"])


def stage_warnings(dossier, accepted_stage_keys=()):
    """Advisory notes about WHERE in the build this dossier sits. Never blocking: Điều 23 leaves the
    stages to agreement, and a sequence the app drew is not grounds to refuse a signature.

    Returns the same {code, blocks, vi, en} shape `readiness` uses, so a caller can concatenate them
    without knowing which list a note came from."""
    out = []
    s = stage((dossier or {}).get("stage"))
    if not s:
        return out
    done = {str(k or "").strip().lower() for k in (accepted_stage_keys or ())}

    if s["covered"]:
        out.append({
            "code": "stage_covered", "blocks": False,
            "vi": "Công việc giai đoạn này sẽ bị che khuất. Chụp ảnh hiện trạng và đính kèm bản vẽ "
                  "đánh dấu trước khi cho phép che lấp — không có cách nào kiểm tra lại sau đó.",
            "en": "Work in this stage gets covered up. Photograph it and attach a marked-up drawing "
                  "before permission to cover is given — there is no way to check it afterwards.",
        })
    prev = s.get("after")
    if prev and prev not in done:
        p = stage(prev) or {}
        out.append({
            "code": "stage_after_" + prev, "blocks": False,
            "vi": "Giai đoạn “%s” thường hoàn tất trước giai đoạn này." % (p.get("vi") or prev),
            "en": "Stage “%s” normally completes before this one." % (p.get("en") or prev),
        })
    t = (dossier or {}).get("accType")
    if t and s.get("types") and t not in s["types"]:
        tt = acceptance_type(t) or {}
        out.append({
            "code": "stage_type_unusual", "blocks": False,
            "vi": "“%s” không phải loại nghiệm thu thường gặp ở giai đoạn “%s” — xác nhận nếu đúng ý."
                  % (tt.get("vi") or t, s["vi"]),
            "en": "“%s” is not the usual acceptance type for stage “%s” — confirm if intended."
                  % (tt.get("en") or t, s["en"]),
        })
    return out


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

    # ── where in the build this sits ──────────────────────────────────────────────────────────
    # Advisory by construction: Điều 23 leaves the stages to agreement between the client and the
    # contractor, so a sequence this app drew is not grounds to refuse anybody's signature.
    out.extend(stage_warnings(dossier, (dossier or {}).get("_stagesDone") or ()))

    # ── the checklist's provenance ────────────────────────────────────────────────────────────
    # A shipped form is a DRAFT written against the standard it names, not a transcription of an
    # approved ITP. Nothing refuses a dossier for using one — that would make the library useless
    # on day one — but the person about to sign is told, on the same panel as everything else,
    # that these lines have not been through the project's QA/QC.
    if (dossier or {}).get("formCode") and not (dossier or {}).get("formAdopted"):
        add("form_not_adopted", False,
            "Biểu mẫu %s là bản mẫu đi kèm phần mềm, chưa được QA/QC dự án soát xét và ban hành. "
            "Nhận về dự án, rà soát rồi đánh dấu đã duyệt trước khi dùng cho hồ sơ ký chính thức."
            % (dossier or {}).get("formCode"),
            "Form %s is a template shipped with the portal — not reviewed or issued by this "
            "project's QA/QC. Adopt it into the project, review it, and mark it approved before it "
            "carries a signed minute." % (dossier or {}).get("formCode"))

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
#  The checklist library
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  97 forms, civil through detailed MEP, in acceptance_forms.py. Re-exported here so every caller
#  keeps asking one module the question "what forms are there" — the content moved, the surface did
#  not.
#
#  Every shipped form carries `adopted: False`. They are drafts written against the standards they
#  name, not transcriptions of an approved ITP, and the difference has to be visible to whoever is
#  about to sign one. `adoption_warning` below is what puts it on the screen; a project adopts a
#  form by copying it in, reviewing it, and saying so.

FORM_LIBRARY = acceptance_forms.LIBRARY
LIBRARY_COUNTS = acceptance_forms.counts


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
        "stages": STAGES,
        "counts": LIBRARY_COUNTS(),
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


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Coverage — what is left to accept
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  The question a project manager asks weekly and currently answers by counting: of everything the
#  ITP said would be inspected, and everything the WBS says will be delivered, how much has actually
#  been accepted?
#
#  THE HONESTY PROBLEM, AND WHY THIS IS BUILT THE WAY IT IS
#
#  Nothing joins a dossier to the ITP it satisfies. The tempting fix is to match them by name — the
#  dossier says "Lắp đặt thang máng cáp" and so does ITP 47, so call it covered. That produces a
#  number that is confidently wrong: it silently pairs the tray acceptance on level 2 with the ITP
#  for level 5, reports 80% coverage, and the first anybody knows is when the consultant asks for
#  the missing minutes.
#
#  So: coverage is computed from EXPLICIT LINKS only. A dossier covers an ITP when somebody said it
#  does. Name similarity produces a SUGGESTION, offered for one-click confirmation and never
#  applied on its own.
#
#  And the count of unlinked dossiers is returned beside every figure, because it is the figure's
#  own error bar. Ninety per cent coverage computed from links, with forty dossiers linked to
#  nothing, is not ninety per cent — it is an unknown number, and the screen has to say so rather
#  than draw a green bar. `trust` below is that statement.

COV_ACCEPTED = "accepted"      # at least one accepted dossier against it
COV_OPEN = "open"              # dossiers exist, none accepted yet
COV_CALLED = "called"          # an inspection was called, no dossier compiled
COV_NONE = "none"              # nothing at all


def _fold(v):
    """Accent- and case-insensitive, matching the browser's _accFold and the pm_ registers'
    _pmFold. Used for SUGGESTIONS only — never for a figure anybody reports."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(v or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.replace("đ", "d").split())


def _acc_state(dossiers):
    if any(str(d.get("status") or "").strip().lower() == "accepted" for d in dossiers):
        return COV_ACCEPTED
    return COV_OPEN if dossiers else COV_NONE


def coverage(itps=(), deliverables=(), dossiers=(), plans=(), today=""):
    """What has been accepted, against what was planned to be.

    Every argument is a plain list of rows; nothing here reads a database or a clock, so the whole
    thing is exercised from tests/test_acceptance.py.

      itps          pm_quality_itp rows — the inspections the ITP planned
      deliverables  pm_deliverables rows — the WBS packages
      dossiers      pm_acc rows
      plans         pm_acc_plans rows — inspections called
      today         'YYYY-MM-DD', for the overdue flag. Empty means do not judge lateness at all,
                    which is the honest answer when the caller has not said what day it is.
    """
    by_itp, by_wbs, by_stage = {}, {}, {}
    unlinked_dos, unlinked_plans = [], []

    for d in dossiers or ():
        i, w = str(d.get("itpId") or ""), str(d.get("deliverableId") or "")
        if i:
            by_itp.setdefault(i, []).append(d)
        if w:
            by_wbs.setdefault(w, []).append(d)
        if not i and not w:
            unlinked_dos.append(d)
        st = str(d.get("stage") or "").strip().lower()
        if st:
            by_stage.setdefault(st, []).append(d)

    plans_by_itp = {}
    for p in plans or ():
        i = str(p.get("itpId") or "")
        if i:
            plans_by_itp.setdefault(i, []).append(p)
        elif not str(p.get("dossierId") or ""):
            unlinked_plans.append(p)

    def rows_for(src, key_id, label_fields, bucket, plan_bucket=None):
        out = []
        for r in src or ():
            rid = str(r.get("id") or "")
            mine = bucket.get(rid, [])
            called = (plan_bucket or {}).get(rid, [])
            state = _acc_state(mine)
            if state == COV_NONE and called:
                state = COV_CALLED
            due = str(r.get("plannedFinish") or r.get("dueDate") or r.get("finish") or "")[:10]
            out.append({
                "id": rid,
                "no": str(r.get(key_id) or "").strip(),
                "title": next((str(r.get(f) or "") for f in label_fields if r.get(f)), ""),
                "discipline": str(r.get("discipline") or ""),
                "due": due,
                "state": state,
                "dossiers": len(mine),
                "accepted": len([d for d in mine
                                 if str(d.get("status") or "").strip().lower() == "accepted"]),
                "called": len(called),
                # Late only when the caller SAID what day it is. A missing date is not a reason to
                # call something on time, and it is not a reason to call it late either.
                "overdue": bool(today and due and due < today and state != COV_ACCEPTED),
                "refs": [str(d.get("refNo") or d.get("id") or "") for d in mine][:6],
            })
        return out

    itp_rows = rows_for(itps, "itpNo", ("title", "name"), by_itp, plans_by_itp)
    wbs_rows = rows_for(deliverables, "wbs", ("name", "title"), by_wbs)

    def tally(rows):
        t = {COV_ACCEPTED: 0, COV_OPEN: 0, COV_CALLED: 0, COV_NONE: 0}
        for r in rows:
            t[r["state"]] += 1
        return {"total": len(rows), "accepted": t[COV_ACCEPTED], "open": t[COV_OPEN],
                "called": t[COV_CALLED], "none": t[COV_NONE],
                "overdue": len([r for r in rows if r["overdue"]]),
                "pct": (0 if not rows else int(round(t[COV_ACCEPTED] * 100.0 / len(rows))))}

    stage_rows = []
    for s in STAGES:
        mine = by_stage.get(s["key"], [])
        stage_rows.append({
            "key": s["key"], "no": s["no"], "vi": s["vi"], "en": s["en"], "covered": s["covered"],
            "dossiers": len(mine),
            "accepted": len([d for d in mine
                             if str(d.get("status") or "").strip().lower() == "accepted"]),
        })
    # Dossiers naming a stage this app does not know — an import, or a stage somebody renamed.
    # Counted rather than dropped: a row that vanishes from a coverage screen is the worst kind.
    _known = {s["key"] for s in STAGES}
    stage_unknown = sum(len(v) for k, v in by_stage.items() if k not in _known)
    stage_none = len([d for d in (dossiers or ()) if not str(d.get("stage") or "").strip()])

    total_dos = len(dossiers or ())
    linked = total_dos - len(unlinked_dos)
    return {
        "itp": dict(tally(itp_rows), rows=itp_rows),
        "wbs": dict(tally(wbs_rows), rows=wbs_rows),
        "stages": stage_rows,
        "stageUnknown": stage_unknown,
        "stageNotStated": stage_none,
        "unlinkedDossiers": len(unlinked_dos),
        "unlinkedPlans": len(unlinked_plans),
        "trust": _coverage_trust(total_dos, linked, len(itps or ()), len(deliverables or ())),
    }


def _coverage_trust(total_dossiers, linked, n_itp, n_wbs):
    """Can the percentages above be believed, and if not, why not.

    This is not a caveat bolted onto a number — it is the number's error bar, and it decides what
    the screen is allowed to draw. A coverage bar over a register where nothing is linked is a
    picture of an assumption."""
    pct = 0 if not total_dossiers else int(round(linked * 100.0 / total_dossiers))
    if not n_itp and not n_wbs:
        return {"level": "none", "linkedPct": pct,
                "vi": "Chưa có ITP hay hạng mục WBS nào để đối chiếu. Lập kế hoạch ITP ở tab Chất "
                      "lượng, hoặc khai báo hạng mục ở tab Phạm vi, rồi quay lại đây.",
                "en": "There is no ITP or WBS package to measure against. Plan ITPs on the Quality "
                      "tab, or set up packages on the Scope tab, then come back."}
    if not total_dossiers:
        return {"level": "empty", "linkedPct": 0,
                "vi": "Chưa lập hồ sơ nghiệm thu nào — số liệu dưới đây là điểm xuất phát, không "
                      "phải kết quả.",
                "en": "No acceptance dossier has been compiled yet — the figures below are a "
                      "starting point, not a result."}
    if pct == 100:
        return {"level": "full", "linkedPct": 100,
                "vi": "Mọi hồ sơ đều đã gắn với ITP hoặc hạng mục WBS, nên các tỷ lệ dưới đây phản "
                      "ánh đúng thực tế.",
                "en": "Every dossier is linked to an ITP or a WBS package, so the percentages below "
                      "say what they appear to say."}
    if pct >= 60:
        lvl = "partial"
    else:
        lvl = "low"
    return {
        "level": lvl, "linkedPct": pct,
        "vi": "Mới %d%% số hồ sơ được gắn với ITP hoặc hạng mục WBS. Các hồ sơ chưa gắn KHÔNG được "
              "tính vào tỷ lệ dưới đây, nên độ phủ thực tế cao hơn con số hiển thị — gắn hết rồi "
              "hãy dùng số này để báo cáo." % pct,
        "en": "Only %d%% of dossiers are linked to an ITP or a WBS package. Unlinked dossiers are "
              "NOT counted below, so real coverage is higher than the figure shown — link them "
              "before reporting this number." % pct,
    }


def suggest_links(itps=(), dossiers=(), limit=60):
    """Candidate dossier→ITP pairings, with the reason each is suggested.

    Offered for confirmation, NEVER applied. Two rules, strongest first:

      `number`   the ITP's number appears verbatim in the dossier's reference, title or job
                 description. Somebody typed it; that is close to a statement of intent.
      `title`    same discipline AND the folded titles match exactly. Weaker — two floors of the
                 same tray run produce identical titles — so it is offered only when exactly ONE
                 ITP in that discipline has that title, and it is offered as a suggestion, which is
                 the whole point of not doing this automatically.
    """
    out = []
    linked = {str(d.get("itpId") or "") for d in dossiers or ()}
    free = [d for d in (dossiers or ()) if not str(d.get("itpId") or "")]
    if not free:
        return out

    by_title = {}
    for t in itps or ():
        key = (str(t.get("discipline") or "").upper(), _fold(t.get("title") or t.get("name")))
        by_title.setdefault(key, []).append(t)

    for d in free:
        hay = _fold(" ".join(str(d.get(k) or "") for k in
                             ("refNo", "title", "titleEn", "jobDescription", "note")))
        hit, why = None, ""
        for t in itps or ():
            no = _fold(t.get("itpNo"))
            # A bare "1" matches everything; require something with substance to it.
            if no and len(no) >= 3 and no in hay:
                hit, why = t, "number"
                break
        if hit is None:
            key = (str(d.get("discipline") or "").upper(), _fold(d.get("title")))
            same = by_title.get(key) or []
            if len(same) == 1:
                hit, why = same[0], "title"
        if hit is None:
            continue
        out.append({
            "dossierId": str(d.get("id") or ""), "dossierRef": str(d.get("refNo") or ""),
            "dossierTitle": str(d.get("title") or ""),
            "itpId": str(hit.get("id") or ""), "itpNo": str(hit.get("itpNo") or ""),
            "itpTitle": str(hit.get("title") or hit.get("name") or ""),
            "why": why,
            "alreadyLinkedElsewhere": str(hit.get("id") or "") in linked,
        })
        if len(out) >= limit:
            break
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  Thư mời nghiệm thu — the invitation, and who it goes to
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  Điều 21 requires the client's supervisor to be present when a work is accepted, and Điều 24 adds
#  the client for a completion. Neither says how you invite them, and in practice it is an email
#  sent by hand the evening before — which is exactly the step that gets forgotten, and the one a
#  consultant points at when they say they were never told.
#
#  Two things this module is careful about.
#
#  FIRST, it never reports sending to nobody. An invitation with an empty recipient list is not a
#  sent invitation; it is silence that looks like success, and the project only finds out when the
#  consultant does not turn up. So `notice_plan` returns the reasons it CANNOT send, the same shape
#  `readiness` uses, and the caller refuses on them.
#
#  SECOND, the addresses are not people's portal accounts. The supervision consultant and the
#  client are external — they have no login here — so their contacts are project configuration, and
#  a party with no contact recorded is a blocker with a name rather than a silently skipped row.

EMAIL_RE = None   # compiled lazily; see _valid_email


def _valid_email(a):
    """Good enough to catch a typo and a pasted name, not an RFC implementation.

    Deliberately permissive: an over-strict pattern rejects addresses that work, and the cost of a
    false reject here is somebody being unable to invite the consultant at all."""
    global EMAIL_RE
    if EMAIL_RE is None:
        import re as _re
        EMAIL_RE = _re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
    return bool(EMAIL_RE.match(str(a or "").strip()))


def parse_contacts(raw):
    """A party's contacts, from whatever the settings screen stored.

    Accepts a list of {name, email}, a list of plain addresses, or one comma/semicolon/newline
    separated string — because all three are what a person pasting from Outlook actually produces,
    and losing their addresses to a shape mismatch is not a lesson anybody should have to learn."""
    out, seen = [], set()

    def add(name, email):
        e = str(email or "").strip().strip("<>")
        if not e or e.lower() in seen:
            return
        seen.add(e.lower())
        out.append({"name": str(name or "").strip(), "email": e, "valid": _valid_email(e)})

    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, (list, tuple)):
        for c in raw:
            if isinstance(c, dict):
                add(c.get("name"), c.get("email"))
            else:
                add("", c)
        return out
    for chunk in str(raw or "").replace(";", ",").replace("\n", ",").split(","):
        c = chunk.strip()
        if not c:
            continue
        # "Trần Văn B <b@ricons.vn>" — the shape Outlook copies out.
        if "<" in c and ">" in c:
            add(c[:c.index("<")], c[c.index("<") + 1:c.index(">")])
            continue
        # "Trần Văn B b@ricons.vn" — the SAME paste after the settings sanitiser has stripped the
        # angle brackets, which it does because they could be markup. Found by saving a real pasted
        # contact list: the address was left glued to the name, failed validation, and the party
        # still counted as reachable because a second address on the line was fine. The invitation
        # would have gone out with a named recipient silently missing.
        bits = c.split()
        if len(bits) > 1 and _valid_email(bits[-1]):
            add(" ".join(bits[:-1]), bits[-1])
            continue
        add("", c)
    return out


def notice_recipients(acc_type, contacts):
    """Who an invitation for this kind of acceptance goes to, party by party.

    The parties come from the acceptance TYPE — the same list that decides whose signature the
    minute must carry — so the people invited and the people who have to sign can never drift
    apart. The contractor is included: on a real site the person who called the inspection is not
    always the person who has to be at it.
    """
    out = []
    for pk in required_parties(acc_type):
        meta = party(pk) or {}
        people = parse_contacts((contacts or {}).get(pk))
        out.append({"key": pk, "vi": meta.get("vi", pk), "en": meta.get("en", pk),
                    "people": people,
                    "ok": bool([p for p in people if p["valid"]])})
    return out


def notice_plan(row, acc_type, contacts, sender=""):
    """Everything the caller needs to decide whether this invitation can go out.

    Returns {to, cc, parties, blocked} where `blocked` is the familiar
    {code, blocks, vi, en} shape. Nothing here sends anything or reads a clock.
    """
    row = row or {}
    parties = notice_recipients(acc_type, contacts)
    blocked = []

    def stop(code, vi, en):
        blocked.append({"code": code, "blocks": True, "vi": vi, "en": en})

    # The contractor is invited but is US — an invitation that cannot reach our own site engineer
    # is a nuisance, not a reason to leave the consultant uninvited.
    externals = [p for p in parties if p["key"] != PARTY_CONTRACTOR]
    for p in externals:
        if not p["people"]:
            stop("no_contact_" + p["key"],
                 "Chưa khai báo địa chỉ email của %s — vào tab Đánh số & các bên để bổ sung."
                 % p["vi"],
                 "No email address recorded for the %s — add one on the Numbering & parties tab."
                 % p["en"].lower())
        else:
            # ANY unreadable entry stops the send, not only a party with none readable. The weaker
            # rule ("is there at least one good address") let an invitation go out to one of the
            # consultant's two people with nothing said about the other — whoever typed the list
            # believes both were invited, and the one who was not is the one who complains.
            bad = [x["email"] for x in p["people"] if not x["valid"]]
            if bad:
                stop("bad_contact_" + p["key"],
                     "Địa chỉ email của %s không đọc được: %s. Sửa hoặc xóa dòng này — nếu để "
                     "nguyên, người đó sẽ không nhận được thư mời." % (p["vi"], ", ".join(bad)),
                     "This %s address cannot be read: %s. Fix or remove it — left as it is, that "
                     "person is not invited." % (p["en"].lower(), ", ".join(bad)))

    if not str(row.get("acceptDate") or "").strip():
        stop("no_date", "Chưa có ngày nghiệm thu — thư mời phải nêu rõ ngày.",
             "No acceptance date — an invitation has to state the day.")
    if not str(row.get("timeFrom") or "").strip():
        stop("no_time", "Chưa có giờ bắt đầu.", "No start time.")
    if not str(row.get("location") or "").strip():
        stop("no_place", "Chưa có vị trí nghiệm thu — thư mời phải nêu rõ địa điểm.",
             "No location — an invitation has to state where.")
    if not str(row.get("title") or "").strip():
        stop("no_work", "Chưa có tên công việc nghiệm thu.", "The work to be inspected is not named.")
    if sender is not None and not str(sender or "").strip():
        stop("no_sender",
             "Chưa cấu hình hộp thư gửi thư mời — quản trị viên đặt trong phần Cài đặt duyệt.",
             "No mailbox is configured to send from — an administrator sets one in the approval settings.")

    to = [x["email"] for p in externals for x in p["people"] if x["valid"]]
    cc = [x["email"] for p in parties if p["key"] == PARTY_CONTRACTOR
          for x in p["people"] if x["valid"]]
    return {"to": to, "cc": cc, "parties": parties, "blocked": blocked}


def notice_rows(row, acc_type, project=None, settings=None):
    """The invitation's particulars, in the order a consultant reads them.

    Bilingual pairs, so the email says everything twice rather than picking a language for a reader
    the app has never met."""
    row, project, settings = row or {}, project or {}, settings or {}
    t = acceptance_type(acc_type) or {}
    d = discipline(row.get("discipline")) or {}
    st = stage(row.get("stage")) or {}
    when = str(row.get("acceptDate") or "")
    hours = " – ".join([x for x in (row.get("timeFrom"), row.get("timeTo")) if x])
    out = [
        ("Dự án / Project", project.get("name") or ""),
        ("Gói thầu / Package", project.get("package") or project.get("scope") or ""),
        ("Số phiếu mời / Invitation No.", row.get("arfNo") or row.get("refNo") or ""),
        ("Loại nghiệm thu / Kind", "%s / %s" % (t.get("vi") or "", t.get("en") or "")),
        ("Căn cứ / Legal basis", t.get("law") or ""),
        ("Bộ môn / Discipline", "%s — %s" % (d.get("code") or "", d.get("vi") or "")),
        ("Hạng mục / Work", row.get("title") or ""),
        ("", row.get("titleEn") or ""),
        ("Ngày / Date", when),
        ("Giờ / Time", hours),
        ("Vị trí / Location", row.get("location") or ""),
        ("Trục / Axis – Zone", row.get("axis") or ""),
        ("Tiêu chuẩn / Standard", row.get("standardRef") or ""),
        ("Biểu mẫu / Checklist form", row.get("formCode") or ""),
    ]
    if st:
        out.append(("Giai đoạn / Stage", "%s / %s" % (st.get("vi") or "", st.get("en") or "")))
    return [(k, v) for k, v in out if str(v or "").strip()]
