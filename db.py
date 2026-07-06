"""
Database layer for the Humiley Timekeeping & Leave Management platform.

Standalone SQLite storage (Python stdlib only) — replaces the original
SharePoint/Graph backend. Holds employees, attendance, leave requests, GPS
zones, and app settings.
"""

import os
import re
import hmac
import json
import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import seed_data

DB_PATH = os.environ.get("TK_DB_PATH", os.path.join(os.path.dirname(__file__), "timekeeping.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            ini         TEXT,
            clr         TEXT,
            dept        TEXT,
            title       TEXT,
            email       TEXT UNIQUE,
            phone       TEXT,
            startDate   TEXT,
            status      TEXT DEFAULT 'Active',
            zone        TEXT,
            gender      TEXT,
            dob         TEXT,
            taxId       TEXT,
            bank        TEXT,
            emergency   TEXT,
            address     TEXT,
            managerEmail TEXT,
            jobLevel     TEXT,
            endDate      TEXT,
            serviceDuration TEXT,
            personalId   TEXT,
            familyStatus TEXT,
            education    TEXT,
            employmentType TEXT,
            englishCert  TEXT,
            note         TEXT,
            photo        TEXT,
            role        TEXT DEFAULT 'staff',
            annualUsed  INTEGER DEFAULT 0,
            annualTotal INTEGER DEFAULT 12,
            sickUsed    INTEGER DEFAULT 0,
            sickTotal   INTEGER DEFAULT 30,
            compoff     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id    TEXT NOT NULL,
            name      TEXT,
            dept      TEXT,
            date      TEXT NOT NULL,
            clock_in  TEXT,
            clock_out TEXT,
            status    TEXT,
            hrs       TEXT,
            loc       TEXT,
            lat       REAL,
            lon       REAL,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS leave (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id     TEXT NOT NULL,
            type       TEXT,
            startDate  TEXT,
            endDate    TEXT,
            days       INTEGER,
            status     TEXT DEFAULT 'pending',
            reason     TEXT,
            note       TEXT,
            created_at TEXT,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS zones (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT,
            lat    REAL,
            lon    REAL,
            radius INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS collections (
            coll TEXT,
            id   TEXT,
            data TEXT,
            PRIMARY KEY (coll, id)
        );

        -- 21 CFR Part 11 signature PIN (second signing component). Salted PBKDF2 hash only;
        -- kept in its own table so it can never leak through a `SELECT * FROM employees` read path.
        CREATE TABLE IF NOT EXISTS esign_pin (
            emp_id       TEXT PRIMARY KEY,
            algo         TEXT    NOT NULL DEFAULT 'pbkdf2_sha256',
            iterations   INTEGER NOT NULL,
            salt         TEXT    NOT NULL,               -- hex, 16 random bytes, unique per set
            hash         TEXT    NOT NULL,               -- hex PBKDF2-HMAC-SHA256 derived key
            prev_hash    TEXT,                           -- hex of previous hash, blocks immediate reuse
            status       TEXT    NOT NULL DEFAULT 'active',  -- 'active' | 'revoked'
            created_ts   TEXT,
            updated_ts   TEXT,
            set_ts       TEXT,                           -- last time the PIN value was set (expiry clock)
            fail_count   INTEGER NOT NULL DEFAULT 0,
            last_fail_ts TEXT,
            locked_until TEXT,                           -- ISO-8601 UTC; NULL = not locked
            must_change  INTEGER NOT NULL DEFAULT 0,     -- 1 after admin reset -> owner must re-enroll
            enrolled_via TEXT,
            enrolled_oid TEXT,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        -- Web Push subscriptions (one row per browser/device per user) for OS notifications.
        CREATE TABLE IF NOT EXISTS push_subs (
            endpoint TEXT PRIMARY KEY,
            email    TEXT NOT NULL,
            sub      TEXT NOT NULL,   -- full PushSubscription JSON (endpoint + p256dh/auth keys)
            created  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_att_emp  ON attendance (emp_id);
        CREATE INDEX IF NOT EXISTS idx_att_date ON attendance (date);
        CREATE INDEX IF NOT EXISTS idx_leave_emp ON leave (emp_id);
        CREATE INDEX IF NOT EXISTS idx_push_email ON push_subs (email);
        """
    )
    # migration: add newer columns to older databases
    for col in ("managerEmail TEXT", "jobLevel TEXT", "endDate TEXT", "serviceDuration TEXT",
                "personalId TEXT", "familyStatus TEXT", "education TEXT", "employmentType TEXT",
                "englishCert TEXT", "note TEXT", "photo TEXT", "salary REAL",
                "level TEXT", "dependents INTEGER", "grade TEXT", "appsDenied TEXT", "appsAllowed TEXT"):
        try:
            conn.execute("ALTER TABLE employees ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass  # column already exists
    try:
        conn.execute("ALTER TABLE leave ADD COLUMN token TEXT")  # approval-link token
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE leave ADD COLUMN signatures TEXT")  # 21 CFR Part 11 e-signatures (JSON)
    except sqlite3.OperationalError:
        pass
    # Overtime request/approval on an attendance record: OT only counts once a manager approves it.
    for col in ("ot_status TEXT", "ot_hours REAL", "ot_reason TEXT"):
        try:
            conn.execute("ALTER TABLE attendance ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def seed_hr():
    """Seed the HRMS module collections. Each collection seeds independently so
    newer modules populate even on databases seeded by an earlier version."""
    emps = list_employees()
    pick = [e for e in emps if e.get("status", "Active") != "Inactive"]
    if pick:
        _seed_competency(pick)
        _seed_padr(pick)
        _seed_travel(pick)
        _seed_exits(pick)
        _seed_benefits(pick)
        _seed_learningpaths(pick)
        _seed_claims(pick)
        _seed_enrollments(pick)
        _seed_devices(pick)
        _seed_onboarding(pick)
    if collection_count("jobs") or collection_count("courses") or collection_count("candidates"):
        return False

    jobs = [
        {"title": "Senior Civil Engineer", "dept": "Engineering", "location": "HCMC HQ", "type": "Full Time", "openings": 2, "status": "Open"},
        {"title": "Project Coordinator", "dept": "Project", "location": "Long An", "type": "Full Time", "openings": 1, "status": "Open"},
        {"title": "Accountant", "dept": "Finance", "location": "HCMC HQ", "type": "Full Time", "openings": 1, "status": "Interviewing"},
        {"title": "Site Safety Officer", "dept": "Factory", "location": "Long An", "type": "Contract", "openings": 1, "status": "Open"},
    ]
    for j in jobs:
        put_collection_item("jobs", j)

    candidates = [
        {"name": "Le Minh Anh", "role": "Senior Civil Engineer", "stage": "Interview", "rating": 4, "source": "LinkedIn"},
        {"name": "Tran Quoc Bao", "role": "Senior Civil Engineer", "stage": "Screening", "rating": 3, "source": "Referral"},
        {"name": "Pham Thu Ha", "role": "Accountant", "stage": "Offer", "rating": 5, "source": "VietnamWorks"},
        {"name": "Nguyen Van Cuong", "role": "Project Coordinator", "stage": "Applied", "rating": 0, "source": "Website"},
        {"name": "Do Thi Mai", "role": "Site Safety Officer", "stage": "Applied", "rating": 0, "source": "Website"},
        {"name": "Hoang Gia Long", "role": "Accountant", "stage": "Hired", "rating": 5, "source": "Referral"},
    ]
    for c in candidates:
        put_collection_item("candidates", c)

    onboard_tasks = [
        ("Day 1 — Arrival", "Welcome & office tour, introductions"),
        ("Day 1 — Arrival", "Sign Labor Contract & NDA"),
        ("Day 1 — Arrival", "Personal info, bank, tax code & SI registration"),
        ("Day 1 — Arrival", "IT account, email & company ID / access card"),
        ("Week 1 — Integration", "EHS induction & Code of Conduct"),
        ("Week 1 — Integration", "IT security & expense system training"),
        ("Week 1 — Integration", "Department deep-dive (projects, process, tools)"),
        ("Week 1 — Integration", "Role shadowing with mentor & first task"),
        ("30-60-90 Days", "Draft 30-60-90 day plan + PADR objectives"),
        ("30-60-90 Days", "Day 30 — first check-in with Manager"),
        ("30-60-90 Days", "Day 60 — HR check-in & risk review"),
        ("30-60-90 Days", "Day 90 — probation review (confirm / extend / end)"),
    ]
    for idx, e in enumerate(pick[-3:]):
        done_n = [8, 4, 1][idx % 3]
        put_collection_item("onboarding", {
            "empId": e["id"], "name": e["name"], "role": e.get("title", ""),
            "startDate": e.get("startDate", ""),
            "tasks": [{"phase": ph, "label": t, "done": i < done_n} for i, (ph, t) in enumerate(onboard_tasks)],
        })

    for i, e in enumerate(pick[:8]):
        ratings = [4, 5, 3, 4, 4, 5, 3, 4]
        put_collection_item("reviews", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "cycle": "H1 2026", "rating": ratings[i % len(ratings)],
            "status": ["Completed", "In Review", "Self-assessment"][i % 3],
        })

    goals = [
        {"name": "Deliver Long An factory expansion phase 1", "owner": "Engineering", "progress": 65, "due": "2026-09-30"},
        {"name": "Reduce monthly attendance anomalies below 2%", "owner": "Operations", "progress": 80, "due": "2026-07-31"},
        {"name": "Complete ISO 9001 documentation", "owner": "Quality", "progress": 40, "due": "2026-12-15"},
        {"name": "Hire & onboard 5 new engineers", "owner": "HR", "progress": 50, "due": "2026-10-31"},
    ]
    for g in goals:
        put_collection_item("goals", g)

    courses = [
        {"title": "Workplace Safety (HSE) Essentials", "category": "Compliance", "duration": "45 min", "enrolled": 42, "status": "Active"},
        {"title": "Project Management Fundamentals", "category": "Professional", "duration": "6 modules", "enrolled": 18, "status": "Active"},
        {"title": "Business English — Intermediate", "category": "Language", "duration": "Ongoing", "enrolled": 25, "status": "Active"},
        {"title": "Leadership & Communication", "category": "Leadership", "duration": "4 weeks", "enrolled": 8, "status": "Active"},
        {"title": "AutoCAD for Civil Engineers", "category": "Technical", "duration": "12 hours", "enrolled": 14, "status": "Active"},
    ]
    for c in courses:
        put_collection_item("courses", c)

    boxes = ["Star", "High Potential", "Core Performer", "Solid Performer"]
    succ = ["Ready Now", "Ready in 1 year", "Ready in 2-3 years", "Develop in Role"]
    for i, e in enumerate(pick[:6]):
        put_collection_item("talent", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "title": e.get("title", ""), "box": boxes[i % len(boxes)],
            "potential": ["High", "High", "Medium", "Medium"][i % 4],
            "performance": ["High", "Medium", "High", "Medium"][i % 4],
            "succession": succ[i % len(succ)],
        })

    return True


def _seed_competency(pick):
    if collection_count("competency"):
        return
    comps = ["WS-01 CNC cutting", "WS-02 Frame assembly", "WS-03 PU foaming", "WS-04 Section assembly",
             "WS-05 Hygienic detail", "WS-06 Electrical pre-wire", "WS-07 Final assembly", "WS-08 Panel wiring",
             "WS-09 Pre-test & 5S", "FAT witness", "EN 1886 testing", "Hi-Pot / Megger", "Vibration ISO 21940",
             "Forklift", "Working at height", "LOTO", "Confined space", "Hot work / welding", "First aid",
             "ISO 9001", "VDI 6022", "EU-GMP Annex 1", "BMS / BACnet", "Site commissioning & TAB", "Customer communication"]
    statuses = ["✓", "T", "X", "—"]
    prod = [e for e in pick if (e.get("dept") or "") in ("Factory", "Engineering", "Project", "Operation")][:10]
    for idx, e in enumerate(prod):
        cells = {}
        for ci, c in enumerate(comps):
            s = statuses[(idx + ci * 3) % 4]
            if ci < 9 and (e.get("dept") == "Factory"):
                s = "✓" if (idx + ci) % 5 else "T"
            cells[c] = s
        put_collection_item("competency", {"empId": e["id"], "name": e["name"], "role": e.get("title", ""),
                                           "dept": e.get("dept", ""), "cells": cells})


def _seed_travel(pick):
    if collection_count("travel"):
        return
    samples = [
        {"dest": "Long An Factory", "purpose": "Site commissioning support", "transport": "Company car", "from": "2026-07-08", "to": "2026-07-10", "cost": 3500000, "advance": 2000000, "status": "Submitted"},
        {"dest": "Hà Nội", "purpose": "Client meeting — AHU project", "transport": "Flight", "from": "2026-07-15", "to": "2026-07-16", "cost": 8500000, "advance": 5000000, "status": "Approved"},
        {"dest": "Singapore", "purpose": "Supplier factory audit", "transport": "Flight", "from": "2026-08-03", "to": "2026-08-06", "cost": 22000000, "advance": 10000000, "status": "Submitted"},
    ]
    for i, e in enumerate(pick[:3]):
        s = samples[i % len(samples)]
        put_collection_item("travel", dict(s, empId=e["id"], name=e["name"], dept=e.get("dept", "")))


EXIT_CLEARANCE = [
    ("Manager", "Knowledge transfer & handover document"),
    ("Manager", "Outstanding work / projects reassigned"),
    ("IT", "Return laptop, phone & company assets"),
    ("IT", "Revoke email, system & VPN access"),
    ("Admin", "Return access card, keys & uniform"),
    ("Finance", "Settle advances, claims & company loans"),
    ("HR", "Final timesheet & annual-leave payout calculated"),
    ("HR", "Severance / final settlement processed"),
    ("HR", "Social Insurance book closed & returned"),
    ("HR", "Exit interview completed"),
]


def _seed_exits(pick):
    if collection_count("exits"):
        return
    # One in-progress resignation to demonstrate the offboarding workflow.
    cand = [e for e in pick if (e.get("role") or "") != "manager"]
    if not cand:
        cand = pick
    e = cand[-1]
    done_n = 4
    put_collection_item("exits", {
        "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
        "title": e.get("title", ""), "type": "Resignation",
        "initiated": "2026-06-02", "lastDay": "2026-07-02", "noticeDays": 30,
        "reason": "Career change — relocating to home province.",
        "status": "Clearance",
        "clearance": [{"owner": o, "label": l, "done": i < done_n}
                      for i, (o, l) in enumerate(EXIT_CLEARANCE)],
        "leavePayout": "", "severance": 0, "deductions": 0,
        "settlementNote": "", "rehire": "Yes",
    })


def _seed_onboarding(pick):
    """Onboarding checklists for the most recent hires — visible to Admin and to the
    employee (in My Training) where they tick steps to complete them."""
    if collection_count("onboarding"):
        return
    tasks_tpl = [
        ("Pre-boarding", "Send welcome email & first-day logistics"),
        ("Pre-boarding", "Prepare desk, PPE & workstation"),
        ("Pre-boarding", "Provision laptop & equipment in the asset register"),
        ("Day 1 — Arrival", "Welcome & office tour, introductions"),
        ("Day 1 — Arrival", "Sign Labor Contract & NDA"),
        ("Day 1 — Arrival", "IT account, email & company ID / access card"),
        ("Week 1 — Integration", "EHS induction & Code of Conduct"),
        ("Week 1 — Integration", "Benefits & welfare enrollment (insurance, allowances)"),
        ("Week 1 — Integration", "Role shadowing with mentor & first task"),
        ("30-60-90 Days", "Draft 30-60-90 day plan + PADR objectives"),
        ("30-60-90 Days", "Day 30 — first check-in with Manager"),
    ]
    cand = [e for e in pick if (e.get("role") or "") != "manager"]
    for idx, e in enumerate(cand or pick):
        done_n = 3 + (idx % 5)  # 3–7 of 11 done — leaves steps for the employee to tick
        put_collection_item("onboarding", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "title": e.get("title", ""), "startDate": e.get("startDate", ""),
            "tasks": [{"phase": ph, "label": lb, "done": i < done_n} for i, (ph, lb) in enumerate(tasks_tpl)],
        })


def _seed_devices(pick):
    """Company device / equipment register — laptops, monitors, phones per employee
    plus shared company assets. Demonstrates the asset-management module."""
    if collection_count("devices"):
        return
    laptops = ["Dell Latitude 5440", "Lenovo ThinkPad T14", "HP EliteBook 840", "MacBook Pro 14"]
    items = []
    for i, e in enumerate(pick):
        items.append({"name": laptops[i % len(laptops)], "category": "Laptop", "serial": "HML-LT-%03d" % (i + 1),
                      "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                      "qty": 1, "unitPrice": 22000000, "purchaseDate": "2024-01-15", "status": "Assigned", "note": ""})
        items.append({"name": "Dell 24\" Monitor P2422H", "category": "Monitor", "serial": "HML-MN-%03d" % (i + 1),
                      "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                      "qty": 1, "unitPrice": 4500000, "purchaseDate": "2024-01-15", "status": "Assigned", "note": ""})
        if (e.get("role") or "") == "manager":
            items.append({"name": "iPhone 13", "category": "Phone", "serial": "HML-PH-%03d" % (i + 1),
                          "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                          "qty": 1, "unitPrice": 16000000, "purchaseDate": "2024-03-01", "status": "Assigned", "note": ""})
    items += [
        {"name": "HP LaserJet Pro Printer", "category": "Printer", "serial": "HML-PR-001", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 2, "unitPrice": 6500000, "purchaseDate": "2023-11-10", "status": "Available", "note": "Shared office printers"},
        {"name": "Epson Projector EB-X06", "category": "Other", "serial": "HML-PJ-001", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 1, "unitPrice": 12000000, "purchaseDate": "2023-09-05", "status": "Available", "note": "Meeting room"},
        {"name": "Toyota Hilux (Company)", "category": "Vehicle", "serial": "51A-678.90", "assignedTo": "", "empId": "", "department": "Operation", "qty": 1, "unitPrice": 850000000, "purchaseDate": "2022-06-20", "status": "Available", "note": "Site transport"},
        {"name": "Total Station Survey Kit", "category": "Tool", "serial": "HML-TL-001", "assignedTo": "", "empId": "", "department": "Engineering", "qty": 3, "unitPrice": 120000000, "purchaseDate": "2023-02-14", "status": "Available", "note": "Field survey"},
        {"name": "Dell Latitude (spare pool)", "category": "Laptop", "serial": "HML-LT-099", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 2, "unitPrice": 22000000, "purchaseDate": "2024-05-01", "status": "Available", "note": "Spare pool"},
        {"name": "Lenovo ThinkPad (repair)", "category": "Laptop", "serial": "HML-LT-077", "assignedTo": "", "empId": "", "department": "Engineering", "qty": 1, "unitPrice": 21000000, "purchaseDate": "2023-08-12", "status": "In Repair", "note": "Keyboard fault"},
    ]
    for it in items:
        put_collection_item("devices", it)


def _seed_claims(pick):
    """One multi-line expense claim (a trip with several items) for demo."""
    if collection_count("claims"):
        return
    if not pick:
        return
    e = pick[min(2, len(pick) - 1)]
    put_collection_item("claims", {
        "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
        "title": "Long An site visit (3 days)", "type": "Multi-item",
        "ts": "12/06/2026", "status": "Submitted",
        "items": [
            {"id": "ci-1", "category": "Hotel / Accommodation", "amount": 2400000, "note": "2 nights", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-2", "category": "Meal", "amount": 850000, "note": "Team dinner", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-3", "category": "Transport", "amount": 1200000, "note": "Car + fuel", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-4", "category": "Per diem", "amount": 600000, "note": "3 days", "attachment": "", "attachmentName": "", "status": "Submitted"},
        ],
        "amount": 5050000,
    })


def _seed_enrollments(pick):
    if collection_count("enrollments"):
        return
    if not pick:
        return
    courses = ["Workplace Safety (HSE) Essentials", "Project Management Fundamentals", "Business English — Intermediate", "Leadership & Communication", "AutoCAD for Civil Engineers"]
    statuses = [("Completed", 100), ("In progress", 60), ("In progress", 30), ("Enrolled", 0)]
    for i, e in enumerate(pick[:10]):
        crs = courses[i % len(courses)]
        st, pg = statuses[i % len(statuses)]
        put_collection_item("enrollments", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "course": crs, "status": st, "progress": pg,
            "rating": (5 if i % 3 == 0 else 4) if st == "Completed" else 0,
            "feedback": "Very practical, well delivered." if (st == "Completed" and i % 3 == 0) else "",
        })


def _seed_benefits(pick):
    """HR-managed benefits & allowances by grade (G1-G10). Baseline lunch/phone/
    transport match _payComputed welfare so Payroll and Profile agree."""
    if collection_count("benefits"):
        return
    rows = [
        {"grade": "G1",  "lunch": 730000, "phone": 0,       "transport": 300000,  "parking": 0,       "health": "Group accident only",                    "training": 3000000,   "note": "Intern"},
        {"grade": "G2",  "lunch": 730000, "phone": 200000,  "transport": 500000,  "parking": 0,       "health": "IP 200M / OP 20M (from Day 91)",          "training": 5000000,   "note": "Junior"},
        {"grade": "G3",  "lunch": 730000, "phone": 300000,  "transport": 500000,  "parking": 0,       "health": "IP 200M / OP 20M",                        "training": 8000000,   "note": "Engineer / Officer"},
        {"grade": "G4",  "lunch": 730000, "phone": 300000,  "transport": 700000,  "parking": 0,       "health": "IP 200M / OP 20M + rider",                "training": 12000000,  "note": "Senior"},
        {"grade": "G5",  "lunch": 730000, "phone": 500000,  "transport": 1000000, "parking": 500000,  "health": "IP 200M / OP 20M + rider",                "training": 15000000,  "note": "Lead / Supervisor"},
        {"grade": "G6",  "lunch": 730000, "phone": 700000,  "transport": 1500000, "parking": 500000,  "health": "Family health rider",                     "training": 20000000,  "note": "Asst. Manager"},
        {"grade": "G7",  "lunch": 730000, "phone": 1000000, "transport": 2000000, "parking": 1000000, "health": "Family health rider",                     "training": 30000000,  "note": "Manager"},
        {"grade": "G8",  "lunch": 730000, "phone": 1500000, "transport": 3000000, "parking": 1000000, "health": "Family + dependents",                     "training": 40000000,  "note": "Senior Manager"},
        {"grade": "G9",  "lunch": 730000, "phone": 2000000, "transport": 0,       "parking": 1500000, "health": "Family + dependents (car in lieu)",       "training": 60000000,  "note": "Director"},
        {"grade": "G10", "lunch": 730000, "phone": 3000000, "transport": 0,       "parking": 2000000, "health": "Family + dependents + executive plan",    "training": 100000000, "note": "Executive / MD"},
    ]
    for b in rows:
        put_collection_item("benefits", dict(b, id="ben-" + b["grade"]))


def _seed_learningpaths(pick):
    """Role-based development roadmaps (career learning paths)."""
    if collection_count("learningpaths"):
        return
    paths = [
        {"role": "Civil Engineer", "track": "Engineering", "stages": [
            {"name": "Foundation", "months": "0-6", "courses": ["Workplace Safety (HSE) Essentials", "AutoCAD for Civil Engineers"], "certs": ["HSE induction"]},
            {"name": "Practitioner", "months": "6-18", "courses": ["Project Management Fundamentals"], "certs": ["ISO 9001 awareness"]},
            {"name": "Advanced", "months": "18-36", "courses": ["Leadership & Communication"], "certs": ["Site commissioning & TAB"]},
            {"name": "Lead", "months": "36+", "courses": ["Leadership & Communication"], "certs": ["PE / Chartered (target)"]},
        ]},
        {"role": "AHU Factory Technician", "track": "Factory", "stages": [
            {"name": "Foundation", "months": "0-3", "courses": ["Workplace Safety (HSE) Essentials"], "certs": ["LOTO", "Working at height"]},
            {"name": "Practitioner", "months": "3-12", "courses": [], "certs": ["EN 1886 testing", "Hi-Pot / Megger"]},
            {"name": "Advanced", "months": "12-24", "courses": [], "certs": ["FAT witness", "VDI 6022"]},
            {"name": "Lead", "months": "24+", "courses": ["Leadership & Communication"], "certs": ["Site commissioning & TAB"]},
        ]},
        {"role": "Project Coordinator", "track": "Project", "stages": [
            {"name": "Foundation", "months": "0-6", "courses": ["Business English — Intermediate", "Workplace Safety (HSE) Essentials"], "certs": []},
            {"name": "Practitioner", "months": "6-18", "courses": ["Project Management Fundamentals"], "certs": ["ISO 9001"]},
            {"name": "Advanced", "months": "18-36", "courses": ["Leadership & Communication"], "certs": ["PMP (target)"]},
        ]},
    ]
    for i, p in enumerate(paths):
        put_collection_item("learningpaths", dict(p, id="lp-" + str(i + 1)))


def _seed_padr(pick):
    if collection_count("padr"):
        return
    goal_pool = [
        ("Deliver assigned projects on time & on budget", 30, "100% milestones met"),
        ("Quality — defect/rework rate within target", 25, "< 2% rework"),
        ("HSE compliance & 5S", 15, "Zero incidents"),
        ("Skill development & certification", 15, "2 competencies gained"),
        ("Teamwork & customer focus", 15, "Positive 360 feedback"),
    ]
    cyc_status = ["Goal-setting", "Mid-year", "Self-assessment", "Calibrated", "Finalized"]
    for i, e in enumerate(pick[:10]):
        st = cyc_status[i % len(cyc_status)]
        goals = [{"objective": o, "weight": w, "target": t,
                  "selfScore": (4 if i % 2 else 3) if st in ("Self-assessment", "Calibrated", "Finalized") else 0,
                  "mgrScore": (4 if i % 3 else 3) if st in ("Calibrated", "Finalized") else 0}
                 for (o, w, t) in goal_pool]
        put_collection_item("padr", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""), "cycle": "2026",
            "status": st, "goals": goals,
            "rating": (4 if i % 2 else 3) if st == "Finalized" else 0,
            "idp": "Lead a sub-project; complete PM fundamentals course" if i % 2 else "Mentoring & ISO 9001 refresher",
        })


def is_seeded():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
    conn.close()
    return n > 0


def seed():
    """Populate the database from seed_data on first run only."""
    if is_seeded():
        return False
    conn = get_conn()
    cur = conn.cursor()
    for e in seed_data.EMPLOYEES:
        role = "manager" if e["title"] in seed_data.MANAGER_TITLES else "staff"
        cols = ["id", "name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
                "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
                "role", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]
        vals = [e.get(c) for c in cols[:-6]] + [role, e["annualUsed"], e["annualTotal"],
                                                 e["sickUsed"], e["sickTotal"], e["compoff"]]
        cur.execute("INSERT INTO employees (%s) VALUES (%s)" % (
            ",".join(cols), ",".join(["?"] * len(cols))), vals)
    for z in seed_data.ZONES:
        cur.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                    (z["name"], z["lat"], z["lon"], z["radius"]))
    for a in seed_data.sample_attendance():
        cur.execute("INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,hrs,loc) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (a["emp_id"], a["name"], a["dept"], a["date"], a.get("clock_in"),
                     a.get("clock_out"), a["status"], a.get("hrs"), a.get("loc")))
    for l in seed_data.LEAVE:
        cur.execute("INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (l["emp_id"], l["type"], l["startDate"], l["endDate"], l["days"],
                     l["status"], l["reason"], now_iso()))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _rows(sql, params=()):
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row(sql, params=()):
    conn = get_conn()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

EMP_FIELDS = ["name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
              "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
              "managerEmail", "jobLevel", "endDate", "serviceDuration", "personalId",
              "familyStatus", "education", "employmentType", "englishCert", "note", "photo",
              "role", "level", "salary", "grade", "dependents", "appsDenied", "appsAllowed",
              "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]


def list_employees():
    return _rows("SELECT * FROM employees ORDER BY id")


def get_employee(emp_id):
    return _row("SELECT * FROM employees WHERE id = ?", (emp_id,))


def get_employee_by_email(email):
    if not email:
        return None
    return _row("SELECT * FROM employees WHERE LOWER(email) = LOWER(?)", (email.strip(),))


def next_emp_id():
    """Auto-generate the next HML-### employee id."""
    rows = _rows("SELECT id FROM employees WHERE id LIKE 'HML-%'")
    nums = []
    for r in rows:
        tail = r["id"].split("-")[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return "HML-%03d" % ((max(nums) + 1) if nums else 1)


def create_employee(data):
    emp_id = data.get("id") or next_emp_id()
    fields = ["id"] + EMP_FIELDS
    vals = [emp_id] + [data.get(f) for f in EMP_FIELDS]
    conn = get_conn()
    conn.execute("INSERT INTO employees (%s) VALUES (%s)" % (
        ",".join(fields), ",".join(["?"] * len(fields))), vals)
    conn.commit()
    conn.close()
    return emp_id


def update_employee(emp_id, data):
    sets, params = [], []
    for f in EMP_FIELDS:
        if f in data:
            sets.append("%s = ?" % f)
            params.append(data[f])
    if not sets:
        return
    params.append(emp_id)
    conn = get_conn()
    conn.execute("UPDATE employees SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


def delete_employee(emp_id):
    conn = get_conn()
    conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

def list_attendance(emp_id=None, start=None, end=None):
    sql = "SELECT * FROM attendance WHERE 1=1"
    params = []
    if emp_id:
        sql += " AND emp_id = ?"; params.append(emp_id)
    if start:
        sql += " AND date >= ?"; params.append(start)
    if end:
        sql += " AND date <= ?"; params.append(end)
    sql += " ORDER BY date DESC, clock_in DESC"
    return _rows(sql, params)


def open_attendance(emp_id, date):
    return _row("SELECT * FROM attendance WHERE emp_id = ? AND date = ? AND clock_out IS NULL "
                "ORDER BY id DESC LIMIT 1", (emp_id, date))


def _hrs_between(cin, cout):
    try:
        ih, im = map(int, cin.split(":")); oh, om = map(int, cout.split(":"))
        mins = (oh * 60 + om) - (ih * 60 + im)
        return "%dh %02dm" % (mins // 60, mins % 60)
    except (ValueError, AttributeError):
        return ""


def clock_in(emp_id, date, time_hm, loc=None, lat=None, lon=None, status="on-time"):
    emp = get_employee(emp_id)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,status,loc,lat,lon) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (emp_id, emp["name"] if emp else None, emp["dept"] if emp else None,
         date, time_hm, status, loc, lat, lon))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def clock_out(att_id, time_hm, ot_hours=0, ot_reason=""):
    rec = _row("SELECT * FROM attendance WHERE id = ?", (att_id,))
    if not rec:
        return None
    hrs = _hrs_between(rec["clock_in"], time_hm)
    try:
        oth = float(ot_hours or 0)
    except (TypeError, ValueError):
        oth = 0
    conn = get_conn()
    if oth > 0:
        # An overtime REQUEST — pending until a manager approves. Until then it does not count.
        conn.execute("UPDATE attendance SET clock_out = ?, hrs = ?, ot_status = 'pending', ot_hours = ?, ot_reason = ? WHERE id = ?",
                     (time_hm, hrs, oth, (ot_reason or ""), att_id))
    else:
        conn.execute("UPDATE attendance SET clock_out = ?, hrs = ? WHERE id = ?", (time_hm, hrs, att_id))
    conn.commit()
    conn.close()
    return hrs


def get_attendance(att_id):
    return _row("SELECT * FROM attendance WHERE id = ?", (att_id,))


def decide_attendance_ot(att_id, decision):
    """Approve or reject a pending overtime request. Only approved OT counts in the system."""
    st = "approved" if str(decision or "").lower() in ("approve", "approved", "yes") else "rejected"
    conn = get_conn()
    conn.execute("UPDATE attendance SET ot_status = ? WHERE id = ?", (st, att_id))
    conn.commit()
    conn.close()
    return st


def generate_attendance(weeks=6, force=False, anchor=None):
    """Generate realistic recent attendance for all active employees.

    Idempotent: skips entirely when the table already has rows (unless force),
    and never duplicates a given (emp_id, date). Deterministic (seeded RNG) so
    repeated boots/imports don't churn. Returns the number of rows inserted.
    """
    import random
    from datetime import date as _date, timedelta
    conn = get_conn()
    have = conn.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"]
    if have and not force:
        conn.close()
        return 0
    rng = random.Random(20260621)
    emps = [e for e in list_employees() if (e.get("status") or "Active") != "Inactive"]
    # map an employee's stored zone label to a short location tag
    zone_short = {}
    for z in list_zones():
        nm = (z["name"] or "")
        zone_short[nm] = "Factory" if ("factory" in nm.lower() or "long an" in nm.lower()) else "HQ"
    anchor = anchor or _date.today()
    rows = []
    for emp in emps:
        loc_base = zone_short.get(emp.get("zone") or "", "HQ")
        for d in range(weeks * 7):
            day = anchor - timedelta(days=d)
            if day.weekday() >= 5:  # weekend
                continue
            iso = day.isoformat()
            if conn.execute("SELECT 1 FROM attendance WHERE emp_id=? AND date=?",
                            (emp["id"], iso)).fetchone():
                continue
            roll = rng.random()
            if roll < 0.04:  # absent
                rows.append((emp["id"], emp.get("name"), emp.get("dept"), iso,
                             None, None, "absent", "", None))
                continue
            in_h, in_m = 8, rng.randint(0, 34)
            if rng.random() < 0.12:  # late
                in_h, in_m = 8, rng.randint(20, 55)
                status = "late"
            else:
                in_h, in_m = (7, rng.randint(45, 59)) if rng.random() < 0.5 else (8, rng.randint(0, 14))
                status = "on-time"
            cin = "%02d:%02d" % (in_h, in_m)
            out_h, out_m = 17, rng.randint(0, 50)
            cout = "%02d:%02d" % (out_h, out_m)
            loc = "Out of Zone" if rng.random() < 0.02 else loc_base
            rows.append((emp["id"], emp.get("name"), emp.get("dept"), iso,
                         cin, cout, status, _hrs_between(cin, cout), loc))
    conn.executemany(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,hrs,loc) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

def list_leave(emp_id=None, status=None, emp_ids=None):
    sql = ("SELECT l.*, e.name AS emp_name, e.dept AS emp_dept, e.managerEmail AS emp_managerEmail "
           "FROM leave l LEFT JOIN employees e ON e.id = l.emp_id WHERE 1=1")
    params = []
    if emp_id:
        sql += " AND l.emp_id = ?"; params.append(emp_id)
    if emp_ids is not None:
        if not emp_ids:
            return []
        sql += " AND l.emp_id IN (%s)" % ",".join(["?"] * len(emp_ids))
        params.extend(emp_ids)
    if status:
        sql += " AND l.status = ?"; params.append(status)
    sql += " ORDER BY l.startDate DESC"
    return _rows(sql, params)


def list_reports(manager_email):
    """Employees whose direct manager is the given email."""
    if not manager_email:
        return []
    return _rows("SELECT * FROM employees WHERE LOWER(managerEmail) = LOWER(?)", (manager_email,))


def get_leave(leave_id):
    return _row("SELECT * FROM leave WHERE id = ?", (leave_id,))


def create_leave(data):
    import secrets
    token = secrets.token_urlsafe(24)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at,token) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (data["emp_id"], data.get("type"), data.get("startDate"), data.get("endDate"),
         data.get("days"), data.get("status", "pending"), data.get("reason"), now_iso(), token))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid, token


def get_leave_by_token(token):
    if not token:
        return None
    return _row("SELECT * FROM leave WHERE token = ?", (token,))


def set_leave_status(leave_id, status, note=None):
    conn = get_conn()
    conn.execute("UPDATE leave SET status = ?, note = ? WHERE id = ?", (status, note, leave_id))
    conn.commit()
    conn.close()


def append_leave_signature(leave_id, sig, new_status=None):
    """Append a 21 CFR Part 11 e-signature (dict) to a leave record, optionally set its status.
    Returns the row (dict) or None if not found."""
    row = _row("SELECT * FROM leave WHERE id = ?", (leave_id,))
    if not row:
        return None
    try:
        sigs = json.loads(row.get("signatures") or "[]")
    except Exception:
        sigs = []
    sigs.append(sig)
    conn = get_conn()
    if new_status is not None:
        conn.execute("UPDATE leave SET signatures = ?, status = ? WHERE id = ?",
                     (json.dumps(sigs), new_status, leave_id))
    else:
        conn.execute("UPDATE leave SET signatures = ? WHERE id = ?", (json.dumps(sigs), leave_id))
    conn.commit()
    conn.close()
    out = dict(row); out["signatures"] = sigs
    if new_status is not None:
        out["status"] = new_status
    return out


# ---------------------------------------------------------------------------
# 21 CFR Part 11 — signature PIN (second signing component)
#   Stored ONLY as a salted PBKDF2-HMAC-SHA256 hash. The plaintext PIN is never
#   written, logged or returned. Verification is constant-time; repeated failures
#   lock the credential; PINs age out and cannot be immediately reused.
# ---------------------------------------------------------------------------

_HAS_SCRYPT        = hasattr(hashlib, "scrypt")   # scrypt needs OpenSSL (present on the prod Ubuntu box)
SCRYPT_N           = 16384             # scrypt cost — ~16 MiB working set per derive
SCRYPT_R           = 8
SCRYPT_P           = 1
PIN_ITERATIONS     = 600_000           # PBKDF2 rounds (fallback when scrypt is unavailable)
PIN_ALGO           = "scrypt" if _HAS_SCRYPT else "pbkdf2_sha256"   # current KDF for new/changed PINs
PIN_COST           = SCRYPT_N if _HAS_SCRYPT else PIN_ITERATIONS    # cost stored alongside each hash
PIN_SALT_BYTES     = 16
PIN_DKLEN          = 32
PIN_MIN, PIN_MAX   = 6, 12
PIN_LOCK_THRESHOLD = 5
PIN_LOCK_SECONDS   = 15 * 60
PIN_MAX_AGE_DAYS   = 180
# Optional server-side pepper — kept OUTSIDE the database (env var). When set, a leak of the
# SQLite file alone cannot be brute-forced offline. Set TK_ESIGN_PEPPER to a long random string
# in production (e.g. `openssl rand -hex 32`). Empty = no pepper (still salted + slow KDF).
PIN_PEPPER         = os.environ.get("TK_ESIGN_PEPPER", "").encode("utf-8")


def _pin_pre(pin):
    """Fold in the server-side pepper (if configured) before the KDF."""
    pw = (pin or "").encode("utf-8")
    return hmac.new(PIN_PEPPER, pw, hashlib.sha256).digest() if PIN_PEPPER else pw


def _pin_derive(pin, salt_hex, algo=PIN_ALGO, cost=None):
    """Derive the hex key for a PIN + hex salt. Supports scrypt (memory-hard, current) and
    pbkdf2_sha256 (fallback + legacy rows)."""
    salt = bytes.fromhex(salt_hex)
    pw = _pin_pre(pin)
    if algo == "scrypt":
        n = int(cost or SCRYPT_N)
        return hashlib.scrypt(pw, salt=salt, n=n, r=SCRYPT_R, p=SCRYPT_P, maxmem=132 * 1024 * 1024, dklen=PIN_DKLEN).hex()
    return hashlib.pbkdf2_hmac("sha256", pw, salt, int(cost or PIN_ITERATIONS), dklen=PIN_DKLEN).hex()


def _pin_parse_iso(s):
    """Parse an ISO timestamp to an aware UTC datetime, or None if unparseable."""
    try:
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except Exception:
        return None


def _pin_norm(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def validate_pin_policy(emp, pin):
    """Return a machine reason string if the PIN violates policy, else None."""
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9A-Za-z]{%d,%d}" % (PIN_MIN, PIN_MAX), pin or ""):
        return "length"
    if len(set(pin)) == 1:
        return "all_same"
    low = pin.lower()

    def _seq(s, step):
        return len(s) > 1 and all(ord(s[i + 1]) - ord(s[i]) == step for i in range(len(s) - 1))
    if _seq(low, 1) or _seq(low, -1):
        return "sequential"
    if pin in ("1234", "0000", "1111", "2580", "123456", "654321", "111111", "000000", "121212", "abcdef"):
        return "trivial"
    np = _pin_norm(pin)
    if emp and len(np) >= 4:
        for f in ("id", "phone", "email", "dob", "taxId", "personalId"):
            v = emp.get(f) if isinstance(emp, dict) else None
            if not v:
                continue
            nv = _pin_norm(str(v).split("@")[0] if f == "email" else str(v))
            if nv and len(nv) >= 4 and (np == nv or np in nv):
                return "personal_info"
    return None


def get_pin_status(emp_id):
    """Public status for the owner's PIN. NEVER returns hash/salt material."""
    row = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if not row or not row.get("hash"):
        return {"enrolled": False}
    now = datetime.now(timezone.utc)
    locked = False
    lu = row.get("locked_until")
    if lu:
        d = _pin_parse_iso(lu)
        locked = (d is None) or (d > now)   # unparseable -> treat as locked (fail closed)
    age_days = None
    expired = False
    st = row.get("set_ts")
    if st:
        d = _pin_parse_iso(st)
        if d is None:
            expired = True                  # unparseable -> treat as expired (fail closed)
        else:
            age_days = (now - d).days
            expired = age_days > PIN_MAX_AGE_DAYS
    return {"enrolled": True, "status": row.get("status"),
            "revoked": row.get("status") == "revoked",
            "mustChange": bool(row.get("must_change")),
            "locked": locked, "lockedUntil": lu if locked else None,
            "expired": expired, "ageDays": age_days, "setAt": st}


def all_pin_statuses():
    """PIN status for every employee (manager governance view). Never returns hash/salt material."""
    out = []
    for e in list_employees():
        st = get_pin_status(e.get("id"))
        out.append({"empId": e.get("id"), "name": e.get("name"), "dept": e.get("dept"),
                    "title": e.get("title"), "email": e.get("email"),
                    "enrolled": st.get("enrolled", False), "setAt": st.get("setAt"),
                    "locked": st.get("locked", False), "expired": st.get("expired", False),
                    "revoked": st.get("revoked", False), "mustChange": st.get("mustChange", False)})
    return out


def set_pin(emp_id, new_pin, enrolled_via="M365 session", enrolled_oid=None):
    """Enroll or change the PIN (upsert). Blocks immediate reuse of the previous PIN.
    Returns (ok, reason)."""
    prev = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if prev and prev.get("hash") and prev.get("salt"):
        if hmac.compare_digest(_pin_derive(new_pin, prev["salt"], prev.get("algo") or "pbkdf2_sha256", prev.get("iterations")), prev["hash"]):
            return (False, "reuse")   # cannot re-set the identical current PIN
    salt_hex = secrets.token_bytes(PIN_SALT_BYTES).hex()
    h = _pin_derive(new_pin, salt_hex, PIN_ALGO, PIN_COST)
    ts = now_iso()
    conn = get_conn()
    if prev:
        conn.execute(
            "UPDATE esign_pin SET algo=?, iterations=?, salt=?, hash=?, prev_hash=?, status='active', "
            "updated_ts=?, set_ts=?, fail_count=0, last_fail_ts=NULL, locked_until=NULL, must_change=0, "
            "enrolled_via=?, enrolled_oid=? WHERE emp_id=?",
            (PIN_ALGO, PIN_COST, salt_hex, h, prev.get("hash"), ts, ts, enrolled_via, enrolled_oid, emp_id))
    else:
        conn.execute(
            "INSERT INTO esign_pin (emp_id, algo, iterations, salt, hash, status, created_ts, updated_ts, "
            "set_ts, fail_count, must_change, enrolled_via, enrolled_oid) "
            "VALUES (?,?,?,?,?, 'active', ?,?,?, 0, 0, ?, ?)",
            (emp_id, PIN_ALGO, PIN_COST, salt_hex, h, ts, ts, ts, enrolled_via, enrolled_oid))
    conn.commit()
    conn.close()
    return (True, None)


def verify_pin(emp_id, pin):
    """Constant-time PIN verification with lockout / expiry / revoke gates.
    Returns (ok, reason). reason in {None, no_pin, revoked, must_change, locked, expired, bad_pin}."""
    row = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if not row or not row.get("hash"):
        _pin_derive(pin or "", secrets.token_bytes(PIN_SALT_BYTES).hex())  # burn a derive (timing parity)
        return (False, "no_pin")
    if row.get("status") == "revoked":
        return (False, "revoked")
    if row.get("must_change"):
        return (False, "must_change")
    now = datetime.now(timezone.utc)
    lu = row.get("locked_until")
    if lu:
        d = _pin_parse_iso(lu)
        if d is None or d > now:        # unparseable -> treat as locked (fail closed)
            return (False, "locked")
    st = row.get("set_ts")
    if st:
        d = _pin_parse_iso(st)
        if d is None or (now - d).days > PIN_MAX_AGE_DAYS:   # unparseable -> treat as expired (fail closed)
            return (False, "expired")
    got = _pin_derive(pin or "", row["salt"], row.get("algo") or "pbkdf2_sha256", row.get("iterations"))
    ok = hmac.compare_digest(got, row["hash"])
    conn = get_conn()
    if ok:
        if row.get("algo") != PIN_ALGO or (row.get("iterations") or 0) != PIN_COST:
            ns = secrets.token_bytes(PIN_SALT_BYTES).hex()      # transparently upgrade the stored hash to the current KDF
            nh = _pin_derive(pin, ns, PIN_ALGO, PIN_COST)
            conn.execute("UPDATE esign_pin SET salt=?, hash=?, iterations=?, algo=?, fail_count=0, locked_until=NULL WHERE emp_id=?",
                         (ns, nh, PIN_COST, PIN_ALGO, emp_id))
        else:
            conn.execute("UPDATE esign_pin SET fail_count=0, locked_until=NULL WHERE emp_id=?", (emp_id,))
        conn.commit()
        conn.close()
        return (True, None)
    fc = (row.get("fail_count") or 0) + 1
    locked = fc >= PIN_LOCK_THRESHOLD
    if locked:
        lock_iso = (now + timedelta(seconds=PIN_LOCK_SECONDS)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE esign_pin SET fail_count=0, last_fail_ts=?, locked_until=? WHERE emp_id=?",
                     (now_iso(), lock_iso, emp_id))
    else:
        conn.execute("UPDATE esign_pin SET fail_count=?, last_fail_ts=? WHERE emp_id=?",
                     (fc, now_iso(), emp_id))
    conn.commit()
    conn.close()
    # Audit the unauthorized-use attempt (Part 11 §11.300(d) / §11.10(e)) — never records the PIN.
    try:
        emp = get_employee(emp_id) or {}
        put_collection_item("audit", {"actor": emp.get("name") or "System", "actorId": emp_id,
            "action": "E-signature PIN — " + ("locked" if locked else "failed attempt"),
            "target": "esign_pin/" + str(emp_id),
            "detail": ("locked for %d min after %d consecutive failures" % (PIN_LOCK_SECONDS // 60, PIN_LOCK_THRESHOLD)) if locked else ("consecutive failures=" + str(fc)),
            "ts": now_iso()})
    except Exception:
        pass
    return (False, "locked" if locked else "bad_pin")


def admin_reset_pin(emp_id):
    """Admin de-authorize: wipe the hash and force the owner to re-enroll. Cannot set a PIN value."""
    conn = get_conn()
    conn.execute("UPDATE esign_pin SET hash='', prev_hash=NULL, must_change=1, status='active', "
                 "fail_count=0, locked_until=NULL, updated_ts=? WHERE emp_id=?", (now_iso(), emp_id))
    conn.commit()
    conn.close()


def revoke_pin(emp_id):
    """Admin revoke: mark the credential revoked (owner must re-enroll to sign again)."""
    conn = get_conn()
    conn.execute("UPDATE esign_pin SET status='revoked', updated_ts=? WHERE emp_id=?", (now_iso(), emp_id))
    conn.commit()
    conn.close()


def remove_pin(emp_id):
    """Owner removes their own PIN entirely."""
    conn = get_conn()
    conn.execute("DELETE FROM esign_pin WHERE emp_id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones():
    return _rows("SELECT * FROM zones ORDER BY id")


def create_zone(data):
    conn = get_conn()
    cur = conn.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                       (data.get("name"), data.get("lat"), data.get("lon"), data.get("radius")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_zone(zone_id, data):
    sets, params = [], []
    for f in ("name", "lat", "lon", "radius"):
        if f in data:
            sets.append("%s = ?" % f); params.append(data[f])
    if not sets:
        return
    params.append(zone_id)
    conn = get_conn()
    conn.execute("UPDATE zones SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


def delete_zone(zone_id):
    conn = get_conn()
    conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    row = _row("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))
    conn.commit()
    conn.close()


# ── Web Push subscriptions (OS notifications) ──
def push_sub_add(email, sub):
    """Store/refresh a browser's PushSubscription for a user (keyed by its endpoint)."""
    endpoint = (sub or {}).get("endpoint")
    if not endpoint:
        return
    conn = get_conn()
    # On conflict only refresh a row that already belongs to this user — a client cannot
    # re-point another person's (opaque) endpoint to itself.
    conn.execute("INSERT INTO push_subs (endpoint,email,sub,created) VALUES (?,?,?,?) "
                 "ON CONFLICT(endpoint) DO UPDATE SET sub = excluded.sub "
                 "WHERE push_subs.email = excluded.email",
                 (endpoint, (email or "").lower(), json.dumps(sub), now_iso()))
    conn.commit()
    conn.close()


def push_subs_for(emails):
    """Return [(endpoint, sub_dict), …] for the given list of user emails."""
    emails = [(e or "").lower() for e in (emails or []) if e]
    if not emails:
        return []
    ph = ",".join("?" * len(emails))
    rows = _rows("SELECT endpoint, sub FROM push_subs WHERE email IN (%s)" % ph, tuple(emails))
    out = []
    for r in rows:
        try:
            out.append((r["endpoint"], json.loads(r["sub"])))
        except (ValueError, TypeError):
            pass
    return out


def push_sub_remove(endpoint):
    if not endpoint:
        return
    conn = get_conn()
    conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()


# ── Generic collections store (recruitment, onboarding, performance, etc.) ──
def list_collection(coll):
    rows = _rows("SELECT data FROM collections WHERE coll = ? ORDER BY id", (coll,))
    return [json.loads(r["data"]) for r in rows]


def collection_count(coll):
    row = _row("SELECT COUNT(*) AS n FROM collections WHERE coll = ?", (coll,))
    return row["n"] if row else 0


def put_collection_item(coll, item):
    """Insert or update one item (a dict). Generates an id if missing. Returns the item."""
    if not item.get("id"):
        item["id"] = coll[:3] + "-" + uuid.uuid4().hex[:8]
    conn = get_conn()
    conn.execute("INSERT INTO collections (coll,id,data) VALUES (?,?,?) "
                 "ON CONFLICT(coll,id) DO UPDATE SET data = excluded.data",
                 (coll, item["id"], json.dumps(item)))
    conn.commit()
    conn.close()
    return item


def delete_collection_item(coll, item_id):
    conn = get_conn()
    conn.execute("DELETE FROM collections WHERE coll = ? AND id = ?", (coll, item_id))
    conn.commit()
    conn.close()
