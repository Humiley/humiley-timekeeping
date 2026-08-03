"""Tamper-evident audit hash chain.

Every audit row is a link in a keyed-HMAC chain (hash = HMAC(TK_AUDIT_PEPPER, prevHash | canonical(row))),
maintained in the single write path db.put_collection_item(coll="audit"). verify_audit_chain() recomputes
it and detects any edit, reorder, deletion (middle OR tail), or out-of-band insertion made directly
against the DB file — the kind of tampering the API-layer append-only guards alone cannot catch.
"""
import os
import json
import sqlite3
import tempfile

import pytest

import app
import db


@pytest.fixture
def iso_db():
    """A private, freshly-migrated DB (module global swapped) so tamper tests never corrupt the shared
    session DB other tests verify against. All db.* calls read db.DB_PATH at call time, so the swap
    redirects put_collection_item / verify_audit_chain here for the duration of the test."""
    saved = db.DB_PATH
    db.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="tk-audit-"), "a.db")
    db.init_db()
    try:
        yield db.DB_PATH
    finally:
        db.DB_PATH = saved


def _mk(n, **extra):
    return db.put_collection_item("audit", dict({"actor": "x", "action": "Event %d" % n,
                                                 "target": "t/%d" % n, "detail": "d%d" % n,
                                                 "ts": "2026-08-03T00:00:0%d" % (n % 10)}, **extra))


def _raw(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


# ── the happy path ──────────────────────────────────────────────────────────

def test_new_rows_are_chained_and_verify(iso_db):
    a, b, c = _mk(1), _mk(2), _mk(3)
    assert (a["seq"], b["seq"], c["seq"]) == (1, 2, 3)
    assert a["prevHash"] == "" and b["prevHash"] == a["hash"] and c["prevHash"] == b["hash"]
    v = db.verify_audit_chain()
    assert v == {"ok": True, "count": 3, "unchained": 0, "headHash": c["hash"], "brokenAtSeq": None, "keyed": True}


def test_empty_chain_verifies(iso_db):
    v = db.verify_audit_chain()
    assert v["ok"] is True and v["count"] == 0


# ── tamper detection ─────────────────────────────────────────────────────────

def test_editing_a_rows_content_is_detected(iso_db):
    _mk(1); mid = _mk(2); _mk(3)
    conn = _raw(iso_db)
    d = json.loads(conn.execute("SELECT data FROM collections WHERE coll='audit' AND id=?", (mid["id"],)).fetchone()["data"])
    d["detail"] = "TAMPERED — payment amount changed after the fact"
    conn.execute("UPDATE collections SET data=? WHERE coll='audit' AND id=?", (json.dumps(d), mid["id"]))
    conn.commit(); conn.close()
    v = db.verify_audit_chain()
    assert v["ok"] is False and v["brokenAtSeq"] == 2 and "altered" in v["reason"]


def test_deleting_a_middle_row_is_detected(iso_db):
    _mk(1); mid = _mk(2); _mk(3)
    conn = _raw(iso_db)
    conn.execute("DELETE FROM collections WHERE coll='audit' AND id=?", (mid["id"],))
    conn.commit(); conn.close()
    v = db.verify_audit_chain()
    assert v["ok"] is False and "gap" in v["reason"].lower()


def test_deleting_the_newest_row_is_detected_via_head_checkpoint(iso_db):
    _mk(1); _mk(2); tail = _mk(3)
    conn = _raw(iso_db)
    conn.execute("DELETE FROM collections WHERE coll='audit' AND id=?", (tail["id"],))
    conn.commit(); conn.close()
    v = db.verify_audit_chain()
    # walking the surviving prefix (1,2) is internally consistent; only the persisted head reveals the loss
    assert v["ok"] is False and "head mismatch" in v["reason"]


def test_out_of_band_insert_is_detected(iso_db):
    _mk(1); _mk(2)
    conn = _raw(iso_db)
    conn.execute("INSERT INTO collections (coll,id,data) VALUES ('audit','aud-forged',?)",
                 (json.dumps({"id": "aud-forged", "actor": "attacker", "action": "Granted admin"}),))
    conn.commit(); conn.close()
    v = db.verify_audit_chain()
    assert v["ok"] is False and "not part of the hash chain" in v["reason"]


# ── append-only at the sink ──────────────────────────────────────────────────

def test_reput_of_an_existing_audit_id_never_rewrites_the_link(iso_db):
    a = _mk(1)
    again = db.put_collection_item("audit", dict(a, detail="rewrite attempt", action="Forged"))
    assert again["detail"] == a["detail"] and again["hash"] == a["hash"]        # original returned unchanged
    stored = db.get_collection_item("audit", a["id"])
    assert stored["detail"] == a["detail"] and stored["action"] == a["action"]  # DB untouched
    assert db.verify_audit_chain()["ok"] is True


# ── migration: chain a DB that predates the feature ──────────────────────────

def test_backfill_chains_a_legacy_audit_log():
    saved = db.DB_PATH
    path = os.path.join(tempfile.mkdtemp(prefix="tk-audit-legacy-"), "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE collections (coll TEXT, id TEXT, data TEXT, PRIMARY KEY (coll,id))")
    for i in (1, 2, 3):
        conn.execute("INSERT INTO collections (coll,id,data) VALUES ('audit',?,?)",
                     ("aud-old%d" % i, json.dumps({"id": "aud-old%d" % i, "actor": "legacy", "action": "Old %d" % i})))
    conn.commit(); conn.close()
    db.DB_PATH = path
    try:
        db.init_db()                       # runs the one-time backfill
        rows = sorted(db.list_collection("audit"), key=lambda r: r["seq"])
        assert [r["seq"] for r in rows] == [1, 2, 3]
        assert all(r.get("hash") for r in rows)
        v = db.verify_audit_chain()
        assert v["ok"] is True and v["count"] == 3
        # backfill is one-time: a second init must not re-chain or change the head
        head1 = rows[-1]["hash"]
        db.init_db()
        assert db.verify_audit_chain()["headHash"] == head1
    finally:
        db.DB_PATH = saved


# ── the admin endpoint ───────────────────────────────────────────────────────

def test_verify_endpoint_is_admin_only(api, tokens):
    db.put_collection_item("audit", {"actor": "x", "action": "Endpoint probe", "target": "t/1", "detail": ""})
    st, body = api("GET", "/api/admin/audit/verify", tokens["admin"])
    assert st == 200 and body.get("ok") is True and body.get("count", 0) >= 1
    st2, _ = api("GET", "/api/admin/audit/verify", tokens["management"])   # Finance/Approver, not admin
    assert st2 == 403
    st3, _ = api("GET", "/api/admin/audit/verify", tokens["staff"])
    assert st3 == 403
