# -*- coding: utf-8 -*-
"""Danh mục hồ sơ hoàn thành công trình — the completion dossier's table of contents.

Nghị định 06/2021/NĐ-CP Điều 26 requires the completed-works dossier to be assembled and kept, and
its Phụ lục VIb lists what goes in it. That list is what a client's handover meeting works through
line by line, and what the construction authority asks for under Điều 25. Assembling it at the end
of a job, from memory and a shared drive, is where projects lose weeks.

WHAT THE PORTAL MAY AND MAY NOT CLAIM

Half of this list is inside the app. The acceptance minutes, the material acceptances, the
commissioning records, the punch lists and the statutory clearances are all registers this module
already governs, and their counts are FACTS — a row saying "47 biên bản nghiệm thu công việc" is
evidence, and clicking it lands on the 47.

The other half is not. Contracts, design approvals, survey reports, the as-built drawings, the O&M
manuals — the portal has never seen any of them. For those the index records a DECLARATION: a named
person stating on a date that the document exists and where it is.

Those two things must never look the same on a screen somebody signs off from. A tick that means
"the register contains this" and a tick that means "somebody said so" carry completely different
weight at an audit, and an index that rendered them identically would be the single most misleading
artefact this whole module could produce. So `source` is on every row, the totals are reported
separately, and the printed sheet prints the distinction.

ON THE LIST ITSELF

The structure below is the standard four-part shape of Phụ lục VIb. Which rows a given project
actually needs depends on its class of works, its funding and its contract, and that is a judgement
for the project — so every row can be marked not-applicable with a recorded reason, exactly the way
the Điều 24 clearances work. Nothing here refuses anything.

Pure module: no database, no request, no clock.
"""

# who is expected to hold the original
H_CLIENT = "client"
H_CONTRACTOR = "contractor"
H_CONSULTANT = "consultant"
H_DESIGNER = "designer"

HOLDERS = [
    {"key": H_CLIENT, "vi": "Chủ đầu tư", "en": "Client"},
    {"key": H_CONTRACTOR, "vi": "Nhà thầu thi công", "en": "Contractor"},
    {"key": H_CONSULTANT, "vi": "Tư vấn giám sát", "en": "Supervision consultant"},
    {"key": H_DESIGNER, "vi": "Nhà thầu thiết kế", "en": "Designer"},
]

# how a row is satisfied
SRC_REGISTER = "register"      # counted from a register this app governs — a fact
SRC_DECLARED = "declared"      # somebody states it exists and says where — a claim

PARTS = [
    {"key": "I", "vi": "Hồ sơ chuẩn bị đầu tư xây dựng và hợp đồng",
     "en": "Investment preparation and contracts"},
    {"key": "II", "vi": "Hồ sơ khảo sát xây dựng, thiết kế xây dựng công trình",
     "en": "Site investigation and design"},
    {"key": "III", "vi": "Hồ sơ quản lý chất lượng thi công xây dựng công trình",
     "en": "Construction quality management"},
    {"key": "IV", "vi": "Hồ sơ quản lý, vận hành, bảo trì và bảo hành",
     "en": "Operation, maintenance and warranty"},
]


def _I(no, part, vi, en, holder, source=SRC_DECLARED, reg="", required=True, note_vi="", note_en=""):
    return {"no": no, "part": part, "vi": vi, "en": en, "holder": holder,
            "source": source, "reg": reg, "required": required,
            "note_vi": note_vi, "note_en": note_en}


ITEMS = [
    # ── I · chuẩn bị đầu tư và hợp đồng ───────────────────────────────────────────────────────
    _I("I.1", "I", "Quyết định chủ trương đầu tư, quyết định phê duyệt dự án",
       "Investment policy decision and project approval decision", H_CLIENT),
    _I("I.2", "I", "Văn bản chấp thuận của cơ quan quản lý nhà nước có thẩm quyền về quy hoạch, "
                   "đấu nối hạ tầng kỹ thuật",
       "Authority approvals on planning and utility connections", H_CLIENT),
    _I("I.3", "I", "Giấy phép xây dựng (đối với công trình phải có giấy phép)",
       "Construction permit, where one is required", H_CLIENT, required=False,
       note_vi="Chỉ áp dụng với công trình thuộc đối tượng phải cấp phép.",
       note_en="Only for works that require a permit."),
    _I("I.4", "I", "Hồ sơ đền bù, giải phóng mặt bằng, giao đất, cho thuê đất",
       "Compensation, site clearance and land allocation records", H_CLIENT, required=False),
    _I("I.5", "I", "Hợp đồng xây dựng: tư vấn, thi công, cung cấp thiết bị và các phụ lục",
       "Construction contracts — consultancy, works, equipment supply — and their annexes", H_CLIENT),
    _I("I.6", "I", "Bảo lãnh thực hiện hợp đồng, bảo lãnh tạm ứng, bảo hiểm công trình",
       "Performance and advance-payment securities, works insurance", H_CLIENT),

    # ── II · khảo sát và thiết kế ─────────────────────────────────────────────────────────────
    _I("II.1", "II", "Nhiệm vụ khảo sát và báo cáo kết quả khảo sát xây dựng",
       "Site investigation brief and report", H_DESIGNER),
    _I("II.2", "II", "Văn bản thông báo chấp thuận nghiệm thu kết quả khảo sát xây dựng",
       "Written acceptance of the site investigation result", H_CLIENT),
    _I("II.3", "II", "Nhiệm vụ thiết kế và hồ sơ thiết kế các bước",
       "Design brief and the design at each stage", H_DESIGNER),
    _I("II.4", "II", "Văn bản thẩm định, thẩm tra thiết kế xây dựng",
       "Design appraisal and third-party review", H_CLIENT),
    _I("II.5", "II", "Quyết định phê duyệt thiết kế xây dựng công trình",
       "Design approval decision", H_CLIENT),
    _I("II.6", "II", "Hồ sơ thiết kế bản vẽ thi công đã được chủ đầu tư đóng dấu phê duyệt",
       "Shop drawings stamped approved by the client", H_DESIGNER),
    _I("II.7", "II", "Văn bản thẩm duyệt thiết kế về phòng cháy chữa cháy",
       "Fire-safety design appraisal", H_CLIENT, required=False,
       note_vi="Với công trình thuộc đối tượng thẩm duyệt về PCCC.",
       note_en="For works subject to fire-safety design appraisal."),

    # ── III · quản lý chất lượng thi công — where the portal actually holds the evidence ──────
    _I("III.1", "III", "Danh mục thay đổi thiết kế trong quá trình thi công",
       "Schedule of design changes during construction", H_CONSULTANT),
    _I("III.2", "III", "Bản vẽ hoàn công",
       "As-built drawings", H_CONTRACTOR,
       note_vi="Bản vẽ hoàn công là tài liệu riêng, không phải bản vẽ ghi chú kèm biên bản nghiệm "
               "thu — phần mềm không thay thế được và không tự đếm mục này.",
       note_en="As-builts are their own document, not the marked-up drawings attached to acceptance "
               "minutes. The portal does not hold them and does not count this row."),
    _I("III.3", "III", "Kế hoạch, biện pháp kiểm tra, kiểm soát chất lượng thi công (ITP)",
       "Inspection and test plans", H_CONTRACTOR,
       source=SRC_REGISTER, reg="itp"),
    _I("III.4", "III", "Chứng chỉ xuất xứ, chứng nhận chất lượng và kết quả thí nghiệm vật liệu, "
                       "cấu kiện, thiết bị",
       "Certificates of origin and quality, and test results for materials and equipment",
       H_CONTRACTOR, source=SRC_REGISTER, reg="acc:material"),
    _I("III.5", "III", "Kết quả quan trắc, đo đạc, thí nghiệm trong quá trình thi công",
       "Monitoring, survey and testing results during construction", H_CONTRACTOR),
    _I("III.6", "III", "Nhật ký thi công xây dựng công trình",
       "Construction site diary", H_CONTRACTOR),
    _I("III.7", "III", "Biên bản nghiệm thu công việc xây dựng",
       "Work acceptance minutes", H_CONTRACTOR,
       source=SRC_REGISTER, reg="acc:work",
       note_vi="Nghị định 06/2021 Điều 21.", note_en="Decree 06/2021 Art. 21."),
    _I("III.8", "III", "Biên bản nghiệm thu giai đoạn thi công hoặc bộ phận công trình",
       "Stage or part-of-works acceptance minutes", H_CONTRACTOR,
       source=SRC_REGISTER, reg="acc:stage", required=False,
       note_vi="Nghị định 06/2021 Điều 23 — khi các bên thỏa thuận là cần thiết.",
       note_en="Decree 06/2021 Art. 23 — where the parties agree one is needed."),
    _I("III.9", "III", "Kết quả thí nghiệm, hiệu chỉnh, vận hành chạy thử không tải và có tải",
       "Testing, adjusting and no-load / on-load trial run results", H_CONTRACTOR,
       source=SRC_REGISTER, reg="acc:commission"),
    _I("III.10", "III", "Biên bản nghiệm thu hoàn thành hạng mục công trình, công trình xây dựng",
       "Completion acceptance minutes for work items and for the works", H_CLIENT,
       source=SRC_REGISTER, reg="acc:handover_part+handover_all",
       note_vi="Nghị định 06/2021 Điều 24.", note_en="Decree 06/2021 Art. 24."),
    _I("III.11", "III", "Phụ lục các tồn tại cần sửa chữa, khắc phục",
       "Annex of outstanding items to be rectified", H_CLIENT,
       source=SRC_REGISTER, reg="defects", required=False,
       note_vi="Nghị định 06/2021 Điều 24 khoản 3 — chỉ có khi còn tồn tại tại thời điểm nghiệm thu.",
       note_en="Decree 06/2021 Art. 24(3) — only where items remain open at acceptance."),
    _I("III.12", "III", "Văn bản chấp thuận kết quả nghiệm thu về phòng cháy chữa cháy, bảo vệ "
                        "môi trường và các văn bản khác theo quy định",
       "Fire-safety, environmental and other statutory acceptances", H_CLIENT,
       source=SRC_REGISTER, reg="clearances"),
    _I("III.13", "III", "Thông báo kết quả kiểm tra công tác nghiệm thu của cơ quan chuyên môn "
                        "về xây dựng",
       "Construction authority's notice on its check of the acceptance", H_CLIENT,
       source=SRC_REGISTER, reg="clearance:authority_check", required=False,
       note_vi="Nghị định 06/2021 Điều 24 khoản 2 và Điều 25 — với công trình thuộc đối tượng kiểm tra.",
       note_en="Decree 06/2021 Arts. 24(2) and 25 — for works that attract the check."),
    _I("III.14", "III", "Hồ sơ giải quyết sự cố công trình (nếu có)",
       "Records of any construction incident and its resolution", H_CLIENT, required=False),

    # ── IV · vận hành, bảo trì, bảo hành ──────────────────────────────────────────────────────
    _I("IV.1", "IV", "Quy trình vận hành, khai thác công trình",
       "Operating procedures for the works", H_CONTRACTOR,
       note_vi="Nghị định 06/2021 Điều 27.", note_en="Decree 06/2021 Art. 27."),
    _I("IV.2", "IV", "Quy trình bảo trì và định mức bảo trì công trình",
       "Maintenance procedures and schedules", H_CONTRACTOR),
    _I("IV.3", "IV", "Tài liệu hướng dẫn vận hành, bảo dưỡng thiết bị (O&M)",
       "Equipment operation and maintenance manuals", H_CONTRACTOR),
    _I("IV.4", "IV", "Biên bản đào tạo vận hành cho chủ quản lý sử dụng",
       "Operator training record for the operating owner", H_CONTRACTOR),
    _I("IV.5", "IV", "Danh mục vật tư dự phòng, dụng cụ chuyên dụng bàn giao",
       "Spare parts and special tools handed over", H_CONTRACTOR, required=False),
    _I("IV.6", "IV", "Biên bản bàn giao công trình đưa vào sử dụng",
       "Handover minute", H_CLIENT,
       source=SRC_REGISTER, reg="acc:handover_deed",
       note_vi="Luật Xây dựng Điều 124.", note_en="Law on Construction Art. 124."),
    _I("IV.7", "IV", "Cam kết bảo hành và bảo lãnh bảo hành công trình",
       "Warranty undertaking and warranty security", H_CONTRACTOR,
       note_vi="Nghị định 06/2021 Điều 28.", note_en="Decree 06/2021 Art. 28."),
]

ITEM_NOS = [i["no"] for i in ITEMS]


def item(no):
    n = str(no or "").strip().upper()
    return next((i for i in ITEMS if i["no"].upper() == n), None)


def part(key):
    k = str(key or "").strip().upper()
    return next((p for p in PARTS if p["key"] == k), None)


def holder(key):
    k = str(key or "").strip().lower()
    return next((h for h in HOLDERS if h["key"] == k), None)


# ── the states a row can be in ───────────────────────────────────────────────────────────────────
ST_HELD = "held"          # counted in a register, or declared present
ST_MISSING = "missing"    # required, and neither counted nor declared
ST_NA = "na"              # the project says it does not apply, with a reason
ST_OPTIONAL = "optional"  # not required and not present — nothing to chase


def _count(reg, ctx):
    """How many documents a register-backed row actually has behind it.

    Reads the assembled context rather than a database, so this function is the whole reason the
    index can be tested: every count below is derivable from four plain lists."""
    if not reg:
        return 0
    if reg == "itp":
        return len(ctx.get("itps") or ())
    if reg == "defects":
        return len(ctx.get("openDefects") or ())
    if reg == "clearances":
        return len(ctx.get("clearances") or ())
    if reg.startswith("clearance:"):
        want = reg.split(":", 1)[1]
        return len([c for c in (ctx.get("clearances") or ()) if c.get("key") == want])
    if reg.startswith("acc:"):
        want = set(reg.split(":", 1)[1].split("+"))
        return len([d for d in (ctx.get("accepted") or ())
                    if str(d.get("accType") or "").strip().lower() in want])
    return 0


def build_index(items_state=(), accepted=(), itps=(), open_defects=(), clearances=()):
    """The completion dossier's table of contents, with what the portal can actually vouch for.

      items_state   pm_acc_index rows — the project's declarations, keyed by item number
      accepted      accepted pm_acc dossiers
      itps          pm_quality_itp rows
      open_defects  outstanding punch-list items across the project
      clearances    the evidenced statutory clearances gathered off completion dossiers

    Returns rows in Phụ lục order plus a summary that keeps COUNTED and DECLARED apart, because a
    tick meaning "the register contains this" and a tick meaning "somebody said so" are not the
    same evidence and must not be added together.
    """
    ctx = {"accepted": list(accepted or ()), "itps": list(itps or ()),
           "openDefects": list(open_defects or ()), "clearances": list(clearances or ())}
    by_no = {str(r.get("no") or "").strip().upper(): r for r in (items_state or ())}

    rows, counted, declared, missing, na = [], 0, 0, 0, 0
    for it in ITEMS:
        st = by_no.get(it["no"].upper(), {})
        applies = st.get("applies")
        n = _count(it["reg"], ctx) if it["source"] == SRC_REGISTER else 0
        ref = str(st.get("ref") or "").strip()
        # A declaration is only a declaration when somebody NAMED made it. A ref typed with no
        # signature is a note, and counting it would be the app inventing an attestation.
        said = bool(st.get("declared") and str(st.get("declaredBy") or "").strip())

        if applies is False:
            state = ST_NA
        elif it["source"] == SRC_REGISTER:
            state = ST_HELD if n else (ST_MISSING if it["required"] else ST_OPTIONAL)
        else:
            state = ST_HELD if said else (ST_MISSING if it["required"] else ST_OPTIONAL)

        if state == ST_HELD:
            if it["source"] == SRC_REGISTER:
                counted += 1
            else:
                declared += 1
        elif state == ST_MISSING:
            missing += 1
        elif state == ST_NA:
            na += 1

        rows.append(dict(it, state=state, count=n, ref=ref,
                         declaredBy=str(st.get("declaredBy") or ""),
                         declaredOn=str(st.get("declaredOn") or ""),
                         naReason=str(st.get("naReason") or ""),
                         note=str(st.get("note") or "")))

    total_required = len([r for r in rows if r["required"] and r["state"] != ST_NA])
    return {
        "parts": PARTS, "holders": HOLDERS, "rows": rows,
        "summary": {
            "total": len(rows), "counted": counted, "declared": declared,
            "missing": missing, "na": na, "required": total_required,
            "held": counted + declared,
        },
        "verdict": _index_verdict(counted, declared, missing, rows),
    }


def _index_verdict(counted, declared, missing, rows):
    """What this index is, in one sentence, before anybody prints it.

    The distinction it insists on: counted rows are evidence the app can produce on demand; declared
    rows are somebody's word. Both belong in the dossier; only one of them is something the portal
    can stand behind, and a sheet that blurred them would be the most misleading thing this module
    could put on paper."""
    gaps = [r["no"] for r in rows if r["state"] == ST_MISSING]
    # The counted / declared split belongs on BOTH verdicts. It is tempting to say it only on a
    # complete index — the moment before printing — but somebody reading a half-filled one is
    # deciding what to chase, and "eight of these ticks are somebody's word" changes that decision.
    split_vi = ("Trong đó %d mục do phần mềm đếm trực tiếp từ sổ đăng ký, %d mục là lời xác nhận "
                "của người phụ trách." % (counted, declared))
    split_en = ("Of what is present, %d are counted directly from the registers and %d are "
                "somebody's declaration." % (counted, declared))
    if missing:
        _more = "…" if len(gaps) > 8 else ""
        return {
            "level": "incomplete", "missing": gaps,
            "vi": "Còn %d mục bắt buộc chưa có: %s. Hồ sơ hoàn thành chưa đủ để bàn giao theo "
                  "Nghị định 06/2021 Điều 26. %s"
                  % (missing, ", ".join(gaps[:8]) + _more, split_vi),
            "en": "%d required item(s) are still missing: %s. The completion dossier is not yet "
                  "ready to hand over under Decree 06/2021 Art. 26. %s"
                  % (missing, ", ".join(gaps[:8]) + _more, split_en),
        }
    return {
        "level": "complete", "missing": [],
        "vi": "Đủ mục theo danh mục. %d mục được phần mềm đếm trực tiếp từ sổ đăng ký; %d mục do "
              "người phụ trách xác nhận là đã có — phần này là lời xác nhận, không phải bằng chứng "
              "phần mềm tự kiểm tra được." % (counted, declared),
        "en": "Every listed item is accounted for. %d are counted directly from the registers; %d "
              "are somebody's declaration that the document exists — that half is an attestation, "
              "not something the portal verified." % (counted, declared),
    }
