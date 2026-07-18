"""HTTP integration / regression tests against the real Handler.

Pins the security fixes from the 2026-07 QA passes:
  - auth is required on the collection API
  - Work Schedules are a real manager-only managed collection (CRUD, updates in place)
  - a payment can only be edited by its owner while still pending (owner-scope guard)
  - approval status can't be forged through the generic write path (Part 11 integrity)
  - attendance rows (which carry GPS) are scoped — staff can't read another person's rows
"""
import db
import app


PAY = {"reqNo": "PR-T", "payee": "ACME Co", "category": "Office", "amount": 1000,
       "status": "Submitted", "attachment": "data:application/pdf;base64,JVBERi0xLjQK"}


# --------------------------------------------------------------------------- auth required
def test_collection_api_requires_auth(api):
    st, _ = api("GET", "/api/coll/payments")
    assert st in (401, 403), "unauthenticated read of a collection must be rejected"


# --------------------------------------------------------------------------- schedules CRUD (manager)
def test_schedules_crud_manager(api, tokens):
    st, r = api("POST", "/api/coll/schedules", tokens["admin"],
                {"name": "Test Shift", "dept": "All", "start": "08:00", "end": "17:00", "active": True})
    assert st == 200 and r["item"].get("id"), r
    sid = r["item"]["id"]

    st, r = api("GET", "/api/coll/schedules", tokens["admin"])
    assert st == 200 and any(x["id"] == sid for x in r["items"])

    # PATCH replaces the whole item in place — must UPDATE, not duplicate
    st, r = api("PATCH", "/api/coll/schedules/" + sid, tokens["admin"],
                {"id": sid, "name": "Test Shift EDITED", "dept": "All",
                 "start": "09:00", "end": "18:00", "active": True})
    assert st == 200
    st, r = api("GET", "/api/coll/schedules", tokens["admin"])
    matches = [x for x in r["items"] if x["id"] == sid]
    assert len(matches) == 1, "PATCH must update in place, not create a duplicate"
    assert matches[0]["name"] == "Test Shift EDITED"

    st, _ = api("DELETE", "/api/coll/schedules/" + sid, tokens["admin"])
    assert st == 200
    st, r = api("GET", "/api/coll/schedules", tokens["admin"])
    assert not any(x["id"] == sid for x in r["items"])


def test_schedules_write_is_manager_only(api, tokens):
    st, _ = api("POST", "/api/coll/schedules", tokens["staff"], {"name": "Sneaky"})
    assert st == 403, "a staff user must not be able to create work schedules"


# --------------------------------------------------------------------------- payment owner-scope
def test_payment_edit_is_owner_scoped(api, tokens):
    st, r = api("POST", "/api/coll/payments", tokens["staff"], dict(PAY, reqNo="PR-OWN"))
    assert st == 200, r
    pid = r["item"]["id"]
    assert r["item"]["empId"] == "HML-STF", "create must stamp the owner from the session"

    # a DIFFERENT staff user must not be able to edit it
    st, r = api("PATCH", "/api/coll/payments/" + pid, tokens["other"],
                dict(PAY, reqNo="PR-OWN", payee="HIJACKED", amount=9999))
    assert st == 403, "a non-owner must not be able to edit a pending payment"

    # the owner CAN edit it while it is still pending
    st, r = api("PATCH", "/api/coll/payments/" + pid, tokens["staff"],
                dict(PAY, reqNo="PR-OWN", payee="ACME Renamed", amount=1200))
    assert st == 200, r
    assert r["item"]["payee"] == "ACME Renamed"


def test_payment_status_cannot_be_forged(api, tokens):
    st, r = api("POST", "/api/coll/payments", tokens["staff"], dict(PAY, reqNo="PR-FORGE"))
    assert st == 200, r
    pid = r["item"]["id"]

    # the owner tries to self-approve via the generic write path
    st, r = api("PATCH", "/api/coll/payments/" + pid, tokens["staff"],
                dict(PAY, reqNo="PR-FORGE", status="Approved"))
    assert st == 200
    # ...but approval only flows through /api/esign, so the status must be preserved
    assert r["item"]["status"] == "Submitted", "status must not be settable via the generic write path"
    assert not r["item"].get("signatures"), "signatures must not be injectable via PATCH"


# --------------------------------------------------------------------------- attendance privacy scope
def test_overtime_cannot_exceed_worked_span(api, tokens):
    """Requested OT can't exceed the time actually checked in (a 1h presence can't claim 5h OT)."""
    import app
    import db
    today = app.Handler._vn_day()
    db.clock_in("HML-OTH", today, "08:00")   # checked in at 08:00; checking out at 09:00 => 1h span
    st, r = api("POST", "/api/attendance/checkout", tokens["other"], {"time": "09:00", "otHours": 5})
    assert st == 400
    assert "overtime" in (r.get("error") or "").lower()


def test_forgotten_checkout_is_rejected(api, tokens):
    """A forgotten check-out from an earlier day would wrap to a ~19-23h shift. The checkout must
    reject that (HR corrects it) rather than record a fabricated overnight."""
    import app
    import db
    yday = app.Handler._vn_day(-1)
    db.clock_in("HML-STF", yday, "08:00")   # checked in yesterday, never checked out
    st, r = api("POST", "/api/attendance/checkout", tokens["staff"], {"time": "06:00"})
    assert st == 400, "an absurd overnight span must be rejected, not stored"
    assert "missed check-out" in (r.get("error") or "").lower() or "16 hours" in (r.get("error") or "")


def test_email_approve_link_does_not_finalize(base_url):
    """The one-click email approval links no longer auto-approve (that bypassed the Part 11
    e-signature and let a requester self-approve via their own leaked token). They deep-link into
    the portal instead — so hitting /approve must NOT change the leave's status."""
    import urllib.request
    import db
    rid, token = db.create_leave({"emp_id": "HML-STF", "type": "Annual Leave",
                                  "startDate": "2026-08-01", "endDate": "2026-08-03",
                                  "days": 3, "status": "pending"})
    with urllib.request.urlopen(base_url + "/approve?t=%s&action=approve" % token, timeout=10) as r:
        html = r.read().decode()
    assert "inbox" in html.lower(), "the link should deep-link into the portal inbox"
    assert db.get_leave(rid)["status"] == "pending", "the one-click link must NOT finalize the approval"


def test_attendance_gps_is_scoped(api, tokens):
    # an attendance row for the admin, carrying GPS coordinates
    db.clock_in("HML-ADM", "2026-07-15", "08:00", loc="HQ", lat=10.7769, lon=106.7009)

    # a staff user asking for the admin's rows is clamped back to self → must NOT see admin GPS
    st, r = api("GET", "/api/attendance?emp_id=HML-ADM", tokens["staff"])
    assert st == 200
    assert all(row.get("emp_id") != "HML-ADM" for row in r["attendance"]), \
        "staff must not be able to read another employee's GPS-bearing rows"

    # management/admin can see the row
    st, r = api("GET", "/api/attendance?emp_id=HML-ADM", tokens["admin"])
    assert st == 200
    assert any(row.get("emp_id") == "HML-ADM" for row in r["attendance"])
