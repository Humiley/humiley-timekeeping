const HB = require("./humiley_brand");
const S = "/tmp/shots/";
const OUT = "/Users/huynguyen/Library/CloudStorage/OneDrive-Humiley(2)/Claude Projects/TimeKeeping Web App/deliverables/";

// ---- training content: section dividers + screenshot slides ----
const DECK = [
  { type: "divider", no: "01", t: "Getting Started", tvn: "Bắt đầu" },
  { type: "shot", sec: "01", label: "ACCESS", t: "Five access levels", tvn: "Năm cấp truy cập", img: "04_permissions",
    b: [["Sign in with Microsoft 365 — no password to remember.", "Đăng nhập bằng Microsoft 365 — không cần nhớ mật khẩu."],
        ["Levels build on each other: User → Contributor → Approver → Editor → Admin.", "Các cấp cộng dồn: User → Contributor → Approver → Editor → Admin."],
        ["What you see and can do is set by your level + the modules enabled for you.", "Bạn thấy và làm được gì tuỳ theo cấp của bạn và các phân hệ được bật."]] },
  { type: "shot", sec: "01", label: "HR DASHBOARD", t: "Company dashboard", tvn: "Bảng điều khiển công ty", img: "01_company_dashboard",
    b: [["A live snapshot: headcount, attendance, leave, recruitment, performance.", "Ảnh chụp trực tiếp: nhân sự, chấm công, nghỉ phép, tuyển dụng, hiệu suất."],
        ["PowerBI-style charts update from real data; filter by department.", "Biểu đồ kiểu PowerBI cập nhật từ dữ liệu thật; lọc theo phòng ban."],
        ["Export the view to a branded PDF anytime.", "Xuất bản hiển thị ra PDF có thương hiệu bất kỳ lúc nào."]] },
  { type: "divider", no: "02", t: "People & HR", tvn: "Nhân sự & HR" },
  { type: "shot", sec: "02", label: "EMPLOYEE DATABASE", t: "Employee database", tvn: "Cơ sở dữ liệu nhân sự", img: "02_employee_database",
    b: [["Full employee records: role, department, devices, documents.", "Hồ sơ nhân viên đầy đủ: vai trò, phòng ban, thiết bị, tài liệu."],
        ["Add, edit, import from Excel/CSV; export for reporting.", "Thêm, sửa, nhập từ Excel/CSV; xuất để báo cáo."],
        ["Self-service: staff manage their own profile, leave, claims & training.", "Tự phục vụ: nhân viên tự quản lý hồ sơ, nghỉ phép, hoàn ứng & đào tạo."]] },
  { type: "shot", sec: "02", label: "PAYROLL", t: "Payroll & finance", tvn: "Lương & tài chính", img: "03_payroll",
    b: [["Monthly pay runs with PIT, SI and employer cost computed automatically.", "Bảng lương hàng tháng với TNCN, BHXH và chi phí chủ sử dụng tự tính."],
        ["Visible to Approver+ only; only Editor/Admin can run or edit payroll.", "Chỉ Approver+ xem được; chỉ Editor/Admin chạy hoặc sửa lương."],
        ["History kept from 2024 — trend charts and exportable reports.", "Lưu lịch sử từ 2024 — biểu đồ xu hướng và báo cáo xuất được."]] },
  { type: "divider", no: "03", t: "PMC — Project Workspace", tvn: "PMC — Không gian dự án" },
  { type: "shot", sec: "03", label: "PORTFOLIO", t: "Project portfolio", tvn: "Danh mục dự án", img: "05_pmc_portfolio",
    b: [["Every project at a glance: value, health (RAG), CPI/SPI, milestones.", "Toàn bộ dự án trong một màn hình: giá trị, tình trạng (RAG), CPI/SPI, cột mốc."],
        ["Staff see assigned projects; managers see the whole portfolio.", "Nhân viên thấy dự án được giao; quản lý thấy toàn danh mục."]] },
  { type: "shot", sec: "03", label: "OVERVIEW", t: "Project overview", tvn: "Tổng quan dự án", img: "06_pm_overview",
    b: [["KPI tiles + charts: cost (EVM), deliverables, schedule, risk exposure.", "Ô KPI + biểu đồ: chi phí (EVM), sản phẩm bàn giao, tiến độ, mức rủi ro."],
        ["The project charter, change log and lessons learned, all in one place.", "Hiến chương dự án, sổ thay đổi và bài học kinh nghiệm, tất cả một nơi."]] },
  { type: "shot", sec: "03", label: "SCHEDULE", t: "Schedule — Gantt", tvn: "Tiến độ — Gantt", img: "07_pm_schedule",
    b: [["A Gantt timeline with milestones, the critical path and a today line.", "Dòng thời gian Gantt với cột mốc, đường găng và vạch hôm nay."],
        ["Filter by all / year / month, or a custom day-to-day range; export PDF.", "Lọc theo tất cả / năm / tháng, hoặc khoảng ngày tuỳ chọn; xuất PDF."]] },
  { type: "shot", sec: "03", label: "COST / EVM", t: "Cost & earned value", tvn: "Chi phí & giá trị thu được", img: "08_pm_cost_evm",
    b: [["Budget vs committed vs actual by category, with CPI/SPI and forecast (EAC).", "Ngân sách / cam kết / thực tế theo nhóm, kèm CPI/SPI và dự báo (EAC)."],
        ["Earned-value analysis gives an early warning on cost and schedule.", "Phân tích giá trị thu được cảnh báo sớm về chi phí và tiến độ."]] },
  { type: "shot", sec: "03", label: "RISK", t: "Risk register & heatmap", tvn: "Sổ rủi ro & bản đồ nhiệt", img: "09_pm_risk",
    b: [["Probability × impact heatmap; auto-scored bands (Low→Critical).", "Bản đồ nhiệt Xác suất × Tác động; tự chấm điểm theo dải (Thấp→Nghiêm trọng)."],
        ["Filter the register by category, response, owner, contractor or status.", "Lọc sổ theo phân loại, ứng phó, chủ trì, nhà thầu hoặc trạng thái."]] },
  { type: "shot", sec: "03", label: "QUALITY / ITP", t: "Quality & ITP timeline", tvn: "Chất lượng & lịch ITP", img: "10_pm_quality_itp",
    b: [["Inspections, NCRs, audits and tests in one quality register.", "Kiểm tra, NCR, đánh giá và thử nghiệm trong một sổ chất lượng."],
        ["Inspection & Test Plans on a timeline with a day-range filter.", "Kế hoạch kiểm tra & thử nghiệm trên dòng thời gian với bộ lọc khoảng ngày."]] },
  { type: "shot", sec: "03", label: "PROCUREMENT", t: "Procurement & contracts", tvn: "Mua sắm & hợp đồng", img: "11_pm_procurement",
    b: [["Subcontract packages, vendors, values, retention and payment certificates.", "Gói thầu phụ, nhà cung cấp, giá trị, tiền giữ lại và chứng chỉ thanh toán."],
        ["Filterable register; cost/procurement edits are manager-only.", "Sổ có thể lọc; sửa chi phí/mua sắm chỉ dành cho quản lý."]] },
  { type: "shot", sec: "03", label: "STAKEHOLDERS", t: "Stakeholders (Mendelow)", tvn: "Bên liên quan (Mendelow)", img: "12_pm_stakeholders",
    b: [["Power / interest grid places each stakeholder in the right quadrant.", "Lưới Quyền lực / Quan tâm đặt mỗi bên liên quan vào đúng góc phần tư."],
        ["Track influence, interest and attitude to plan engagement.", "Theo dõi ảnh hưởng, quan tâm và thái độ để lập kế hoạch tiếp cận."]] },
  { type: "shot", sec: "03", label: "DOCUMENTS", t: "SharePoint document structure", tvn: "Cấu trúc tài liệu SharePoint", img: "13_pm_documents_sharepoint",
    b: [["Paste the project's SharePoint link in Edit → it builds the full folder tree.", "Dán link SharePoint của dự án trong Sửa → tự tạo toàn bộ cây thư mục."],
        ["50 standard PMC folders with owner, confidentiality and retention.", "50 thư mục PMC chuẩn kèm chủ trì, mức bảo mật và thời gian lưu."],
        ["Every folder is a one-click link straight into SharePoint.", "Mỗi thư mục là một liên kết mở thẳng vào SharePoint."]] },
  { type: "divider", no: "04", t: "Sales & Administration", tvn: "Kinh doanh & Quản trị" },
  { type: "shot", sec: "04", label: "CRM", t: "Sales pipeline (CRM)", tvn: "Quy trình bán hàng (CRM)", img: "14_crm_pipeline",
    b: [["Deals by stage with value and probability; companies, contacts, products.", "Cơ hội theo giai đoạn kèm giá trị và xác suất; công ty, liên hệ, sản phẩm."],
        ["Convert a Won deal into a PMC project in one click (manager+).", "Chuyển cơ hội Thắng thành dự án PMC chỉ một cú nhấp (manager+)."]] },
  { type: "shot", sec: "04", label: "LANGUAGE", t: "English & Vietnamese", tvn: "Tiếng Anh & Tiếng Việt", img: "15_vietnamese_dashboard",
    b: [["Switch the whole portal between EN and VN with the flag in the top bar.", "Chuyển toàn bộ cổng giữa EN và VN bằng cờ ở thanh trên cùng."],
        ["Labels, menus, tables and chart legends all translate.", "Nhãn, menu, bảng và chú giải biểu đồ đều được dịch."]] },
];

async function build(bilingual) {
  const docNo = bilingual ? "HML-DECK-0002" : "HML-DECK-0001";
  const { pres, dim } = HB.createPres("WIDE", { title: "Humiley Portal — Training" });
  HB.coverSlide(pres, dim, {
    title: "People & Workplace\nPortal — Training.",
    titleVN: bilingual ? "Cổng Nhân sự & Vận hành — Đào tạo" : undefined,
    subtitle: "HR · CRM · PMC project management — a guided tour",
    docNo: docNo, issued: "Issued 2026 · Rev 01.0",
  });
  let page = 2, total = DECK.filter(d => d.type === "shot").length + 4;
  DECK.forEach(d => {
    if (d.type === "divider") {
      HB.sectionDivider(pres, dim, { partNo: d.no, title: d.t, titleVN: bilingual ? d.tvn : undefined });
      return;
    }
    const s = HB.contentSlide(pres, dim, { sectionNo: d.sec, label: d.label, title: d.t,
      titleVN: bilingual ? d.tvn : undefined, pageNo: page++, total: total, docNo: docNo });
    // screenshot (left), bordered
    s.addImage({ path: S + d.img + ".jpg", x: 0.55, y: 1.95, w: 7.45, h: 4.69 });
    s.addShape("rect", { x: 0.55, y: 1.95, w: 7.45, h: 4.69, fill: { type: "none" }, line: { color: HB.BRAND.line || "CFD6E2", width: 1 } });
    // bullets (right)
    let by = 2.15;
    d.b.forEach(p => {
      const rt = bilingual ? HB.biText(p[0], p[1], { size: 12 }) : [{ text: p[0], options: { fontFace: "Calibri", fontSize: 13, color: HB.BRAND.body } }];
      s.addText([{ text: "▸ ", options: { color: HB.BRAND.emerald, fontFace: "Calibri", fontSize: 13, bold: true } }].concat(rt),
        { x: 8.25, y: by, w: 4.5, h: 1.4, valign: "top", lineSpacingMultiple: 1.0 });
      by += bilingual ? 1.5 : 1.1;
    });
  });
  HB.closingSlide(pres, dim, { headline: "Questions?", titleVN: bilingual ? "Câu hỏi?" : undefined,
    contact: { email: "contact@humiley.com", web: "www.humiley.com" } });
  const fn = OUT + (bilingual ? "Humiley-Portal-Training-EN-VN.pptx" : "Humiley-Portal-Training-EN.pptx");
  await pres.writeFile({ fileName: fn });
  console.log("wrote", fn);
}

(async () => { await build(false); await build(true); })();
