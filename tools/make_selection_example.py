#!/usr/bin/env python3
"""Write the worked selection-document example the handoff spec points at.

Generated rather than hand-written, so its content hash is genuinely correct — a spec whose own
example fails the check it documents is worse than no example. Re-run after changing the shape:

    PYTHONPATH=. python3 tools/make_selection_example.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ahu_selection as S   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "examples", "aeroselect-selection-example.json")

payload = {
    "project": {
        "number": "P-2026-014",
        "name": "Cleanroom Block B — AHU package",
        "client": "Vinh Phuc Pharma JSC",
        "location": "Vinh Phuc, Vietnam",
        "elevation_m": 10,
    },
    "unit": {
        "tag": "AHU-B-01",
        "model": "AeroSmart AS-24",
        "family": "hygienic",
        "airflow_m3h": 12000,
        "esp_pa": 450,
        "voltage_v": 400,
        "coilDesignBar": 16,
        "cleanroom": "ISO 7",
        "dimensions_mm": {"width": 2400, "height": 2000, "length": 6750},
    },
    # D, T and TB are computed by AeroSelect. L and F are the classes the unit is SOLD as — the
    # factory's tests T3 and T4 are what establish them on the built casing.
    "classes": {"D": "D1", "L": "L1", "F": "F9", "T": "T1", "TB": "TB1"},
    "performance": {
        "erp": {"verdict": "PASS", "sfpIntWm3s": 810.0, "limitWm3s": 1000.0},
        "euroventClass": "A+",
        "faceVelocity_ms": 2.1,
    },
    "sections": [
        {"type": "outdoor_intake"}, {"type": "filter_pre"}, {"type": "filter_bag"},
        {"type": "cooling_coil_chw"}, {"type": "heating_coil_hw"},
        {"type": "fan_supply"}, {"type": "filter_hepa"},
    ],
}

doc = {
    "aeroselect": {
        "document": "selection",
        "specVersion": S.SPEC_VERSION,
        "selectionRef": "AS-2026-0410",
        "engine": "AeroSelect",
        "engineVersion": "2.0.0",
        "generatedOn": "2026-08-20T09:14:00Z",
        "contentHash": S.content_hash(payload),
        # No `signature` here on purpose: the example must import cleanly on a portal with no
        # shared secret configured, and be reported as unverified — which is the honest default.
    },
    "payload": payload,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

check = S.parse(doc)
print("wrote", OUT)
print("  parses  :", S.summary(check))
print("  hash    :", check["contentHash"])
print("  verified:", check["verified"], "(no secret configured — the honest default)")
print("  targets :", S.classes_measured_by_test(check))
