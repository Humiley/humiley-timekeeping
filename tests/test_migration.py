"""init_db runs live on the production SQLite DB on every deploy — including a DESTRUCTIVE step that
collapses duplicate open attendance rows before creating the one-open-row-per-day unique index. That
path was previously untested. This boots an OLD-schema DB in the pre-fix state and asserts the
migration is non-destructive and complete.
"""
import os
import sqlite3
import tempfile

import db


def test_migration_dedupes_open_attendance_adds_columns_and_stamps_version():
    tmp = os.path.join(tempfile.mkdtemp(prefix="tk-mig-"), "old.db")
    # OLD schema: attendance WITHOUT the ot_* columns and WITHOUT the unique open-row index, carrying
    # two OPEN rows for the same (emp, date) — the exact pre-fix production state.
    c = sqlite3.connect(tmp)
    c.execute("CREATE TABLE attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT, date TEXT,"
              " clock_in TEXT, clock_out TEXT)")
    c.executemany("INSERT INTO attendance (emp_id, date, clock_in, clock_out) VALUES (?,?,?,?)", [
        ("E1", "2026-01-01", "08:00", None),    # dup open #1 (older)
        ("E1", "2026-01-01", "08:05", None),    # dup open #2 (newer) — the one kept open
        ("E1", "2026-01-02", "08:00", None),    # different day — must stay untouched
        ("E2", "2026-01-01", "08:00", "17:00"), # already closed — must stay untouched
    ])
    c.commit()
    c.close()

    saved = db.DB_PATH
    db.DB_PATH = tmp
    try:
        db.init_db()   # destructive dedup + ADD COLUMN + unique index + version marker
        v = sqlite3.connect(tmp)
        rows = v.execute("SELECT emp_id, date, clock_out FROM attendance ORDER BY id").fetchall()
        assert len(rows) == 4                                              # NO rows deleted
        open_dup = [r for r in rows if r[0] == "E1" and r[1] == "2026-01-01" and r[2] is None]
        assert len(open_dup) == 1                                          # exactly one open row survives
        assert any(r[0] == "E1" and r[1] == "2026-01-02" and r[2] is None for r in rows)  # other day untouched
        assert any(r[0] == "E2" and r[2] == "17:00" for r in rows)         # closed row untouched
        assert v.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_att_open'").fetchone()
        cols = {r[1] for r in v.execute("PRAGMA table_info(attendance)").fetchall()}
        assert {"ot_status", "ot_hours", "ot_reason"} <= cols              # ADD COLUMN path ran
        assert v.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        v.close()
    finally:
        db.DB_PATH = saved   # restore so the shared session DB keeps working for the rest of the suite


def test_get_collection_item_matches_the_old_scan(base_url):
    # The indexed single-item lookup must be exactly equivalent to the list-and-scan it replaced.
    db.put_collection_item("gcitest", {"id": "gc-1", "x": 1})
    db.put_collection_item("gcitest", {"id": "gc-2", "x": 2})
    assert db.get_collection_item("gcitest", "gc-1") == {"id": "gc-1", "x": 1}
    assert db.get_collection_item("gcitest", "gc-2") == {"id": "gc-2", "x": 2}
    assert db.get_collection_item("gcitest", "nope") is None            # missing -> None (like next(..., None))
    assert db.get_collection_item("no-such-coll", "gc-1") is None
    # equivalence with the old scan for a present id
    scan = next((x for x in db.list_collection("gcitest") if x.get("id") == "gc-2"), None)
    assert db.get_collection_item("gcitest", "gc-2") == scan


def test_unique_index_blocks_a_second_open_row_after_migration():
    saved = db.DB_PATH
    tmp = os.path.join(tempfile.mkdtemp(prefix="tk-mig2-"), "fresh.db")
    db.DB_PATH = tmp
    try:
        db.init_db()
        conn = sqlite3.connect(tmp)
        conn.execute("INSERT INTO attendance (emp_id, date, clock_in) VALUES ('E9','2026-02-01','08:00')")
        conn.commit()
        try:
            conn.execute("INSERT INTO attendance (emp_id, date, clock_in) VALUES ('E9','2026-02-01','09:00')")
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        conn.close()
        assert raised, "the unique index must reject a second OPEN row for the same emp+date"
    finally:
        db.DB_PATH = saved
