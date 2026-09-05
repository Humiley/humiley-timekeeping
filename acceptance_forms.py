# -*- coding: utf-8 -*-
"""The checklist library — civil through to detailed MEP.

WHAT THESE ARE, AND WHAT THEY ARE NOT

Every form below is a DRAFT written against the standard it names. Not one of them has been through
a project's QA/QC, and none is a transcription of an approved Inspection and Test Plan. That
distinction is the whole reason `adopted` exists further down: a form stays marked un-adopted until
somebody on the project reviews it and says so, and a dossier compiled from an un-adopted form
carries a warning that reaches the readiness panel.

The alternative — shipping these as though they were approved — is the failure this module was
written to avoid twice over. A checklist that LOOKS authoritative gets signed, and a signature
against a line nobody reviewed is worse than an empty library, because an empty library makes
somebody go and find the real one.

So the contract with whoever uses this is:

  · these give you the SHAPE and the coverage — the eighty per cent of an ITP that is the same on
    every project, in both languages, with the method and the acceptance criterion beside each line;
  · your QA/QC adds what is specific to this contract, deletes what does not apply, corrects the
    editions, and ADOPTS it. That act is recorded;
  · a project's own imported form always wins over the one shipped here.

ON THE STANDARDS CITED

Only editions I could state with confidence are pinned to a year (see acceptance.STANDARDS and the
note it carries). Where a form covers work whose Vietnamese standard I could not name precisely, it
cites the discipline-level standard or the project specification rather than a number invented to
look complete. A wrong TCVN number on a signed minute is a finding at audit; "theo chỉ dẫn kỹ thuật
của dự án" is not.

Kept separate from acceptance.py on purpose. That module is the LAW — the articles, the chain, the
gate — and it is small enough to read in one sitting. This is content, and content grows.
"""

# ── the four things a checklist line says ────────────────────────────────────────────────────────
M_V = "Quan sát / Visual"
M_M = "Đo / Measure"
M_T = "Thí nghiệm / Test"
M_D = "Kiểm tra hồ sơ / Document"
M_C = "Đối chiếu / Compare"
M_F = "Chạy thử / Functional"
M_W = "Chứng kiến / Witness"

# Criteria that recur. Written once so a change is one edit, and so the register can be searched for
# every line judged against the same thing.
C_DWG = "Bản vẽ thi công được duyệt / Approved shop drawing"
C_SPEC = "Chỉ dẫn kỹ thuật dự án / Project specification"
C_MFR = "Hướng dẫn nhà sản xuất / Manufacturer's instruction"
C_MS = "Biện pháp thi công được duyệt / Approved method statement"
C_SUB = "Vật tư được phê duyệt / Approved material submittal"


def F(code, disc, vi, en, std, *items):
    """One form. Items are (vi, en[, method[, criteria]]) — the trailing two are optional because a
    genuinely self-evident line should not be padded with ceremony to fit the shape."""
    return {
        "code": code, "disc": disc, "vi": vi, "en": en, "standard": std,
        "items": [{"vi": i[0], "en": i[1],
                   "method": i[2] if len(i) > 2 else "",
                   "criteria": i[3] if len(i) > 3 else ""} for i in items],
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  OSM · Nghiệm thu vật tư, thiết bị đầu vào — Nghị định 06/2021 Điều 12
# ═══════════════════════════════════════════════════════════════════════════════════════════════

OSM = [
    F("OSM-001", "OSM", "Vật tư, thiết bị đầu vào — chung", "Incoming material and equipment — general",
      "NĐ 06/2021 Điều 12",
      ("Chủng loại, quy cách đúng vật tư đã được phê duyệt", "Type and specification match the approved submittal", M_C, C_SUB),
      ("Số lượng nhận đúng phiếu giao hàng", "Quantity received matches the delivery note", M_M, "Phiếu giao hàng / Delivery note"),
      ("Có chứng chỉ xuất xứ (CO)", "Certificate of origin provided", M_D, "NĐ 06/2021 Điều 12"),
      ("Có chứng nhận chất lượng (CQ) của nhà sản xuất", "Manufacturer's certificate of quality provided", M_D, "NĐ 06/2021 Điều 12"),
      ("Có kết quả thí nghiệm phù hợp tiêu chuẩn áp dụng", "Test results conform to the applicable standard", M_D, C_SPEC),
      ("Nhãn mác, mã hiệu lô hàng rõ ràng, truy xuất được", "Labels and batch marks legible and traceable", M_V),
      ("Bao bì nguyên vẹn, không hư hỏng do vận chuyển", "Packaging intact, no transport damage", M_V),
      ("Hạn sử dụng còn hiệu lực", "Shelf life still valid", M_V),
      ("Điều kiện lưu kho tại công trường đáp ứng yêu cầu", "Site storage conditions meet the requirement", M_V, C_MFR),
      ("Vật tư không đạt được tách riêng và ghi nhãn loại bỏ", "Rejected material segregated and marked", M_V, "NĐ 06/2021 Điều 12")),

    F("OSM-002", "OSM", "Xi măng", "Cement", "TCVN 2682 / TCVN 6260",
      ("Loại và mác xi măng đúng thiết kế", "Cement type and grade as designed", M_C, C_SUB),
      ("Ngày sản xuất, lô hàng ghi rõ trên bao", "Production date and batch marked on the bag", M_V),
      ("Không vón cục, không ẩm", "No lumps, not damp", M_V),
      ("Kho chứa khô ráo, kê cao khỏi nền", "Store dry and raised off the floor", M_V),
      ("Có kết quả thí nghiệm cường độ của lô", "Strength test result for the batch provided", M_D),
      ("Thời gian đông kết, độ mịn đạt yêu cầu", "Setting time and fineness within limits", M_T)),

    F("OSM-003", "OSM", "Cốt liệu — cát, đá", "Aggregate — sand and stone", "TCVN 7570",
      ("Nguồn cung cấp đúng nguồn đã được chấp thuận", "Source as approved", M_C, C_SUB),
      ("Cỡ hạt, cấp phối đạt yêu cầu", "Particle size and grading within limits", M_T, "TCVN 7572"),
      ("Hàm lượng bùn, bụi, sét trong giới hạn", "Silt, dust and clay content within limits", M_T, "TCVN 7572"),
      ("Không lẫn tạp chất hữu cơ", "Free of organic impurities", M_T),
      ("Độ ẩm được xác định trước khi trộn", "Moisture content determined before batching", M_T),
      ("Bãi chứa có phân khu, thoát nước tốt", "Stockpile segregated and well drained", M_V)),

    F("OSM-004", "OSM", "Thép cốt bê tông", "Steel reinforcement", "TCVN 1651",
      ("Mác thép, đường kính đúng thiết kế", "Steel grade and diameter as designed", M_C, C_DWG),
      ("Có CO, CQ và kết quả thí nghiệm kéo, uốn của từng lô", "CO, CQ and tensile/bend test per batch", M_D, "TCVN 1651"),
      ("Sai lệch đường kính trong dung sai cho phép", "Diameter tolerance within limits", M_M, "TCVN 1651"),
      ("Bề mặt sạch, không rỉ vảy, không dính dầu mỡ", "Surface clean, no loose scale, no oil", M_V),
      ("Không cong vênh, không nứt, không khuyết tật", "No distortion, cracks or defects", M_V),
      ("Xếp kê cách mặt đất, có che chắn", "Stacked off the ground and covered", M_V)),

    F("OSM-005", "OSM", "Bê tông thương phẩm", "Ready-mixed concrete", "TCVN 4453:1995",
      ("Cấp phối và mác bê tông đúng thiết kế", "Mix design and grade as designed", M_D, C_DWG),
      ("Phiếu giao hàng ghi giờ trộn, giờ đến, khối lượng", "Ticket states batching time, arrival time and volume", M_D),
      ("Thời gian vận chuyển trong giới hạn cho phép", "Transit time within the permitted limit", M_M, C_SPEC),
      ("Độ sụt đo tại hiện trường đạt yêu cầu", "Slump measured on site within limits", M_T, "TCVN 3106"),
      ("Nhiệt độ bê tông trong giới hạn", "Concrete temperature within limits", M_M, C_SPEC),
      ("Lấy mẫu đúc mẫu thử theo tần suất quy định", "Test cubes/cylinders cast at the required frequency", M_T, "TCVN 3105"),
      ("Không thêm nước tại hiện trường", "No water added on site", M_W, "TCVN 4453:1995")),

    F("OSM-006", "OSM", "Cáp điện, dây dẫn", "Cables and wires", "TCVN 6612 / TCVN 5935",
      ("Chủng loại, tiết diện, số lõi đúng thiết kế", "Type, cross-section and core count as designed", M_C, C_DWG),
      ("Có CO, CQ và biên bản thử nghiệm xuất xưởng", "CO, CQ and factory test report provided", M_D),
      ("Nhãn in trên vỏ cáp đầy đủ, đọc được", "Sheath printing complete and legible", M_V),
      ("Cuộn cáp nguyên vẹn, hai đầu được bịt kín", "Drum intact, both ends sealed", M_V),
      ("Đo điện trở cách điện trước khi lắp đặt", "Insulation resistance measured before installation", M_T, "TCVN 7447"),
      ("Chiều dài cuộn đúng phiếu giao", "Drum length matches the delivery note", M_M)),

    F("OSM-007", "OSM", "Ống và phụ kiện cơ điện", "MEP pipes and fittings", C_SPEC,
      ("Vật liệu, áp lực danh định, đường kính đúng thiết kế", "Material, pressure rating and diameter as designed", M_C, C_DWG),
      ("Có CO, CQ; ống chịu áp có chứng chỉ thử áp xuất xưởng", "CO, CQ; pressure pipe carries a works pressure certificate", M_D),
      ("Đầu ống được bịt, ren và mặt bích không hư hỏng", "Pipe ends capped; threads and flanges undamaged", M_V),
      ("Không móp, xước sâu, biến dạng", "No dents, deep scratches or distortion", M_V),
      ("Đánh dấu chủng loại còn nguyên trên thân ống", "Type marking intact on the pipe body", M_V),
      ("Phụ kiện, gioăng đồng bộ với ống", "Fittings and gaskets compatible with the pipe", M_C, C_MFR)),

    F("OSM-008", "OSM", "Thiết bị PCCC đầu vào", "Incoming fire-protection equipment", "TCVN 3890:2023",
      ("Chủng loại đúng hồ sơ thẩm duyệt PCCC", "Type matches the fire-authority appraised design", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Có giấy chứng nhận kiểm định phương tiện PCCC", "Fire-equipment inspection certificate provided", M_D, "TCVN 3890:2023"),
      ("Còn hạn kiểm định", "Inspection certificate still valid", M_D),
      ("Nhãn, mã hiệu, thông số kỹ thuật đầy đủ", "Labels, model and rating complete", M_V),
      ("Nguyên vẹn, không han rỉ, không móp", "Intact, no corrosion or dents", M_V),
      ("Số lượng đúng danh mục được duyệt", "Quantity matches the approved schedule", M_M)),

    F("OSM-009", "OSM", "Thiết bị cơ khí, máy đóng gói sẵn", "Packaged mechanical plant", C_MFR,
      ("Model, công suất, thông số đúng bảng thiết bị được duyệt", "Model, capacity and rating as per the approved schedule", M_C, C_SUB),
      ("Có bảng thông số xuất xưởng và biên bản thử nghiệm", "Factory data sheet and test report provided", M_D),
      ("Vỏ máy, sơn phủ nguyên vẹn", "Casing and paint finish intact", M_V),
      ("Đủ phụ kiện, tài liệu O&M và danh mục phụ tùng", "Accessories, O&M manual and spare-part list complete", M_D),
      ("Chân đế, gối đỡ, giảm chấn đi kèm đúng chủng loại", "Bases, supports and vibration isolators as specified", M_V),
      ("Bảo quản, che chắn trong thời gian chờ lắp", "Protected and covered while awaiting installation", M_V)),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  CIV · Xây dựng và kết cấu
# ═══════════════════════════════════════════════════════════════════════════════════════════════

CIV = [
    # ── 1xx nền móng ──────────────────────────────────────────────────────────────────────────
    F("CIV-101", "CIV", "Định vị công trình, trắc địa", "Setting out and survey control", "TCVN 9398:2012",
      ("Mốc chuẩn được bàn giao và có biên bản", "Benchmarks handed over with a record", M_D, "TCVN 9398:2012"),
      ("Trục, tim công trình đúng bản vẽ", "Grid lines and centre lines as per drawing", M_M, C_DWG),
      ("Cao độ chuẩn được chuyển và kiểm tra", "Datum level transferred and verified", M_M),
      ("Sai lệch định vị trong dung sai cho phép", "Setting-out tolerance within limits", M_M, "TCVN 9398:2012"),
      ("Mốc được bảo vệ, không xê dịch", "Markers protected and undisturbed", M_V),
      ("Thiết bị trắc địa còn hạn hiệu chuẩn", "Survey instruments within calibration", M_D)),

    F("CIV-102", "CIV", "Công tác đào đất", "Excavation", "TCVN 4447",
      ("Kích thước, cao độ đáy hố đúng thiết kế", "Excavation size and formation level as designed", M_M, C_DWG),
      ("Mái dốc, chống vách đúng biện pháp được duyệt", "Slopes and shoring as per the approved method", M_V, C_MS),
      ("Đáy hố khô ráo, không đọng nước", "Formation dry, no standing water", M_V),
      ("Đất yếu, vật lạ đã được bóc bỏ", "Soft spots and obstructions removed", M_V),
      ("Địa chất đáy hố phù hợp báo cáo khảo sát", "Formation soil matches the site investigation", M_C),
      ("Hệ thống thoát nước, hạ mực nước ngầm hoạt động", "Dewatering and drainage operating", M_F),
      ("Biện pháp an toàn hố đào được thực hiện", "Excavation safety measures in place", M_V, "QCVN 18:2021/BXD")),

    F("CIV-103", "CIV", "Đắp và đầm nền", "Filling and compaction", "TCVN 4447",
      ("Vật liệu đắp đúng chủng loại được duyệt", "Fill material as approved", M_C, C_SUB),
      ("Chiều dày mỗi lớp đắp không vượt quy định", "Layer thickness within the specified limit", M_M, C_MS),
      ("Độ ẩm vật liệu trong khoảng tối ưu", "Moisture content within the optimum range", M_T),
      ("Số lượt đầm đúng biện pháp thi công", "Number of compaction passes as per method", M_W, C_MS),
      ("Hệ số đầm chặt K đạt yêu cầu thiết kế", "Degree of compaction meets the design K value", M_T, C_DWG),
      ("Cao độ hoàn thiện trong dung sai", "Finished level within tolerance", M_M),
      ("Không đắp lên nền đọng nước hoặc đất hữu cơ", "No filling over ponded water or organic soil", M_V)),

    F("CIV-104", "CIV", "Thi công cọc — khoan nhồi", "Bored pile installation", "TCVN 9395:2012",
      ("Vị trí, cao độ đầu cọc đúng bản vẽ", "Pile position and cut-off level as per drawing", M_M, C_DWG),
      ("Đường kính, chiều sâu khoan đạt thiết kế", "Bore diameter and depth as designed", M_M),
      ("Dung dịch giữ thành đạt chỉ tiêu quy định", "Drilling fluid properties within specification", M_T, "TCVN 9395:2012"),
      ("Lồng thép đúng thiết kế, có con kê định vị", "Reinforcement cage as designed with spacers", M_V, C_DWG),
      ("Vệ sinh đáy hố khoan trước khi đổ bê tông", "Base cleaned before concreting", M_V, "TCVN 9395:2012"),
      ("Ống đổ đặt đúng cao độ, rút đúng quy trình", "Tremie set and withdrawn to procedure", M_W, C_MS),
      ("Khối lượng bê tông thực tế so với lý thuyết", "Actual against theoretical concrete volume", M_M),
      ("Lấy mẫu bê tông theo tần suất quy định", "Concrete samples taken at the required frequency", M_T)),

    F("CIV-105", "CIV", "Thí nghiệm kiểm tra cọc", "Pile testing", "TCVN 9395 / TCVN 9396",
      ("Số lượng cọc thí nghiệm đúng yêu cầu thiết kế", "Number of piles tested as required by design", M_D, C_DWG),
      ("Thí nghiệm siêu âm / PIT thực hiện đúng quy trình", "Sonic logging / PIT carried out to procedure", M_T),
      ("Không phát hiện khuyết tật thân cọc", "No shaft defects detected", M_T),
      ("Thí nghiệm nén tĩnh đạt tải trọng thiết kế", "Static load test reaches the design load", M_T),
      ("Độ lún trong giới hạn cho phép", "Settlement within the permitted limit", M_M, C_DWG),
      ("Đơn vị thí nghiệm có năng lực được công nhận", "Testing body holds the required accreditation", M_D),
      ("Báo cáo thí nghiệm đầy đủ và được duyệt", "Test report complete and approved", M_D)),

    F("CIV-106", "CIV", "Đài móng, giằng móng", "Pile caps and ground beams", "TCVN 4453:1995",
      ("Đập đầu cọc đến cao độ thiết kế", "Pile heads broken down to design level", M_M, C_DWG),
      ("Thép chờ cọc đủ chiều dài neo vào đài", "Pile starter bars have full anchorage into the cap", M_M, "TCVN 5574:2018"),
      ("Bê tông lót đủ chiều dày, phẳng", "Blinding of correct thickness and level", M_M),
      ("Kích thước đài, giằng đúng bản vẽ", "Cap and beam dimensions as per drawing", M_M, C_DWG),
      ("Cốt thép đúng thiết kế, đủ lớp bảo vệ", "Reinforcement as designed with correct cover", M_M),
      ("Chi tiết chờ, ống chờ MEP đã lắp và nghiệm thu", "MEP cast-ins and sleeves installed and accepted", M_C, "NĐ 06/2021 Điều 21"),
      ("Ván khuôn kín, chống mất nước xi măng", "Formwork tight against grout loss", M_V)),

    # ── 2xx bê tông ───────────────────────────────────────────────────────────────────────────
    F("CIV-201", "CIV", "Ván khuôn, đà giáo", "Formwork and falsework", "TCVN 4453:1995",
      ("Kích thước hình học đúng bản vẽ", "Geometry as per drawing", M_M, C_DWG),
      ("Tim, cốt, độ thẳng đứng trong dung sai", "Alignment, level and plumb within tolerance", M_M, "TCVN 4453:1995"),
      ("Hệ chống đỡ đủ khả năng chịu lực, được tính toán", "Falsework designed and adequate", M_D, C_MS),
      ("Liên kết chắc chắn, chống phình, chống xê dịch", "Ties secure against bulging and movement", M_V),
      ("Mối nối ván khuôn kín khít", "Panel joints tight", M_V),
      ("Bề mặt sạch, phủ chất chống dính đều", "Surface clean and release agent applied evenly", M_V),
      ("Có lỗ vệ sinh chân cột, chân vách", "Clean-out openings provided at column and wall bases", M_V),
      ("Chân chống đặt trên nền cứng, có gỗ đệm", "Props bear on firm ground with sole plates", M_V, "QCVN 18:2021/BXD")),

    F("CIV-202", "CIV", "Cốt thép trước khi đổ bê tông", "Reinforcement before concreting", "TCVN 4453:1995",
      ("Chủng loại, đường kính thép đúng thiết kế", "Bar type and diameter as designed", M_M, C_DWG),
      ("Số lượng, khoảng cách thanh thép đúng bản vẽ", "Bar count and spacing as per drawing", M_M, C_DWG),
      ("Chiều dài neo, nối chồng đạt yêu cầu", "Anchorage and lap lengths acceptable", M_M, "TCVN 5574:2018"),
      ("Vị trí mối nối đúng quy định, so le đúng tỷ lệ", "Lap positions and staggering as specified", M_V, "TCVN 5574:2018"),
      ("Lớp bê tông bảo vệ đủ, con kê đúng chủng loại và mật độ", "Cover achieved; spacers of correct type and density", M_M, "TCVN 5574:2018"),
      ("Thép đai đủ số lượng, đúng khoảng cách, móc đúng góc", "Links complete, correctly spaced, hooks to the correct angle", M_M),
      ("Thép sạch, không dính dầu mỡ, không rỉ vảy", "Bars clean, free of oil and loose scale", M_V),
      ("Chi tiết đặt sẵn, ống chờ MEP đã lắp và nghiệm thu", "Cast-in items and MEP sleeves installed and accepted", M_C, "NĐ 06/2021 Điều 21"),
      ("Vệ sinh trong ván khuôn trước khi đổ", "Formwork cleaned out before the pour", M_V),
      ("Thép chờ cho giai đoạn sau đúng vị trí và chiều dài", "Starter bars for the next stage correctly placed", M_M, C_DWG)),

    F("CIV-203", "CIV", "Đổ và bảo dưỡng bê tông", "Concrete placing and curing", "TCVN 4453:1995",
      ("Bê tông đúng cấp phối, có phiếu giao hàng", "Concrete of the correct mix with delivery ticket", M_D, C_DWG),
      ("Độ sụt kiểm tra tại hiện trường đạt yêu cầu", "Slump checked on site and within limits", M_T, "TCVN 3106"),
      ("Chiều cao rơi tự do không vượt quy định", "Free-fall height within the specified limit", M_M, "TCVN 4453:1995"),
      ("Đầm đúng phương pháp, không đầm quá hoặc thiếu", "Compaction correct — neither over- nor under-vibrated", M_W, C_MS),
      ("Mạch ngừng đặt đúng vị trí thiết kế", "Construction joints at the designed positions", M_V, C_DWG),
      ("Bề mặt hoàn thiện đúng yêu cầu", "Surface finish as specified", M_V, C_SPEC),
      ("Lấy mẫu thử theo tần suất quy định", "Test samples taken at the required frequency", M_T, "TCVN 3105"),
      ("Bảo dưỡng bắt đầu đúng thời điểm và đủ thời gian", "Curing started on time and maintained for the full period", M_W, "TCVN 8828"),
      ("Thời gian tháo ván khuôn theo cường độ đạt được", "Formwork struck according to the strength achieved", M_D, "TCVN 4453:1995")),

    F("CIV-204", "CIV", "Kết quả thí nghiệm bê tông", "Concrete test results", "TCVN 3118:2022",
      ("Mẫu được đúc, bảo dưỡng và đánh dấu đúng quy trình", "Samples cast, cured and marked to procedure", M_D, "TCVN 3105"),
      ("Cường độ 7 ngày đạt xu hướng dự kiến", "7-day strength on the expected trend", M_T),
      ("Cường độ 28 ngày đạt mác thiết kế", "28-day strength meets the design grade", M_T, "TCVN 3118:2022"),
      ("Đơn vị thí nghiệm được công nhận", "Testing laboratory accredited", M_D),
      ("Kết quả gắn được với vị trí đổ cụ thể", "Results traceable to the specific pour", M_C),
      ("Trường hợp không đạt: đã đánh giá và có phương án xử lý", "Where a result fails: evaluated with a disposition recorded", M_D, "NĐ 06/2021 Điều 21")),

    F("CIV-205", "CIV", "Bề mặt bê tông sau tháo ván khuôn", "Concrete surface after striking", "TCVN 4453:1995",
      ("Kích thước, tim cốt trong dung sai cho phép", "Dimensions and alignment within tolerance", M_M, "TCVN 4453:1995"),
      ("Không rỗ tổ ong, không lộ cốt thép", "No honeycombing, no exposed reinforcement", M_V),
      ("Không nứt vượt giới hạn cho phép", "No cracking beyond the permitted limit", M_M, "TCVN 5574:2018"),
      ("Bề mặt đạt yêu cầu hoàn thiện", "Surface meets the specified finish", M_V, C_SPEC),
      ("Khuyết tật đã được xử lý theo phương án được duyệt", "Defects made good to the approved method", M_V),
      ("Mạch ngừng được xử lý trước khi đổ tiếp", "Construction joints prepared before the next pour", M_V)),

    F("CIV-206", "CIV", "Bê tông ứng lực trước", "Post-tensioned concrete", C_SPEC,
      ("Vị trí, cao độ cáp đúng bản vẽ ứng lực", "Tendon profile and levels as per the PT drawing", M_M, C_DWG),
      ("Ống ghen liên tục, kín, không móp", "Ducts continuous, sealed and undented", M_V),
      ("Neo, bản đệm đặt vuông góc với cáp", "Anchorages and bearing plates square to the tendon", M_V, C_MFR),
      ("Kích căng còn hạn hiệu chuẩn", "Jack within calibration", M_D),
      ("Lực căng và độ giãn dài đạt giá trị thiết kế", "Jacking force and elongation match the design", M_T, C_DWG),
      ("Sai lệch độ giãn dài trong giới hạn cho phép", "Elongation deviation within the permitted limit", M_M, C_SPEC),
      ("Bơm vữa lấp lòng ống đầy, không rỗng", "Grouting complete with no voids", M_W),
      ("Cắt đầu cáp và bịt đầu neo sau khi vữa đạt cường độ", "Tendon ends cut and anchorages sealed after grout strength", M_V)),

    # ── 3xx kết cấu thép ──────────────────────────────────────────────────────────────────────
    F("CIV-301", "CIV", "Chế tạo kết cấu thép", "Structural steel fabrication", "TCVN 5575",
      ("Vật liệu đúng mác thép, có chứng chỉ", "Steel of the correct grade with certificates", M_D, "TCVN 5575"),
      ("Kích thước cấu kiện trong dung sai chế tạo", "Member dimensions within fabrication tolerance", M_M, "TCVN 5575"),
      ("Mối hàn đúng loại, đúng kích thước thiết kế", "Welds of the correct type and size", M_M, C_DWG),
      ("Thợ hàn có chứng chỉ phù hợp", "Welders hold the appropriate qualification", M_D),
      ("Kiểm tra không phá hủy đạt yêu cầu", "Non-destructive testing acceptable", M_T, C_SPEC),
      ("Lỗ bu lông đúng vị trí, đúng đường kính", "Bolt holes correctly positioned and sized", M_M, C_DWG),
      ("Làm sạch bề mặt đạt cấp quy định trước khi sơn", "Surface prepared to the specified grade before painting", M_V, C_SPEC),
      ("Chiều dày lớp sơn đạt yêu cầu", "Paint dry-film thickness as specified", M_M, C_SPEC),
      ("Đánh dấu, mã hiệu cấu kiện đầy đủ", "Members marked and identified", M_V)),

    F("CIV-302", "CIV", "Lắp dựng kết cấu thép", "Structural steel erection", "TCVN 5575",
      ("Bu lông neo đúng vị trí, cao độ, dung sai", "Holding-down bolts correctly positioned and levelled", M_M, C_DWG),
      ("Cấu kiện đúng mã hiệu, đúng vị trí lắp", "Members of the correct mark in the correct position", M_C, C_DWG),
      ("Độ thẳng đứng, độ võng trong dung sai lắp dựng", "Plumb and camber within erection tolerance", M_M, "TCVN 5575"),
      ("Bu lông đủ số lượng, đúng cấp bền", "Bolts complete and of the correct grade", M_V, C_DWG),
      ("Mô men siết bu lông cường độ cao đạt yêu cầu", "High-strength bolt torque as specified", M_T, C_SPEC),
      ("Mối hàn hiện trường đạt yêu cầu, có NDT", "Site welds acceptable with NDT", M_T, C_SPEC),
      ("Hệ giằng tạm và giằng vĩnh cửu đầy đủ", "Temporary and permanent bracing complete", M_V, C_MS),
      ("Chèn vữa chân cột đầy, không rỗng", "Base-plate grouting complete with no voids", M_V),
      ("Sơn dặm vị trí hàn, vị trí trầy xước", "Touch-up paint at welds and damaged areas", M_V)),

    F("CIV-303", "CIV", "Sơn chống cháy kết cấu thép", "Structural steel fire protection", "QCVN 06:2022/BXD",
      ("Vật liệu chống cháy đúng loại được thẩm duyệt", "Fire-protection material as appraised", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Bề mặt thép được làm sạch và sơn lót đúng quy trình", "Steel cleaned and primed to procedure", M_V, C_MFR),
      ("Chiều dày lớp phủ đạt giới hạn chịu lửa yêu cầu", "Coating thickness achieves the required fire rating", M_M, "QCVN 06:2022/BXD"),
      ("Số điểm đo đủ theo quy định lấy mẫu", "Measurement points to the required sampling rate", M_M, C_SPEC),
      ("Không bong tróc, không nứt, phủ kín các góc", "No flaking or cracking; corners fully covered", M_V),
      ("Điều kiện nhiệt độ, độ ẩm khi thi công đạt yêu cầu", "Ambient temperature and humidity within limits", M_M, C_MFR),
      ("Có biên bản nghiệm thu và ảnh chụp từng khu vực", "Record and photographs for each area", M_D)),

    # ── 4xx xây, chống thấm, hoàn thiện thô ───────────────────────────────────────────────────
    F("CIV-401", "CIV", "Công tác xây", "Masonry", "TCVN 4085",
      ("Chủng loại gạch, vữa đúng thiết kế", "Block and mortar types as designed", M_C, C_SUB),
      ("Tim tường, chiều dày đúng bản vẽ", "Wall lines and thickness as per drawing", M_M, C_DWG),
      ("Độ thẳng đứng, độ phẳng trong dung sai", "Plumb and flatness within tolerance", M_M, "TCVN 4085"),
      ("Mạch vữa đầy, đều, đúng chiều dày", "Joints full, even and of the correct thickness", M_V, "TCVN 4085"),
      ("Câu gạch so le đúng quy định", "Bonding pattern correct", M_V),
      ("Thép râu liên kết với cột, vách đủ số lượng", "Wall ties into columns and walls complete", M_M, C_DWG),
      ("Giằng tường, lanh tô đúng thiết kế", "Bond beams and lintels as designed", M_M, C_DWG),
      ("Chừa lỗ chờ MEP đúng vị trí, không đục phá sau", "MEP openings left in place, not chased afterwards", M_C, C_DWG),
      ("Bảo dưỡng khối xây đủ thời gian", "Masonry cured for the required period", M_W)),

    F("CIV-402", "CIV", "Chống thấm", "Waterproofing", C_SPEC,
      ("Vật liệu chống thấm đúng hệ được duyệt", "Waterproofing system as approved", M_C, C_SUB),
      ("Bề mặt nền khô, sạch, không nứt, được xử lý góc", "Substrate dry, clean, crack-free, fillets formed", M_V, C_MFR),
      ("Chiều dày, số lớp đúng chỉ dẫn nhà sản xuất", "Thickness and number of coats as instructed", M_M, C_MFR),
      ("Chồng mí đủ chiều rộng tại các mối nối", "Overlaps of the required width at joints", M_M, C_MFR),
      ("Xử lý cổ ống, chân tường, khe co giãn đầy đủ", "Pipe penetrations, upstands and movement joints detailed", M_V, C_DWG),
      ("Ngâm nước thử 24–72 giờ không rò rỉ", "Flood test 24–72 h with no leakage", M_T, C_SPEC),
      ("Lớp bảo vệ thi công ngay sau khi nghiệm thu", "Protection layer applied immediately after acceptance", M_V),
      ("Ảnh chụp hiện trạng trước khi che phủ", "Photographs taken before covering up", M_D)),

    F("CIV-403", "CIV", "Khe co giãn, khe lún", "Movement and settlement joints", C_SPEC,
      ("Vị trí, chiều rộng khe đúng bản vẽ", "Joint position and width as per drawing", M_M, C_DWG),
      ("Vật liệu chèn khe đúng chủng loại", "Joint filler as specified", M_C, C_SUB),
      ("Băng cản nước liên tục, mối nối đúng quy trình", "Waterstop continuous with joints made to procedure", M_V, C_MFR),
      ("Khe sạch, không lẫn vữa, bê tông", "Joint clean and free of mortar and concrete", M_V),
      ("Nắp che khe lắp phẳng, chắc chắn", "Cover plates level and secure", M_V),
      ("Khe xuyên qua lớp chống thấm được xử lý kín", "Joints through waterproofing detailed watertight", M_V)),

    F("CIV-404", "CIV", "Đường nội bộ, sân bãi", "Internal roads and hardstanding", "TCVN 4054",
      ("Nền đường đạt độ chặt yêu cầu", "Subgrade compaction meets the requirement", M_T, C_DWG),
      ("Chiều dày các lớp kết cấu đúng thiết kế", "Pavement layer thicknesses as designed", M_M, C_DWG),
      ("Cao độ, độ dốc ngang, dốc dọc đúng bản vẽ", "Levels, crossfall and longitudinal grade as per drawing", M_M, C_DWG),
      ("Vật liệu từng lớp đúng chủng loại được duyệt", "Materials for each layer as approved", M_C, C_SUB),
      ("Độ bằng phẳng mặt đường trong dung sai", "Surface regularity within tolerance", M_M, C_SPEC),
      ("Bó vỉa, rãnh thoát đúng tuyến và cao độ", "Kerbs and channels on line and level", M_M, C_DWG),
      ("Hố ga, nắp đan ngang bằng mặt hoàn thiện", "Manholes and covers flush with the finished surface", M_M),
      ("Vạch sơn, biển báo theo bản vẽ", "Line marking and signage as per drawing", M_V, C_DWG)),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  ARC · Kiến trúc và hoàn thiện
# ═══════════════════════════════════════════════════════════════════════════════════════════════

ARC = [
    F("ARC-101", "ARC", "Trát tường, trần", "Plastering to walls and ceilings", "TCVN 9377-2:2012",
      ("Bề mặt nền được làm sạch, tưới ẩm, tạo nhám", "Substrate cleaned, dampened and keyed", M_V, "TCVN 9377-2:2012"),
      ("Lưới chống nứt tại vị trí giáp ranh vật liệu khác nhau", "Anti-crack mesh at junctions of dissimilar materials", M_V, C_DWG),
      ("Mốc trát, cữ được đặt đúng cao độ và mặt phẳng", "Screeds and beads set to line and level", M_M),
      ("Chiều dày lớp trát đúng quy định", "Plaster thickness as specified", M_M, "TCVN 9377-2:2012"),
      ("Độ phẳng kiểm tra bằng thước 2 m trong dung sai", "Flatness checked with a 2 m straightedge, within tolerance", M_M, "TCVN 9377-2:2012"),
      ("Góc cạnh thẳng, vuông, không sứt", "Arrises straight, square and undamaged", M_V),
      ("Không rỗ, không bong, gõ không kêu bộp", "No pitting or hollowness on tapping", M_V),
      ("Bảo dưỡng đủ thời gian trước lớp hoàn thiện", "Cured for the full period before finishing", M_W)),

    F("ARC-102", "ARC", "Ốp lát gạch", "Tiling", "TCVN 9377-1:2012",
      ("Chủng loại, kích thước, màu gạch đúng mẫu được duyệt", "Tile type, size and colour as approved", M_C, C_SUB),
      ("Nền được xử lý phẳng, sạch, đủ độ bám", "Substrate level, clean and with adequate key", M_V),
      ("Vữa dán, keo dán đúng chủng loại và định mức", "Adhesive of the correct type and coverage", M_C, C_MFR),
      ("Độ phẳng mặt lát trong dung sai cho phép", "Finished flatness within tolerance", M_M, "TCVN 9377-1:2012"),
      ("Mạch đều, thẳng, đúng chiều rộng thiết kế", "Joints even, straight and of the specified width", M_M, C_DWG),
      ("Gõ kiểm tra không có viên bộp, không rỗng", "Tapping reveals no hollow tiles", M_V, "TCVN 9377-1:2012"),
      ("Độ dốc thoát nước đúng thiết kế ở khu vực ướt", "Falls to drainage as designed in wet areas", M_M, C_DWG),
      ("Cắt gạch tại góc, cạnh gọn, đúng mạch", "Cuts at corners and edges neat and aligned", M_V),
      ("Chít mạch đầy, đều màu, sạch bề mặt", "Grouting full, even in colour and surface cleaned", M_V)),

    F("ARC-103", "ARC", "Sơn hoàn thiện", "Painting", "TCVN 8652 / TCVN 8653",
      ("Hệ sơn đúng chủng loại được duyệt, đúng số lớp", "Paint system as approved with the correct number of coats", M_C, C_SUB),
      ("Bề mặt khô, sạch, độ ẩm trong giới hạn", "Surface dry and clean, moisture within limits", M_M, C_MFR),
      ("Bả matít phẳng, xả nhám đều", "Skim coat flat and evenly sanded", M_V),
      ("Sơn lót phủ kín trước khi sơn phủ", "Primer fully covering before topcoat", M_V),
      ("Màu sắc đồng đều, đúng mẫu đã duyệt", "Colour uniform and matching the approved sample", M_C),
      ("Không chảy, không vón, không lộ vệt cọ, không lộ nền", "No runs, bittiness, brush marks or grinning", M_V),
      ("Đường ranh giới màu thẳng, sắc nét", "Colour break lines straight and sharp", M_V),
      ("Che chắn, không dây bẩn sang hạng mục khác", "Adjacent work masked and undamaged", M_V)),

    F("ARC-104", "ARC", "Trần thạch cao, trần treo", "Suspended and plasterboard ceilings", C_SPEC,
      ("Cao độ trần đúng bản vẽ", "Ceiling level as per drawing", M_M, C_DWG),
      ("Ty treo, khung xương đúng khoảng cách quy định", "Hangers and grid at the specified spacing", M_M, C_MFR),
      ("Khung được liên kết vào kết cấu, không treo vào ống MEP", "Grid fixed to structure, never hung from MEP services", M_V, C_MS),
      ("Độ phẳng mặt trần trong dung sai", "Ceiling flatness within tolerance", M_M, C_SPEC),
      ("Tấm trần phẳng, không cong vênh, mạch đều", "Boards flat, not bowed, joints even", M_V),
      ("Xử lý mối nối, băng keo, bả phẳng", "Joints taped and skimmed flat", M_V),
      ("Vị trí đèn, đầu phun, miệng gió, đầu báo đúng bản vẽ phối hợp", "Lights, sprinklers, diffusers and detectors as per the coordinated drawing", M_C, C_DWG),
      ("Cửa thăm trần bố trí đủ tại vị trí cần bảo trì", "Access panels provided where maintenance access is needed", M_V, C_DWG),
      ("Khu vực trần chống cháy đúng cấu tạo được thẩm duyệt", "Fire-rated ceiling built to the appraised detail", M_C, "QCVN 06:2022/BXD")),

    F("ARC-105", "ARC", "Vách ngăn nhẹ", "Lightweight partitions", C_SPEC,
      ("Tim vách, chiều dày đúng bản vẽ", "Partition line and thickness as per drawing", M_M, C_DWG),
      ("Khung xương đúng chủng loại, khoảng cách quy định", "Studs of the correct type and spacing", M_M, C_MFR),
      ("Liên kết chân, đỉnh vách chắc chắn", "Head and base fixings secure", M_V),
      ("Bông cách âm, cách nhiệt đúng chủng loại và tỷ trọng", "Acoustic or thermal insulation of the correct type and density", M_C, C_SUB),
      ("Gia cường tại vị trí treo thiết bị", "Additional framing where equipment is to be hung", M_V, C_DWG),
      ("Tấm ốp đủ số lớp, so le mối nối", "Boards to the correct number of layers with staggered joints", M_V, C_SPEC),
      ("Vách chống cháy đúng cấu tạo và được chèn bịt kín", "Fire-rated partitions built to detail and fire-stopped", M_C, "QCVN 06:2022/BXD"),
      ("Độ thẳng đứng, độ phẳng trong dung sai", "Plumb and flatness within tolerance", M_M)),

    F("ARC-106", "ARC", "Cửa đi, cửa sổ", "Doors and windows", C_SPEC,
      ("Chủng loại, kích thước, chiều mở đúng bảng thống kê cửa", "Type, size and hand as per the door schedule", M_C, C_DWG),
      ("Khuôn cửa thẳng, vuông, chắc chắn", "Frames straight, square and secure", M_M),
      ("Khe hở cánh — khuôn đều, đúng quy định", "Leaf-to-frame clearances even and within limits", M_M, C_SPEC),
      ("Phụ kiện đúng chủng loại, lắp đủ, hoạt động êm", "Ironmongery correct, complete and operating smoothly", M_F, C_SUB),
      ("Cửa chống cháy đúng chủng loại được kiểm định, có tem", "Fire doors of the certified type and labelled", M_D, "QCVN 06:2022/BXD"),
      ("Gioăng khói, gioăng nở lắp đủ trên cửa chống cháy", "Smoke and intumescent seals complete on fire doors", M_V, "QCVN 06:2022/BXD"),
      ("Cửa thoát nạn mở theo chiều thoát, có thanh thoát hiểm", "Escape doors open in the direction of travel with panic hardware", M_F, "QCVN 06:2022/BXD"),
      ("Chèn khe khuôn cửa kín, đúng vật liệu", "Frame perimeter sealed with the correct material", M_V),
      ("Đóng mở nhẹ nhàng, không kẹt, tự đóng kín hoàn toàn", "Operates smoothly and self-closers latch fully", M_F)),

    F("ARC-107", "ARC", "Vách kính, mặt dựng", "Glazing and curtain walling", C_SPEC,
      ("Hệ nhôm, kính đúng chủng loại được duyệt", "Aluminium system and glass as approved", M_C, C_SUB),
      ("Kính có tem, đúng cấu tạo và chiều dày thiết kế", "Glass labelled, of the specified make-up and thickness", M_C, C_DWG),
      ("Neo, ke liên kết vào kết cấu đúng thiết kế", "Brackets and anchors to structure as designed", M_V, C_DWG),
      ("Độ thẳng đứng, độ phẳng mặt dựng trong dung sai", "Plumb and plane of the facade within tolerance", M_M, C_SPEC),
      ("Khe hở giãn nở đủ tại các mối nối", "Expansion gaps adequate at joints", M_M, C_MFR),
      ("Keo silicone kết cấu, keo thời tiết thi công đúng quy trình", "Structural and weather silicone applied to procedure", M_V, C_MFR),
      ("Thoát nước, thông hơi khung không bị bịt", "Drainage and ventilation paths in the frame unobstructed", M_V, C_MFR),
      ("Thử phun nước không rò rỉ", "Water spray test with no leakage", M_T, C_SPEC),
      ("Chèn chống cháy tại mép sàn đúng cấu tạo", "Perimeter fire-stopping at slab edges to detail", M_V, "QCVN 06:2022/BXD")),

    F("ARC-108", "ARC", "Sàn hoàn thiện đặc biệt", "Specialist floor finishes", C_SPEC,
      ("Nền bê tông đạt độ phẳng và độ ẩm yêu cầu", "Concrete base meets flatness and moisture requirements", M_T, C_MFR),
      ("Xử lý bề mặt, sơn lót đúng quy trình", "Surface preparation and priming to procedure", M_V, C_MFR),
      ("Chiều dày lớp phủ đạt thiết kế", "Coating or screed thickness as designed", M_M, C_DWG),
      ("Độ phẳng, độ dốc đạt yêu cầu sử dụng", "Flatness and falls suit the intended use", M_M, C_SPEC),
      ("Khe co giãn cắt đúng vị trí và thời điểm", "Movement joints cut in the right place at the right time", M_M, C_DWG),
      ("Bề mặt đồng màu, không bong rộp, không vết chổi", "Uniform colour, no blistering or brush marks", M_V),
      ("Độ cứng, độ chống trượt đạt yêu cầu (nếu quy định)", "Hardness and slip resistance as specified where required", M_T, C_SPEC)),

    F("ARC-109", "ARC", "Thiết bị vệ sinh và phụ kiện", "Sanitary fixtures and accessories", "TCVN 4513:1988",
      ("Chủng loại, model đúng bảng thiết bị được duyệt", "Type and model as per the approved schedule", M_C, C_SUB),
      ("Cao độ, vị trí lắp đúng bản vẽ", "Mounting height and position as per drawing", M_M, C_DWG),
      ("Liên kết chắc chắn vào tường, sàn", "Fixings to wall and floor secure", M_V, C_MFR),
      ("Đấu nối cấp, thoát kín, không rò rỉ", "Supply and waste connections tight with no leaks", M_T),
      ("Bẫy nước đủ chiều cao ngăn mùi", "Traps have the correct seal depth", M_M, "TCVN 4474:1987"),
      ("Xả thử, thoát nhanh, không đọng", "Flush test drains quickly with no ponding", M_F),
      ("Bơm keo chân thiết bị kín, gọn", "Silicone seal at the base neat and complete", M_V),
      ("Bề mặt không trầy xước, đã tháo lớp bảo vệ", "Surfaces unscratched and protective film removed", M_V)),

    F("ARC-110", "ARC", "Chống thấm khu vệ sinh", "Wet-area waterproofing", C_SPEC,
      ("Hệ chống thấm đúng loại được duyệt cho khu vực ướt", "System as approved for wet areas", M_C, C_SUB),
      ("Sàn được tạo dốc về phễu trước khi chống thấm", "Falls formed to gullies before waterproofing", M_M, C_DWG),
      ("Chống thấm lên chân tường đủ chiều cao quy định", "Upstand to the specified height", M_M, C_SPEC),
      ("Cổ ống, phễu thu được xử lý bằng chi tiết chuyên dụng", "Pipe penetrations and gullies detailed with proprietary components", M_V, C_MFR),
      ("Ngâm nước thử 24 giờ, kiểm tra trần tầng dưới", "24-hour flood test, ceiling below inspected", M_T, C_SPEC),
      ("Ảnh chụp trước khi lát hoàn thiện", "Photographs taken before tiling over", M_D)),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  ELE · Hệ thống điện
# ═══════════════════════════════════════════════════════════════════════════════════════════════

ELE = [
    # ── 1xx hạ tầng, đi ngầm ──────────────────────────────────────────────────────────────────
    F("ELE-101", "ELE", "Mương cáp, hào kỹ thuật", "Cable trenches and ducts", "TCVN 9207:2012",
      ("Tuyến, chiều sâu, chiều rộng đúng bản vẽ", "Route, depth and width as per drawing", M_M, C_DWG),
      ("Đáy mương phẳng, có lớp cát đệm đủ chiều dày", "Trench bottom level with sand bedding of the correct thickness", M_M, C_DWG),
      ("Khoảng cách tới các công trình ngầm khác đạt yêu cầu", "Clearance to other buried services acceptable", M_M, "TCVN 9207:2012"),
      ("Ống luồn đúng chủng loại, mối nối kín", "Ducts of the correct type with sealed joints", M_V, C_SUB),
      ("Có dây mồi trong ống chờ", "Draw wire left in spare ducts", M_V),
      ("Lớp cát phủ và gạch/tấm báo hiệu đặt đúng cao độ", "Sand cover and warning tiles at the correct level", M_M, C_DWG),
      ("Băng cảnh báo đặt trên tuyến cáp", "Warning tape laid over the cable route", M_V),
      ("Lấp trả và đầm theo từng lớp", "Backfilled and compacted in layers", M_W, C_MS),
      ("Ảnh chụp và định vị tuyến trước khi lấp", "Photographs and survey of the route before backfilling", M_D)),

    F("ELE-102", "ELE", "Lắp đặt cáp ngầm", "Underground cable installation", "TCVN 9207:2012",
      ("Chủng loại, tiết diện cáp đúng thiết kế", "Cable type and size as designed", M_C, C_DWG),
      ("Đo cách điện trước và sau khi kéo cáp", "Insulation resistance measured before and after pulling", M_T, "TCVN 7447"),
      ("Lực kéo và bán kính uốn trong giới hạn nhà sản xuất", "Pulling tension and bending radius within the maker's limits", M_M, C_MFR),
      ("Cáp không xoắn, không xây xát vỏ", "No twisting or sheath damage", M_V),
      ("Khoảng cách giữa các sợi cáp đạt yêu cầu tản nhiệt", "Spacing between cables adequate for heat dissipation", M_M, "TCVN 9207:2012"),
      ("Biển nhận dạng cáp đặt tại hai đầu và tại các hố", "Cable markers at both ends and at each pit", M_V),
      ("Cáp dự phòng để đủ chiều dài tại tủ và hố nối", "Spare cable length left at panels and joint bays", M_M)),

    F("ELE-103", "ELE", "Lắp đặt lỗ chờ, ống chờ sàn vách", "Slab and wall openings and sleeves", "TCVN 9207:2012",
      ("Vị trí lỗ chờ, ống chờ đúng bản vẽ thi công", "Opening and sleeve positions as per approved shop drawing", M_M, C_DWG),
      ("Cao độ và kích thước trong dung sai cho phép", "Level and dimensions within tolerance", M_M, "±10 mm"),
      ("Chủng loại và đường kính ống chờ đúng thiết kế", "Sleeve type and diameter as designed", M_C, C_DWG),
      ("Ống chờ cố định chắc chắn, không xê dịch khi đổ bê tông", "Sleeves fixed securely against movement during the pour", M_V, C_MS),
      ("Bịt đầu ống chống lọt vữa, bê tông", "Sleeve ends capped against grout and concrete ingress", M_V),
      ("Không xung đột cốt thép chịu lực; cắt thép có chấp thuận kết cấu", "No clash with structural bars; any cutting approved by the structural engineer", M_V, "TCVN 4453:1995"),
      ("Khoảng cách tới hệ thống khác đạt yêu cầu phối hợp", "Clearance to other services meets the coordination requirement", M_M, C_DWG),
      ("Đã đánh dấu, ghi nhãn nhận biết tuyến", "Marked and labelled for route identification", M_V)),

    # ── 2xx containment ──────────────────────────────────────────────────────────────────────
    F("ELE-201", "ELE", "Ống luồn dây điện âm tường, âm sàn", "Concealed conduit in walls and slabs", "TCVN 9207:2012",
      ("Tuyến ống đi thẳng, đúng phương ngang/đứng quy định", "Runs straight and in the permitted horizontal/vertical zones", M_V, "TCVN 9207:2012"),
      ("Chủng loại, đường kính ống đúng thiết kế", "Conduit type and diameter as designed", M_C, C_DWG),
      ("Số lượng dây trong ống không vượt hệ số điền đầy", "Number of cables within the permitted fill factor", M_M, "TCVN 9207:2012"),
      ("Bán kính uốn không nhỏ hơn quy định, không gấp khúc", "Bending radius not below the minimum, no kinks", M_M, C_MFR),
      ("Mối nối, măng sông kín, chắc", "Couplings and joints tight and secure", M_V),
      ("Hộp nối, hộp âm tường đặt đúng cao độ, ngang bằng", "Boxes at the correct height and flush", M_M, C_DWG),
      ("Ống được cố định trước khi đổ bê tông hoặc trát", "Conduit fixed before concreting or plastering", M_V),
      ("Có dây mồi, đầu ống bịt kín", "Draw wire in place and ends capped", M_V),
      ("Ảnh chụp tuyến ống trước khi che khuất", "Photographs of the route before covering up", M_D)),

    F("ELE-202", "ELE", "Thang cáp, máng cáp", "Cable tray and trunking", "TCVN 9207:2012",
      ("Tuyến đi đúng bản vẽ thi công được duyệt", "Route as per the approved shop drawing", M_C, C_DWG),
      ("Cao độ, độ thẳng, độ phẳng đạt yêu cầu", "Level, straightness and flatness acceptable", M_M, "±5 mm / 3 m"),
      ("Khoảng cách giá đỡ đúng chỉ dẫn nhà sản xuất", "Support spacing as instructed by the maker", M_M, C_MFR),
      ("Chủng loại, kích thước, lớp mạ đúng thiết kế", "Type, size and finish as designed", M_C, C_DWG),
      ("Liên kết cơ khí chắc chắn, đủ bu lông, không biến dạng", "Mechanical joints sound, fully bolted, no distortion", M_V),
      ("Liên kết đẳng thế liên tục trên toàn tuyến", "Earth bonding continuous along the whole route", M_T, "TCVN 9358:2012"),
      ("Không có cạnh sắc gây hư hỏng vỏ cáp", "No sharp edges that could damage cable sheathing", M_V),
      ("Khoảng cách tới hệ thống khác và tới kết cấu đạt yêu cầu", "Clearance to other services and to structure acceptable", M_M, C_DWG),
      ("Xuyên tường, xuyên sàn đã chèn bịt chống cháy đúng cấp", "Wall and floor penetrations fire-stopped to the correct rating", M_V, "QCVN 06:2022/BXD"),
      ("Đã dán nhãn tuyến và mã hiệu", "Route labels and identification codes applied", M_V)),

    F("ELE-203", "ELE", "Busduct, thanh dẫn", "Busduct and busbar trunking", C_MFR,
      ("Chủng loại, dòng định mức đúng thiết kế", "Type and current rating as designed", M_C, C_DWG),
      ("Đo cách điện từng đoạn trước khi ghép nối", "Insulation resistance measured on each section before jointing", M_T, "TCVN 7447"),
      ("Mối nối siết đúng mô men quy định", "Joints torqued to the specified value", M_T, C_MFR),
      ("Giá đỡ, khớp giãn nở lắp đúng khoảng cách", "Supports and expansion joints at the correct spacing", M_M, C_MFR),
      ("Thứ tự pha thống nhất toàn tuyến", "Phase sequence consistent along the run", M_T),
      ("Chèn chống cháy tại vị trí xuyên sàn đúng cấp", "Fire-stopping at floor penetrations to the correct rating", M_V, "QCVN 06:2022/BXD"),
      ("Vỏ được nối đất liên tục", "Enclosure earthed continuously", M_T, "TCVN 9358:2012"),
      ("Hộp nối rẽ nhánh lắp đúng vị trí, tiếp cận được", "Tap-off boxes correctly located and accessible", M_V, C_DWG),
      ("Đo cách điện toàn tuyến sau khi hoàn thiện", "Insulation resistance measured on the complete run", M_T, "TCVN 7447")),

    F("ELE-204", "ELE", "Lắp đặt dây, cáp điện", "Cable and wire installation", "TCVN 7447",
      ("Chủng loại, tiết diện cáp đúng thiết kế", "Cable type and cross-section as designed", M_C, C_DWG),
      ("Bán kính uốn không nhỏ hơn giá trị nhà sản xuất quy định", "Bending radius not below the maker's minimum", M_M, C_MFR),
      ("Cáp được đỡ, buộc gọn, không chịu lực kéo tại đầu nối", "Cables supported and tied, no tension at terminations", M_V),
      ("Đầu cốt đúng chủng loại, ép bằng dụng cụ đúng", "Lugs of the correct type crimped with the correct tool", M_V, C_MFR),
      ("Đo điện trở cách điện đạt yêu cầu", "Insulation resistance test passed", M_T, "TCVN 7447"),
      ("Đo điện trở vòng lặp sự cố và thông mạch dây bảo vệ", "Earth-fault loop impedance and CPC continuity verified", M_T, "TCVN 7447"),
      ("Thứ tự pha đúng và thống nhất toàn hệ thống", "Phase sequence correct and consistent", M_T),
      ("Đánh số lõi, dán nhãn hai đầu cáp", "Cores numbered and both ends labelled", M_V),
      ("Bán kính uốn tại tủ đủ, cáp vào tủ có gioăng chèn", "Adequate radius at panels; glands fitted at entries", M_V)),

    # ── 3xx thiết bị ─────────────────────────────────────────────────────────────────────────
    F("ELE-301", "ELE", "Tủ điện phân phối", "Distribution boards and switchboards", "TCVN 7447",
      ("Model, dòng định mức, dòng cắt đúng thiết kế", "Model, rating and breaking capacity as designed", M_C, C_DWG),
      ("Vị trí, cao độ lắp đặt đúng bản vẽ, tiếp cận được", "Location and mounting height as per drawing, accessible", M_M, C_DWG),
      ("Khoảng cách thao tác phía trước tủ đạt yêu cầu", "Working clearance in front of the panel adequate", M_M, "TCVN 7447"),
      ("Tủ cân bằng, cố định chắc chắn vào kết cấu", "Panel plumb and fixed securely to structure", M_M),
      ("Thiết bị đóng cắt đúng chủng loại, đúng vị trí sơ đồ", "Protective devices of the correct type and in the schedule positions", M_C, C_DWG),
      ("Siết đầu nối đúng mô men quy định", "Terminations torqued to the specified value", M_T, C_MFR),
      ("Nhãn mạch, sơ đồ nguyên lý dán trong tủ và cập nhật", "Circuit labels and as-built schematic inside the panel", M_V, "TCVN 7447"),
      ("Nối đất vỏ tủ và thanh nối đất liên tục", "Enclosure and earth bar bonded and continuous", M_T, "TCVN 9358:2012"),
      ("Chèn kín lỗ vào cáp, không hở đáy tủ", "Cable entries sealed, no open base", M_V),
      ("Đo cách điện và thử hoạt động từng lộ", "Insulation test and functional check on each way", M_T, "TCVN 7447")),

    F("ELE-302", "ELE", "Máy biến áp", "Transformer", C_MFR,
      ("Công suất, tổ đấu dây, điện áp đúng thiết kế", "Rating, vector group and voltages as designed", M_C, C_DWG),
      ("Bệ đặt, chống rung, cố định đúng hướng dẫn", "Plinth, anti-vibration and fixing as instructed", M_V, C_MFR),
      ("Khoảng cách an toàn tới tường và thiết bị khác", "Safety clearances to walls and other equipment", M_M, "TCVN 7447"),
      ("Mức dầu, áp suất, chỉ thị nhiệt trong giới hạn (loại dầu)", "Oil level, pressure and temperature indication within limits (oil type)", M_M, C_MFR),
      ("Thông gió phòng máy đủ theo tính toán tỏa nhiệt", "Room ventilation adequate for the heat load", M_M, C_DWG),
      ("Đo điện trở cách điện cuộn dây", "Winding insulation resistance measured", M_T, C_MFR),
      ("Đo tỷ số biến và điện trở một chiều cuộn dây", "Turns ratio and winding DC resistance measured", M_T, C_MFR),
      ("Nối đất trung tính và vỏ máy theo thiết kế", "Neutral and body earthing as designed", M_T, "TCVN 9358:2012"),
      ("Bảng tên, cảnh báo nguy hiểm điện áp lắp đầy đủ", "Nameplate and high-voltage warning signage in place", M_V),
      ("Thiết bị bảo vệ, cảm biến nhiệt đấu nối và thử tác động", "Protection and temperature sensors wired and function-tested", M_F)),

    F("ELE-303", "ELE", "Tủ trung thế", "MV switchgear", C_MFR,
      ("Thông số tủ đúng thiết kế và đơn vị điện lực chấp thuận", "Ratings as designed and accepted by the utility", M_D, C_DWG),
      ("Vận chuyển, lắp đặt không va đập, tủ cân bằng", "Delivered and installed without impact, panel level", M_V),
      ("Liên động cơ khí, khoá liên động hoạt động đúng", "Mechanical interlocks operate correctly", M_F, C_MFR),
      ("Đo cách điện và thử cao áp theo quy trình", "Insulation and high-voltage withstand tests to procedure", M_T, C_MFR),
      ("Thử tác động rơ le bảo vệ theo cài đặt được duyệt", "Protection relays tested to the approved settings", M_T, C_SPEC),
      ("Nối đất tủ và hệ thống tiếp địa liên tục", "Panel earthing continuous with the earthing system", M_T, "TCVN 9358:2012"),
      ("Trang bị an toàn: sào thao tác, thảm cách điện, biển báo", "Safety equipment: operating rod, insulating mat, signage", M_V, "QCVN 01:2020/BCT"),
      ("Sơ đồ vận hành dán tại phòng, nhân sự được huấn luyện", "Operating diagram posted and operators trained", M_D)),

    F("ELE-304", "ELE", "Máy phát điện dự phòng", "Standby generator", C_MFR,
      ("Công suất, model đúng thiết kế", "Rating and model as designed", M_C, C_DWG),
      ("Bệ máy, giảm chấn đúng thiết kế, cân chỉnh đồng trục", "Base and isolators as designed, alignment correct", M_M, C_MFR),
      ("Hệ thống nhiên liệu kín, có bể chứa và chống tràn", "Fuel system tight with tank and bunding", M_V, C_DWG),
      ("Ống khói, giảm âm lắp đúng, không rò khí", "Exhaust and silencer installed correctly with no leaks", M_V, C_MFR),
      ("Thông gió cấp và thải phòng máy đủ lưu lượng", "Room supply and discharge ventilation adequate", M_M, C_DWG),
      ("Ắc quy khởi động, bộ nạp hoạt động", "Starting battery and charger operational", M_F),
      ("Nối đất trung tính và vỏ máy đúng thiết kế", "Neutral and frame earthing as designed", M_T, "TCVN 9358:2012"),
      ("Chạy thử không tải và có tải, ghi thông số", "No-load and on-load test run with readings recorded", M_T, C_MFR),
      ("Thử khởi động tự động khi mất điện lưới, đúng thời gian", "Auto-start on mains failure within the specified time", M_F, C_SPEC),
      ("Cảnh báo, dừng khẩn cấp hoạt động đúng", "Alarms and emergency stop function correctly", M_F)),

    F("ELE-305", "ELE", "Tủ ATS", "Automatic transfer switch", C_MFR,
      ("Dòng định mức, số cực đúng thiết kế", "Rating and number of poles as designed", M_C, C_DWG),
      ("Đấu nối nguồn lưới, nguồn máy phát đúng sơ đồ", "Mains and generator connections as per schematic", M_C, C_DWG),
      ("Liên động chống đóng đồng thời hai nguồn hoạt động", "Interlock preventing parallel closing operates", M_F, C_MFR),
      ("Thời gian chuyển mạch đạt yêu cầu thiết kế", "Transfer time meets the design requirement", M_T, C_SPEC),
      ("Chế độ tự động và bằng tay đều hoạt động", "Both automatic and manual modes operate", M_F),
      ("Thử chuyển và chuyển về khi có điện lưới trở lại", "Transfer and re-transfer on mains restoration tested", M_F),
      ("Tín hiệu trạng thái truyền về BMS đúng", "Status signals to BMS correct", M_F),
      ("Nhãn, sơ đồ và hướng dẫn vận hành dán tại tủ", "Labels, schematic and operating instructions on the panel", M_V)),

    F("ELE-306", "ELE", "Đèn chiếu sáng và công tắc", "Lighting and switches", "TCVN 9206:2012",
      ("Chủng loại đèn, công suất, nhiệt độ màu đúng thiết kế", "Luminaire type, wattage and colour temperature as designed", M_C, C_DWG),
      ("Vị trí đèn đúng bản vẽ phối hợp trần", "Positions as per the coordinated ceiling drawing", M_M, C_DWG),
      ("Lắp chắc chắn, thẳng hàng, cùng cao độ", "Fixed securely, aligned and at a consistent level", M_M),
      ("Công tắc đúng cao độ, đúng nhóm điều khiển", "Switches at the correct height and controlling the right group", M_M, C_DWG),
      ("Đấu nối chắc chắn, dây bảo vệ đấu đủ", "Terminations secure and CPC connected", M_V, "TCVN 7447"),
      ("Đèn sự cố, đèn chỉ dẫn thoát nạn đúng vị trí và hướng", "Emergency and exit luminaires correctly located and oriented", M_C, "QCVN 06:2022/BXD"),
      ("Thử đèn sự cố duy trì đủ thời gian quy định", "Emergency luminaires sustain the required duration", M_T, "TCVN 3890:2023"),
      ("Đo độ rọi đạt giá trị thiết kế", "Illuminance measured meets the design value", M_M, "TCVN 7114"),
      ("Bật/tắt toàn bộ theo nhóm, không nhầm mạch", "All groups switch correctly with no crossed circuits", M_F)),

    F("ELE-307", "ELE", "Ổ cắm và thiết bị đầu cuối", "Socket outlets and terminal devices", "TCVN 9206:2012",
      ("Chủng loại, cấp bảo vệ đúng môi trường lắp đặt", "Type and IP rating suit the location", M_C, C_DWG),
      ("Cao độ và vị trí đúng bản vẽ", "Height and position as per drawing", M_M, C_DWG),
      ("Mặt ổ ngang bằng, không nghiêng, khít tường", "Face plates flush, level and tight to the wall", M_M),
      ("Đấu dây đúng cực L–N–PE", "Wired to the correct L–N–PE terminals", M_V, "TCVN 7447"),
      ("Thử phân cực và thông mạch dây bảo vệ từng ổ", "Polarity and CPC continuity tested at each outlet", M_T, "TCVN 7447"),
      ("Thiết bị RCD bảo vệ tác động đúng dòng và thời gian", "RCD protection trips at the correct current and time", M_T, "TCVN 7447"),
      ("Ổ cắm khu vực ẩm ướt có nắp che, đúng cấp IP", "Outlets in wet areas have covers to the correct IP rating", M_V, "TCVN 9206:2012"),
      ("Nhãn mạch dán tại mặt ổ hoặc theo quy định dự án", "Circuit reference labelled as required by the project", M_V)),

    # ── 4xx nối đất và thử nghiệm ────────────────────────────────────────────────────────────
    F("ELE-401", "ELE", "Hệ thống nối đất", "Earthing system", "TCVN 9358:2012",
      ("Sơ đồ nối đất đúng thiết kế (TN-S, TT…)", "Earthing arrangement as designed (TN-S, TT…)", M_C, C_DWG),
      ("Cọc tiếp địa đủ số lượng, đủ độ sâu, đúng khoảng cách", "Electrodes to the required number, depth and spacing", M_M, C_DWG),
      ("Mối nối hàn hoá nhiệt hoặc ép đạt yêu cầu", "Exothermic or compression joints sound", M_V, C_MFR),
      ("Mối nối ngầm được bảo vệ chống ăn mòn", "Buried joints protected against corrosion", M_V),
      ("Điện trở nối đất đo được đạt giá trị thiết kế", "Measured earth resistance meets the design value", M_T, C_DWG),
      ("Hộp kiểm tra tiếp địa lắp đặt, tiếp cận được", "Test boxes installed and accessible", M_V, "TCVN 9358:2012"),
      ("Liên kết đẳng thế với kết cấu và các hệ kim loại", "Equipotential bonding to structure and metallic services", M_T, "TCVN 9358:2012"),
      ("Thanh nối đất chính có nhãn và sơ đồ", "Main earth bar labelled with a schedule", M_V),
      ("Ảnh chụp mối nối và cọc trước khi lấp", "Photographs of joints and electrodes before backfilling", M_D)),

    F("ELE-402", "ELE", "Thí nghiệm và đóng điện hệ thống điện", "Electrical testing and energisation", "TCVN 7447",
      ("Kiểm tra bằng mắt toàn hệ thống trước khi thử", "Full visual inspection before testing", M_V, "TCVN 7447"),
      ("Thông mạch dây bảo vệ và dây liên kết đẳng thế", "Continuity of protective and bonding conductors", M_T, "TCVN 7447"),
      ("Điện trở cách điện từng mạch đạt giá trị tối thiểu", "Insulation resistance of each circuit at or above the minimum", M_T, "TCVN 7447"),
      ("Phân cực đúng trên toàn hệ thống", "Polarity correct throughout", M_T, "TCVN 7447"),
      ("Điện trở vòng lặp sự cố đạt yêu cầu cắt tự động", "Earth-fault loop impedance permits automatic disconnection", M_T, "TCVN 7447"),
      ("RCD tác động đúng dòng và đúng thời gian", "RCDs trip at the correct current and time", M_T, "TCVN 7447"),
      ("Thứ tự pha và cân bằng tải giữa các pha", "Phase sequence correct and load balanced across phases", M_T),
      ("Cài đặt bảo vệ đúng giá trị được duyệt", "Protection settings as approved", M_D, C_SPEC),
      ("Thử vận hành từng mạch sau khi đóng điện", "Each circuit function-tested after energisation", M_F),
      ("Biên bản thí nghiệm đầy đủ, có chữ ký các bên", "Test records complete and signed by all parties", M_D, "NĐ 06/2021 Điều 21")),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  LTN · Chống sét và nối đất chống sét
# ═══════════════════════════════════════════════════════════════════════════════════════════════

LTN = [
    F("LTN-101", "LTN", "Kim thu sét và bộ phận thu sét", "Air terminals and the air-termination system",
      "TCVN 9385:2012",
      ("Vị trí, chiều cao kim thu sét đúng thiết kế", "Air-terminal positions and heights as designed", M_M, C_DWG),
      ("Vùng bảo vệ bao trùm toàn bộ công trình", "Zone of protection covers the whole structure", M_C, "TCVN 9385:2012"),
      ("Kim, đế, cột đỡ cố định chắc chắn, chịu được tải gió", "Terminals, bases and masts fixed to resist wind load", M_V, C_DWG),
      ("Vật liệu, tiết diện đúng tiêu chuẩn", "Material and cross-section to standard", M_M, "TCVN 9385:2012"),
      ("Kết nối với dây xuống chắc chắn, chống ăn mòn", "Connection to down conductors sound and corrosion-protected", M_V),
      ("Không có bộ phận kim loại nhô cao ngoài vùng bảo vệ", "No metallic parts projecting outside the protected zone", M_V)),

    F("LTN-102", "LTN", "Dây xuống và liên kết", "Down conductors and bonding", "TCVN 9385:2012",
      ("Số lượng và khoảng cách dây xuống đạt yêu cầu", "Number and spacing of down conductors meet the requirement", M_M, "TCVN 9385:2012"),
      ("Tuyến dây xuống ngắn, thẳng, không uốn gấp", "Routes short and straight with no tight bends", M_V, "TCVN 9385:2012"),
      ("Kẹp cố định đủ số lượng, đúng khoảng cách", "Fixing clips complete and correctly spaced", M_M, C_MFR),
      ("Liên kết đẳng thế với kết cấu kim loại và hệ MEP", "Equipotential bonding to metallic structure and MEP services", M_T, "TCVN 9358:2012"),
      ("Khoảng cách an toàn tới hệ thống điện, viễn thông", "Separation distance to power and telecom services", M_M, "TCVN 9385:2012"),
      ("Có hộp kiểm tra tại mỗi dây xuống", "Test joint at each down conductor", M_V, "TCVN 9385:2012")),

    F("LTN-103", "LTN", "Hệ tiếp địa chống sét và đo kiểm", "Lightning earth system and testing", "TCVN 9385:2012",
      ("Cọc, băng tiếp địa đủ số lượng, đủ độ sâu", "Rods and tapes to the required number and depth", M_M, C_DWG),
      ("Mối nối hàn hoá nhiệt đạt yêu cầu", "Exothermic joints sound", M_V),
      ("Hoá chất giảm điện trở sử dụng đúng quy trình (nếu có)", "Resistance-reducing compound used to procedure where applied", M_V, C_MFR),
      ("Điện trở nối đất đo được đạt giá trị thiết kế", "Measured earth resistance meets the design value", M_T, C_DWG),
      ("Đo trong điều kiện thời tiết ghi nhận được", "Measurement taken with the weather conditions recorded", M_T),
      ("Thiết bị đo còn hạn hiệu chuẩn", "Test instrument within calibration", M_D),
      ("Liên thông hệ tiếp địa chống sét và tiếp địa an toàn theo thiết kế", "Lightning and safety earths interconnected as designed", M_T, "TCVN 9385:2012"),
      ("Biên bản đo có sơ đồ điểm đo", "Test record includes a plan of the measuring points", M_D)),

    F("LTN-104", "LTN", "Thiết bị chống sét lan truyền", "Surge protective devices", "TCVN 9888",
      ("Cấp SPD và vị trí lắp đúng thiết kế", "SPD class and location as designed", M_C, C_DWG),
      ("Chiều dài dây đấu nối SPD trong giới hạn quy định", "SPD connecting-lead length within the specified limit", M_M, "TCVN 9888"),
      ("Thiết bị bảo vệ trước SPD đúng chủng loại", "Back-up protection ahead of the SPD as specified", M_C, C_DWG),
      ("Chỉ thị trạng thái SPD hiển thị bình thường", "SPD status indicator shows healthy", M_V),
      ("Tín hiệu báo lỗi SPD đấu về tủ hoặc BMS", "SPD fault signal wired to the panel or BMS", M_F),
      ("Nhãn ghi ngày lắp và thông số thiết bị", "Label showing installation date and rating", M_V)),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  ELV · Điện nhẹ
# ═══════════════════════════════════════════════════════════════════════════════════════════════

ELV = [
    F("ELV-101", "ELV", "Hệ thống cáp cấu trúc", "Structured cabling", "TCVN 9250:2021 / ISO-IEC 11801",
      ("Chủng loại cáp, cấp (Cat) đúng thiết kế", "Cable type and category as designed", M_C, C_DWG),
      ("Chiều dài kênh không vượt giới hạn tiêu chuẩn", "Channel length within the standard limit", M_M, "ISO/IEC 11801"),
      ("Bán kính uốn, lực kéo trong giới hạn nhà sản xuất", "Bending radius and pulling tension within the maker's limits", M_M, C_MFR),
      ("Khoảng cách tới cáp động lực đạt yêu cầu chống nhiễu", "Separation from power cabling adequate against interference", M_M, "TCVN 9250:2021"),
      ("Bấm đầu đúng chuẩn T568A/B thống nhất toàn hệ", "Terminated to T568A/B consistently throughout", M_V, "ISO/IEC 11801"),
      ("Tháo xoắn tại đầu bấm không vượt giới hạn", "Untwist at termination within the limit", M_M, "ISO/IEC 11801"),
      ("Thử kênh truyền đạt cấp thiết kế, lưu kết quả từng cổng", "Channel test passes to the design category, results kept per port", M_T, "ISO/IEC 11801"),
      ("Đánh nhãn hai đầu theo quy ước dự án", "Both ends labelled to the project convention", M_V, C_SPEC),
      ("Sơ đồ đấu nối patch panel cập nhật", "Patch panel record updated", M_D)),

    F("ELV-102", "ELV", "Tủ rack và phòng thiết bị", "Racks and equipment rooms", "TCVN 9250:2021",
      ("Vị trí, kích thước rack đúng bản vẽ", "Rack position and size as per drawing", M_M, C_DWG),
      ("Rack cố định chắc chắn, cân bằng, có nối đất", "Rack fixed, level and earthed", M_T, "TCVN 9358:2012"),
      ("Khoảng cách thao tác trước và sau rack đạt yêu cầu", "Front and rear working clearances adequate", M_M, "TCVN 9250:2021"),
      ("Nguồn cấp kép, PDU đúng thiết kế", "Dual supply and PDUs as designed", M_C, C_DWG),
      ("Quản lý cáp gọn gàng, không chắn luồng khí", "Cable management tidy and not blocking airflow", M_V),
      ("Điều hoà, thông gió phòng thiết bị hoạt động", "Room cooling and ventilation operating", M_F, C_DWG),
      ("Chữa cháy phòng thiết bị đúng hồ sơ thẩm duyệt", "Room fire protection as appraised", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Kiểm soát vào ra phòng thiết bị hoạt động", "Room access control operating", M_F)),

    F("ELV-103", "ELV", "Hệ thống camera giám sát", "CCTV system", C_SPEC,
      ("Vị trí, hướng camera đúng bản vẽ và vùng phủ yêu cầu", "Camera positions and directions as per drawing and required coverage", M_C, C_DWG),
      ("Model, độ phân giải, ống kính đúng thiết kế", "Model, resolution and lens as designed", M_C, C_SUB),
      ("Giá đỡ chắc chắn, không rung, chống xoay", "Mounts rigid, vibration-free and tamper-resistant", M_V),
      ("Cấp nguồn PoE hoặc nguồn riêng đúng thiết kế", "PoE or dedicated supply as designed", M_C, C_DWG),
      ("Hình ảnh rõ nét ngày và đêm tại vùng yêu cầu", "Image clear by day and night across the required area", M_F, C_SPEC),
      ("Ghi hình lưu trữ đủ số ngày quy định", "Recording retained for the specified number of days", M_T, C_SPEC),
      ("Đồng bộ thời gian toàn hệ thống", "System time synchronised throughout", M_F),
      ("Phân quyền người dùng và nhật ký truy cập hoạt động", "User permissions and access log operating", M_F),
      ("Camera phục vụ thoát nạn, PCCC theo hồ sơ thẩm duyệt", "Cameras serving escape and fire duties as appraised", M_C, "Hồ sơ thẩm duyệt PCCC")),

    F("ELV-104", "ELV", "Kiểm soát ra vào", "Access control", C_SPEC,
      ("Vị trí đầu đọc, khoá từ đúng bản vẽ", "Reader and lock positions as per drawing", M_M, C_DWG),
      ("Khoá cửa thoát nạn tự nhả khi báo cháy và khi mất điện", "Escape door locks release on fire alarm and on power failure", M_F, "QCVN 06:2022/BXD"),
      ("Nút thoát khẩn cấp lắp đúng vị trí, hoạt động", "Emergency release button correctly located and operating", M_F, "QCVN 06:2022/BXD"),
      ("Đấu nối liên động với hệ báo cháy đúng thiết kế", "Interface to the fire alarm as designed", M_F, C_DWG),
      ("Phân quyền theo nhóm hoạt động đúng", "Group permissions operate correctly", M_F),
      ("Nhật ký ra vào ghi nhận đầy đủ", "Access log records correctly", M_F),
      ("Nguồn dự phòng duy trì đủ thời gian quy định", "Standby power sustains the required duration", M_T, C_SPEC)),

    F("ELV-105", "ELV", "Hệ thống âm thanh công cộng và thông báo", "Public address and voice alarm", "TCVN 3890:2023",
      ("Vị trí loa đúng bản vẽ, phủ hết khu vực yêu cầu", "Loudspeaker positions as per drawing, covering the required areas", M_C, C_DWG),
      ("Cáp loa chịu lửa cho tuyến phục vụ thoát nạn", "Fire-resisting cable on circuits serving escape", M_C, "QCVN 06:2022/BXD"),
      ("Phân vùng loa đúng phân vùng cháy", "Loudspeaker zoning matches the fire zoning", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Mức áp suất âm đo được đạt yêu cầu tại các vị trí", "Measured sound pressure level meets the requirement at each point", M_M, C_SPEC),
      ("Độ rõ lời thông báo đạt yêu cầu", "Speech intelligibility acceptable", M_T, C_SPEC),
      ("Ưu tiên thông báo khẩn cấp hoạt động đúng", "Emergency announcement priority operates correctly", M_F),
      ("Giám sát đứt/chập tuyến loa hoạt động", "Loudspeaker line fault monitoring operating", M_F),
      ("Nguồn dự phòng đủ thời gian quy định", "Standby power sustains the required duration", M_T, "TCVN 3890:2023")),

    F("ELV-106", "ELV", "Hệ thống quản lý toà nhà (BMS)", "Building management system", C_SPEC,
      ("Danh mục điểm (I/O) đúng bảng điểm được duyệt", "Point schedule matches the approved I/O list", M_C, C_DWG),
      ("Tủ điều khiển, bộ điều khiển lắp đúng vị trí, tiếp cận được", "Controllers and panels correctly located and accessible", M_V, C_DWG),
      ("Cảm biến lắp đúng vị trí đo, không bị ảnh hưởng cục bộ", "Sensors correctly located and free of local influence", M_V, C_MFR),
      ("Cảm biến được hiệu chuẩn, có chứng chỉ", "Sensors calibrated with certificates", M_D),
      ("Giá trị hiển thị khớp với đo bằng thiết bị chuẩn", "Displayed values agree with a reference instrument", M_T),
      ("Điều khiển tay/tự động và chuyển chế độ hoạt động đúng", "Manual/auto and mode changeover operate correctly", M_F),
      ("Cảnh báo phát sinh đúng ngưỡng, đúng ưu tiên", "Alarms raised at the correct thresholds and priorities", M_F, C_SPEC),
      ("Giao diện với PCCC, thang máy, máy phát theo thiết kế", "Interfaces to fire, lift and generator systems as designed", M_F, C_DWG),
      ("Xu hướng và báo cáo năng lượng hoạt động", "Trending and energy reporting operating", M_F, "QCVN 09:2017/BXD"),
      ("Chuyển giao mật khẩu quản trị và tài liệu cấu hình", "Administrator credentials and configuration documents handed over", M_D)),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  FF · Phòng cháy chữa cháy
# ═══════════════════════════════════════════════════════════════════════════════════════════════

FF = [
    F("FF-101", "FF", "Đường ống chữa cháy", "Fire-fighting pipework", "TCVN 7336:2021",
      ("Tuyến ống, đường kính đúng bản vẽ đã thẩm duyệt PCCC", "Routes and diameters as per the fire-authority appraised drawing", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Vật liệu ống, phụ kiện đúng chủng loại được kiểm định", "Pipe and fittings of the certified type", M_C, "TCVN 3890:2023"),
      ("Giá treo, gối đỡ đủ số lượng, đúng khoảng cách", "Hangers and supports complete and correctly spaced", M_M, "TCVN 7336:2021"),
      ("Giằng chống lắc lắp tại các vị trí quy định", "Sway bracing at the required positions", M_V, "TCVN 7336:2021"),
      ("Mối hàn, mối ren, khớp nối thực hiện đúng quy trình", "Welds, threads and couplings made to procedure", M_V, C_MFR),
      ("Súc rửa đường ống trước khi lắp đầu phun", "Pipework flushed before heads are fitted", M_W, "TCVN 7336:2021"),
      ("Thử áp lực đạt yêu cầu, giữ áp đủ thời gian quy định", "Pressure test passed and held for the specified duration", M_T, "TCVN 7336:2021"),
      ("Chèn chống cháy tại vị trí xuyên tường, xuyên sàn", "Fire-stopping at wall and floor penetrations", M_V, "QCVN 06:2022/BXD"),
      ("Sơn, nhãn nhận biết đường ống theo quy định", "Pipework painted and labelled as required", M_V, "TCVN 3890:2023")),

    F("FF-102", "FF", "Hệ thống chữa cháy tự động sprinkler", "Automatic sprinkler system", "TCVN 7336:2021",
      ("Chủng loại đầu phun, hệ số K, nhiệt độ tác động đúng thiết kế", "Head type, K-factor and operating temperature as designed", M_C, "TCVN 7336:2021"),
      ("Khoảng cách đầu phun tới trần, tới tường và giữa các đầu", "Head clearance to ceiling, to walls and between heads", M_M, "TCVN 7336:2021"),
      ("Không có vật cản dưới đầu phun trong vùng quy định", "No obstructions below heads within the specified zone", M_V, "TCVN 7336:2021"),
      ("Đầu phun đúng hướng, không bị sơn, không hư hỏng", "Heads correctly oriented, unpainted and undamaged", M_V),
      ("Van chặn có khoá và giám sát trạng thái", "Control valves locked and monitored", M_F, "TCVN 7336:2021"),
      ("Van báo động, công tắc dòng chảy lắp đúng và tác động", "Alarm valve and flow switch installed and operating", M_T, "TCVN 7336:2021"),
      ("Thử dòng chảy tại điểm thử cuối tuyến", "Flow test at the end-of-line test point", M_T, "TCVN 7336:2021"),
      ("Đầu phun dự phòng và dụng cụ thay thế để tại chỗ", "Spare heads and wrench kept on site", M_V, "TCVN 7336:2021"),
      ("Liên động tín hiệu về trung tâm báo cháy", "Signals interfaced to the fire alarm panel", M_F, "TCVN 5738:2021")),

    F("FF-103", "FF", "Họng nước chữa cháy trong nhà và ngoài nhà", "Internal and external fire hydrants",
      "TCVN 3890:2023",
      ("Vị trí họng nước đúng bản vẽ thẩm duyệt, tiếp cận được", "Hydrant positions as appraised and accessible", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Tủ, cuộn vòi, lăng phun đầy đủ, đúng chủng loại kiểm định", "Cabinet, hose and nozzle complete and of the certified type", M_V, "TCVN 3890:2023"),
      ("Cao độ lắp đặt đúng quy định", "Mounting height as required", M_M, "TCVN 3890:2023"),
      ("Áp lực và lưu lượng tại họng bất lợi nhất đạt yêu cầu", "Pressure and flow at the most remote hydrant meet the requirement", M_T, "TCVN 3890:2023"),
      ("Van khoá đóng mở nhẹ nhàng, không rò rỉ", "Valves operate freely with no leakage", M_F),
      ("Họng tiếp nước cho xe chữa cháy đúng vị trí, có biển báo", "Fire brigade inlet correctly located and signed", M_V, "TCVN 3890:2023"),
      ("Đường tiếp cận cho xe chữa cháy thông thoáng", "Fire appliance access route clear", M_V, "QCVN 06:2022/BXD")),

    F("FF-104", "FF", "Máy bơm chữa cháy", "Fire pumps", "TCVN 3890:2023",
      ("Lưu lượng, cột áp bơm đúng thiết kế được thẩm duyệt", "Pump flow and head as appraised", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Bơm chính, bơm dự phòng, bơm bù áp lắp đủ", "Duty, standby and jockey pumps all installed", M_V, C_DWG),
      ("Nguồn điện ưu tiên và nguồn dự phòng đấu nối đúng", "Priority and standby supplies correctly connected", M_C, C_DWG),
      ("Tủ điều khiển bơm hoạt động ở chế độ tự động", "Pump controller operating in automatic", M_F, "TCVN 3890:2023"),
      ("Bơm khởi động đúng ngưỡng áp suất cài đặt", "Pumps start at the set pressure thresholds", M_T, C_SPEC),
      ("Bơm chạy không dừng cho tới khi dừng bằng tay (bơm chính)", "Duty pump runs until manually stopped", M_F, "TCVN 3890:2023"),
      ("Thử lưu lượng theo đường thử, đạt đường đặc tính", "Flow test along the test line matches the pump curve", M_T, C_MFR),
      ("Bể nước chữa cháy đủ dung tích dự trữ theo thiết kế", "Fire water tank holds the designed reserve volume", M_M, "TCVN 3890:2023"),
      ("Tín hiệu trạng thái, sự cố bơm về trung tâm báo cháy", "Pump run and fault signals to the fire alarm panel", M_F, "TCVN 5738:2021")),

    F("FF-105", "FF", "Hệ thống báo cháy tự động", "Automatic fire alarm system", "TCVN 5738:2021",
      ("Chủng loại đầu báo phù hợp môi trường từng khu vực", "Detector types suit each area", M_C, "TCVN 5738:2021"),
      ("Vị trí, khoảng cách đầu báo đạt yêu cầu tiêu chuẩn", "Detector positions and spacing meet the standard", M_M, "TCVN 5738:2021"),
      ("Khoảng cách tới tường, dầm, miệng gió đạt yêu cầu", "Clearance to walls, beams and air outlets acceptable", M_M, "TCVN 5738:2021"),
      ("Nút ấn báo cháy đúng vị trí trên đường thoát nạn", "Manual call points on escape routes as required", M_C, "TCVN 5738:2021"),
      ("Cáp tín hiệu chịu lửa đúng chủng loại", "Signal cable fire-resisting and of the correct type", M_C, "QCVN 06:2022/BXD"),
      ("Phân vùng báo cháy đúng hồ sơ thẩm duyệt", "Zoning as per the appraised design", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Thử tác động từng đầu báo, hiển thị đúng địa chỉ", "Each detector tested and reports the correct address", M_T, "TCVN 5738:2021"),
      ("Chuông, còi, đèn báo động hoạt động, đủ mức âm", "Sounders and beacons operate at the required level", M_T, "TCVN 3890:2023"),
      ("Liên động: thang máy, cửa, quạt, chữa cháy hoạt động đúng", "Cause-and-effect to lifts, doors, fans and suppression correct", M_F, "Hồ sơ thẩm duyệt PCCC"),
      ("Nguồn dự phòng duy trì đủ thời gian quy định", "Standby power sustains the required duration", M_T, "TCVN 5738:2021"),
      ("Ma trận nguyên nhân — hệ quả được thử toàn bộ và lưu hồ sơ", "Full cause-and-effect matrix tested and recorded", M_T, "Hồ sơ thẩm duyệt PCCC")),

    F("FF-106", "FF", "Chữa cháy bằng khí", "Gaseous fire suppression", "TCVN 3890:2023",
      ("Loại khí, khối lượng bình đúng tính toán được thẩm duyệt", "Agent type and cylinder mass as appraised", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Bình chứa cố định chắc chắn, còn hạn kiểm định", "Cylinders securely fixed and within inspection date", M_D),
      ("Đầu phun đúng số lượng, đúng vị trí, đúng hướng", "Nozzles correct in number, position and orientation", M_C, C_DWG),
      ("Độ kín phòng đạt yêu cầu (thử cửa quạt nếu quy định)", "Room integrity acceptable — door-fan test where required", M_T, C_SPEC),
      ("Van xả áp phòng lắp đúng kích thước và vị trí", "Room pressure-relief vent of the correct size and position", M_M, C_DWG),
      ("Còi, đèn cảnh báo trước khi xả khí hoạt động", "Pre-discharge alarms and beacons operate", M_F),
      ("Nút xả bằng tay và nút huỷ xả lắp đúng, hoạt động", "Manual release and abort stations installed and operating", M_F),
      ("Thử liên động không xả khí, ghi nhận đầy đủ", "Interlock tested without discharge and fully recorded", M_T),
      ("Biển cảnh báo, hướng dẫn thoát nạn dán tại cửa phòng", "Warning and escape signage at the room entrance", M_V)),

    F("FF-107", "FF", "Chống cháy thụ động và chèn bịt", "Passive fire protection and fire-stopping",
      "QCVN 06:2022/BXD",
      ("Vật liệu chèn bịt đúng hệ được kiểm định cho cấu tạo đó", "Fire-stopping system certified for that construction", M_C, "QCVN 06:2022/BXD"),
      ("Giới hạn chịu lửa đạt yêu cầu của bộ phận ngăn cháy", "Fire rating achieves the requirement for that compartment element", M_C, "QCVN 06:2022/BXD"),
      ("Thi công đúng chiều dày, đúng chi tiết được kiểm định", "Installed to the certified thickness and detail", M_M, C_MFR),
      ("Chèn kín toàn bộ khe hở quanh ống, cáp, máng", "All gaps around pipes, cables and trays fully sealed", M_V),
      ("Không có tuyến MEP xuyên qua sau khi đã chèn bịt", "No MEP services penetrating after sealing", M_V),
      ("Dán nhãn nhận biết tại từng vị trí chèn bịt", "Identification label at each penetration seal", M_V, C_SPEC),
      ("Ảnh chụp từng vị trí trước và sau khi chèn bịt", "Photographs of each penetration before and after", M_D),
      ("Sổ theo dõi vị trí chèn bịt được lập và cập nhật", "Fire-stopping register created and maintained", M_D)),

    F("FF-108", "FF", "Hệ thống tăng áp, hút khói", "Pressurisation and smoke control", "QCVN 06:2022/BXD",
      ("Quạt, ống gió đúng thiết kế được thẩm duyệt", "Fans and ductwork as appraised", M_C, "Hồ sơ thẩm duyệt PCCC"),
      ("Ống gió chịu lửa đúng giới hạn quy định", "Ductwork fire-rated to the required limit", M_C, "QCVN 06:2022/BXD"),
      ("Van chặn lửa, van khói lắp đúng vị trí và thao tác được", "Fire and smoke dampers correctly located and operable", M_F, "QCVN 06:2022/BXD"),
      ("Chênh áp buồng thang, sảnh đệm đạt giá trị quy định", "Stair and lobby pressure differential meets the requirement", M_M, "QCVN 06:2022/BXD"),
      ("Lực mở cửa thoát nạn không vượt giới hạn cho phép", "Escape door opening force within the permitted limit", M_M, "QCVN 06:2022/BXD"),
      ("Lưu lượng hút khói đạt yêu cầu tại từng tầng", "Smoke extract flow meets the requirement on each floor", M_M, "QCVN 06:2022/BXD"),
      ("Quạt khởi động đúng theo tín hiệu báo cháy", "Fans start on the correct fire alarm signal", M_F, "Hồ sơ thẩm duyệt PCCC"),
      ("Nguồn điện ưu tiên cho quạt hoạt động khi mất điện lưới", "Priority supply keeps fans running on mains failure", M_T),
      ("Bù khí cấp vào đủ để hệ hút khói làm việc", "Make-up air adequate for the extract system to work", M_M, "QCVN 06:2022/BXD")),

    F("FF-109", "FF", "Phương tiện chữa cháy ban đầu và biển báo", "First-aid fire equipment and signage",
      "TCVN 3890:2023",
      ("Số lượng, loại bình chữa cháy đúng danh mục được duyệt", "Extinguisher number and type as per the approved schedule", M_C, "TCVN 3890:2023"),
      ("Vị trí bố trí, cao độ treo đúng quy định", "Positions and mounting heights as required", M_M, "TCVN 3890:2023"),
      ("Bình còn hạn kiểm định, kim áp suất trong vùng xanh", "Extinguishers in date with the gauge in the green", M_V),
      ("Biển chỉ dẫn thoát nạn đúng vị trí, nhìn thấy rõ", "Escape signage correctly positioned and clearly visible", M_V, "QCVN 06:2022/BXD"),
      ("Đèn chỉ dẫn thoát nạn sáng khi mất điện, đủ thời gian", "Escape luminaires operate on power failure for the required time", M_T, "TCVN 3890:2023"),
      ("Sơ đồ thoát nạn dán tại vị trí quy định trên mỗi tầng", "Escape plans posted where required on each floor", M_V, "TCVN 3890:2023"),
      ("Đường thoát nạn không bị cản trở", "Escape routes unobstructed", M_V, "QCVN 06:2022/BXD")),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  HVAC · Thông gió và điều hoà không khí
# ═══════════════════════════════════════════════════════════════════════════════════════════════

HVAC = [
    # ── 1xx phía gió ─────────────────────────────────────────────────────────────────────────
    F("HVAC-101", "HVAC", "Ống gió và phụ kiện", "Ductwork and accessories", "TCVN 5687",
      ("Tuyến, kích thước ống gió đúng bản vẽ được duyệt", "Routes and duct sizes as per the approved drawing", M_C, C_DWG),
      ("Vật liệu, chiều dày tôn đúng theo cấp áp suất", "Material and sheet gauge correct for the pressure class", M_M, C_SPEC),
      ("Mối nối kín, gioăng đầy đủ, không rò rỉ nhìn thấy", "Joints sealed, gaskets complete, no visible leakage", M_V),
      ("Giá treo đủ số lượng, đúng khoảng cách, có đệm chống rung", "Hangers complete, correctly spaced, with anti-vibration pads", M_M, C_MFR),
      ("Ống gió không đè lên trần, không treo vào hệ khác", "Ductwork not bearing on ceilings or hung from other services", M_V),
      ("Cửa thăm vệ sinh bố trí tại vị trí cần tiếp cận", "Access doors where cleaning access is needed", M_V, C_SPEC),
      ("Vệ sinh bên trong ống trước khi đóng trần", "Duct interior cleaned before the ceiling is closed", M_V),
      ("Nhãn nhận biết tuyến và hướng gió", "Route labels and airflow direction marked", M_V),
      ("Ống gió chịu lửa đúng cấu tạo được thẩm duyệt", "Fire-rated ductwork built to the appraised detail", M_C, "QCVN 06:2022/BXD")),

    F("HVAC-102", "HVAC", "Thử rò rỉ đường ống gió", "Duct leakage test", C_SPEC,
      ("Đoạn thử được xác định và cô lập đúng quy trình", "Test section defined and isolated to procedure", M_D, C_MS),
      ("Thiết bị thử còn hạn hiệu chuẩn", "Test equipment within calibration", M_D),
      ("Áp suất thử đạt giá trị quy định và ổn định", "Test pressure reached and held stable", M_T, C_SPEC),
      ("Lưu lượng rò rỉ không vượt cấp kín yêu cầu", "Leakage rate within the required tightness class", M_T, C_SPEC),
      ("Vị trí rò rỉ được xử lý và thử lại", "Leaks made good and retested", M_T),
      ("Biên bản thử ghi rõ đoạn, áp suất, kết quả", "Test record states section, pressure and result", M_D)),

    F("HVAC-103", "HVAC", "Bảo ôn ống gió", "Duct insulation", "QCVN 09:2017/BXD",
      ("Vật liệu, chiều dày bảo ôn đúng thiết kế", "Insulation material and thickness as designed", M_M, C_DWG),
      ("Bảo ôn chỉ thi công sau khi thử rò rỉ đạt", "Insulation applied only after a passed leakage test", M_D),
      ("Lớp cách hơi liên tục, mối nối dán kín", "Vapour barrier continuous with sealed joints", M_V, C_MFR),
      ("Không hở tại giá treo, tại co, tại tê", "No gaps at hangers, bends or tees", M_V),
      ("Bảo ôn ngoài trời có lớp bảo vệ chống thời tiết", "External insulation weather-protected", M_V, C_SPEC),
      ("Không đọng sương trên bề mặt khi vận hành", "No condensation on the surface in operation", M_V)),

    F("HVAC-104", "HVAC", "Van gió, van chặn lửa, miệng gió", "Dampers, fire dampers and terminals", "TCVN 5687",
      ("Van gió lắp đúng vị trí, thao tác được, có cần chỉ thị", "Dampers correctly located, operable, with position indicator", M_F, C_DWG),
      ("Van chặn lửa đúng chủng loại kiểm định, đúng vị trí ngăn cháy", "Fire dampers of the certified type at compartment lines", M_C, "QCVN 06:2022/BXD"),
      ("Van chặn lửa có cửa thăm tiếp cận được để bảo trì", "Access panel to each fire damper for maintenance", M_V, "QCVN 06:2022/BXD"),
      ("Thử đóng van chặn lửa theo tín hiệu báo cháy", "Fire damper closure tested on the fire alarm signal", M_T, "Hồ sơ thẩm duyệt PCCC"),
      ("Miệng gió đúng chủng loại, kích thước, hướng thổi", "Terminals of the correct type, size and throw direction", M_C, C_DWG),
      ("Miệng gió lắp phẳng, thẳng hàng với trần", "Terminals flush and aligned with the ceiling", M_M),
      ("Hộp gió, ống mềm không bị gấp, không quá dài", "Plenums and flexible ducts not kinked or over-length", M_M, C_SPEC)),

    # ── 2xx phía nước ────────────────────────────────────────────────────────────────────────
    F("HVAC-201", "HVAC", "Đường ống nước lạnh, nước ngưng", "Chilled water and condensate pipework", "TCVN 5687",
      ("Tuyến, đường kính ống đúng bản vẽ", "Routes and diameters as per drawing", M_C, C_DWG),
      ("Vật liệu ống, phụ kiện đúng chủng loại được duyệt", "Pipe and fittings as approved", M_C, C_SUB),
      ("Độ dốc ống nước ngưng đủ để thoát tự chảy", "Condensate pipe falls adequate for gravity drainage", M_M, C_DWG),
      ("Giá đỡ đủ số lượng, đúng khoảng cách, có gối trượt", "Supports complete, correctly spaced, with slide bearings", M_M, C_MFR),
      ("Van chặn, van cân bằng, van một chiều lắp đúng vị trí", "Isolating, balancing and check valves correctly located", M_C, C_DWG),
      ("Điểm xả khí đặt tại vị trí cao, điểm xả cặn tại vị trí thấp", "Air vents at high points and drains at low points", M_V, C_DWG),
      ("Thử áp lực đạt yêu cầu, giữ áp đủ thời gian", "Pressure test passed and held for the required duration", M_T, C_SPEC),
      ("Súc rửa, xử lý hoá chất đường ống trước khi chạy", "Pipework flushed and chemically treated before operation", M_W, C_SPEC),
      ("Bảo ôn đúng chiều dày, kín mạch hơi", "Insulation of the correct thickness with a continuous vapour barrier", M_M, "QCVN 09:2017/BXD")),

    F("HVAC-202", "HVAC", "Đường ống gas lạnh", "Refrigerant pipework", C_MFR,
      ("Đường kính, chiều dài tuyến trong giới hạn nhà sản xuất", "Diameter and run length within the maker's limits", M_M, C_MFR),
      ("Ống đồng đúng chủng loại, chiều dày thành ống đạt yêu cầu", "Copper of the correct grade and wall thickness", M_M, C_SUB),
      ("Hàn trong môi trường khí trơ, mối hàn sạch", "Brazed under inert gas with clean joints", M_W, C_MFR),
      ("Bẫy dầu, độ dốc đúng chỉ dẫn nhà sản xuất", "Oil traps and gradients as instructed", M_V, C_MFR),
      ("Thử kín bằng khí nitơ đạt áp suất và thời gian quy định", "Nitrogen pressure test to the specified pressure and duration", M_T, C_MFR),
      ("Hút chân không đạt độ chân không và giữ ổn định", "Evacuation reaches and holds the required vacuum", M_T, C_MFR),
      ("Nạp gas đúng chủng loại và đúng khối lượng tính toán", "Charged with the correct refrigerant to the calculated mass", M_M, C_MFR),
      ("Bảo ôn kín toàn tuyến, kể cả tại co và giá đỡ", "Insulation continuous including bends and supports", M_V),
      ("Nhật ký nạp gas và biên bản thử lưu đầy đủ", "Charging log and test records retained", M_D)),

    # ── 3xx thiết bị ─────────────────────────────────────────────────────────────────────────
    F("HVAC-301", "HVAC", "Lắp đặt AHU / FCU", "AHU and FCU installation", C_MFR,
      ("Model, công suất đúng bảng thiết bị được duyệt", "Model and capacity as per the approved schedule", M_C, C_SUB),
      ("Vị trí, cao độ lắp đúng bản vẽ, đủ không gian bảo trì", "Position and level as per drawing with maintenance access", M_M, C_DWG),
      ("Giá treo, bệ máy, giảm chấn đúng thiết kế", "Supports, base and vibration isolators as designed", M_V, C_MFR),
      ("Đấu nối ống mềm, khớp nối mềm tại đầu máy", "Flexible connections at the unit", M_V, C_MFR),
      ("Khay nước ngưng có độ dốc, bẫy nước đúng chiều cao", "Condensate tray falls correctly with a trap of the correct depth", M_M, C_MFR),
      ("Thử xả nước ngưng thoát hết, không tràn", "Condensate drain test clears fully with no overflow", M_T),
      ("Lọc gió đúng cấp, lắp đúng chiều, kín khung", "Filters of the correct grade, correctly oriented and sealed", M_V, C_SPEC),
      ("Chiều quay quạt đúng, dòng điện trong định mức", "Fan rotation correct and current within rating", M_T, C_MFR),
      ("Cách âm, chống rung không truyền sang kết cấu", "Acoustic and vibration isolation not bridged to structure", M_V),
      ("Đấu nối điều khiển và tín hiệu về BMS đúng bảng điểm", "Control and BMS signals wired to the point schedule", M_F, C_DWG)),

    F("HVAC-302", "HVAC", "Máy làm lạnh (chiller)", "Chiller", C_MFR,
      ("Model, công suất lạnh đúng thiết kế", "Model and cooling capacity as designed", M_C, C_SUB),
      ("Bệ máy, giảm chấn, cân chỉnh đúng hướng dẫn", "Plinth, isolators and alignment as instructed", M_M, C_MFR),
      ("Khoảng cách bảo trì và thông thoáng xung quanh đạt yêu cầu", "Maintenance and ventilation clearances adequate", M_M, C_MFR),
      ("Đấu nối nước vào/ra đúng chiều, có van chặn và lọc", "Water connections correct with isolating valves and strainer", M_V, C_DWG),
      ("Lưu lượng nước qua bình bay hơi, bình ngưng đạt thiết kế", "Water flow through evaporator and condenser as designed", M_M, C_SPEC),
      ("Nguồn điện, bảo vệ đúng thiết kế, siết đúng mô men", "Power supply and protection as designed, torqued correctly", M_T, C_MFR),
      ("Chạy thử ghi nhận áp suất, nhiệt độ, dòng điện", "Test run with pressures, temperatures and currents recorded", M_T, C_MFR),
      ("Bảo vệ áp suất cao/thấp, bảo vệ dòng chảy hoạt động", "High/low pressure and flow protections operate", M_F, C_MFR),
      ("Kết nối BMS đọc đúng trạng thái và cảnh báo", "BMS connection reports correct status and alarms", M_F, C_DWG),
      ("Nhà sản xuất nghiệm thu và cấp chứng nhận chạy thử", "Manufacturer's commissioning attendance and certificate", M_D)),

    F("HVAC-303", "HVAC", "Tháp giải nhiệt", "Cooling tower", C_MFR,
      ("Model, lưu lượng, nhiệt độ vào/ra đúng thiết kế", "Model, flow and entering/leaving temperatures as designed", M_C, C_SUB),
      ("Kết cấu đỡ, chống rung, cố định chịu tải gió", "Support structure, isolation and wind fixings adequate", M_V, C_DWG),
      ("Khoảng cách tới vật cản đủ để không tuần hoàn khí nóng", "Clearance adequate to avoid hot-air recirculation", M_M, C_MFR),
      ("Tấm tản nước, tấm chắn nước lắp đủ, không hư hỏng", "Fill and drift eliminators complete and undamaged", M_V),
      ("Hệ thống phân phối nước đều, không tắc", "Water distribution even and unblocked", M_F),
      ("Van phao, van xả đáy, xả tràn hoạt động", "Float valve, bleed and overflow operate", M_F),
      ("Chiều quay quạt đúng, độ rung trong giới hạn", "Fan rotation correct and vibration within limits", M_T, C_MFR),
      ("Xử lý nước tuần hoàn theo phương án được duyệt", "Circulating water treatment as approved", M_D, C_SPEC),
      ("Biện pháp phòng ngừa vi sinh được thực hiện và ghi nhận", "Microbiological control measures applied and recorded", M_D, C_SPEC)),

    F("HVAC-304", "HVAC", "Quạt thông gió, hút mùi", "Ventilation and extract fans", "TCVN 5687",
      ("Model, lưu lượng, cột áp đúng bảng thiết bị", "Model, flow and pressure as per the equipment schedule", M_C, C_SUB),
      ("Vị trí lắp đúng bản vẽ, tiếp cận được để bảo trì", "Position as per drawing with maintenance access", M_M, C_DWG),
      ("Giá đỡ, giảm chấn, khớp nối mềm lắp đủ", "Supports, isolators and flexible connections complete", M_V, C_MFR),
      ("Chiều quay đúng, dòng điện làm việc trong định mức", "Rotation correct, running current within rating", M_T),
      ("Độ ồn và độ rung trong giới hạn cho phép", "Noise and vibration within the permitted limits", M_M, C_SPEC),
      ("Miệng thải đặt đúng vị trí, không hút lại vào cấp gió", "Discharge positioned to avoid short-circuiting to intake", M_M, "TCVN 5687"),
      ("Quạt phục vụ PCCC đấu nguồn ưu tiên và liên động đúng", "Fire-duty fans on priority supply with correct interlock", M_F, "Hồ sơ thẩm duyệt PCCC")),

    # ── 4xx cân chỉnh và chạy thử ────────────────────────────────────────────────────────────
    F("HVAC-401", "HVAC", "Cân chỉnh lưu lượng gió (TAB)", "Air balancing (TAB)", C_SPEC,
      ("Hệ thống đã hoàn thiện, lọc sạch, cửa gió lắp đủ", "System complete, filters clean, all terminals fitted", M_V),
      ("Thiết bị đo còn hạn hiệu chuẩn", "Instruments within calibration", M_D),
      ("Lưu lượng tổng của từng AHU đạt thiết kế", "Total airflow of each AHU meets the design", M_M, C_DWG),
      ("Lưu lượng từng miệng gió trong dung sai cho phép", "Airflow at each terminal within tolerance", M_M, C_SPEC),
      ("Chênh áp qua lọc, qua dàn trong giới hạn", "Pressure drop across filters and coils within limits", M_M, C_MFR),
      ("Cân bằng áp suất giữa các khu vực theo thiết kế", "Pressure relationships between areas as designed", M_M, C_DWG),
      ("Van gió được khoá vị trí sau khi cân chỉnh", "Dampers locked in position after balancing", M_V),
      ("Báo cáo TAB đầy đủ, có sơ đồ và bảng số liệu", "TAB report complete with schematics and data tables", M_D)),

    F("HVAC-402", "HVAC", "Cân chỉnh lưu lượng nước", "Water balancing", C_SPEC,
      ("Hệ thống đã súc rửa, xả khí hoàn toàn", "System flushed and fully vented", M_W),
      ("Lọc Y được vệ sinh sau khi súc rửa", "Strainers cleaned after flushing", M_V),
      ("Lưu lượng qua từng nhánh, từng dàn đạt thiết kế", "Flow through each branch and coil meets the design", M_M, C_DWG),
      ("Chênh áp qua van cân bằng đạt giá trị tính toán", "Differential across balancing valves at the calculated value", M_M, C_SPEC),
      ("Bơm làm việc tại điểm trên đường đặc tính thiết kế", "Pumps operating at the design point on the curve", M_T, C_MFR),
      ("Van cân bằng được khoá và ghi vị trí cài đặt", "Balancing valves locked and settings recorded", M_V),
      ("Báo cáo cân chỉnh đầy đủ, có sơ đồ hệ thống", "Balancing report complete with a system schematic", M_D)),

    F("HVAC-403", "HVAC", "Chạy thử và nghiệm thu hệ thống HVAC", "HVAC commissioning and acceptance",
      "TCVN 5687",
      ("Tất cả hạng mục thành phần đã được nghiệm thu", "All component works already accepted", M_C, "NĐ 06/2021 Điều 21"),
      ("Chạy thử không tải toàn hệ thống, không sự cố", "No-load run of the whole system without fault", M_T),
      ("Chạy thử có tải đạt điều kiện thiết kế", "On-load run achieves the design condition", M_T, C_DWG),
      ("Nhiệt độ, độ ẩm phòng đạt yêu cầu thiết kế", "Room temperature and humidity meet the design", M_M, C_DWG),
      ("Chuyển chế độ, khởi động/dừng theo lịch hoạt động đúng", "Mode change and scheduled start/stop operate correctly", M_F),
      ("Liên động với hệ báo cháy hoạt động đúng ma trận", "Fire alarm interlocks operate to the cause-and-effect matrix", M_F, "Hồ sơ thẩm duyệt PCCC"),
      ("Cảnh báo và bảo vệ thiết bị tác động đúng", "Alarms and equipment protections operate correctly", M_F),
      ("Độ ồn tại khu vực sử dụng trong giới hạn", "Noise level in occupied areas within limits", M_M, C_SPEC),
      ("Bàn giao tài liệu O&M, sơ đồ hoàn công và đào tạo vận hành", "O&M manuals, as-builts and operator training handed over", M_D, "NĐ 06/2021 Điều 27")),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  PLU · Cấp thoát nước
# ═══════════════════════════════════════════════════════════════════════════════════════════════

PLU = [
    F("PLU-101", "PLU", "Đường ống cấp nước bên trong", "Internal water supply pipework", "TCVN 4513:1988",
      ("Tuyến, đường kính ống đúng bản vẽ được duyệt", "Routes and diameters as per the approved drawing", M_C, C_DWG),
      ("Vật liệu ống, phụ kiện đúng chủng loại được duyệt", "Pipe and fittings as approved", M_C, C_SUB),
      ("Mối nối thực hiện đúng quy trình nhà sản xuất", "Joints made to the maker's procedure", M_V, C_MFR),
      ("Giá đỡ đủ số lượng, đúng khoảng cách", "Supports complete and correctly spaced", M_M, C_MFR),
      ("Van chặn bố trí đủ để cô lập từng khu vực", "Isolating valves allow each area to be isolated", M_V, C_DWG),
      ("Thử áp lực đạt yêu cầu và giữ áp đủ thời gian", "Pressure test passed and held for the required duration", M_T, C_SPEC),
      ("Súc xả và khử trùng trước khi đưa vào sử dụng", "Flushed and disinfected before use", M_T, "QCVN 01-1:2018/BYT"),
      ("Bảo ôn, chống đọng sương nơi yêu cầu", "Insulation and condensation control where required", M_V, C_SPEC),
      ("Dán nhãn, đánh dấu hướng dòng chảy", "Labelled with flow direction marked", M_V),
      ("Chèn chống cháy tại vị trí xuyên tường, xuyên sàn", "Fire-stopping at wall and floor penetrations", M_V, "QCVN 06:2022/BXD")),

    F("PLU-102", "PLU", "Đường ống thoát nước và thông hơi", "Drainage and vent pipework", "TCVN 4474:1987",
      ("Tuyến, đường kính đúng bản vẽ", "Routes and diameters as per drawing", M_C, C_DWG),
      ("Độ dốc ống đạt yêu cầu tự chảy", "Gradients adequate for gravity flow", M_M, "TCVN 4474:1987"),
      ("Bẫy nước đủ chiều cao ngăn mùi tại mọi thiết bị", "Traps with the correct seal depth at every fixture", M_M, "TCVN 4474:1987"),
      ("Ống thông hơi đúng thiết kế, thoát lên mái đúng vị trí", "Vent pipes as designed and terminating correctly at roof", M_V, C_DWG),
      ("Cửa thăm, ống kiểm tra bố trí tại vị trí cần thiết", "Rodding eyes and access provided where needed", M_V, C_DWG),
      ("Giá đỡ đủ, ống không võng", "Supports complete, no sagging", M_M),
      ("Thử kín nước hoặc thử khói đạt yêu cầu", "Water or smoke tightness test passed", M_T, C_SPEC),
      ("Xả thử toàn tuyến thoát nhanh, không đọng, không trào ngược", "Full-flow discharge test drains freely with no backflow", M_F),
      ("Chống ồn cho ống thoát đi qua khu vực yên tĩnh", "Acoustic treatment where drainage passes quiet areas", M_V, C_SPEC)),

    F("PLU-103", "PLU", "Bể chứa nước", "Water storage tanks", "QCVN 01-1:2018/BYT",
      ("Dung tích, vật liệu bể đúng thiết kế", "Capacity and material as designed", M_C, C_DWG),
      ("Bể kín, có nắp đậy, chống côn trùng và ánh sáng", "Tank sealed, covered, insect- and light-proof", M_V, "QCVN 01-1:2018/BYT"),
      ("Ống vào, ra, tràn, xả cặn bố trí đúng thiết kế", "Inlet, outlet, overflow and drain as designed", M_V, C_DWG),
      ("Van phao, báo mức hoạt động đúng", "Float valve and level signals operate correctly", M_F),
      ("Thang, sàn thao tác an toàn, tiếp cận được để vệ sinh", "Safe access ladder and platform for cleaning", M_V, "QCVN 18:2021/BXD"),
      ("Thử kín nước 24 giờ không rò rỉ", "24-hour water tightness test with no leakage", M_T),
      ("Vệ sinh, khử trùng bể trước khi đưa vào sử dụng", "Tank cleaned and disinfected before use", M_W, "QCVN 01-1:2018/BYT"),
      ("Xét nghiệm mẫu nước đạt quy chuẩn nước sinh hoạt", "Water sample meets the domestic water regulation", M_T, "QCVN 01-1:2018/BYT"),
      ("Bể nước chữa cháy có dung tích dự trữ không dùng chung", "Fire reserve volume held and not drawn for domestic use", M_V, "TCVN 3890:2023")),

    F("PLU-104", "PLU", "Máy bơm nước sinh hoạt", "Domestic water pumps", C_MFR,
      ("Model, lưu lượng, cột áp đúng bảng thiết bị được duyệt", "Model, flow and head as per the approved schedule", M_C, C_SUB),
      ("Bệ máy, giảm chấn, khớp nối mềm lắp đúng", "Base, isolators and flexible connections correct", M_V, C_MFR),
      ("Van chặn, van một chiều, lọc lắp đủ và đúng chiều", "Isolating, check valves and strainer complete and correctly oriented", M_V, C_DWG),
      ("Đồng hồ áp suất, bình tích áp lắp đúng thiết kế", "Pressure gauges and accumulator as designed", M_V, C_DWG),
      ("Chiều quay đúng, dòng điện làm việc trong định mức", "Rotation correct and running current within rating", M_T),
      ("Luân phiên bơm chính/dự phòng hoạt động đúng", "Duty/standby alternation operates correctly", M_F),
      ("Bảo vệ chạy khô, bảo vệ quá tải tác động", "Dry-run and overload protections operate", M_F),
      ("Áp lực tại điểm bất lợi nhất đạt yêu cầu", "Pressure at the most remote fixture meets the requirement", M_M, C_DWG),
      ("Độ ồn, độ rung trong giới hạn cho phép", "Noise and vibration within permitted limits", M_M, C_SPEC)),

    F("PLU-105", "PLU", "Thoát nước mưa", "Rainwater drainage", "TCVN 7957:2023",
      ("Vị trí, đường kính phễu thu và ống đứng đúng thiết kế", "Outlet and downpipe positions and sizes as designed", M_C, C_DWG),
      ("Độ dốc mái về phễu thu đạt yêu cầu, không đọng nước", "Roof falls to outlets adequate with no ponding", M_M, C_DWG),
      ("Phễu thu có lưới chắn rác, tiếp cận được để vệ sinh", "Outlets have leaf guards and are accessible for cleaning", M_V),
      ("Chống thấm quanh phễu thu thi công đúng chi tiết", "Waterproofing around outlets to detail", M_V, C_DWG),
      ("Thử xả nước toàn mái, thoát hết trong thời gian quy định", "Full roof flood test drains within the specified time", M_T, C_SPEC),
      ("Ống đứng cố định chắc, có khớp giãn nở nơi cần", "Downpipes securely fixed with expansion joints where needed", M_V),
      ("Đấu nối vào hệ thống thoát ngoài nhà đúng cao độ", "Connection to the external system at the correct level", M_M, C_DWG)),

    F("PLU-106", "PLU", "Thoát nước thải và xử lý", "Foul drainage and treatment", "TCVN 7957:2023",
      ("Tuyến, cao độ, độ dốc cống đúng bản vẽ", "Routes, levels and gradients as per drawing", M_M, C_DWG),
      ("Hố ga đúng kích thước, có bậc lên xuống nơi cần", "Manholes of the correct size with step irons where required", M_M, C_DWG),
      ("Đáy hố ga tạo dòng, không đọng cặn", "Manhole benching formed to channel flow", M_V, "TCVN 7957:2023"),
      ("Nắp hố ga đúng tải trọng, ngang bằng mặt hoàn thiện", "Covers of the correct load class and flush with the finished level", M_M, C_DWG),
      ("Bể tách mỡ, bể tự hoại đúng dung tích thiết kế", "Grease trap and septic tank of the designed capacity", M_M, C_DWG),
      ("Thử kín nước tuyến cống đạt yêu cầu", "Drain tightness test passed", M_T, C_SPEC),
      ("Thông tắc thử bằng bi hoặc camera đạt yêu cầu", "Ball or CCTV survey confirms the line is clear", M_T, C_SPEC),
      ("Đấu nối ra hệ thống ngoài công trình được chấp thuận", "Connection to the external system approved", M_D),
      ("Nước thải sau xử lý đạt quy chuẩn xả thải", "Treated effluent meets the discharge regulation", M_T, "Giấy phép môi trường")),

    F("PLU-107", "PLU", "Nghiệm thu hoàn thành hệ thống cấp thoát nước", "Plumbing system completion",
      "TCVN 4513:1988 / TCVN 4474:1987",
      ("Toàn bộ hạng mục thành phần đã được nghiệm thu", "All component works already accepted", M_C, "NĐ 06/2021 Điều 21"),
      ("Thử áp lực toàn hệ thống đạt yêu cầu", "Whole-system pressure test passed", M_T, C_SPEC),
      ("Súc xả và khử trùng hoàn tất, có kết quả xét nghiệm", "Flushing and disinfection complete with test results", M_T, "QCVN 01-1:2018/BYT"),
      ("Vận hành thử toàn bộ thiết bị, không rò rỉ", "All fixtures operated with no leakage", M_F),
      ("Áp lực và lưu lượng tại điểm bất lợi nhất đạt thiết kế", "Pressure and flow at the most remote point meet the design", M_M, C_DWG),
      ("Thoát nước nhanh, không trào ngược, không mùi", "Drainage clears quickly with no backflow or odour", M_F),
      ("Đồng hồ nước lắp đặt, đọc được, đã ghi chỉ số bàn giao", "Meters installed, readable, handover reading recorded", M_D),
      ("Sơ đồ hoàn công, danh mục van và tài liệu O&M bàn giao", "As-builts, valve schedule and O&M manuals handed over", M_D, "NĐ 06/2021 Điều 27")),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  GEN · Liên bộ môn — giai đoạn, bàn giao, hồ sơ
# ═══════════════════════════════════════════════════════════════════════════════════════════════

GEN = [
    F("GEN-001", "GEN", "Biểu mẫu trống — tự soạn danh mục kiểm tra", "Blank form — write your own checklist",
      "", ("", "", "", "")),

    F("GEN-101", "GEN", "Nghiệm thu giai đoạn thi công", "Stage acceptance", "NĐ 06/2021 Điều 23",
      ("Phạm vi giai đoạn được xác định và thoả thuận bằng văn bản", "Stage scope defined and agreed in writing", M_D, "NĐ 06/2021 Điều 23"),
      ("Toàn bộ công việc trong giai đoạn đã có biên bản nghiệm thu", "Every work in the stage has an acceptance minute", M_C, "NĐ 06/2021 Điều 21"),
      ("Kết quả thí nghiệm của giai đoạn đầy đủ và đạt", "Stage test results complete and compliant", M_D),
      ("Sai lệch so với thiết kế đã được xử lý hoặc chấp thuận", "Deviations from design resolved or approved", M_D),
      ("Tồn tại chuyển tiếp được lập danh mục và ấn định thời hạn", "Carried-forward items listed with dates", M_D, "NĐ 06/2021 Điều 24"),
      ("Bản vẽ hoàn công của giai đoạn được lập và xác nhận", "Stage as-built drawings produced and endorsed", M_D, "NĐ 06/2021 Điều 26"),
      ("Ảnh chụp hiện trạng trước khi che khuất được lưu", "Photographic record before covering up retained", M_D),
      ("Điều kiện an toàn để chuyển sang giai đoạn tiếp theo", "Safe conditions to proceed to the next stage", M_V, "QCVN 18:2021/BXD")),

    F("GEN-102", "GEN", "Nghiệm thu hoàn thành hạng mục công trình", "Completion acceptance of a work item",
      "NĐ 06/2021 Điều 24",
      ("Hạng mục hoàn thành theo thiết kế được phê duyệt", "Work item complete to the approved design", M_C, C_DWG),
      ("Toàn bộ công việc thành phần đã được nghiệm thu", "All component works accepted", M_C, "NĐ 06/2021 Điều 21"),
      ("Kết quả thí nghiệm, chạy thử đạt yêu cầu", "Test and trial-run results acceptable", M_D, "NĐ 06/2021 Điều 24"),
      ("Văn bản chấp thuận về PCCC (nếu thuộc đối tượng)", "Fire-safety acceptance where applicable", M_D, "NĐ 06/2021 Điều 24"),
      ("Văn bản về bảo vệ môi trường (nếu thuộc đối tượng)", "Environmental clearance where applicable", M_D, "NĐ 06/2021 Điều 24"),
      ("Tồn tại còn lại không ảnh hưởng chịu lực, an toàn, công năng", "Remaining items affect neither strength, safety nor function", M_V, "NĐ 06/2021 Điều 24 khoản 3"),
      ("Hồ sơ hoàn thành hạng mục được tập hợp đầy đủ", "Completion dossier for the item assembled", M_D, "NĐ 06/2021 Điều 26"),
      ("Quy trình vận hành, bảo trì được bàn giao", "Operation and maintenance procedures handed over", M_D, "NĐ 06/2021 Điều 27"),
      ("Thời hạn bảo hành được xác định và ghi trong biên bản", "Warranty period determined and stated in the minute", M_D, "NĐ 06/2021 Điều 28")),

    F("GEN-103", "GEN", "Bàn giao công trình đưa vào sử dụng", "Handover of the works into use",
      "Luật Xây dựng Điều 124",
      ("Công trình đã được nghiệm thu hoàn thành", "The works has passed completion acceptance", M_C, "NĐ 06/2021 Điều 24"),
      ("Hồ sơ hoàn thành công trình bàn giao đầy đủ theo danh mục", "Completion dossier handed over in full per the schedule", M_D, "NĐ 06/2021 Điều 26"),
      ("Bản vẽ hoàn công đầy đủ, có xác nhận của các bên", "As-built drawings complete and endorsed by all parties", M_D),
      ("Quy trình vận hành, bảo trì và định mức bảo trì bàn giao", "Operation, maintenance procedures and schedules handed over", M_D, "NĐ 06/2021 Điều 27"),
      ("Đào tạo vận hành cho chủ quản lý sử dụng đã thực hiện", "Operator training delivered to the operating owner", M_D),
      ("Danh mục vật tư dự phòng, dụng cụ chuyên dụng bàn giao", "Spare parts and special tools handed over", M_D),
      ("Chìa khoá, mật khẩu, quyền quản trị hệ thống bàn giao", "Keys, passwords and system administrator rights handed over", M_D),
      ("Chỉ số công tơ điện, đồng hồ nước tại thời điểm bàn giao", "Electricity and water meter readings at handover", M_M),
      ("Thời hạn và điều kiện bảo hành được thống nhất", "Warranty period and conditions agreed", M_D, "NĐ 06/2021 Điều 28"),
      ("Biên bản bàn giao có chữ ký của các bên liên quan", "Handover minute signed by all parties", M_D, "Luật Xây dựng Điều 124")),
]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  The library, assembled
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
#  `adopted: False` on every one of them, and that flag is the point of this whole file's opening
#  paragraph. It rides on the form, reaches the browser through the catalogue, and shows on the
#  library screen and again in the readiness panel of any dossier compiled from an un-adopted form.
#  A project adopts a form by copying it in and reviewing it — an act the app records — and the
#  project's copy then carries `adopted: True` because somebody decided it should.

LIBRARY = OSM + CIV + ARC + ELE + LTN + ELV + FF + HVAC + PLU + GEN

for _f in LIBRARY:
    _f.setdefault("adopted", False)
    _f.setdefault("origin", "shipped")


def by_code(code):
    c = str(code or "").strip().upper()
    return next((f for f in LIBRARY if f["code"].upper() == c), None)


def by_discipline(disc):
    d = str(disc or "").strip().upper()
    return [f for f in LIBRARY if not d or f["disc"] == d]


def counts():
    """Forms and checklist lines per discipline — what the library screen prints beside each one.
    Computed rather than written down: a hand-maintained count is wrong the first time somebody
    adds a form and does not think to update it."""
    out = {}
    for f in LIBRARY:
        c = out.setdefault(f["disc"], {"forms": 0, "items": 0})
        c["forms"] += 1
        c["items"] += len([i for i in f["items"] if i["vi"] or i["en"]])
    return out
