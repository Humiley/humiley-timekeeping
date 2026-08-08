"""Asset receipt acknowledgment — the HOLDER of a device e-signs from their own My Devices.

Staff cannot PATCH the devices collection at all (manager-only write), so acknowledging receipt goes
through a dedicated owner-scoped, APPEND-ONLY path in _coll_update: a caller may add exactly one ack
signature to a device assigned to them (by empId, or by name when empId is absent), and nothing else on
the record is writable that way. A non-owner is rejected; a non-image "signature" is rejected.
"""
import db

SIG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _device(assigned_to="Staff One", emp_id="HML-STF", price=22_000_000):
    d = db.put_collection_item("devices", {"name": "Dell Latitude", "category": "Laptop",
        "assignedTo": assigned_to, "empId": emp_id, "department": "Engineering", "qty": 1,
        "unitPrice": price, "status": "Assigned"})
    return d["id"]


def test_holder_can_acknowledge_receipt(api, tokens):
    did = _device()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"], {"ackSignature": {"image": SIG}})
    assert st == 200, b
    row = next(x for x in db.list_collection("devices") if x.get("id") == did)
    sig = next((s for s in (row.get("signatures") or []) if s.get("ack")), None)
    assert sig and sig.get("image") == SIG and "acknowledged receipt" in (sig.get("meaning") or "").lower()
    assert row.get("ackOn") and row.get("ackBy")


def test_non_owner_cannot_acknowledge(api, tokens):
    did = _device(assigned_to="Someone Else", emp_id="HML-OTH")   # assigned to a different employee
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"], {"ackSignature": {"image": SIG}})
    assert st == 403, b
    row = next(x for x in db.list_collection("devices") if x.get("id") == did)
    assert not any(s.get("ack") for s in (row.get("signatures") or []))


def test_ack_requires_a_drawn_image_not_a_url(api, tokens):
    did = _device()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"],
                {"ackSignature": {"image": "https://evil.example/x"}})
    assert st == 400, b


def test_ack_is_append_only_cannot_rewrite_the_asset(api, tokens):
    # A staff caller sending other fields alongside the ack must NOT change assignee/status/price —
    # the ack path only appends a signature; everything else on the record is preserved.
    did = _device()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"],
                {"ackSignature": {"image": SIG}, "assignedTo": "Hijack", "empId": "HML-OTH",
                 "status": "Available", "unitPrice": 1})
    assert st == 200, b
    row = next(x for x in db.list_collection("devices") if x.get("id") == did)
    assert row.get("assignedTo") == "Staff One" and row.get("empId") == "HML-STF"
    assert row.get("status") == "Assigned" and row.get("unitPrice") == 22_000_000


def test_staff_still_cannot_do_a_plain_device_patch(api, tokens):
    # Without ackSignature, a staff PATCH of devices is still manager-only (unchanged).
    did = _device()
    st, b = api("PATCH", "/api/coll/devices/" + did, tokens["staff"], {"status": "Retired"})
    assert st == 403, b
