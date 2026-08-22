# -*- coding: utf-8 -*-
"""The deletion loop, actually executed.

Every other test of this endpoint runs against the shared fixture org, which is entirely HML-* — so
`plan()` is empty, the endpoint returns at its early exit, and the assertions that "nothing was
deleted" are about a code path that never ran. An adversarial review confirmed it by instrumenting
the suite: across the whole repository, `db.delete_zone` was called zero times and the audit entry
was written zero times.

That is the defect shape this codebase keeps producing — a check that passes on something it never
looked at — and it was in the tests guarding its only bulk-delete endpoint.

This file puts REAL shipped-sample rows into the database, runs the removal at full strength, and
asserts positively on both sides: what went, and what survived.
"""
import pytest

import db
import demo_data
import seed_data

PHRASE = "REMOVE SAMPLE DATA"

# EMPLOYEES[1] is the first non-protected sample record (EMPLOYEES[0] carries an admin address).
SAMPLE = seed_data.EMPLOYEES[1]
SAMPLE_2 = seed_data.EMPLOYEES[2]
SEED_DATE = sorted(demo_data.seed_attendance_dates())[0]


@pytest.fixture
def sample_org(base_url):
    """Real shipped-sample rows, torn down whatever the test does to them."""
    made = []

    def emp(rec, **over):
        row = {k: rec.get(k) for k in ("id", "name", "email", "dept", "title")}
        row.update({"role": "staff", "level": "staff"})
        row.update(over)
        db.create_employee(row)
        made.append(row["id"])
        return row

    a = emp(SAMPLE)                                   # untouched sample -> removable
    b = emp(SAMPLE_2, name="Real Person")             # edited -> must survive
    admin = emp(seed_data.EMPLOYEES[0])               # protected address -> must survive
    real = emp({"id": "HML-REAL", "name": "Nguyen Van That",
                "email": "that@humiley.com", "dept": "Engineering", "title": "Engineer"})

    # the removable one carries only sample-shaped attendance
    db.clock_in(a["id"], SEED_DATE, "08:00", loc="HQ")
    # the real employee has a real punch that must survive untouched
    db.clock_in("HML-REAL", "2026-08-20", "07:30", loc="Site")

    z = db.create_zone(seed_data.ZONES[0])
    real_zone = db.create_zone({"name": "Mega Lifesciences Site", "lat": 10.91,
                                "lon": 106.71, "radius": 250})

    yield {"removable": a, "edited": b, "admin": admin, "real": real,
           "zone": z, "realZone": real_zone}

    for eid in made:
        if db.get_employee(eid):
            db.delete_employee(eid)
    for zz in (db.list_zones() or []):
        if zz.get("name") in (seed_data.ZONES[0]["name"], "Mega Lifesciences Site"):
            db.delete_zone(zz.get("id"))


def _remove(api, tok, **body):
    return api("POST", "/api/admin/demo-data/remove", tok, body)


# ── the loop runs, and it runs on the right rows ────────────────────────────────────────────────
def test_the_deletion_loop_actually_executes(api, tokens, sample_org):
    st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert st == 200, r
    assert r["removed"]["employees"] >= 1, \
        "if this is 0 the loop did not run and every assertion below is vacuous"
    assert db.get_employee(sample_org["removable"]["id"]) is None


def test_the_edited_sample_record_survives(api, tokens, sample_org):
    _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert db.get_employee(sample_org["edited"]["id"]) is not None


def test_the_protected_administrator_survives(api, tokens, sample_org):
    _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert db.get_employee(seed_data.EMPLOYEES[0]["id"]) is not None


def test_a_real_employee_and_their_punch_survive(api, tokens, sample_org):
    _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert db.get_employee("HML-REAL") is not None
    rows = db.list_attendance(emp_id="HML-REAL") or []
    assert len(rows) == 1 and rows[0]["date"] == "2026-08-20", \
        "a real punch was destroyed by a sweep of the sample"


# ── zones ───────────────────────────────────────────────────────────────────────────────────────
def test_the_sample_zone_goes_and_a_real_one_stays(api, tokens, sample_org):
    _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    names = [z.get("name") for z in (db.list_zones() or [])]
    assert seed_data.ZONES[0]["name"] not in names
    assert "Mega Lifesciences Site" in names


def test_a_sample_zone_with_a_changed_radius_is_left_alone(api, tokens, base_url):
    """The radius is the field somebody tunes on a live site, and it decides whether a punch reads
    as on-site. A changed radius is an edit, and an edit makes the row theirs."""
    z = seed_data.ZONES[0]
    zid = db.create_zone(dict(z, radius=int(z["radius"]) + 150))
    try:
        st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
        assert st == 200, r
        assert any(x.get("id") == zid for x in (db.list_zones() or [])), \
            "a geofence somebody had widened was deleted as sample data"
    finally:
        if any(x.get("id") == zid for x in (db.list_zones() or [])):
            db.delete_zone(zid)


# ── in use ──────────────────────────────────────────────────────────────────────────────────────
def test_a_sample_record_somebody_has_been_punching_on_is_left_alone(api, tokens, base_url):
    """seed sample_attendance() writes a deterministic set of dates. A punch on any other date
    cannot be a sample row — so the record is in use, and in use means it is somebody's."""
    rec = {k: SAMPLE.get(k) for k in ("id", "name", "email", "dept", "title")}
    rec.update({"role": "staff", "level": "staff"})
    db.create_employee(rec)
    db.clock_in(rec["id"], "2026-08-19", "08:00", loc="Site")
    try:
        st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
        assert st == 200, r
        assert db.get_employee(rec["id"]) is not None, \
            "a sample record with real punches on it was deleted, and the punches with it"
        assert len(db.list_attendance(emp_id=rec["id"]) or []) == 1
    finally:
        if db.get_employee(rec["id"]):
            db.delete_employee(rec["id"])


# ── the recovery record exists BEFORE the destruction ───────────────────────────────────────────
def test_every_removed_row_is_in_the_audit_snapshot(api, tokens, sample_org):
    st, r = _remove(api, tokens["admin"], confirm=PHRASE, backupConfirmed=True)
    assert st == 200 and r["removed"]["employees"] >= 1

    entry = next((a for a in db.list_collection("audit")
                  if a.get("action") == "Removed shipped sample data"
                  and a.get("id") == r.get("auditId")), None)
    assert entry is not None, "no audit entry — the removal is unrecoverable"
    snap = entry.get("snapshot") or {}
    ids = [e["employee"]["id"] for e in snap.get("employees", [])]
    assert sample_org["removable"]["id"] in ids

    rec = next(e for e in snap["employees"] if e["employee"]["id"] == sample_org["removable"]["id"])
    assert rec["employee"]["email"] == SAMPLE["email"], "the row must round-trip, not just its id"
    assert len(rec["attendance"]) == 1 and rec["attendance"][0]["date"] == SEED_DATE, \
        "the cascaded attendance must be IN the snapshot — after the delete it exists nowhere else"
    assert any(z.get("name") == seed_data.ZONES[0]["name"] for z in snap.get("zones", []))


def test_the_snapshot_is_written_before_anything_is_deleted(api, tokens, sample_org):
    """Order matters: every delete commits on its own connection, so a snapshot written afterwards
    is a recovery record that may never exist for data that is already gone."""
    import app
    import inspect
    src = inspect.getsource(app.Handler._demo_data_remove)
    assert src.index('put_collection_item("audit"') < src.index("db.delete_employee("), \
        "the recovery record must be committed before the destruction it describes"
