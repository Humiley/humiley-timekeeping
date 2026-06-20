"""
Seed data for the Humiley Timekeeping & Leave Management platform.

Mirrors the original platform's demo data so the standalone app starts with the
same employees, GPS zones, and sample leave records — but now persisted in
SQLite and editable through the admin/API.
"""

# Role mapping: the Managing Director and HR are managers; everyone else is staff.
MANAGER_TITLES = {"Managing Director", "HR Manager"}

EMPLOYEES = [
    {"id": "EMP001", "name": "Huy Nguyen Duc", "ini": "HN", "clr": "#205090", "dept": "Engineering", "title": "Managing Director", "email": "huy.nguyen@humiley.com", "phone": "+84 909 840 714", "startDate": "2018-12-01", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1982-03-15", "taxId": "0123456789", "bank": "123456789 — Vietcombank", "emergency": "Nguyen Thi Hoa (+84 908 111 222)", "address": "I3-2608 Ha Do Centrosa, D10 HCMC", "annualUsed": 4, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 2},
    {"id": "EMP002", "name": "Lan Tran", "ini": "LT", "clr": "#00B060", "dept": "HR & Admin", "title": "HR Manager", "email": "lan.tran@humiley.com", "phone": "+84 901 234 567", "startDate": "2019-03-15", "status": "Active", "zone": "HQ", "gender": "Female", "dob": "1988-07-22", "taxId": "0234567890", "bank": "234567890 — ACB", "emergency": "Tran Van Nam (+84 907 222 333)", "address": "123 Nguyen Thi Minh Khai, D1 HCMC", "annualUsed": 2, "annualTotal": 12, "sickUsed": 1, "sickTotal": 30, "compoff": 0},
    {"id": "EMP003", "name": "Minh Vu", "ini": "MV", "clr": "#F59E0B", "dept": "Projects", "title": "Project Manager", "email": "minh.vu@humiley.com", "phone": "+84 912 345 678", "startDate": "2020-01-10", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1990-11-30", "taxId": "0345678901", "bank": "345678901 — Techcombank", "emergency": "Vu Thi Lan (+84 906 333 444)", "address": "456 Le Van Sy, D3 HCMC", "annualUsed": 6, "annualTotal": 12, "sickUsed": 2, "sickTotal": 30, "compoff": 0},
    {"id": "EMP004", "name": "Phuc Dang", "ini": "PD", "clr": "#8B5CF6", "dept": "Finance", "title": "Finance Lead", "email": "phuc.dang@humiley.com", "phone": "+84 923 456 789", "startDate": "2020-06-01", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1987-04-18", "taxId": "0456789012", "bank": "456789012 — BIDV", "emergency": "Dang Thi Thu (+84 905 444 555)", "address": "789 Truong Chinh, Tan Binh HCMC", "annualUsed": 3, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 1},
    {"id": "EMP005", "name": "Binh Le", "ini": "BL", "clr": "#EF4444", "dept": "Field Services", "title": "Field Engineer", "email": "binh.le@humiley.com", "phone": "+84 934 567 890", "startDate": "2021-03-01", "status": "Active", "zone": "Factory", "gender": "Male", "dob": "1992-09-05", "taxId": "0567890123", "bank": "567890123 — MB Bank", "emergency": "Le Van Binh (+84 904 555 666)", "address": "Long An Province", "annualUsed": 3, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 3},
    {"id": "EMP006", "name": "Duc Thanh", "ini": "DT", "clr": "#163866", "dept": "Engineering", "title": "Senior Engineer", "email": "duc.thanh@humiley.com", "phone": "+84 945 678 901", "startDate": "2021-06-15", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1993-02-14", "taxId": "0678901234", "bank": "678901234 — VPBank", "emergency": "Thanh Thi Nga (+84 903 666 777)", "address": "234 Dinh Tien Hoang, Binh Thanh HCMC", "annualUsed": 2, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0},
    {"id": "EMP007", "name": "Kim Pham", "ini": "KP", "clr": "#8B5CF6", "dept": "Engineering", "title": "Electrical Engineer", "email": "kim.pham@humiley.com", "phone": "+84 956 789 012", "startDate": "2022-01-10", "status": "Active", "zone": "HQ", "gender": "Female", "dob": "1995-06-28", "taxId": "0789012345", "bank": "789012345 — Sacombank", "emergency": "Pham Van Kinh (+84 902 777 888)", "address": "567 CMT8, D10 HCMC", "annualUsed": 1, "annualTotal": 12, "sickUsed": 2, "sickTotal": 30, "compoff": 0},
    {"id": "EMP008", "name": "Mai Quynh", "ini": "MQ", "clr": "#00B060", "dept": "Projects", "title": "Project Coordinator", "email": "mai.quynh@humiley.com", "phone": "+84 967 890 123", "startDate": "2022-03-15", "status": "Active", "zone": "HQ", "gender": "Female", "dob": "1996-12-10", "taxId": "0890123456", "bank": "890123456 — VietinBank", "emergency": "Quynh Van Mai (+84 901 888 999)", "address": "890 Vo Van Tan, D3 HCMC", "annualUsed": 1, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 1},
    {"id": "EMP009", "name": "An Nguyen", "ini": "AN", "clr": "#3168A8", "dept": "Engineering", "title": "Automation Engineer", "email": "an.nguyen@humiley.com", "phone": "+84 978 901 234", "startDate": "2022-06-01", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1994-08-20", "taxId": "0901234567", "bank": "901234567 — Agribank", "emergency": "Nguyen Thi An (+84 900 999 000)", "address": "123 Hai Ba Trung, D1 HCMC", "annualUsed": 2, "annualTotal": 12, "sickUsed": 1, "sickTotal": 30, "compoff": 0},
    {"id": "EMP010", "name": "Ha Nguyen", "ini": "HN", "clr": "#F97316", "dept": "Field Services", "title": "Site Engineer", "email": "ha.nguyen@humiley.com", "phone": "+84 989 012 345", "startDate": "2023-01-15", "status": "Active", "zone": "Factory", "gender": "Female", "dob": "1997-03-25", "taxId": "0012345678", "bank": "012345678 — OCB", "emergency": "Nguyen Van Ha (+84 908 000 111)", "address": "Long An Province", "annualUsed": 1, "annualTotal": 12, "sickUsed": 1, "sickTotal": 30, "compoff": 0},
    {"id": "EMP011", "name": "Tuan Nguyen", "ini": "TN", "clr": "#3168A8", "dept": "Projects", "title": "Engineer", "email": "tuan.nguyen@humiley.com", "phone": "+84 901 123 456", "startDate": "2023-04-01", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "1998-05-15", "taxId": "0123456780", "bank": "123456780 — Vietcombank", "emergency": "Nguyen Thi Tuan (+84 907 111 222)", "address": "456 Pham Ngu Lao, D1 HCMC", "annualUsed": 1, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0},
    {"id": "EMP012", "name": "Linh Vo", "ini": "LV", "clr": "#10B981", "dept": "HR & Admin", "title": "HR Officer", "email": "linh.vo@humiley.com", "phone": "+84 912 234 567", "startDate": "2023-07-01", "status": "Active", "zone": "HQ", "gender": "Female", "dob": "1999-09-09", "taxId": "0234567801", "bank": "234567801 — ACB", "emergency": "Vo Van Linh (+84 906 222 333)", "address": "789 Nguyen Hue, D1 HCMC", "annualUsed": 1, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0},
    {"id": "EMP013", "name": "Trong Phan", "ini": "TP", "clr": "#6366F1", "dept": "Field Services", "title": "Technician", "email": "trong.phan@humiley.com", "phone": "+84 923 345 678", "startDate": "2023-09-15", "status": "Active", "zone": "Factory", "gender": "Male", "dob": "2000-01-20", "taxId": "0345678012", "bank": "345678012 — Techcombank", "emergency": "Phan Thi Trong (+84 905 333 444)", "address": "Long An Province", "annualUsed": 0, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0},
    {"id": "EMP014", "name": "Thu Hoang", "ini": "TH", "clr": "#EC4899", "dept": "Finance", "title": "Accountant", "email": "thu.hoang@humiley.com", "phone": "+84 934 456 789", "startDate": "2024-01-10", "status": "Active", "zone": "HQ", "gender": "Female", "dob": "1998-07-14", "taxId": "0456780123", "bank": "456780123 — BIDV", "emergency": "Hoang Van Thu (+84 904 444 555)", "address": "234 Le Loi, D1 HCMC", "annualUsed": 0, "annualTotal": 12, "sickUsed": 1, "sickTotal": 30, "compoff": 0},
    {"id": "EMP015", "name": "Nam Bui", "ini": "NB", "clr": "#14B8A6", "dept": "Engineering", "title": "Intern Engineer", "email": "nam.bui@humiley.com", "phone": "+84 945 567 890", "startDate": "2024-06-01", "status": "Active", "zone": "HQ", "gender": "Male", "dob": "2002-04-08", "taxId": "0567801234", "bank": "567801234 — MB Bank", "emergency": "Bui Thi Nam (+84 903 555 666)", "address": "567 Nguyen Trai, D5 HCMC", "annualUsed": 0, "annualTotal": 12, "sickUsed": 0, "sickTotal": 30, "compoff": 0},
]

ZONES = [
    {"name": "HQ — District 10, HCMC", "lat": 10.7769, "lon": 106.6985, "radius": 200},
    {"name": "Factory — Long An Province", "lat": 10.5427, "lon": 106.4139, "radius": 350},
]

# Sample leave records (assigned to the Managing Director as the demo user).
LEAVE = [
    {"emp_id": "EMP001", "type": "Annual Leave", "startDate": "2026-05-19", "endDate": "2026-05-23", "days": 5, "status": "pending", "reason": "Family vacation"},
    {"emp_id": "EMP001", "type": "Sick Leave", "startDate": "2026-04-28", "endDate": "2026-04-28", "days": 1, "status": "approved", "reason": "Medical appointment"},
    {"emp_id": "EMP003", "type": "Annual Leave", "startDate": "2026-03-10", "endDate": "2026-03-14", "days": 5, "status": "approved", "reason": "Annual leave"},
    {"emp_id": "EMP002", "type": "Maternity Leave", "startDate": "2026-02-01", "endDate": "2026-02-28", "days": 28, "status": "approved", "reason": "Maternity"},
    {"emp_id": "EMP007", "type": "Sick Leave", "startDate": "2026-01-15", "endDate": "2026-01-15", "days": 1, "status": "rejected", "reason": "Overlap with project deadline"},
]


def sample_attendance(days_back=5):
    """Generate recent attendance for active employees so the dashboard and
    reports have realistic data. Deterministic (no randomness)."""
    from datetime import date, timedelta
    out = []
    today = date(2026, 5, 9)  # anchor to the platform's demo "today"
    patterns = [("07:58", "17:30", "on-time"), ("08:22", "17:45", "late"),
                ("07:52", "17:05", "on-time"), ("08:05", "17:15", "on-time"),
                ("08:35", "17:30", "late")]
    for d in range(days_back):
        day = today - timedelta(days=d)
        if day.weekday() >= 5:  # skip weekends
            continue
        for i, e in enumerate(EMPLOYEES):
            cin, cout, status = patterns[(i + d) % len(patterns)]
            # leave a couple absent occasionally
            if (i + d) % 11 == 0:
                out.append({"emp_id": e["id"], "name": e["name"], "dept": e["dept"],
                            "date": day.isoformat(), "clock_in": None, "clock_out": None,
                            "status": "absent", "loc": None})
                continue
            ih, im = map(int, cin.split(":")); oh, om = map(int, cout.split(":"))
            mins = (oh * 60 + om) - (ih * 60 + im)
            hrs = "%dh %02dm" % (mins // 60, mins % 60)
            out.append({"emp_id": e["id"], "name": e["name"], "dept": e["dept"],
                        "date": day.isoformat(), "clock_in": cin, "clock_out": cout,
                        "status": status, "hrs": hrs, "loc": "HQ" if e["zone"] == "HQ" else "Factory"})
    return out
