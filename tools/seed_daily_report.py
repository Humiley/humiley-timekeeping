#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the Daily Report with the two reports we were handed, so the screen can be compared to them.

This is a DEVELOPMENT tool, not a demo seeder: the point is to reproduce
DailyReport_Mega_Taikisha_09.01.2026.pdf and DailyReport_Mega_Newtecons_09.02.2026.pdf closely
enough that the screen and the exported PDF can be held up against the originals side by side.
Every figure below was read off one of those two files.

    TK_DB_PATH=<worktree>/timekeeping.db python3 tools/seed_daily_report.py

Rows are written with `source: "manual"` so a later SharePoint sync of the same day replaces them
cleanly rather than fighting them.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

PROJECT = {
    "id": "P-MEGA", "name": "Mega Lifesciences",
    "location": "Nhon Trach Industrial Park - Dong Nai",
    "investor": "Mega Lifesciences PCL",
    "consultant": "Newtecons JSC / Taikisha Vietnam Inc",
    "pmConsultant": "Humiley Vietnam Co., Ltd",
    "clientName": "MEGA", "clientLogo": "",
    "startDate": "2025-11-14", "endDate": "2027-04-28",
    "owner": "Admin User", "createdById": "HML-ADM",
}

TAIKISHA = {
    "id": "C-TAI", "name": "Taikisha", "projectId": "P-MEGA", "logo": "",
    "mgmtRoles": ["Admin", "Cad Staff", "Project Manager Electrical", "Project Manager Mechanical",
                  "Safety man", "Site Manager", "Storage man", "Supervisor"],
    "workerTrades": ["Electrical Works", "Fire Fighting Works", "HVAC", "Other Works",
                     "Plumbing Works"],
    "categories": ["Electrical Works", "Fire Fighting Works", "HVAC Works", "Other Works",
                   "Plumbing Works", "Utility Works"],
    "lists": {}, "owner": "Admin User", "createdById": "HML-ADM",
}
NEWTECONS = {
    "id": "C-NEW", "name": "Newtecons", "projectId": "P-MEGA", "logo": "",
    "mgmtRoles": ["Design Coordination", "HSSE Supervisor", "Office Manger", "Project Manager",
                  "QAQC Supervisor", "Quantity Surveyor", "Secretary", "Site Manager",
                  "Supervisor Engineer"],
    "workerTrades": ["Finishing", "Infrastructure", "Steel structure", "Structure", "Surveying",
                     "Temporary electricity and water"],
    "categories": ["Architectural Finishing Works", "Civil Structure Works", "External Works"],
    "lists": {}, "owner": "Admin User", "createdById": "HML-ADM",
}

# Page 4 of the Taikisha file, verbatim.
TAI_PROGRESS = [
    ("Electrical Works", "Electrical manhole manufacturing", 0, 85, "2026-07-31", "2026-09-29"),
    ("Electrical Works", "Install PVC conduit and PVC Box on Brick Wall 2FL", 0, 25, "2026-08-26", "2026-10-25"),
    ("Electrical Works", "Install support on ceiling - Block E 1FL", 30, 30, "2026-09-01", "2026-09-11"),
    ("Electrical Works", "Install support on ceiling - Zone 2 1FL", 10, 10, "2026-08-31", "2026-09-26"),
    ("Electrical Works", "Install support on ceiling - Zone 2 2FL", 20, 60, "2026-08-24", "2026-09-20"),
    ("Electrical Works", "Install support on ceiling - Zone 3 2FL", 5, 5, "2026-08-31", "2026-09-25"),
    ("Electrical Works", "Install underground pipe -External", 0, 95, "2026-06-21", "2026-09-30"),
    ("Fire Fighting Works", "Install support on ceiling - Zone 1 1FL", 15, 50, "2026-08-23", "2026-09-22"),
    ("Fire Fighting Works", "Install support on ceiling - Zone 1 2FL", 10, 86, "2026-08-12", "2026-09-30"),
    ("Fire Fighting Works", "Install support on ceiling - Zone 2 2FL", 20, 45, "2026-08-18", "2026-09-17"),
    ("Fire Fighting Works", "Installing Fire block E plumping", 5, 10, "2026-08-31", "2026-09-12"),
    ("Fire Fighting Works", "Installing Fire fighting pipes - Zone 1 2F", 11, 40, "2026-08-21", "2026-09-14"),
    ("Fire Fighting Works", "Installing Fire fighting pipes - Zone 2 2F", 10, 25, "2026-08-29", "2026-09-12"),
    ("HVAC Works", "Install ACD pipe at - Zone 1 1FL", 0, 84, "2026-08-22", "2026-09-12"),
    ("HVAC Works", "Install cover for opening - Zone 2 2FL", 10, 60, "2026-08-18", "2026-09-05"),
    ("HVAC Works", "Install cover for opening - Zone 3 2FL", 10, 40, "2026-08-29", "2026-09-12"),
    ("HVAC Works", "Install PAc duct Zone 1 1FL", 8, 60, "2026-08-25", "2026-09-14"),
    ("HVAC Works", "Install support on ceiling - Zone 1 1FL", 3, 97, "2026-08-11", "2026-09-05"),
    ("HVAC Works", "Install support on ceiling - Zone 1 2FL", 15, 95, "2026-08-12", "2026-09-05"),
    ("HVAC Works", "Install ventilation duct Zone 1 1FL", 0, 62, "2026-08-23", "2026-09-12"),
    ("Other Works", "Monitor and marking the machine base (Fan, CDU, Chiller pump, ...)", 20, 45, "2026-08-25", "2026-09-05"),
    ("Plumbing Works", "Install hanger block E plumping", 5, 20, "2026-08-28", "2026-09-05"),
    ("Plumbing Works", "Install PPR pipe - Zone 1 1FL", 28, 60, "2026-08-26", "2026-09-30"),
    ("Plumbing Works", "Install support on ceiling - Zone 1 1FL", 20, 84, "2026-08-20", "2026-09-12"),
    ("Plumbing Works", "Install underground pipe - External", 0, 98, "2026-06-08", "2026-09-15"),
    ("Plumbing Works", "Install underground pipe - Zone 3 1FL", 0, 80, "2026-08-10", "2026-09-05"),
    ("Plumbing Works", "Install Waste water toilet 2FL zone 1", 5, 60, "2026-08-25", "2026-09-05"),
    ("Utility Works", "Install support on ceiling - Zone 1 1FL", 5, 70, "2026-08-18", "2026-10-15"),
    ("Utility Works", "Install support on ceiling - Zone 1 2FL", 7, 20, "2026-08-28", "2026-09-12"),
    ("Utility Works", "Install support on ceiling - Zone 2 1FL", 5, 10, "2026-08-29", "2026-09-12"),
]
# Page 6 of the Taikisha file.
TAI_PLAN = [
    ("Electrical Works", "IInstall support on ceiling", "1FL Zone 2"),
    ("Electrical Works", "Install support on ceiling", "2FL Zone 2"),
    ("Electrical Works", "Install underground pipe - External", "External"),
    ("Fire Fighting Works", "Install ceiling support - Zone 1 2FL", "2FL Zone 1"),
    ("Fire Fighting Works", "Install ceiling support - Zone 2 2FL", "2FL Zone 2"),
    ("Fire Fighting Works", "Installing Fire fighting pipes - Zone 1 1F", "1FL Zone 1"),
    ("Fire Fighting Works", "Installing Fire fighting pipes - Zone 1 2F", "2FL Zone 1"),
    ("HVAC Works", "Install ACD pipe at - Zone 1 1FL", "Zone 1 1FL"),
    ("HVAC Works", "Install cover for opening - Zone 2 2FL", "Zone 2 2FL"),
    ("HVAC Works", "Install support on ceiling - Zone 1 1FL", "Zone 1 1FL"),
    ("HVAC Works", "Install support on ceiling - Zone 1 2FL", "Zone 1 2FL"),
    ("HVAC Works", "Install ventilation duct Zone 1 1FL", "Zone 1 1FL"),
    ("Other Works", "Fabricate support at workshop", "Workshop Subcon"),
    ("Plumbing Works", "Install ceiling support - Zone 1 1FL", "Zone 1 1FL"),
    ("Plumbing Works", "Install PPR pipe Zone 1 1FL", "Zone 1 1FL"),
    ("Plumbing Works", "Install underground pipe - External", "External"),
    ("Plumbing Works", "Install underground pipe - Zone 2 1FL", "Zone 2 1FL"),
    ("Plumbing Works", "Install underground pipe - Zone 3 1FL", "Zone 3 1FL"),
    ("Utility Works", "IInstall ceiling support - Zone 1 1FL", "1FL Zone 1"),
    ("Utility Works", "IInstall ceiling support - Zone 2 1FL", "1FL Zone 2"),
    ("Utility Works", "IInstall utility piping - Zone 1 1FL", "1FL Zone 1"),
]
# Page 4 of the Newtecons file.
NEW_PROGRESS = [
    ("Architectural Finishing Works", "Construction of Brick wall - Warehouse C", 1, 99, "2026-08-15", "2026-10-05"),
    ("Architectural Finishing Works", "Construction of Plastering - Warehouse C", 10, 80, "2026-08-23", "2026-10-02"),
    ("Architectural Finishing Works", "Construction of 2nd floor Brick wall - Zone 1,Manufacturing A", 0, 99, "2026-08-12", "2026-10-05"),
    ("Architectural Finishing Works", "Construction of steel Frame for Panel - Warehouse C", 2, 99, "2026-08-17", "2026-11-03"),
    ("Architectural Finishing Works", "Install Panel Wall - Warehouse C", 3, 62, "2026-08-17", "2026-11-03"),
    ("Civil Structure Works", "Construction of 1st floor slab - Manufacturing A", 2, 89, "2026-07-22", "2026-08-27"),
    ("Civil Structure Works", "Construction of roof floor slab - Manufacturing A", 4, 87, "2026-08-03", "2026-08-27"),
    ("Civil Structure Works", "Structural construction - Auxiliary Administration E", 0, 94, "2026-06-15", "2026-09-03"),
    ("Civil Structure Works", "Structural construction - Block Q", 1, 85, "2026-08-10", "2026-09-04"),
    ("Civil Structure Works", "Structural construction - PCC Panel room G", 1, 66, "2026-07-07", "2026-09-03"),
    ("External Works", "Construction of storm drainage system", 0, 91, "2026-04-23", "2026-11-22"),
]

SAFETY_ALL_YES = {
    "Barricade & Warning Sign Check": {"status": "Yes", "notes": ""},
    "Daily Toolbox Talk (15 mins)": {"status": "Yes", "notes": ""},
    "Emergency Access & Exit Inspection": {"status": "Yes", "notes": ""},
    "Equipment Safety Inspection": {"status": "Yes", "notes": ""},
    "Fire Prevention & Hot Work Inspection": {"status": "Yes", "notes": ""},
    "First Aid & Emergency Preparedness Check": {"status": "Yes", "notes": ""},
    "Housekeeping Inspection": {"status": "Yes", "notes": ""},
    "PPE Compliance Inspection": {"status": "Yes", "notes": ""},
    "Temporary Electrical Safety Check": {"status": "Yes", "notes": ""},
    "Work Permit Verification": {"status": "Yes", "notes": ""},
    "Working at Height Safety Check": {"status": "Yes", "notes": ""},
}


def _prog(rows):
    return [{"category": c, "item": i, "daily": d, "accum": a, "start": s, "finish": f}
            for c, i, d, a, s, f in rows]


def _plan(rows):
    return [{"category": c, "item": i, "location": l, "notes": ""} for c, i, l in rows]


def report(cid, day, weather, mgmt, workers, progress=None, plan=None, equipment=None,
           inspection_plan=None, safety=None):
    return {
        "id": "DR-%s-%s" % (cid, day), "projectId": "P-MEGA", "contractorId": cid, "date": day,
        "source": "manual", "status": "submitted",
        "owner": "Admin User", "createdById": "HML-ADM",
        "weather": weather, "mgmt": mgmt, "workers": workers,
        "equipment": equipment or [], "materials": [],
        "progress": progress or [], "plan": plan or [],
        "documents": [], "defects": [],
        "inspections": [], "inspectionPlan": inspection_plan or [],
        "safety": safety if safety is not None else SAFETY_ALL_YES,
        "recommendations": [],
    }


# The six earlier days each bar chart shows, so the 7-day charts and the delta arrows are real.
TAI_HISTORY = [("2026-08-26", 17, 104), ("2026-08-27", 17, 120), ("2026-08-28", 18, 120),
               ("2026-08-29", 20, 111), ("2026-08-30", 3, 21), ("2026-08-31", 14, 74)]
NEW_HISTORY = [("2026-08-27", 13, 139), ("2026-08-28", 13, 160), ("2026-08-29", 13, 154),
               ("2026-08-30", 13, 103), ("2026-08-31", 13, 120), ("2026-09-01", 13, 93)]


def main():
    db.init_db()
    db.put_collection_item("dr_projects", PROJECT)
    db.put_collection_item("dr_contractors", TAIKISHA)
    db.put_collection_item("dr_contractors", NEWTECONS)

    sunny = {"morning": "Sunny", "afternoon": "Sunny", "evening": "Sunny",
             "avgTemp": "30", "rainHours": "1"}
    clear = {"morning": "Clear up", "afternoon": "Clear up", "evening": "Clear up",
             "avgTemp": "30", "rainHours": "0"}

    for day, m, w in TAI_HISTORY:
        db.put_collection_item("dr_reports", report(
            "C-TAI", day, sunny, {"Supervisor": m}, {"HVAC": w}))
    for day, m, w in NEW_HISTORY:
        db.put_collection_item("dr_reports", report(
            "C-NEW", day, clear, {"Supervisor Engineer": m}, {"Structure": w}))

    # 01/09 — the Taikisha report, page for page.
    db.put_collection_item("dr_reports", report(
        "C-TAI", "2026-09-01", sunny,
        {"Admin": 0, "Cad Staff": 7, "Project Manager Electrical": 0,
         "Project Manager Mechanical": 0, "Safety man": 0, "Site Manager": 1,
         "Storage man": 0, "Supervisor": 5},
        {"Electrical Works": 17, "Fire Fighting Works": 10, "HVAC": 43, "Other Works": 0,
         "Plumbing Works": 21},
        progress=_prog(TAI_PROGRESS), plan=_plan(TAI_PLAN),
        equipment=[{"item": "Concrete Drill Battery", "qty": "6", "unit": "pcs", "notes": ""},
                   {"item": "Excavator", "qty": "1", "unit": "pcs", "notes": ""},
                   {"item": "Plate compactor", "qty": "1", "unit": "pcs", "notes": ""}]))

    # 02/09 — the Newtecons report.
    db.put_collection_item("dr_reports", report(
        "C-NEW", "2026-09-02", clear,
        {"Design Coordination": 1, "HSSE Supervisor": 2, "Office Manger": 1, "Project Manager": 1,
         "QAQC Supervisor": 1, "Quantity Surveyor": 1, "Secretary": 1, "Site Manager": 1,
         "Supervisor Engineer": 4},
        {"Finishing": 30, "Infrastructure": 0, "Steel structure": 0, "Structure": 52,
         "Surveying": 4, "Temporary electricity and water": 0},
        progress=_prog(NEW_PROGRESS),
        plan=_plan([(c, i, l) for c, i, l in [
            ("Architectural Finishing Works", "Construction of Brick wall - Warehouse C", "Warehouse C"),
            ("Architectural Finishing Works", "Construction of Plastering - Warehouse C", "Warehouse C"),
            ("Architectural Finishing Works", "Construction of 2nd floor Brick wall - Manufacturing A", "Manufacturing A"),
            ("Architectural Finishing Works", "Construction of steel Frame for Panel - Warehouse C", "Warehouse C"),
            ("Architectural Finishing Works", "Install Panel Wall - Warehouse C", "Warehouse C"),
            ("Civil Structure Works", "Construction of 1st floor slab - Manufacturing A", "Manufacturing A"),
            ("Civil Structure Works", "Construction of roof floor slab - Manufacturing A", "Manufacturing A"),
            ("Civil Structure Works", "Structural construction - Auxiliary Administration", "Auxiliary Administration E"),
            ("Civil Structure Works", "Structural construction - PCC Panel room G", "PCC Panel room G"),
            ("External Works", "Construction of storm drainage system", "Infrastructure")]]),
        equipment=[{"item": n, "qty": q, "unit": "pcs", "notes": ""} for n, q in [
            ("Boom lift", "2"), ("Bulldozer", "1"), ("Crawler Crane", "1"), ("Excavator", "3"),
            ("Kato Crane", "3"), ("Roller", "2"), ("Tower crane", "1"), ("Truck", "2")]],
        inspection_plan=[{"item": "Inspection of beam rebar & formwork",
                          "location": "Manufacturing A", "time": "14h00", "notes": ""}]))

    print("seeded: 1 project, 2 contractors, %d reports"
          % len([r for r in db.list_collection("dr_reports")]))


if __name__ == "__main__":
    main()
