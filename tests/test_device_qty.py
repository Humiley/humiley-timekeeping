"""Per-assignment quantity model: an asset holds a total `qty` and an `assignments[]` list. A holder
e-signs ONLY their own assignment (append-only), a non-holder is rejected, and the admin backfill marks
every unacknowledged assignment as acknowledged-on-record (an honest migration note, not a forged sig).
"""
import db

SIG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _dev_with_assigns():
    d = db.put_collection_item("devices", {"name": "Uniform", "category": "Uniform / Shirt", "qty": 6,
        "unitPrice": 250000, "status": "Assigned", "assignments": [
            {"id": "a1", "empId": "HML-STF", "name": "Staff One", "qty": 2, "assignedOn": "2026-07-25", "signatures": []},
            {"id": "a2", "empId": "HML-OTH", "name": "Other Staff", "qty": 3, "assignedOn": "2026-07-25", "signatures": []}]})
    return d["id"]


def test_holder_signs_only_their_own_assignment(api, tokens):
    did = _dev_with_assigns()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"], {"ackSignature": {"image": SIG}})  # staff == HML-STF
    assert st == 200, b
    row = next(x for x in db.list_collection("devices") if x.get("id") == did)
    a1 = next(a for a in row["assignments"] if a["id"] == "a1")   # Staff One's — signed
    a2 = next(a for a in row["assignments"] if a["id"] == "a2")   # Other Staff's — untouched
    assert a1.get("ackOn") and any(s.get("ack") for s in (a1.get("signatures") or []))
    assert not a2.get("ackOn") and not any(s.get("ack") for s in (a2.get("signatures") or []))


def test_non_holder_cannot_sign_any_assignment(api, tokens):
    did = _dev_with_assigns()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["mgr"], {"ackSignature": {"image": SIG}})  # HML-MGR holds nothing
    assert st == 403, b


def test_admin_backfill_marks_unacknowledged(api, tokens):
    did = _dev_with_assigns()
    st, b = api("POST", "/api/devices/ack-backfill", tokens["admin"], {})
    assert st == 200 and b.get("count") >= 2, b
    row = next(x for x in db.list_collection("devices") if x.get("id") == did)
    for a in row["assignments"]:
        assert a.get("ackOn") and any(s.get("legacy") for s in (a.get("signatures") or []))


def test_backfill_requires_admin(api, tokens):
    st, b = api("POST", "/api/devices/ack-backfill", tokens["mgr"], {})
    assert st == 403, b
