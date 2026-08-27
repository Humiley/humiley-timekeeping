# -*- coding: utf-8 -*-
"""A geofence zone's Active toggle and Department select had nowhere to be stored.

The GPS Locations register has had an "Active" column since it was written. Its entire handler was

    onclick="this.classList.toggle('on');this.classList.toggle('off')"

— two CSS classes and nothing else. An administrator could retire a decommissioned site, watch the
row go grey, and have that zone go on clearing check-ins; the toggle even sprang back to "on" on the
next navigation, because the class was hardcoded.

The Add Location modal had the same shape one level down: `saveLocation` read `dept` and `notes` out
of the form and then posted {name, lat, lon, radius}. Scoping a zone to Factory saved nothing, and
the register answered "All Depts" — which reads as the column's default, not as a refusal.

None of it could be stored: the zones table had four columns.

These tests are about the STORE. The gate that reads them is _zoneApplies, covered in
tests/zone_gate.js.
"""
import os
import sqlite3

import db


def _cols(name="zones"):
    conn = db.get_conn()
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % name)}
    finally:
        conn.close()


def _clean(zid):
    try:
        db.delete_zone(zid)
    except Exception:
        pass


# ── the columns exist at all ────────────────────────────────────────────────────────────────────
def test_the_table_can_hold_what_the_form_collects(base_url):
    have = _cols()
    for col in ("active", "dept", "notes"):
        assert col in have, "zones has no %r column, so that control cannot be honoured" % col


# ── and every existing zone keeps authorising exactly what it authorises now ────────────────────
def test_a_zone_created_without_saying_is_on_and_applies_to_everyone(base_url):
    """The migration adds columns to LIVE rows. A default that switched them off, or scoped them to
    a department nobody is in, would silently stop every check-in in the country."""
    zid = db.create_zone({"name": "ZZ Probe A", "lat": 10.77, "lon": 106.70, "radius": 200})
    try:
        z = [r for r in db.list_zones() if r["id"] == zid][0]
        assert z["active"] == 1, "a new zone must authorise, not refuse"
        assert (z.get("dept") or "All") == "All", "got %r — scoping must be opt-in" % z.get("dept")
    finally:
        _clean(zid)


def test_an_existing_row_predating_the_columns_reads_as_on(base_url):
    """Insert the way the OLD code did — four columns — then read it back through list_zones."""
    conn = db.get_conn()
    try:
        cur = conn.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                           ("ZZ Legacy", 10.5, 106.5, 300))
        conn.commit()
        zid = cur.lastrowid
    finally:
        conn.close()
    try:
        z = [r for r in db.list_zones() if r["id"] == zid][0]
        # DEFAULT 1 on the ALTER is what makes this true for rows that already existed in production.
        assert z["active"] == 1, "a zone from before the column existed must not become inactive"
    finally:
        _clean(zid)


# ── the toggle and the select actually persist ──────────────────────────────────────────────────
def test_switching_a_zone_off_persists(base_url):
    zid = db.create_zone({"name": "ZZ Probe B", "lat": 10.77, "lon": 106.70, "radius": 200})
    try:
        db.update_zone(zid, {"active": 0})
        z = [r for r in db.list_zones() if r["id"] == zid][0]
        assert z["active"] == 0, "the Active toggle wrote nothing"
        db.update_zone(zid, {"active": 1})
        assert [r for r in db.list_zones() if r["id"] == zid][0]["active"] == 1, "it cannot be switched back on"
    finally:
        _clean(zid)


def test_department_and_notes_survive_the_round_trip(base_url):
    zid = db.create_zone({"name": "ZZ Probe C", "lat": 10.77, "lon": 106.70, "radius": 200,
                          "dept": "Factory", "notes": "client site, contract to Dec"})
    try:
        z = [r for r in db.list_zones() if r["id"] == zid][0]
        assert z["dept"] == "Factory", "got %r — the Department select is decoration again" % z.get("dept")
        assert "contract to Dec" in (z["notes"] or ""), "Notes vanished on save"
        db.update_zone(zid, {"dept": "All"})
        assert [r for r in db.list_zones() if r["id"] == zid][0]["dept"] == "All"
    finally:
        _clean(zid)


# ── the update is a whitelist, not a passthrough ────────────────────────────────────────────────
def test_update_zone_ignores_a_key_it_does_not_own(base_url):
    """_zone_update hands the request body straight to db.update_zone, so the column list IS the
    input validation. A passthrough would let a PATCH write any column in the table."""
    zid = db.create_zone({"name": "ZZ Probe D", "lat": 10.77, "lon": 106.70, "radius": 200})
    try:
        db.update_zone(zid, {"id": 999999, "bogus": "x"})
        rows = [r for r in db.list_zones() if r["id"] == zid]
        assert rows, "the row's own id was overwritten by the request body"
        assert "bogus" not in rows[0]
    finally:
        _clean(zid)


def test_an_empty_patch_is_a_no_op_not_a_wipe(base_url):
    zid = db.create_zone({"name": "ZZ Probe E", "lat": 10.77, "lon": 106.70, "radius": 200,
                          "dept": "Engineering"})
    try:
        db.update_zone(zid, {})
        z = [r for r in db.list_zones() if r["id"] == zid][0]
        assert z["name"] == "ZZ Probe E" and z["dept"] == "Engineering" and z["radius"] == 200
    finally:
        _clean(zid)
