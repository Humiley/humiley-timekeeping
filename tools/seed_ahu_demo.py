#!/usr/bin/env python3
"""Seed a small AHU production demo: two people, an order, and one modular unit with its route.

For looking at the module with real data in it. Writes to whatever TK_DB_PATH points at, so point
it at a throwaway file — never the production database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db          # noqa: E402
import ahu         # noqa: E402

db.init_db()

if not db.list_employees():
    db.create_employee({"id": "HML-ADM", "name": "Admin User", "email": "admin@humiley.com",
                        "role": "manager", "level": "admin", "title": "Managing Director",
                        "dept": "Operation", "annualTotal": 12, "annualUsed": 0})
    db.create_employee({"id": "HML-PRD", "name": "Tran Van Long", "email": "long@humiley.com",
                        "role": "staff", "level": "staff", "title": "Production Lead",
                        "dept": "Factory", "managerEmail": "admin@humiley.com"})
    db.create_employee({"id": "HML-QC", "name": "Pham Thi Mai", "email": "mai@humiley.com",
                        "role": "staff", "level": "staff", "title": "QC Inspector",
                        "dept": "Factory", "managerEmail": "admin@humiley.com"})
    print("seeded 3 employees")

if not db.list_collection("ahu_orders"):
    order = db.put_collection_item("ahu_orders", {
        "id": "ahu-ord-demo", "poNumber": "PO-2026-0417", "customer": "Vinh Phuc Pharma JSC",
        "project": "Cleanroom Block B — AHU package", "orderDate": "2026-07-28",
        "deliveryDate": "2026-09-30", "incoterms": "DDP Ho Chi Minh City",
        "paymentTerms": "30% advance / 60% on FAT / 10% on handover", "warrantyMonths": 18,
        "contractReviewSigned": True, "contractReviewBy": "Admin User",
        "contractReviewOn": "2026-07-29", "scheduleBaselined": "Yes", "openExceptions": 0,
        "fatRequired": "Yes", "salesOwner": "Admin User",
        "productionLead": "Tran Van Long", "qcInspector": "Pham Thi Mai"})
    print("seeded order", order["poNumber"])

    for i, (pin, tag, fam, cr) in enumerate([
            ("PIN-2026-0417-01", "AHU-B-01", "hygienic", "ISO7"),
            ("PIN-2026-0417-02", "AHU-B-02", "modular", None),
            ("PIN-2026-0417-03", "AHU-B-03", "outdoor", None)]):
        unit = db.put_collection_item("ahu_units", {
            "id": "ahu-unit-demo-%d" % (i + 1), "orderId": "ahu-ord-demo",
            "pin": pin, "tag": tag, "family": fam,
            "model": "AeroSmart AS-%d" % (18 + i * 6),
            "airflow": 12000 + i * 4000, "esp": 450, "voltage": 400, "coilDesignBar": 16,
            "cleanroom": cr, "selectionRef": "AS-2026-%03d" % (410 + i),
            "fatRequired": "Yes" if i == 0 else "", "bomStatus": "Draft",
            "productionLead": "Tran Van Long", "qcInspector": "Pham Thi Mai",
            "status": "In production"})
        rows = ahu.instantiate(unit, db.get_collection_item("ahu_orders", "ahu-ord-demo"))
        for r in rows:
            r.setdefault("id", "%s-%s" % (unit["id"], r["code"]))
            db.put_collection_item("ahu_steps", r)
        print("seeded", pin, fam, "with", len(rows), "steps")

    # A little history on the first unit so the board is not uniformly empty.
    for code, who in [("G1", "Admin User")]:
        s = db.get_collection_item("ahu_steps", "ahu-unit-demo-1-" + code)
        if s:
            s["status"] = "Passed"
            s["signedBy"] = who
            s["signedOn"] = "2026-08-01"
            db.put_collection_item("ahu_steps", s)
    db.put_collection_item("ahu_docs", {
        "id": "ahu-doc-demo-1", "unitId": "ahu-unit-demo-1", "kind": "GA drawing",
        "docNo": "HML-AHU-GA-HYG-0417-01", "title": "General arrangement — AHU-B-01",
        "rev": "C01", "status": "Issued", "issuedOn": "2026-08-03", "form": "HML-AHU-GA-HYG-001"})
    for n, (p, q) in enumerate([("PROF-40", 48), ("PANEL-50PU", 62), ("FAN-EC-560", 2),
                                ("COIL-CHW-6R", 1), ("FLT-F9", 6)]):
        db.put_collection_item("ahu_bom", {
            "id": "ahu-bom-demo-%d" % n, "unitId": "ahu-unit-demo-1", "partNo": p,
            "description": p, "qty": q, "kittedQty": q if n < 3 else 0,
            "receivedQty": q if n < 3 else 0, "iqcStatus": "Passed" if n < 3 else "Pending",
            "shortageQty": 0})
    print("seeded a GA drawing and 5 BOM lines on the first unit")

# ── The evidence registers ──────────────────────────────────────────────────────────────────────
# Seeded because an empty screen cannot be told apart from a broken one. Somebody opening Quality
# Evidence on a fresh demo database was seeing nothing at all, which is the same thing a bug looks
# like — and it gave them no idea what a good record is supposed to contain.
#
# The examples are deliberately not all healthy. One instrument is out of calibration, one has no
# due date at all, and one qualification has expired: those are the three states the screen exists
# to separate, and a demo where everything is green demonstrates nothing.

if not db.list_collection("ahu_instruments"):
    for i in [
        {"id": "ahu-instr-1", "name": "Digital manometer", "type": "Manometer",
         "serial": "DM-99181", "maker": "Testo 512-1", "calDate": "2026-03-15",
         "calDue": "2027-03-15", "certNo": "VN-CAL-2026-4417", "calBy": "QUATEST 3",
         "location": "QC room"},
        {"id": "ahu-instr-2", "name": "Hi-pot tester", "type": "Hi-pot tester",
         "serial": "HP-0042", "maker": "Kikusui TOS5301", "calDate": "2025-06-30",
         # Out of calibration: signing a T7 against this is refused, which is the point.
         "calDue": "2026-06-30", "certNo": "VN-CAL-2025-2210", "calBy": "QUATEST 3",
         "location": "Test bay"},
        {"id": "ahu-instr-3", "name": "Vane anemometer", "type": "Anemometer",
         "serial": "AN-7734", "maker": "TSI 5725",
         # No due date recorded. Reads UNKNOWN, never VALID — and is listed separately, because an
         # instrument with no due date never appears in a report sorted by due date.
         "location": "Test bay"},
    ]:
        db.put_collection_item("ahu_instruments", i)
    print("seeded 3 test instruments (one expired, one with no due date)")

if not db.list_collection("ahu_quals"):
    for q in [
        {"id": "ahu-qual-1", "person": "Pham Thi Mai", "scope": "ipqc",
         "qualifiedOn": "2025-02-01", "expiresOn": "2028-02-01", "certRef": "HML-QA-COMP-014",
         "issuedBy": "QA Manager"},
        {"id": "ahu-qual-2", "person": "Pham Thi Mai", "scope": "T3, T4",
         "qualifiedOn": "2025-02-01", "expiresOn": "2028-02-01", "certRef": "HML-QA-COMP-015",
         "issuedBy": "QA Manager"},
        {"id": "ahu-qual-3", "person": "Tran Van Long", "scope": "T7",
         # Expired: the hi-pot qualification lapsed and nobody renewed it.
         "qualifiedOn": "2023-01-10", "expiresOn": "2026-01-10", "certRef": "HML-QA-COMP-009",
         "issuedBy": "QA Manager"},
    ]:
        db.put_collection_item("ahu_quals", q)
    print("seeded 3 qualifications (one expired)")

if not db.list_collection("ahu_trace"):
    # Two units share a fan batch, so the recall search has something real to find. This is the shape
    # of the question that matters: a supplier reports a fault in B-2026-14, which units got it?
    for n, (unit_id, comp, maker, serial, batch) in enumerate([
        ("ahu-unit-demo-1", "Fan", "ebm-papst", "EB-2026-0091", "B-2026-14"),
        ("ahu-unit-demo-2", "Fan", "ebm-papst", "EB-2026-0092", "B-2026-14"),
        ("ahu-unit-demo-1", "Motor", "WEG", "WG-2026-5512", "M-2026-03"),
        ("ahu-unit-demo-1", "Coil", "Kaori", "KO-771-A", "C-2026-99"),
    ]):
        db.put_collection_item("ahu_trace", {
            "id": "ahu-trace-demo-%d" % n, "unitId": unit_id, "component": comp,
            "maker": maker, "serial": serial, "batch": batch, "recordedOn": "2026-08-05"})
    print("seeded 4 component serials (two units share fan batch B-2026-14)")

print("done")
