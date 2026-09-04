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

print("done")
