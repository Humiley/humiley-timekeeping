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


# --------------------------------------------------------------------------- appsDenied on writes (round-3 hunt)
def test_appsdenied_blocks_hr_writes(api, tokens):
    """A user whose HR app is disabled by an admin must be blocked from CREATING HR records via the
    API, not just from reading them — the appsDenied gate was read-only before."""
    # appsDenied is stored as a comma-separated string (the admin UI joins the list), matching _apps_denied
    db.update_employee("HML-MGR", {"appsDenied": "hr"})
    try:
        st, r = api("POST", "/api/coll/candidates", tokens["mgr"],
                    {"id": "CAND-DENY", "name": "X Candidate", "stage": "Offer"})
        assert st == 403, "a disabled HR app must block writes too, not only reads"
    finally:
        db.update_employee("HML-MGR", {"appsDenied": ""})


# --------------------------------------------------------------------------- leave-days balance integrity
def test_leave_days_bounded_to_range(api, tokens):
    """`days` drives the annual/sick balance decrement on approval; a direct API call must not send 0
    (a full week of leave that consumes no balance) or a value larger than the date span."""
    base = {"type": "Annual Leave", "startDate": "2026-08-03", "endDate": "2026-08-07"}  # span = 5
    st, r = api("POST", "/api/leave", tokens["staff"], dict(base, days=0))
    assert st == 400, "days=0 over a real date range must be rejected"
    st, r = api("POST", "/api/leave", tokens["staff"], dict(base, days=99))
    assert st == 400, "days greater than the selected span must be rejected"
    st, r = api("POST", "/api/leave", tokens["staff"], dict(base, days=5))
    assert st == 200, r


# --------------------------------------------------------------------------- claim per-line re-approval
def test_claim_line_approval_resets_on_amount_change(api, tokens):
    """An already-approved claim line must LOSE its approval if its amount is edited — otherwise an
    owner could inflate an approved line while it keeps the 'Approved' stamp, with no re-signature."""
    st, r = api("POST", "/api/coll/claims", tokens["staff"],
                {"id": "CLM-REAP", "name": "Staff One",
                 "items": [{"id": "L1", "amount": 100000}, {"id": "L2", "amount": 50000}]})
    assert st == 200, r
    # simulate L1 already approved by a director + the claim partially approved
    row = next(x for x in db.list_collection("claims") if x.get("id") == "CLM-REAP")
    row["items"][0]["status"] = "Approved"; row["items"][0]["approvedBy"] = "Director User"
    row["status"] = "Partially approved"
    db.put_collection_item("claims", row)
    # owner edits L1's amount 50x
    st, r = api("PATCH", "/api/coll/claims/CLM-REAP", tokens["staff"],
                {"id": "CLM-REAP", "name": "Staff One",
                 "items": [{"id": "L1", "amount": 5000000}, {"id": "L2", "amount": 50000}]})
    assert st == 200, r
    l1 = next(it for it in r["item"]["items"] if it["id"] == "L1")
    assert l1.get("status") == "Submitted", "an edited approved line must drop back to Submitted"
    assert not l1.get("approvedBy"), "the stale approver stamp must be cleared on an amount change"
    # the untouched line keeps its (unchanged) status
    l2 = next(it for it in r["item"]["items"] if it["id"] == "L2")
    assert (l2.get("status") or "Submitted") == "Submitted"


# --------------------------------------------------------------------------- punch clock integrity (D)
def _freeze_company_clock(monkeypatch):
    """Freeze the company (UTC+7) clock at 2026-07-18 09:05 so future/past punch times are
    deterministic regardless of when the suite runs. The server thread shares app.Handler, so
    patching the class staticmethods reaches the live handler; monkeypatch reverts afterwards."""
    from datetime import datetime as _dt, timedelta as _td
    fixed = _dt(2026, 7, 18, 9, 5)
    monkeypatch.setattr(app.Handler, "_vn_now", staticmethod(lambda: fixed))
    monkeypatch.setattr(app.Handler, "_vn_day", staticmethod(lambda offset_days=0: (fixed + _td(days=offset_days)).strftime("%Y-%m-%d")))


def test_checkin_time_cannot_be_in_the_future(api, tokens, monkeypatch):
    """A punch may be backdated (a late/forgotten punch) but never post-dated past the company clock —
    a future time fabricates hours (a 21:00 check-out entered at 09:05 = a phantom ~15h shift)."""
    _freeze_company_clock(monkeypatch)          # company clock = 09:05
    st, r = api("POST", "/api/attendance/checkin", tokens["management"], {"time": "21:00"})
    assert st == 400, "a future check-in time must be rejected"
    assert "future" in (r.get("error") or "").lower()
    # a backdated (earlier same-day) punch is still allowed — the arrival was real, just logged late
    st, r = api("POST", "/api/attendance/checkin", tokens["management"], {"time": "06:00"})
    assert st == 200, r


def test_checkout_time_cannot_be_in_the_future(api, tokens, monkeypatch):
    _freeze_company_clock(monkeypatch)          # company clock = 09:05
    st, r = api("POST", "/api/attendance/checkout", tokens["editor"], {"time": "21:00"})
    assert st == 400, "a future check-out time must be rejected"
    assert "future" in (r.get("error") or "").lower()
