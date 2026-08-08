#!/usr/bin/env python3
"""Batch-generate a personalised, bilingual "set up your signing PIN" letter for every employee,
on the official Humiley letterhead (one .docx per person, addressed by name).

Roster source:
  * default  -> seed_data.EMPLOYEES (the portal's built-in team)
  * --csv X  -> a CSV exported from the portal with columns: name,title,dept  (email optional)
"""
import csv
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SK = os.environ.get("HUMILEY_BRAND_SKILL", "")  # path to the humiley-brand skill (has scripts/fill_letter.py)
OUTDIR = os.path.join(REPO, "deliverables", "pin-guides")
SCRATCH = os.environ.get("TMPDIR", "/tmp").rstrip("/")

# ---- the guide body (bilingual, 4 paragraphs → fits one page) ----
BODY_EN = [
    "The Humiley People & Workplace Portal now records every submission and approval as a 21 CFR Part 11 "
    "electronic signature. So you can sign quickly — without re-entering your Microsoft 365 password each "
    "time — you can set up your own private signing PIN. This one-page guide shows you how; it takes about a minute.",

    "To set it up: (1) sign in to the portal and open My Profile; (2) in the “Signature & Security” "
    "section, click “Set up signature PIN”; (3) choose a PIN of 6 to 12 letters or digits and type it again "
    "to confirm; (4) confirm once with Microsoft 365 when prompted. Your PIN is saved immediately, and only you "
    "ever know it — Humiley stores it in a scrambled form that no one, including administrators, can read.",

    "From then on, whenever you submit or approve something, a signature box appears: simply enter your PIN and "
    "click Sign. You can always choose “Use Microsoft 365 instead” if you prefer. Every signature you apply "
    "records your name, the exact date and time (UTC) and the meaning of the signing, and cannot be altered afterwards.",

    "Please keep your PIN private and never share it. Five wrong attempts lock PIN signing for 15 minutes (you can "
    "still sign with Microsoft 365 in the meantime), and your PIN refreshes every 180 days. You can change or remove "
    "it at any time from My Profile. If you need any help enrolling, please contact HR or IT. Thank you for helping "
    "keep Humiley’s records secure and compliant.",
]
BODY_VN = [
    "Cổng Nhân sự & Vận hành Humiley nay ghi nhận mọi lần gửi và phê duyệt dưới dạng chữ ký điện tử theo 21 CFR Part 11. Để ký nhanh mà không phải nhập lại mật khẩu Microsoft 365 mỗi lần, bạn có thể thiết lập mã PIN chữ ký riêng của mình. Hướng dẫn một trang này chỉ mất khoảng một phút.",

    "Để thiết lập: (1) đăng nhập cổng và mở Hồ sơ của tôi; (2) trong mục “Chữ ký & Bảo mật”, nhấn “Thiết lập mã PIN chữ ký”; (3) chọn mã PIN gồm 6 đến 12 chữ cái hoặc chữ số và nhập lại để xác nhận; (4) xác nhận một lần bằng Microsoft 365 khi được yêu cầu. Mã PIN được lưu ngay và chỉ mình bạn biết — Humiley lưu dưới dạng mã hóa mà không ai, kể cả quản trị viên, có thể đọc.",

    "Từ đó, mỗi khi bạn gửi hoặc phê duyệt, một ô chữ ký sẽ hiện ra: chỉ cần nhập mã PIN và nhấn Ký. Bạn luôn có thể chọn “Dùng Microsoft 365 thay thế” nếu muốn. Mỗi chữ ký đều ghi lại tên bạn, ngày giờ chính xác (UTC) và ý nghĩa của lần ký, và không thể sửa đổi sau đó.",

    "Vui lòng giữ mã PIN riêng tư và không chia sẻ. Năm lần nhập sai sẽ khóa việc ký bằng PIN trong 15 phút (bạn vẫn có thể ký bằng Microsoft 365), và mã PIN làm mới mỗi 180 ngày. Bạn có thể đổi hoặc gỡ bỏ bất kỳ lúc nào từ Hồ sơ của tôi. Nếu cần hỗ trợ, vui lòng liên hệ Nhân sự hoặc CNTT. Cảm ơn bạn đã góp phần giữ cho hồ sơ của Humiley an toàn và tuân thủ.",
]


def roster_from_seed():
    sys.path.insert(0, REPO)
    import seed_data
    return [{"name": e["name"], "title": e.get("title", ""), "dept": e.get("dept", "")}
            for e in seed_data.EMPLOYEES if e.get("status", "Active") != "Inactive"]


def roster_from_csv(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            nm = (row.get("name") or row.get("Name") or "").strip()
            if nm:
                out.append({"name": nm, "title": (row.get("title") or row.get("Title") or "").strip(),
                            "dept": (row.get("dept") or row.get("Dept") or row.get("Department") or "").strip()})
    return out


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def main():
    csv_path = None
    if len(sys.argv) > 2 and sys.argv[1] == "--csv":
        csv_path = sys.argv[2]
    roster = roster_from_csv(csv_path) if csv_path else roster_from_seed()
    os.makedirs(OUTDIR, exist_ok=True)
    ok = 0
    for e in roster:
        spec = {
            "place": "Ho Chi Minh City", "date": "04 July 2026", "ref": "HML-PIN-GUIDE",
            "recipient_name": e["name"],
            "recipient_title": e["title"] or "Team member",
            "recipient_company": "Humiley Group Inc.",
            "recipient_address": (e["dept"] + " Department") if e["dept"] else "People & Workplace",
            "recipient_citycountry": "Ho Chi Minh City, Vietnam",
            "salutation_vn": e["name"],
            "subject": "How to set up your electronic signing PIN",
            "subject_vn": "Cách thiết lập mã PIN chữ ký điện tử của bạn",
            "body": BODY_EN, "body_vn": BODY_VN,
            "signatory_name": "TONY NGUYEN", "signatory_title": "Chief Executive Officer",
            "signatory_email": "tony.nguyen@humiley.com",
            "encl": "", "cc": "",
            "footer_code": "HML-PIN-GUIDE",
        }
        sp = os.path.join(SCRATCH, "pin_guide_spec.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        out = os.path.join(OUTDIR, "HML-PIN-Guide-" + slug(e["name"]) + "-EN-VN.docx")
        r = subprocess.run([sys.executable, os.path.join(SK, "scripts", "fill_letter.py"),
                            "--template", "EN_VN", "--out", out, "--spec", sp],
                           capture_output=True, text=True)
        if os.path.exists(out):
            ok += 1
        else:
            print("FAILED:", e["name"], r.stderr[-300:])
    print("Generated %d/%d letters -> %s" % (ok, len(roster), OUTDIR))


if __name__ == "__main__":
    main()
