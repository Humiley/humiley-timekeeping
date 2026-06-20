import csv, re, unicodedata, sys
import db
db.init_db()

CSV = "/Users/huynguyen/Downloads/HML_Employees Profile.csv"
# In the codespace the CSV is uploaded next to the app; allow override via argv
if len(sys.argv) > 1:
    CSV = sys.argv[1]

PAL = ['#205090','#00B060','#F59E0B','#8B5CF6','#EF4444','#163866','#3168A8','#10B981','#F97316','#EC4899','#0EA5E9','#A855F7']

def ascii_slug(name):
    s = name.replace('Đ','D').replace('đ','d')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^A-Za-z\s]', '', s).strip().lower()
    return re.sub(r'\s+', '.', s)

def initials(name):
    p = [w for w in re.sub(r'\s+', ' ', name).strip().split() if w]
    return ''.join(w[0] for w in p[-2:]).upper() if p else '??'

def clean(v):
    return (v or '').strip()

def enum(v):  # "Male (Nam)" -> "Male"
    v = clean(v)
    return re.sub(r'\s*\(.*\)\s*', '', v).strip()

# Real Microsoft 365 mailbox addresses (so these people can sign in)
EMAIL_OVERRIDE = {
    "Nguyen Anh Giang": "giang.nguyen@humiley.com",
    "Son Nguyen":       "son.nguyen@humiley.com",
    "Yen Pham":         "yen.pham@humiley.com",
    "Nguyen Duc Nguyen":"nguyen.duc@humiley.com",
    "Nguyen An Dung":   "dung.nguyen@humiley.com",
}
ADMINS = {"tony.nguyen@humiley.com", "giang.nguyen@humiley.com"}
# CSV "Manager" column value -> that manager's email
MANAGER_EMAIL = {
    "Tony Nguyen":  "tony.nguyen@humiley.com",
    "Giang Nguyen": "giang.nguyen@humiley.com",
    "Duc Nguyen":   "nguyen.duc@humiley.com",
    "Tuat Tran":    "tran.viet.tuat@humiley.com",
    "Tuat  Tran":   "tran.viet.tuat@humiley.com",
}

rows = list(csv.DictReader(open(CSV, encoding='utf-8-sig')))
used_emails = set()

def uniq_email(name):
    base = ascii_slug(name) or 'employee'
    em = base + "@humiley.com"
    n = 2
    while em in used_emails:
        em = base + str(n) + "@humiley.com"; n += 1
    used_emails.add(em)
    return em

records = []
# Tony (Managing Director) is not a CSV row — add him as top admin
records.append({
    "id": "HML-001", "name": "Tony Nguyen", "email": "tony.nguyen@humiley.com",
    "title": "Managing Director", "jobLevel": "Director", "dept": "Management",
    "status": "Active", "managerEmail": "", "role": "manager",
})
used_emails.add("tony.nguyen@humiley.com")

for i, r in enumerate(rows):
    name = clean(r.get("Full Name"))
    if not name:
        continue
    email = EMAIL_OVERRIDE.get(name) or uniq_email(name)
    used_emails.add(email)
    rec = {
        "id": clean(r.get("Employee ID")) or ("HML-%03d" % (200 + i)),
        "name": name,
        "email": email,
        "gender": enum(r.get("Gender ( Giới tính )")),
        "dob": clean(r.get("Date of Birth (Ngày sinh)")),
        "title": clean(r.get("Position (Chức vụ)")),
        "jobLevel": clean(r.get("Job Level")),
        "dept": clean(r.get("Department (Phòng Ban)")),
        "startDate": clean(r.get("StartDate")),
        "endDate": clean(r.get("End date")),
        "serviceDuration": clean(r.get("Sevices Duration (Thời gian làm việc)")),
        "phone": clean(r.get("Phone Number (Số điện thoại)")),
        "status": "Inactive" if "inactive" in clean(r.get("Status (Tình trạng)")).lower() else "Active",
        "address": clean(r.get("Address (Địa chỉ)")),
        "personalId": clean(r.get("Personal ID/Passport No. (CMND/Hộ chiếu)")),
        "familyStatus": enum(r.get("Family Status (Tình Trạng Hôn Nhân)")),
        "education": clean(r.get("Education Level (Trình độ học vấn)")),
        "employmentType": clean(r.get("FTE/PTE/INT")),
        "emergency": clean(r.get("Emergency contact ( Liên hệ khẩn cấp)")).replace("\n", " "),
        "englishCert": clean(r.get("English Certificate (Chứng chỉ tiếng anh)")),
        "note": clean(r.get("Note (Ghi chú)")),
        "_mgrName": clean(r.get("Manager (Người quản lý) ")) or clean(r.get("Manager (Người quản lý)")),
    }
    records.append(rec)

# resolve manager emails
name_to_email = {r["name"]: r["email"] for r in records}
for rec in records:
    mn = rec.pop("_mgrName", "")
    if not mn:
        continue
    rec["managerEmail"] = MANAGER_EMAIL.get(mn) or name_to_email.get(mn) or ""

# finalize roles/colours/initials/leave defaults
for i, rec in enumerate(records):
    rec.setdefault("managerEmail", "")
    rec["role"] = "manager" if rec["email"] in ADMINS else "staff"
    rec["ini"] = initials(rec["name"])
    rec["clr"] = PAL[i % len(PAL)]
    rec["zone"] = "HQ"
    rec.setdefault("annualUsed", 0); rec.setdefault("annualTotal", 12)
    rec.setdefault("sickUsed", 0); rec.setdefault("sickTotal", 30); rec.setdefault("compoff", 0)

# wipe and insert
conn = db.get_conn()
conn.execute("DELETE FROM attendance"); conn.execute("DELETE FROM leave"); conn.execute("DELETE FROM employees")
conn.commit(); conn.close()
for rec in records:
    db.create_employee(rec)

print("Imported %d employees (incl. Tony). Admins: %s" % (len(records), ", ".join(ADMINS)))
print("Sample logins (mailbox users):")
for e in db.list_employees():
    if e["email"] in (set(EMAIL_OVERRIDE.values()) | ADMINS):
        print("  %-7s %-20s %-28s mgr=%s" % (e["id"], e["name"], e["email"], e.get("managerEmail") or "-"))
print("Total active:", len([e for e in db.list_employees() if e["status"]=="Active"]))
