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
    # NOTE the integers. A whole-number float cannot survive the round trip between the two
    # languages that have to agree on these bytes:
    #
    #   python3 -c "import json;print(json.dumps(810.0))"  ->  810.0
    #   node    -e "console.log(JSON.stringify(810.0))"    ->  810
    #
    # JavaScript has no int/float distinction and cannot emit the trailing .0 at all. An example
    # carrying 810.0 is therefore unreproducible from a JS exporter — which defeats the entire
    # purpose of shipping it as the thing they assert against. See assert_js_reproducible below.
    "performance": {
        "erp": {"verdict": "PASS", "sfpIntWm3s": 810, "limitWm3s": 1000},
        "euroventClass": "A+",
        "faceVelocity_ms": 2.1,          # a genuine fraction — renders identically in both
    },
    "sections": [
        {"type": "outdoor_intake"}, {"type": "filter_pre"}, {"type": "filter_bag"},
        {"type": "cooling_coil_chw"}, {"type": "heating_coil_hw"},
        {"type": "fan_supply"}, {"type": "filter_hepa"},
    ],
}

env = {
    "document": "selection",
    "specVersion": S.SPEC_VERSION,
    "selectionRef": "AS-2026-0410",
    "engine": "AeroSelect",
    "engineVersion": "2.0.0",
    "generatedOn": "2026-08-20T09:14:00Z",
}
# The hash covers the envelope's identifying fields as well as the payload, so it is computed once
# the envelope is complete. No `signature` here on purpose: the example must import cleanly on a
# portal with no shared secret configured, and be reported unverified — the honest default.
env["contentHash"] = S.content_hash(env, payload)
doc = {"aeroselect": env, "payload": payload}


def assert_js_reproducible(obj, path="payload"):
    """Refuse to write an example a JavaScript exporter could never reproduce.

    The fixture exists so the AeroSelect side can assert byte-equality against it. That promise is
    only true if every value in it renders identically under Python's json.dumps and JavaScript's
    JSON.stringify. Whole-number floats do not: Python writes 810.0, JavaScript writes 810, and the
    hashes then differ for a document that is otherwise perfectly correct.

    Caught only after the spec had already told them to assert against it, so it is a guard now
    rather than a comment.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert_js_reproducible(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_js_reproducible(v, "%s[%d]" % (path, i))
    elif isinstance(obj, float) and obj.is_integer():
        raise SystemExit(
            "REFUSING to write the example: %s is %r, a whole-number float.\n"
            "  Python renders it %s; JavaScript renders it %s. A JS exporter could never\n"
            "  reproduce this file's hash, which is the one thing the example is for.\n"
            "  Write it as the integer %d instead."
            % (path, obj, json.dumps(obj), int(obj), int(obj)))


assert_js_reproducible(doc["payload"])
assert_js_reproducible({"envelope": {k: env[k] for k in S.SIGNED_ENVELOPE_FIELDS}})

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
