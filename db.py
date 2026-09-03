"""
Database layer for the Humiley Timekeeping & Leave Management platform.

Standalone SQLite storage (Python stdlib only) — replaces the original
SharePoint/Graph backend. Holds employees, attendance, leave requests, GPS
zones, and app settings.
"""

import os
import re
import hmac
import json
import hashlib
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta

import seed_data

DB_PATH = os.environ.get("TK_DB_PATH", os.path.join(os.path.dirname(__file__), "timekeeping.db"))
SCHEMA_VERSION = 2   # bumped when init_db's migrations change; written to PRAGMA user_version

# ── Tamper-evident audit hash chain ──────────────────────────────────────────
# Every audit row is a link in a keyed-HMAC hash chain: hash = HMAC(AUDIT_KEY, prevHash | canonical(row)).
# A dedicated pepper (NOT the PIN pepper or SSO secret — key separation) keys it, so an attacker with raw
# DB-write access cannot forge a valid successor link without the secret. The chain is maintained in the
# SINGLE write path (put_collection_item where coll=="audit") under a lock, so every audit write in the
# app is covered with no per-call-site changes; verify_audit_chain() recomputes it end to end.
AUDIT_KEY   = os.environ.get("TK_AUDIT_PEPPER", "").encode("utf-8")
_AUDIT_LOCK = threading.Lock()   # serialize read-head -> insert -> advance-head so concurrent writers can't fork the chain


# ── One connection per thread, not one per query ────────────────────────────────────────────────
#
# Every db.* read used to open a SQLite connection, run one statement and close it again. The
# statement is the cheap part: on an open connection a read is ~0.01-0.05 ms, and opening the
# connection to do it costs more than the read itself.
#
# Measured through the real server on a throwaway database, 40 units / 1,360 steps, best of 12,
# reproduced across runs:
#
#     GET /api/ahu/board    9 connections -> 1     17.5 ms -> 13.9 ms   (-21%)
#     GET /api/ahu/kpi     12 connections -> 1     13.2 ms ->  9.8 ms   (-26%)
#     GET /api/coll/...     2 connections -> 1      1.5 ms ->  1.1 ms
#
# A fifth to a quarter off a read endpoint, and it scales with how many collections the endpoint
# touches, which is the shape of most screens here.
#
# Beware measuring this: an isolated open/query/close loop reports a far bigger number, because a
# close that happens to be the LAST connection makes SQLite checkpoint and delete the WAL — work a
# real server with other threads in flight would not usually be doing. Reuse removes that churn too,
# but the honest figure to quote is the one above, taken through actual requests.
#
# `close()` therefore does not close: it hands the connection back, having first restored everything
# a caller could have changed. The scope is a THREAD, and how many requests that covers depends on
# the client: the server sets no protocol_version, so BaseHTTPRequestHandler speaks HTTP/1.0 and
# most clients get one request per connection — but it still honours `Connection: keep-alive`, and
# then one thread serves several requests in turn. That is the reason app.py releases per REQUEST
# rather than leaving it to the thread ending: on a kept-alive socket, the thread may not end for a
# while, and request N+1 must not inherit anything from request N.
#
# THE TWO THINGS THIS HAS TO GET RIGHT, both of which were silently free when every caller got its
# own connection:
#
#   Nesting. Two paths hold BEGIN IMMEDIATE open and then call something that does its own
#   get_conn/close INSIDE it: `next_doc_no` calls a caller-supplied `floor_fn` that scans a whole
#   collection, and `gl_post` calls `gl_is_closed`, which reads the period register. If that inner
#   close released, it would roll back the document-number allocation and, worse, the ledger post.
#   Hence the depth count: only the outermost release actually releases.
#
#   State left behind. `_coll_write` sets `isolation_level = None` and never puts it back, which was
#   harmless when the connection was thrown away and is poison when it is reused — every later write
#   on that thread would silently lose its implicit transaction. Release restores it, and rolls back
#   anything uncommitted, so a reused connection is indistinguishable from a fresh one.
_local = threading.local()


class _ReusableConn(sqlite3.Connection):
    """A connection whose close() returns it to this thread instead of closing it.

    Subclassing rather than wrapping so that execute/commit/rollback/in_transaction and everything
    else stay the real C implementations — a proxy would have to forward each one, and the one it
    forgot would be the one that mattered.
    """

    def close(self):
        _release(self)

    def _close_for_real(self):
        sqlite3.Connection.close(self)


def get_conn():
    # WAL lets readers and a writer work concurrently (the stdlib server is multi-threaded), and
    # busy_timeout makes a contended write WAIT briefly instead of raising "database is locked".
    # synchronous=NORMAL is durable under WAL and much faster. These are the biggest cheap wins for
    # SQLite under real concurrent use.
    st = _local.__dict__
    conn = st.get("conn")
    # DB_PATH is not a constant: several tests point it at a scratch file and then put it back, and
    # a cached connection to the previous file would quietly answer from the wrong database.
    if conn is not None and st.get("path") != DB_PATH:
        _drop(conn)
        conn = None
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, factory=_ReusableConn)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        # journal_mode is DELIBERATELY not here. It is persisted in the database header, so it
        # survives every connection — but re-asserting it takes a lock. _enable_wal() sets it once,
        # at startup.
        st["conn"], st["path"], st["depth"] = conn, DB_PATH, 0
    conn.row_factory = sqlite3.Row
    st["depth"] = st.get("depth", 0) + 1
    return conn


def _drop(conn):
    """Forget this connection and really close it."""
    st = _local.__dict__
    if st.get("conn") is conn:
        st["conn"], st["path"], st["depth"] = None, None, 0
    try:
        conn._close_for_real()
    except Exception:
        pass


def _release(conn):
    """A caller is done with the connection. Only the outermost caller actually releases it."""
    st = _local.__dict__
    if st.get("conn") is not conn:
        # Not this thread's connection — it belongs to a thread that has since ended, and is being
        # finalised here. Close it for real; there is nothing to hand back to.
        try:
            conn._close_for_real()
        except Exception:
            pass
        return
    depth = st.get("depth", 0) - 1
    st["depth"] = max(0, depth)
    if depth > 0:
        return                     # an inner read finished; the transaction above it still owns this
    try:
        if conn.in_transaction:
            conn.rollback()        # exactly what closing a connection used to do with uncommitted work
        conn.isolation_level = ""  # undo _coll_write's isolation_level = None
    except Exception:
        _drop(conn)                # cannot be restored to a known state, so do not hand it back


def end_thread_conn():
    """Force this thread's connection back to depth 0, whatever the call sites did.

    The depth count is only as good as the balance between get_conn() and close(), and one function
    that takes a connection down an exception path without giving it back would pin the depth above
    zero for the rest of the thread's life — no rollback, no isolation_level restore, for every
    request that thread went on to serve. That is too sharp an edge to leave resting on the
    discipline of 40-odd call sites.

    app.py calls this in the `finally` of every request, so a leak can cost at most the request it
    happened in. Safe to call when nothing is open.
    """
    st = _local.__dict__
    conn = st.get("conn")
    if conn is None:
        return
    st["depth"] = 1                # so the release below is the outermost one
    _release(conn)


def _enable_wal():
    """Set the journal mode once, at startup, instead of on every connection."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    _enable_wal()
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            ini         TEXT,
            clr         TEXT,
            dept        TEXT,
            title       TEXT,
            email       TEXT UNIQUE,
            phone       TEXT,
            startDate   TEXT,
            status      TEXT DEFAULT 'Active',
            zone        TEXT,
            gender      TEXT,
            dob         TEXT,
            taxId       TEXT,
            bank        TEXT,
            emergency   TEXT,
            address     TEXT,
            managerEmail TEXT,
            jobLevel     TEXT,
            endDate      TEXT,
            serviceDuration TEXT,
            personalId   TEXT,
            familyStatus TEXT,
            education    TEXT,
            employmentType TEXT,
            englishCert  TEXT,
            note         TEXT,
            photo        TEXT,
            role        TEXT DEFAULT 'staff',
            annualUsed  INTEGER DEFAULT 0,
            annualTotal INTEGER DEFAULT 12,
            sickUsed    INTEGER DEFAULT 0,
            sickTotal   INTEGER DEFAULT 30,
            compoff     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id    TEXT NOT NULL,
            name      TEXT,
            dept      TEXT,
            date      TEXT NOT NULL,
            clock_in  TEXT,
            clock_out TEXT,
            status    TEXT,
            hrs       TEXT,
            loc       TEXT,
            lat       REAL,
            lon       REAL,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS leave (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id     TEXT NOT NULL,
            type       TEXT,
            startDate  TEXT,
            endDate    TEXT,
            days       INTEGER,
            status     TEXT DEFAULT 'pending',
            reason     TEXT,
            note       TEXT,
            created_at TEXT,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS zones (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT,
            lat    REAL,
            lon    REAL,
            radius INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS collections (
            coll TEXT,
            id   TEXT,
            data TEXT,
            PRIMARY KEY (coll, id)
        );

        -- Tamper-evident audit hash chain: singleton checkpoint holding the current chain length and
        -- head hash. Persisting the head separately makes tail-truncation (deleting the newest audit
        -- rows) detectable — without it, chopping the end of the chain would leave a valid-looking prefix.
        CREATE TABLE IF NOT EXISTS audit_chain (
            id        INTEGER PRIMARY KEY,           -- always 1 (singleton)
            seq       INTEGER NOT NULL DEFAULT 0,    -- number of chained audit rows
            head_hash TEXT    NOT NULL DEFAULT '',   -- hash of the most recent link
            head_mac  TEXT,                          -- HMAC(key, seq|head_hash) — authenticates the checkpoint
            key_fp    TEXT                           -- fingerprint of the sealing key (key-change ≠ tamper)
        );

        -- Document number sequences. One row per (series, year); `n` is the last number ISSUED.
        -- The counter lives in the database rather than being derived from the documents because a
        -- number must be unique across everybody, and a browser can only see its own rows: payment
        -- requests numbered themselves client-side from `max(mine) + 1`, so on a SELF_OWNED
        -- collection every user's first request was PR-YYYY-001.
        CREATE TABLE IF NOT EXISTS doc_counters (
            series TEXT    NOT NULL,
            year   INTEGER NOT NULL,
            n      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (series, year)
        );

        -- 21 CFR Part 11 signature PIN (second signing component). Salted PBKDF2 hash only;
        -- kept in its own table so it can never leak through a `SELECT * FROM employees` read path.
        CREATE TABLE IF NOT EXISTS esign_pin (
            emp_id       TEXT PRIMARY KEY,
            algo         TEXT    NOT NULL DEFAULT 'pbkdf2_sha256',
            iterations   INTEGER NOT NULL,
            salt         TEXT    NOT NULL,               -- hex, 16 random bytes, unique per set
            hash         TEXT    NOT NULL,               -- hex PBKDF2-HMAC-SHA256 derived key
            prev_hash    TEXT,                           -- hex of previous hash, blocks immediate reuse
            status       TEXT    NOT NULL DEFAULT 'active',  -- 'active' | 'revoked'
            created_ts   TEXT,
            updated_ts   TEXT,
            set_ts       TEXT,                           -- last time the PIN value was set (expiry clock)
            fail_count   INTEGER NOT NULL DEFAULT 0,
            last_fail_ts TEXT,
            locked_until TEXT,                           -- ISO-8601 UTC; NULL = not locked
            must_change  INTEGER NOT NULL DEFAULT 0,     -- 1 after admin reset -> owner must re-enroll
            enrolled_via TEXT,
            enrolled_oid TEXT,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        );

        -- Effective-dated employee history. The portal knew what was true; it did not know what WAS
        -- true, because every employee edit is an in-place UPDATE that keeps no prior value. That made
        -- "what were we paying him in March", "when did Engineering go from 6 to 9" and the labour
        -- management book Decree 145/2020 Art. 3 requires all unanswerable — and it silently defeated
        -- the payroll dual-control, since a signed run's payslips were regenerated from mutable inputs.
        --
        -- Append-only. One row per FIELD per change, not per record, so a query can ask exactly one
        -- question ("salary as at 2026-03-31") without parsing a blob. `effective` is the business date
        -- the change takes force (a rise agreed today may start next month); `ts` is when it was
        -- recorded. That pair is deliberately NOT bitemporal — nobody here will ask what we BELIEVED
        -- the January org looked like as of March, and the third dimension doubles the cost of every
        -- query for that one question.
        CREATE TABLE IF NOT EXISTS emp_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id     TEXT NOT NULL,
            effective  TEXT NOT NULL,        -- YYYY-MM-DD, the date the change takes force
            field      TEXT NOT NULL,        -- salary | grade | title | dept | managerEmail | status
            old_value  TEXT,
            new_value  TEXT,
            reason     TEXT,                 -- promotion, annual review, transfer, correction…
            actor      TEXT,
            actor_id   TEXT,
            source     TEXT,                 -- 'edit' | 'backfill' — a backfilled row is inferred
            ts         TEXT NOT NULL         -- when it was RECORDED (never edited)
            -- Deliberately NO foreign key to employees. This is the effective-dated employment
            -- record — the thing a settlement dispute and Decree 145/2020 Art. 3 are answered from.
            -- With ON DELETE CASCADE one DELETE erased it, and because employee_references did not
            -- count it, the deletion was allowed and then logged "no history on record". A legal
            -- record has to outlive the row it describes; an orphan is recoverable, an erasure is not.
        );
        CREATE INDEX IF NOT EXISTS idx_emp_events_emp_eff ON emp_events (emp_id, effective);
        CREATE INDEX IF NOT EXISTS idx_emp_events_field_eff ON emp_events (field, effective);

        -- Web Push subscriptions (one row per browser/device per user) for OS notifications.
        CREATE TABLE IF NOT EXISTS push_subs (
            endpoint TEXT PRIMARY KEY,
            email    TEXT NOT NULL,
            sub      TEXT NOT NULL,   -- full PushSubscription JSON (endpoint + p256dh/auth keys)
            created  TEXT
        );

        -- ── The general ledger ────────────────────────────────────────────────────────────
        --
        -- Real tables, not the `collections` blob store, and the difference is the point. A ledger
        -- is asked "every entry in this account, this period" thousands of times by one trial
        -- balance; a JSON blob per row answers that by loading the whole ledger into Python and
        -- filtering it. It also needs a UNIQUE constraint the database itself enforces, because
        -- the one thing that must never happen — the same document posting twice — cannot be
        -- prevented by a check in application code that two requests can both pass.
        --
        -- A BATCH is one source document. Its entries live or die with it: gl_entries has a
        -- foreign key ON DELETE CASCADE not because entries are ever deleted (they are not — see
        -- gl.py rule 5) but so that a half-written batch cannot survive a crash mid-insert.
        CREATE TABLE IF NOT EXISTS gl_batches (
            id         TEXT PRIMARY KEY,
            source     TEXT NOT NULL,          -- payrun / invoice / receipt / ... (gl.SOURCES)
            source_id  TEXT NOT NULL,          -- the document's own id, so it can be traced back
            kind       TEXT NOT NULL,          -- post | reverse
            period     TEXT NOT NULL,          -- YYYY-MM, from the DOCUMENT's date
            doc_date   TEXT NOT NULL,
            memo       TEXT,
            posted_at  TEXT NOT NULL,
            posted_by  TEXT,
            posted_by_id TEXT,
            reverses   TEXT,                   -- the batch id this one contras, if any
            debit      REAL NOT NULL,
            credit     REAL NOT NULL,
            -- The idempotency guard, enforced by the database rather than hoped for. Posting the
            -- same pay run twice would double the month's salary, insurance and PIT — and BOTH
            -- sides would double, so the ledger would still balance and no report would say so.
            UNIQUE (source, source_id, kind)
        );

        CREATE TABLE IF NOT EXISTS gl_entries (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            batch     TEXT NOT NULL REFERENCES gl_batches(id) ON DELETE CASCADE,
            seq       INTEGER NOT NULL,
            period    TEXT NOT NULL,
            account   TEXT NOT NULL,
            name      TEXT,
            debit     REAL NOT NULL DEFAULT 0,
            credit    REAL NOT NULL DEFAULT 0,
            memo      TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_gl_period      ON gl_entries (period);
        CREATE INDEX IF NOT EXISTS idx_gl_acct_period ON gl_entries (account, period);
        CREATE INDEX IF NOT EXISTS idx_gl_batch       ON gl_entries (batch);
        CREATE INDEX IF NOT EXISTS idx_gl_b_period    ON gl_batches (period);
        CREATE INDEX IF NOT EXISTS idx_gl_b_source    ON gl_batches (source, source_id);

        CREATE INDEX IF NOT EXISTS idx_att_emp  ON attendance (emp_id);
        CREATE INDEX IF NOT EXISTS idx_att_date ON attendance (date);
        CREATE INDEX IF NOT EXISTS idx_leave_emp ON leave (emp_id);
        CREATE INDEX IF NOT EXISTS idx_push_email ON push_subs (email);
        """
    )
    # The unread badge, off an index instead of a scan of every message ever posted: 1.08 ms against
    # 29.8 ms at 25,000 messages, and it grows with the number of projects rather than the history.
    # PARTIAL (WHERE coll='pm_chat') so it stays small on a table that holds every collection, and on
    # EXPRESSIONS so no data has to be copied anywhere — SQLite maintains it through inserts, updates
    # and deletes, which is the whole reason this is an index and not a table somebody has to keep in
    # step. Wrapped because a SQLite without JSON1 cannot create it; the callers fall back to the scan.
    try:
        conn.executescript(
            "CREATE INDEX IF NOT EXISTS idx_pm_chat_unread ON collections("
            + _PM_CHAT_PID + ", " + _PM_CHAT_TS + ", " + _PM_CHAT_AUTHOR + ", "
            + _PM_CHAT_MLEN + ") WHERE coll = 'pm_chat';")
    except Exception:
        pass
    # migration: drop the ON DELETE CASCADE from emp_events on databases created with it.
    # SQLite cannot ALTER a foreign key, so the table is rebuilt. Guarded on foreign_key_list, so this
    # runs at most once and is a no-op afterwards; the table is small (one row per recorded change).
    try:
        if conn.execute("PRAGMA foreign_key_list(emp_events)").fetchall():
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executescript("""
                BEGIN;
                CREATE TABLE emp_events_new (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    emp_id     TEXT NOT NULL,
                    effective  TEXT NOT NULL,
                    field      TEXT NOT NULL,
                    old_value  TEXT,
                    new_value  TEXT,
                    reason     TEXT,
                    actor      TEXT,
                    actor_id   TEXT,
                    source     TEXT,
                    ts         TEXT NOT NULL
                );
                INSERT INTO emp_events_new SELECT id, emp_id, effective, field, old_value, new_value,
                       reason, actor, actor_id, source, ts FROM emp_events;
                DROP TABLE emp_events;
                ALTER TABLE emp_events_new RENAME TO emp_events;
                CREATE INDEX IF NOT EXISTS idx_emp_events_emp_eff ON emp_events (emp_id, effective);
                CREATE INDEX IF NOT EXISTS idx_emp_events_field_eff ON emp_events (field, effective);
                COMMIT;
            """)
            conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        pass    # a DB where the rebuild cannot run keeps the old table; the reference guard still holds

    # migration: add newer columns to older databases
    for col in ("managerEmail TEXT", "jobLevel TEXT", "endDate TEXT", "serviceDuration TEXT",
                "personalId TEXT", "familyStatus TEXT", "education TEXT", "employmentType TEXT",
                "englishCert TEXT", "note TEXT", "photo TEXT", "salary REAL",
                "level TEXT", "dependents INTEGER", "grade TEXT", "appsDenied TEXT", "appsAllowed TEXT",
                "schedule TEXT", "procRole TEXT",
                # Collected on the employee form, accepted by the Excel importer and shown on the
                # profile — and, until now, in neither EMP_FIELDS nor this list, so every save threw
                # it away and reported success. Uniform sizes matter on a site: PPE is issued by size.
                "shirtSize TEXT",
                # Annual-leave entitlement drivers (Art. 113(1)): the working-condition class and
                # whether the employee is a person with disabilities. Both raise the statutory base.
                "workConditions TEXT", "disabled INTEGER", "contractExempt TEXT",
                "oshGroup TEXT",
                # Decree 293/2025 wage region (I–IV) of the WORKPLACE, and whether the employee
                # holds a certified vocational qualification. Both drive the minimum-wage check.
                "wageRegion TEXT", "trained INTEGER",
                "bankName TEXT", "bankAcc TEXT", "bankHolder TEXT", "bankBranch TEXT"):
        try:
            conn.execute("ALTER TABLE employees ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass  # column already exists
    # A geofence zone has had an "Active" toggle and a "Department" select on screen since the
    # register was written, and neither had anywhere to be stored: the toggle's whole handler was
    # two classList calls, and saveLocation read `dept` and `notes` out of the form and then posted
    # {name, lat, lon, radius}. An administrator could retire a decommissioned site, watch it grey
    # out, and have it go on authorising check-ins.
    #   active: 1 by default, so every existing zone keeps authorising exactly what it did.
    #   dept:   'All' by default, same reason — scoping is opt-in, never retroactive.
    for col in ("active INTEGER DEFAULT 1", "dept TEXT", "notes TEXT"):
        try:
            conn.execute("ALTER TABLE zones ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE leave ADD COLUMN token TEXT")  # approval-link token
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE leave ADD COLUMN signatures TEXT")  # 21 CFR Part 11 e-signatures (JSON)
    except sqlite3.OperationalError:
        pass
    # Overtime request/approval on an attendance record: OT only counts once a manager approves it.
    # Attendance amendment trail. Attendance now feeds payroll (approved overtime reaches the
    # payslip), so a retroactive edit moves money — and until these existed there was no edit path at
    # all, while check-out told employees to "ask HR to correct your attendance record".
    # Which job a day of work was on. The portal has run a GPS attendance system and a PMBOK project
    # module side by side without ever introducing them, so labour cost per job — the number a
    # contractor most needs — had no answer. Nullable on purpose: a blank means "nobody recorded it",
    # which the cost report reports as unattributed rather than guessing.
    # away_reason: why somebody clocked in while the app could see they were NOT at the site they
    # picked. Blocking that punch outright is what makes people work unrecorded, and unrecorded
    # hours are the employer's exposure, not the worker's — so the punch is taken and the reason
    # is taken with it, in its own column rather than smuggled into the 120-char loc label.
    for col in ("ot_status TEXT", "ot_hours REAL", "ot_reason TEXT",
                "amended_by TEXT", "amended_at TEXT", "amend_reason TEXT", "amend_count INTEGER",
                "project TEXT", "away_reason TEXT"):
        try:
            conn.execute("ALTER TABLE attendance ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    # One-open-record-per-(emp,date) uniqueness. On an EXISTING production DB there may already be
    # duplicate open rows (pre-fix double-taps / orphaned overnight rows), which would make a bare
    # CREATE UNIQUE INDEX abort startup — so we first collapse duplicates (keep the latest open row
    # per emp+date, close the older ones), THEN create the index, and guard the whole thing.
    try:
        dups = conn.execute(
            "SELECT emp_id, date FROM attendance WHERE clock_out IS NULL "
            "GROUP BY emp_id, date HAVING COUNT(*) > 1").fetchall()
        for emp_id, date in dups:
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM attendance WHERE emp_id=? AND date=? AND clock_out IS NULL "
                "ORDER BY id DESC", (emp_id, date)).fetchall()]
            for old_id in ids[1:]:   # keep the newest open row; close the rest to '—' so no data is lost
                conn.execute("UPDATE attendance SET clock_out=COALESCE(clock_out,'—') WHERE id=?", (old_id,))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_att_open ON attendance (emp_id, date) WHERE clock_out IS NULL")
    except sqlite3.OperationalError:
        pass   # a residual duplicate must never abort startup — the app-level guard still applies
    # audit_chain gained head_mac + key_fp after the first release — add them to older chain tables.
    for col in ("head_mac TEXT", "key_fp TEXT"):
        try:
            conn.execute("ALTER TABLE audit_chain ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass  # column already exists
    # Audit hash chain: establish (or continue) the tamper-evident keyed-HMAC chain over the audit log.
    # On a DB that predates the chain, backfill links over the existing rows in insertion (rowid) order
    # so the whole history becomes verifiable from one trusted checkpoint. Runs ONCE — gated on the
    # audit_chain singleton being absent — and is a no-op on every later init (new rows are chained live
    # in put_collection_item). If TK_AUDIT_PEPPER is unset the chain still forms (empty key); it just
    # isn't cryptographically unforgeable until a real pepper is set — hence the startup warning in app.py.
    try:
        head = conn.execute("SELECT seq, head_hash, head_mac, key_fp FROM audit_chain WHERE id=1").fetchone()
        if not head:
            prev, seq = "", 0
            for r in conn.execute("SELECT id, data FROM collections WHERE coll='audit' ORDER BY rowid").fetchall():
                item = json.loads(r["data"])
                seq += 1
                item["seq"] = seq
                item["prevHash"] = prev
                item.setdefault("_rev", 1)
                item["hash"] = _audit_link_hash(prev, item)
                conn.execute("UPDATE collections SET data=? WHERE coll='audit' AND id=?", (json.dumps(item), r["id"]))
                prev = item["hash"]
            conn.execute("INSERT INTO audit_chain (id, seq, head_hash, head_mac, key_fp) VALUES (1, ?, ?, ?, ?)",
                         (seq, prev, _audit_head_mac(seq, prev), _audit_key_fp()))
        elif head["key_fp"] is None:
            # A first-release chain (sealed with THIS key, before head_mac/key_fp existed): stamp them in.
            conn.execute("UPDATE audit_chain SET head_mac=?, key_fp=? WHERE id=1",
                         (_audit_head_mac(head["seq"], head["head_hash"] or ""), _audit_key_fp()))
    except sqlite3.OperationalError:
        pass   # never let the chain backfill abort startup
    # Deliberate operator recovery: TK_AUDIT_RESEAL=1 re-seals the whole chain under the CURRENT pepper
    # (for first-time keying or a key rotation, which otherwise makes verify report every link altered).
    if os.environ.get("TK_AUDIT_RESEAL") == "1":
        # Every path through here gives the connection back exactly once, then takes a fresh one.
        # `close()` no longer closes — it hands the connection back to this thread — so opening one
        # without releasing it pins the thread above depth 0 permanently: no rollback of uncommitted
        # work and no isolation_level restore, for the rest of that thread's life.
        #
        # The old shape released INSIDE the try (`conn.commit(); conn.close()`), so a commit that
        # raised jumped to the except and took a second connection without ever giving the first one
        # back. Rare — this branch needs an operator to set TK_AUDIT_RESEAL — but it is the main
        # thread, which never calls end_thread_conn(), so nothing would ever have cleaned it up.
        committed = True
        try:
            conn.commit()
        except Exception:
            committed = False      # a failed commit must not abort startup...
        conn.close()               # ...and must not cost the release either
        if committed:
            try:
                reseal_audit_chain()
            except Exception:
                pass               # nor must a failed reseal. Same rule as the backfill above.
        conn = get_conn()
    # Schema version marker (PRAGMA user_version): lets ops/tests read the applied schema version and
    # gives future ordered migrations a value to branch on. The ALTERs above are idempotent, so this
    # is a marker today, not a gate.
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()
    conn.close()


def seed_hr():
    """Seed the HRMS module collections. Each collection seeds independently so
    newer modules populate even on databases seeded by an earlier version."""
    emps = list_employees()
    pick = [e for e in emps if e.get("status", "Active") != "Inactive"]
    if pick:
        _seed_competency(pick)
        _seed_padr(pick)
        _seed_travel(pick)
        _seed_exits(pick)
        _seed_benefits(pick)
        _seed_learningpaths(pick)
        _seed_claims(pick)
        _seed_enrollments(pick)
        _seed_devices(pick)
        _seed_onboarding(pick)
    if collection_count("jobs") or collection_count("courses") or collection_count("candidates"):
        return False

    jobs = [
        {"title": "Senior Civil Engineer", "dept": "Engineering", "location": "HCMC HQ", "type": "Full Time", "openings": 2, "status": "Open"},
        {"title": "Project Coordinator", "dept": "Project", "location": "Long An", "type": "Full Time", "openings": 1, "status": "Open"},
        {"title": "Accountant", "dept": "Finance", "location": "HCMC HQ", "type": "Full Time", "openings": 1, "status": "Interviewing"},
        {"title": "Site Safety Officer", "dept": "Factory", "location": "Long An", "type": "Contract", "openings": 1, "status": "Open"},
    ]
    for j in jobs:
        put_collection_item("jobs", j)

    candidates = [
        {"name": "Le Minh Anh", "role": "Senior Civil Engineer", "stage": "Interview", "rating": 4, "source": "LinkedIn"},
        {"name": "Tran Quoc Bao", "role": "Senior Civil Engineer", "stage": "Screening", "rating": 3, "source": "Referral"},
        {"name": "Pham Thu Ha", "role": "Accountant", "stage": "Offer", "rating": 5, "source": "VietnamWorks"},
        {"name": "Nguyen Van Cuong", "role": "Project Coordinator", "stage": "Applied", "rating": 0, "source": "Website"},
        {"name": "Do Thi Mai", "role": "Site Safety Officer", "stage": "Applied", "rating": 0, "source": "Website"},
        {"name": "Hoang Gia Long", "role": "Accountant", "stage": "Hired", "rating": 5, "source": "Referral"},
    ]
    for c in candidates:
        put_collection_item("candidates", c)

    onboard_tasks = [
        ("Day 1 — Arrival", "Welcome & office tour, introductions"),
        ("Day 1 — Arrival", "Sign Labor Contract & NDA"),
        ("Day 1 — Arrival", "Personal info, bank, tax code & SI registration"),
        ("Day 1 — Arrival", "IT account, email & company ID / access card"),
        ("Week 1 — Integration", "EHS induction & Code of Conduct"),
        ("Week 1 — Integration", "IT security & expense system training"),
        ("Week 1 — Integration", "Department deep-dive (projects, process, tools)"),
        ("Week 1 — Integration", "Role shadowing with mentor & first task"),
        ("30-60-90 Days", "Draft 30-60-90 day plan + PADR objectives"),
        ("30-60-90 Days", "Day 30 — first check-in with Manager"),
        ("30-60-90 Days", "Day 60 — HR check-in & risk review"),
        ("30-60-90 Days", "Day 90 — probation review (confirm / extend / end)"),
    ]
    for idx, e in enumerate(pick[-3:]):
        done_n = [8, 4, 1][idx % 3]
        put_collection_item("onboarding", {
            "empId": e["id"], "name": e["name"], "role": e.get("title", ""),
            "startDate": e.get("startDate", ""),
            "tasks": [{"phase": ph, "label": t, "done": i < done_n} for i, (ph, t) in enumerate(onboard_tasks)],
        })

    for i, e in enumerate(pick[:8]):
        ratings = [4, 5, 3, 4, 4, 5, 3, 4]
        put_collection_item("reviews", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "cycle": "H1 2026", "rating": ratings[i % len(ratings)],
            "status": ["Completed", "In Review", "Self-assessment"][i % 3],
        })

    goals = [
        {"name": "Deliver Long An factory expansion phase 1", "owner": "Engineering", "progress": 65, "due": "2026-09-30"},
        {"name": "Reduce monthly attendance anomalies below 2%", "owner": "Operations", "progress": 80, "due": "2026-07-31"},
        {"name": "Complete ISO 9001 documentation", "owner": "Quality", "progress": 40, "due": "2026-12-15"},
        {"name": "Hire & onboard 5 new engineers", "owner": "HR", "progress": 50, "due": "2026-10-31"},
    ]
    for g in goals:
        put_collection_item("goals", g)

    courses = [
        {"title": "Workplace Safety (HSE) Essentials", "category": "Compliance", "duration": "45 min", "enrolled": 42, "status": "Active"},
        {"title": "Project Management Fundamentals", "category": "Professional", "duration": "6 modules", "enrolled": 18, "status": "Active"},
        {"title": "Business English — Intermediate", "category": "Language", "duration": "Ongoing", "enrolled": 25, "status": "Active"},
        {"title": "Leadership & Communication", "category": "Leadership", "duration": "4 weeks", "enrolled": 8, "status": "Active"},
        {"title": "AutoCAD for Civil Engineers", "category": "Technical", "duration": "12 hours", "enrolled": 14, "status": "Active"},
    ]
    for c in courses:
        put_collection_item("courses", c)

    boxes = ["Star", "High Potential", "Core Performer", "Solid Performer"]
    succ = ["Ready Now", "Ready in 1 year", "Ready in 2-3 years", "Develop in Role"]
    for i, e in enumerate(pick[:6]):
        put_collection_item("talent", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "title": e.get("title", ""), "box": boxes[i % len(boxes)],
            "potential": ["High", "High", "Medium", "Medium"][i % 4],
            "performance": ["High", "Medium", "High", "Medium"][i % 4],
            "succession": succ[i % len(succ)],
        })

    return True


def _seed_competency(pick):
    if collection_count("competency"):
        return
    comps = ["WS-01 CNC cutting", "WS-02 Frame assembly", "WS-03 PU foaming", "WS-04 Section assembly",
             "WS-05 Hygienic detail", "WS-06 Electrical pre-wire", "WS-07 Final assembly", "WS-08 Panel wiring",
             "WS-09 Pre-test & 5S", "FAT witness", "EN 1886 testing", "Hi-Pot / Megger", "Vibration ISO 21940",
             "Forklift", "Working at height", "LOTO", "Confined space", "Hot work / welding", "First aid",
             "ISO 9001", "VDI 6022", "EU-GMP Annex 1", "BMS / BACnet", "Site commissioning & TAB", "Customer communication"]
    statuses = ["✓", "T", "X", "—"]
    prod = [e for e in pick if (e.get("dept") or "") in ("Factory", "Engineering", "Project", "Operation")][:10]
    for idx, e in enumerate(prod):
        cells = {}
        for ci, c in enumerate(comps):
            s = statuses[(idx + ci * 3) % 4]
            if ci < 9 and (e.get("dept") == "Factory"):
                s = "✓" if (idx + ci) % 5 else "T"
            cells[c] = s
        put_collection_item("competency", {"empId": e["id"], "name": e["name"], "role": e.get("title", ""),
                                           "dept": e.get("dept", ""), "cells": cells})


def _seed_travel(pick):
    if collection_count("travel"):
        return
    samples = [
        {"dest": "Long An Factory", "purpose": "Site commissioning support", "transport": "Company car", "from": "2026-07-08", "to": "2026-07-10", "cost": 3500000, "advance": 2000000, "status": "Submitted"},
        {"dest": "Hà Nội", "purpose": "Client meeting — AHU project", "transport": "Flight", "from": "2026-07-15", "to": "2026-07-16", "cost": 8500000, "advance": 5000000, "status": "Approved"},
        {"dest": "Singapore", "purpose": "Supplier factory audit", "transport": "Flight", "from": "2026-08-03", "to": "2026-08-06", "cost": 22000000, "advance": 10000000, "status": "Submitted"},
    ]
    for i, e in enumerate(pick[:3]):
        s = samples[i % len(samples)]
        put_collection_item("travel", dict(s, empId=e["id"], name=e["name"], dept=e.get("dept", "")))


EXIT_CLEARANCE = [
    ("Manager", "Knowledge transfer & handover document"),
    ("Manager", "Outstanding work / projects reassigned"),
    ("IT", "Return laptop, phone & company assets"),
    ("IT", "Revoke email, system & VPN access"),
    ("Admin", "Return access card, keys & uniform"),
    ("Finance", "Settle advances, claims & company loans"),
    ("HR", "Final timesheet & annual-leave payout calculated"),
    ("HR", "Severance / final settlement processed"),
    ("HR", "Social Insurance book closed & returned"),
    ("HR", "Exit interview completed"),
]


def _seed_exits(pick):
    if collection_count("exits"):
        return
    # One in-progress resignation to demonstrate the offboarding workflow.
    cand = [e for e in pick if (e.get("role") or "") != "manager"]
    if not cand:
        cand = pick
    e = cand[-1]
    done_n = 4
    put_collection_item("exits", {
        "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
        "title": e.get("title", ""), "type": "Resignation",
        "initiated": "2026-06-02", "lastDay": "2026-07-02", "noticeDays": 30,
        "reason": "Career change — relocating to home province.",
        "status": "Clearance",
        "clearance": [{"owner": o, "label": l, "done": i < done_n}
                      for i, (o, l) in enumerate(EXIT_CLEARANCE)],
        "leavePayout": "", "severance": 0, "deductions": 0,
        "settlementNote": "", "rehire": "Yes",
    })


def _seed_onboarding(pick):
    """Onboarding checklists for the most recent hires — visible to Admin and to the
    employee (in My Training) where they tick steps to complete them."""
    if collection_count("onboarding"):
        return
    tasks_tpl = [
        ("Pre-boarding", "Send welcome email & first-day logistics"),
        ("Pre-boarding", "Prepare desk, PPE & workstation"),
        ("Pre-boarding", "Provision laptop & equipment in the asset register"),
        ("Day 1 — Arrival", "Welcome & office tour, introductions"),
        ("Day 1 — Arrival", "Sign Labor Contract & NDA"),
        ("Day 1 — Arrival", "IT account, email & company ID / access card"),
        ("Week 1 — Integration", "EHS induction & Code of Conduct"),
        ("Week 1 — Integration", "Benefits & welfare enrollment (insurance, allowances)"),
        ("Week 1 — Integration", "Role shadowing with mentor & first task"),
        ("30-60-90 Days", "Draft 30-60-90 day plan + PADR objectives"),
        ("30-60-90 Days", "Day 30 — first check-in with Manager"),
    ]
    cand = [e for e in pick if (e.get("role") or "") != "manager"]
    for idx, e in enumerate(cand or pick):
        done_n = 3 + (idx % 5)  # 3–7 of 11 done — leaves steps for the employee to tick
        put_collection_item("onboarding", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "title": e.get("title", ""), "startDate": e.get("startDate", ""),
            "tasks": [{"phase": ph, "label": lb, "done": i < done_n} for i, (ph, lb) in enumerate(tasks_tpl)],
        })


def _seed_devices(pick):
    """Company device / equipment register — laptops, monitors, phones per employee
    plus shared company assets. Demonstrates the asset-management module."""
    if collection_count("devices"):
        return
    laptops = ["Dell Latitude 5440", "Lenovo ThinkPad T14", "HP EliteBook 840", "MacBook Pro 14"]
    items = []
    for i, e in enumerate(pick):
        items.append({"name": laptops[i % len(laptops)], "category": "Laptop", "serial": "HML-LT-%03d" % (i + 1),
                      "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                      "qty": 1, "unitPrice": 22000000, "purchaseDate": "2024-01-15", "status": "Assigned", "note": ""})
        items.append({"name": "Dell 24\" Monitor P2422H", "category": "Monitor", "serial": "HML-MN-%03d" % (i + 1),
                      "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                      "qty": 1, "unitPrice": 4500000, "purchaseDate": "2024-01-15", "status": "Assigned", "note": ""})
        if (e.get("role") or "") == "manager":
            items.append({"name": "iPhone 13", "category": "Phone", "serial": "HML-PH-%03d" % (i + 1),
                          "assignedTo": e["name"], "empId": e["id"], "department": e.get("dept", ""),
                          "qty": 1, "unitPrice": 16000000, "purchaseDate": "2024-03-01", "status": "Assigned", "note": ""})
    items += [
        {"name": "HP LaserJet Pro Printer", "category": "Printer", "serial": "HML-PR-001", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 2, "unitPrice": 6500000, "purchaseDate": "2023-11-10", "status": "Available", "note": "Shared office printers"},
        {"name": "Epson Projector EB-X06", "category": "Other", "serial": "HML-PJ-001", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 1, "unitPrice": 12000000, "purchaseDate": "2023-09-05", "status": "Available", "note": "Meeting room"},
        {"name": "Toyota Hilux (Company)", "category": "Vehicle", "serial": "51A-678.90", "assignedTo": "", "empId": "", "department": "Operation", "qty": 1, "unitPrice": 850000000, "purchaseDate": "2022-06-20", "status": "Available", "note": "Site transport"},
        {"name": "Total Station Survey Kit", "category": "Tool", "serial": "HML-TL-001", "assignedTo": "", "empId": "", "department": "Engineering", "qty": 3, "unitPrice": 120000000, "purchaseDate": "2023-02-14", "status": "Available", "note": "Field survey"},
        {"name": "Dell Latitude (spare pool)", "category": "Laptop", "serial": "HML-LT-099", "assignedTo": "", "empId": "", "department": "HR & Admin", "qty": 2, "unitPrice": 22000000, "purchaseDate": "2024-05-01", "status": "Available", "note": "Spare pool"},
        {"name": "Lenovo ThinkPad (repair)", "category": "Laptop", "serial": "HML-LT-077", "assignedTo": "", "empId": "", "department": "Engineering", "qty": 1, "unitPrice": 21000000, "purchaseDate": "2023-08-12", "status": "In Repair", "note": "Keyboard fault"},
    ]
    for it in items:
        put_collection_item("devices", it)


def _seed_claims(pick):
    """One multi-line expense claim (a trip with several items) for demo."""
    if collection_count("claims"):
        return
    if not pick:
        return
    e = pick[min(2, len(pick) - 1)]
    put_collection_item("claims", {
        "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
        "title": "Long An site visit (3 days)", "type": "Multi-item",
        "ts": "12/06/2026", "status": "Submitted",
        "items": [
            {"id": "ci-1", "category": "Hotel / Accommodation", "amount": 2400000, "note": "2 nights", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-2", "category": "Meal", "amount": 850000, "note": "Team dinner", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-3", "category": "Transport", "amount": 1200000, "note": "Car + fuel", "attachment": "", "attachmentName": "", "status": "Submitted"},
            {"id": "ci-4", "category": "Per diem", "amount": 600000, "note": "3 days", "attachment": "", "attachmentName": "", "status": "Submitted"},
        ],
        "amount": 5050000,
    })


def _seed_enrollments(pick):
    if collection_count("enrollments"):
        return
    if not pick:
        return
    courses = ["Workplace Safety (HSE) Essentials", "Project Management Fundamentals", "Business English — Intermediate", "Leadership & Communication", "AutoCAD for Civil Engineers"]
    statuses = [("Completed", 100), ("In progress", 60), ("In progress", 30), ("Enrolled", 0)]
    for i, e in enumerate(pick[:10]):
        crs = courses[i % len(courses)]
        st, pg = statuses[i % len(statuses)]
        put_collection_item("enrollments", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""),
            "course": crs, "status": st, "progress": pg,
            "rating": (5 if i % 3 == 0 else 4) if st == "Completed" else 0,
            "feedback": "Very practical, well delivered." if (st == "Completed" and i % 3 == 0) else "",
        })


def _seed_benefits(pick):
    """HR-managed benefits & allowances by grade (G1-G10). Baseline lunch/phone/
    transport match _payComputed welfare so Payroll and Profile agree."""
    if collection_count("benefits"):
        return
    rows = [
        {"grade": "G1",  "lunch": 730000, "phone": 0,       "transport": 300000,  "parking": 0,       "health": "Group accident only",                    "training": 3000000,   "note": "Intern"},
        {"grade": "G2",  "lunch": 730000, "phone": 200000,  "transport": 500000,  "parking": 0,       "health": "IP 200M / OP 20M (from Day 91)",          "training": 5000000,   "note": "Junior"},
        {"grade": "G3",  "lunch": 730000, "phone": 300000,  "transport": 500000,  "parking": 0,       "health": "IP 200M / OP 20M",                        "training": 8000000,   "note": "Engineer / Officer"},
        {"grade": "G4",  "lunch": 730000, "phone": 300000,  "transport": 700000,  "parking": 0,       "health": "IP 200M / OP 20M + rider",                "training": 12000000,  "note": "Senior"},
        {"grade": "G5",  "lunch": 730000, "phone": 500000,  "transport": 1000000, "parking": 500000,  "health": "IP 200M / OP 20M + rider",                "training": 15000000,  "note": "Lead / Supervisor"},
        {"grade": "G6",  "lunch": 730000, "phone": 700000,  "transport": 1500000, "parking": 500000,  "health": "Family health rider",                     "training": 20000000,  "note": "Asst. Manager"},
        {"grade": "G7",  "lunch": 730000, "phone": 1000000, "transport": 2000000, "parking": 1000000, "health": "Family health rider",                     "training": 30000000,  "note": "Manager"},
        {"grade": "G8",  "lunch": 730000, "phone": 1500000, "transport": 3000000, "parking": 1000000, "health": "Family + dependents",                     "training": 40000000,  "note": "Senior Manager"},
        {"grade": "G9",  "lunch": 730000, "phone": 2000000, "transport": 0,       "parking": 1500000, "health": "Family + dependents (car in lieu)",       "training": 60000000,  "note": "Director"},
        {"grade": "G10", "lunch": 730000, "phone": 3000000, "transport": 0,       "parking": 2000000, "health": "Family + dependents + executive plan",    "training": 100000000, "note": "Executive / MD"},
    ]
    for b in rows:
        put_collection_item("benefits", dict(b, id="ben-" + b["grade"]))


def _seed_learningpaths(pick):
    """Role-based development roadmaps (career learning paths)."""
    if collection_count("learningpaths"):
        return
    paths = [
        {"role": "Civil Engineer", "track": "Engineering", "stages": [
            {"name": "Foundation", "months": "0-6", "courses": ["Workplace Safety (HSE) Essentials", "AutoCAD for Civil Engineers"], "certs": ["HSE induction"]},
            {"name": "Practitioner", "months": "6-18", "courses": ["Project Management Fundamentals"], "certs": ["ISO 9001 awareness"]},
            {"name": "Advanced", "months": "18-36", "courses": ["Leadership & Communication"], "certs": ["Site commissioning & TAB"]},
            {"name": "Lead", "months": "36+", "courses": ["Leadership & Communication"], "certs": ["PE / Chartered (target)"]},
        ]},
        {"role": "AHU Factory Technician", "track": "Factory", "stages": [
            {"name": "Foundation", "months": "0-3", "courses": ["Workplace Safety (HSE) Essentials"], "certs": ["LOTO", "Working at height"]},
            {"name": "Practitioner", "months": "3-12", "courses": [], "certs": ["EN 1886 testing", "Hi-Pot / Megger"]},
            {"name": "Advanced", "months": "12-24", "courses": [], "certs": ["FAT witness", "VDI 6022"]},
            {"name": "Lead", "months": "24+", "courses": ["Leadership & Communication"], "certs": ["Site commissioning & TAB"]},
        ]},
        {"role": "Project Coordinator", "track": "Project", "stages": [
            {"name": "Foundation", "months": "0-6", "courses": ["Business English — Intermediate", "Workplace Safety (HSE) Essentials"], "certs": []},
            {"name": "Practitioner", "months": "6-18", "courses": ["Project Management Fundamentals"], "certs": ["ISO 9001"]},
            {"name": "Advanced", "months": "18-36", "courses": ["Leadership & Communication"], "certs": ["PMP (target)"]},
        ]},
    ]
    for i, p in enumerate(paths):
        put_collection_item("learningpaths", dict(p, id="lp-" + str(i + 1)))


def _seed_padr(pick):
    if collection_count("padr"):
        return
    goal_pool = [
        ("Deliver assigned projects on time & on budget", 30, "100% milestones met"),
        ("Quality — defect/rework rate within target", 25, "< 2% rework"),
        ("HSE compliance & 5S", 15, "Zero incidents"),
        ("Skill development & certification", 15, "2 competencies gained"),
        ("Teamwork & customer focus", 15, "Positive 360 feedback"),
    ]
    cyc_status = ["Goal-setting", "Mid-year", "Self-assessment", "Calibrated", "Finalized"]
    for i, e in enumerate(pick[:10]):
        st = cyc_status[i % len(cyc_status)]
        goals = [{"objective": o, "weight": w, "target": t,
                  "selfScore": (4 if i % 2 else 3) if st in ("Self-assessment", "Calibrated", "Finalized") else 0,
                  "mgrScore": (4 if i % 3 else 3) if st in ("Calibrated", "Finalized") else 0}
                 for (o, w, t) in goal_pool]
        put_collection_item("padr", {
            "empId": e["id"], "name": e["name"], "dept": e.get("dept", ""), "cycle": "2026",
            "status": st, "goals": goals,
            "rating": (4 if i % 2 else 3) if st == "Finalized" else 0,
            "idp": "Lead a sub-project; complete PM fundamentals course" if i % 2 else "Mentoring & ISO 9001 refresher",
        })


def is_seeded():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
    conn.close()
    return n > 0


def seed():
    """Populate the database from seed_data on first run only."""
    if is_seeded():
        return False
    conn = get_conn()
    cur = conn.cursor()
    for e in seed_data.EMPLOYEES:
        role = "manager" if e["title"] in seed_data.MANAGER_TITLES else "staff"
        cols = ["id", "name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
                "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
                "role", "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]
        vals = [e.get(c) for c in cols[:-6]] + [role, e["annualUsed"], e["annualTotal"],
                                                 e["sickUsed"], e["sickTotal"], e["compoff"]]
        cur.execute("INSERT INTO employees (%s) VALUES (%s)" % (
            ",".join(cols), ",".join(["?"] * len(cols))), vals)
    for z in seed_data.ZONES:
        cur.execute("INSERT INTO zones (name,lat,lon,radius) VALUES (?,?,?,?)",
                    (z["name"], z["lat"], z["lon"], z["radius"]))
    for a in seed_data.sample_attendance():
        cur.execute("INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,hrs,loc) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (a["emp_id"], a["name"], a["dept"], a["date"], a.get("clock_in"),
                     a.get("clock_out"), a["status"], a.get("hrs"), a.get("loc")))
    for l in seed_data.LEAVE:
        cur.execute("INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (l["emp_id"], l["type"], l["startDate"], l["endDate"], l["days"],
                     l["status"], l["reason"], now_iso()))
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _rows(sql, params=()):
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row(sql, params=()):
    conn = get_conn()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

EMP_FIELDS = ["name", "ini", "clr", "dept", "title", "email", "phone", "startDate",
              "status", "zone", "gender", "dob", "taxId", "bank", "emergency", "address",
              "managerEmail", "jobLevel", "endDate", "serviceDuration", "personalId",
              "familyStatus", "education", "employmentType", "englishCert", "note", "photo",
              "role", "level", "salary", "grade", "dependents", "shirtSize", "appsDenied", "appsAllowed", "schedule",
              # Labour Code Art. 113(1): 'normal' (12 days), 'heavy' (14) or 'especially_heavy' (16).
              # Site and factory duty is not automatically heavy work — it is a classification the
              # company makes against the MOLISA list, so it is recorded, not inferred from a title.
              "workConditions", "disabled",
              # The Decree 293/2025 wage region (I–IV) the person's WORKPLACE is in — the statutory
              # minimum they must be paid at. It is a property of the district they work in, set by
              # the decree's own schedule, so it is recorded rather than derived: `zone` next to it
              # is a GPS check-in geofence and means nothing here. Blank falls back to the company
              # default; blank with no default means nobody is checked, which the register says.
              "wageRegion",
              # Whether they hold a certified vocational qualification, for the 7% uplift IF the
              # company's collective agreement commits to one. Never a statutory floor on its own.
              "trained",
              # Art. 20(2)(c) carve-out, where one applies: 'elderly' | 'foreign' | 'state_director'
              # | 'union_officer'. Blank for almost everyone — it is a legal status somebody records,
              # never something to infer from a name or a job title.
              "contractExempt",
              # Decree 44/2016 occupational-safety training group (1–6), where the company has
              # classified the person. Blank means no safety-training requirement is asserted for
              # them — inventing one for everybody would bury the people who genuinely have one.
              "oshGroup",
              # Structured bank details for the salary transfer file. The legacy free-text `bank`
              # field stays for anything already typed into it, but a payment file cannot be built
              # from prose — it needs the account number on its own.
              "bankName", "bankAcc", "bankHolder", "bankBranch",
              "procRole",
              "annualUsed", "annualTotal", "sickUsed", "sickTotal", "compoff"]


def list_employees():
    return _rows("SELECT * FROM employees ORDER BY id")


# ── Effective-dated employee history ────────────────────────────────────────────────────────────
# The fields worth a dated row: the ones that move money, route approvals or decide reporting.
EMP_HISTORY_FIELDS = ("salary", "grade", "title", "dept", "managerEmail", "status")


def add_emp_event(emp_id, field, old_value, new_value, effective=None, reason="",
                  actor="", actor_id="", source="edit"):
    """Record one dated change. Append-only — there is no update or delete for this table."""
    now = now_iso()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO emp_events (emp_id, effective, field, old_value, new_value, reason, "
            "actor, actor_id, source, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (emp_id, (effective or now[:10])[:10], field,
             None if old_value is None else str(old_value),
             None if new_value is None else str(new_value),
             reason or "", actor or "", actor_id or "", source, now))
        conn.commit()
    finally:
        conn.close()


def drop_inferred_emp_events():
    """Remove every INFERRED (source='backfill') row, returning what was removed.

    The one deletion this table allows, and only for rows nobody recorded. A backfilled row is not
    evidence of a decision — it is a reconstruction from the pay runs, and the first version of that
    reconstruction read a payslip TOTAL as somebody's salary and ingested runs no Director had
    signed. Those rows assert things that were never true, so correcting them would leave two
    contradictory events on the same date rather than one right one; they are removed and rebuilt.

    Rows somebody actually recorded (source='edit') are never touched. The caller writes the removed
    rows into the audit chain before this returns them to the void.
    """
    conn = get_conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM emp_events WHERE source = 'backfill' ORDER BY emp_id, effective")]
        conn.execute("DELETE FROM emp_events WHERE source = 'backfill'")
        conn.commit()
    finally:
        conn.close()
    return rows


def list_emp_events(emp_id=None, field=None, since=None, until=None):
    """The dated trail, newest first. Any combination of filters."""
    sql = "SELECT * FROM emp_events WHERE 1=1"
    args = []
    if emp_id:
        sql += " AND emp_id = ?"; args.append(emp_id)
    if field:
        sql += " AND field = ?"; args.append(field)
    if since:
        sql += " AND effective >= ?"; args.append(since[:10])
    if until:
        sql += " AND effective <= ?"; args.append(until[:10])
    return _rows(sql + " ORDER BY effective DESC, id DESC", tuple(args))


def emp_value_asof(emp_id, field, date):
    """What `field` was for this employee ON `date` — the question the portal could not answer.

    The latest change effective on or before the date. Returns None when nothing was recorded by
    then, which is honestly different from "it was empty": history starts when recording starts."""
    row = _row("SELECT new_value FROM emp_events WHERE emp_id = ? AND field = ? AND effective <= ? "
               "ORDER BY effective DESC, id DESC LIMIT 1", (emp_id, field, str(date)[:10]))
    return row["new_value"] if row else None


def emp_events_count():
    row = _row("SELECT COUNT(*) AS n FROM emp_events")
    return row["n"] if row else 0


def get_employee(emp_id):
    return _row("SELECT * FROM employees WHERE id = ?", (emp_id,))


def get_employee_by_email(email):
    if not email:
        return None
    return _row("SELECT * FROM employees WHERE LOWER(email) = LOWER(?)", (email.strip(),))


def next_emp_id():
    """Auto-generate the next HML-### employee id."""
    rows = _rows("SELECT id FROM employees WHERE id LIKE 'HML-%'")
    nums = []
    for r in rows:
        tail = r["id"].split("-")[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return "HML-%03d" % ((max(nums) + 1) if nums else 1)


def create_employee(data):
    emp_id = data.get("id") or next_emp_id()
    fields = ["id"] + EMP_FIELDS
    vals = [emp_id] + [data.get(f) for f in EMP_FIELDS]
    conn = get_conn()
    conn.execute("INSERT INTO employees (%s) VALUES (%s)" % (
        ",".join(fields), ",".join(["?"] * len(fields))), vals)
    conn.commit()
    conn.close()
    return emp_id


def _scalar(v):
    """SQLite can only bind str/int/float/bytes/None; a stray dict/list from a malformed request body
    would raise InterfaceError (a 500 for any authenticated caller). JSON-encode non-scalars so the
    write degrades gracefully instead of crashing the handler."""
    return v if isinstance(v, (str, int, float, bool, bytes, type(None))) else json.dumps(v, ensure_ascii=False)


def update_employee(emp_id, data):
    sets, params = [], []
    for f in EMP_FIELDS:
        if f in data:
            sets.append("%s = ?" % f)
            params.append(_scalar(data[f]))
    if not sets:
        return
    params.append(emp_id)
    conn = get_conn()
    conn.execute("UPDATE employees SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


# Collections in the generic JSON store that reference an employee by id. There are no foreign keys
# there, so a hard-delete silently ORPHANS these rows (and the id could later be recycled onto them).
# `audit` is deliberately EXCLUDED: it is append-only evidence that must SURVIVE the delete, it carries
# its own actor-name snapshot, and every account accumulates audit rows — blocking on it would make
# deletion impossible rather than exceptional.
EMP_REF_COLLS = ("claims", "travel", "payments", "payruns", "payadjust", "padr", "acks", "devices",
                 "handovers", "exits", "onboarding", "enrollments", "reviews", "goals", "talent",
                 "competency", "pip")
_EMP_REF_KEYS = ("empId", "preparedById", "createdById", "reviewedById", "approvedById", "userId")


def _refs_employee(node, emp_id):
    """True if any id-bearing key ANYWHERE in the record equals this employee id — including nested
    devices[].assignments[].empId and Part 11 signatures[].userId."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _EMP_REF_KEYS and v == emp_id:
                return True
            if isinstance(v, (dict, list)) and _refs_employee(v, emp_id):
                return True
    elif isinstance(node, list):
        return any(_refs_employee(x, emp_id) for x in node)
    return False


def employee_references(emp_id):
    """Everything in the DB that points at this employee, as {label: count}; empty == safe to delete.

    attendance / leave / esign_pin / emp_events matter MOST: their FKs are ON DELETE CASCADE (and
    foreign_keys is ON), so deleting the employee DESTROYS that history outright rather than merely
    orphaning it. emp_events is the effective-dated employment record — append-only through the API,
    and until it was counted here, erasable by one DELETE that then logged "no history on record"."""
    refs = {}
    conn = get_conn()
    try:
        for tbl, label in (("attendance", "attendance record"), ("leave", "leave request"),
                           ("emp_events", "employment-history record")):
            n = conn.execute("SELECT COUNT(*) FROM %s WHERE emp_id = ?" % tbl, (emp_id,)).fetchone()[0]
            if n:
                refs[label] = n
        if conn.execute("SELECT 1 FROM esign_pin WHERE emp_id = ?", (emp_id,)).fetchone():
            refs["e-signature PIN"] = 1
        n = conn.execute("SELECT COUNT(*) FROM employees WHERE managerEmail IS NOT NULL AND managerEmail != '' "
                         "AND managerEmail = (SELECT email FROM employees WHERE id = ?)", (emp_id,)).fetchone()[0]
        if n:
            refs["direct report"] = n
        rows = conn.execute("SELECT coll, data FROM collections WHERE coll IN (%s)"
                            % ",".join("?" * len(EMP_REF_COLLS)), EMP_REF_COLLS).fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            if _refs_employee(json.loads(r["data"]), emp_id):
                refs[r["coll"]] = refs.get(r["coll"], 0) + 1
        except (ValueError, TypeError):
            pass
    return refs


def delete_employee(emp_id):
    conn = get_conn()
    conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

def list_attendance(emp_id=None, start=None, end=None):
    sql = "SELECT * FROM attendance WHERE 1=1"
    params = []
    if emp_id:
        sql += " AND emp_id = ?"; params.append(emp_id)
    if start:
        sql += " AND date >= ?"; params.append(start)
    if end:
        sql += " AND date <= ?"; params.append(end)
    sql += " ORDER BY date DESC, clock_in DESC"
    return _rows(sql, params)


def open_attendance(emp_id, date):
    return _row("SELECT * FROM attendance WHERE emp_id = ? AND date = ? AND clock_out IS NULL "
                "ORDER BY id DESC LIMIT 1", (emp_id, date))


def _hrs_between(cin, cout, overnight=False):
    """Worked minutes as a display string.

    When `overnight`, the clock has gone round once, so the wrap applies WHATEVER the sign — the
    same correction as app.py's _checkout. Wrapping only on a negative made 08:00 -> 17:00 the next
    day read as "9h 00m" instead of the 33 hours it really was, which is how a forgotten check-out
    became an ordinary-looking day. The endpoint refuses anything over 16h, so a value that reaches
    here is a real shift.
    """
    try:
        ih, im = map(int, cin.split(":")); oh, om = map(int, cout.split(":"))
        mins = (oh * 60 + om) - (ih * 60 + im)
        if overnight:
            # 18:00 → 00:30 next day = 6h30, not -18h30. One wrap is the most this can ever need:
            # both times are within a single day, so the result is at most 1439 + 1440 minutes.
            mins += 1440
        if mins < 0:
            return ""             # same-day out<in is rejected upstream; never store negatives
        return "%dh %02dm" % (mins // 60, mins % 60)
    except (ValueError, AttributeError):
        return ""


def open_attendance_any(emp_id, dates):
    """Latest open record on any of the given dates (today + yesterday: overnight checkout)."""
    marks = ",".join(["?"] * len(dates))
    return _row("SELECT * FROM attendance WHERE emp_id = ? AND date IN (%s) AND clock_out IS NULL "
                "ORDER BY date DESC, id DESC LIMIT 1" % marks, [emp_id] + list(dates))


def set_attendance_project(att_id, project):
    """Record (or clear) which job a day was on.

    Separate from `amend_attendance` on purpose: naming the job is not a change to the HOURS, so it
    does not reopen an approved overtime decision or consume an amendment slot. It is closed once
    the month is signed, like everything else that feeds a payslip."""
    conn = get_conn()
    conn.execute("UPDATE attendance SET project = ? WHERE id = ?",
                 ((project or None), int(att_id)))
    conn.commit()
    conn.close()
    return get_attendance(att_id)


def clock_in(emp_id, date, time_hm, loc=None, lat=None, lon=None, status="on-time", project=None,
             away_reason=None):
    emp = get_employee(emp_id)
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO attendance (emp_id,name,dept,date,clock_in,status,loc,lat,lon,project,away_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (emp_id, emp["name"] if emp else None, emp["dept"] if emp else None,
             date, time_hm, status, loc, lat, lon, (project or None), (away_reason or None)))
        conn.commit()
    except sqlite3.IntegrityError:
        # uq_att_open: a concurrent request already opened today's record — atomic double-tap guard
        conn.close()
        return None
    rid = cur.lastrowid
    conn.close()
    return rid


def clock_out(att_id, time_hm, ot_hours=0, ot_reason="", overnight=False):
    rec = _row("SELECT * FROM attendance WHERE id = ?", (att_id,))
    if not rec:
        return None
    hrs = _hrs_between(rec["clock_in"], time_hm, overnight=overnight)
    try:
        oth = float(ot_hours or 0)
    except (TypeError, ValueError):
        oth = 0
    conn = get_conn()
    if oth > 0:
        # An overtime REQUEST — pending until a manager approves. Until then it does not count.
        conn.execute("UPDATE attendance SET clock_out = ?, hrs = ?, ot_status = 'pending', ot_hours = ?, ot_reason = ? WHERE id = ?",
                     (time_hm, hrs, oth, (ot_reason or ""), att_id))
    else:
        conn.execute("UPDATE attendance SET clock_out = ?, hrs = ? WHERE id = ?", (time_hm, hrs, att_id))
    conn.commit()
    conn.close()
    return hrs


def get_attendance(att_id):
    return _row("SELECT * FROM attendance WHERE id = ?", (att_id,))


def list_ot_approved(start, end, emp_id=None):
    """Approved overtime worked in a date range.

    Only APPROVED rows: a pending request is not overtime, it is a question, and a rejected one is an
    answer of no. Paying either would pay for a decision nobody made.
    """
    sql = ("SELECT * FROM attendance WHERE ot_status = 'approved' AND ot_hours > 0 "
           "AND date >= ? AND date <= ?")
    params = [start, end]
    if emp_id:
        sql += " AND emp_id = ?"
        params.append(emp_id)
    return _rows(sql + " ORDER BY date, emp_id", params)


def amend_attendance(att_id, fields, actor="", actor_id="", reason=""):
    """Correct an attendance record, and record that it was corrected.

    Only the times and the overtime figure may be changed — never the date or the employee. Moving a
    shift to another day would move it between months and therefore between pay runs; changing whose
    it is would be a new record, not a correction.

    Returns the row as it stood BEFORE, so the caller can write the before/after into the audit chain.
    """
    before = _row("SELECT * FROM attendance WHERE id = ?", (att_id,))
    if not before:
        return None
    sets, args = [], []
    for k in ("clock_in", "clock_out", "status", "ot_hours", "ot_reason", "ot_status", "hrs"):
        if k in fields:
            sets.append("%s = ?" % k)
            args.append(fields[k])
    if not sets:
        return before
    sets += ["amended_by = ?", "amended_at = ?", "amend_reason = ?",
             "amend_count = COALESCE(amend_count, 0) + 1"]
    args += [actor or "", now_iso(), (reason or "")[:500], att_id]
    conn = get_conn()
    try:
        conn.execute("UPDATE attendance SET " + ", ".join(sets) + " WHERE id = ?", args)
        conn.commit()
    finally:
        conn.close()
    return before


def decide_attendance_ot(att_id, decision):
    """Approve or reject a pending overtime request. Only approved OT counts in the system."""
    st = "approved" if str(decision or "").lower() in ("approve", "approved", "yes") else "rejected"
    conn = get_conn()
    conn.execute("UPDATE attendance SET ot_status = ? WHERE id = ?", (st, att_id))
    conn.commit()
    conn.close()
    return st


def generate_attendance(weeks=6, force=False, anchor=None):
    """Generate realistic recent attendance for all active employees.

    Idempotent: skips entirely when the table already has rows (unless force),
    and never duplicates a given (emp_id, date). Deterministic (seeded RNG) so
    repeated boots/imports don't churn. Returns the number of rows inserted.
    """
    import random
    from datetime import date as _date, timedelta
    conn = get_conn()
    have = conn.execute("SELECT COUNT(*) AS n FROM attendance").fetchone()["n"]
    if have and not force:
        conn.close()
        return 0
    rng = random.Random(20260621)
    emps = [e for e in list_employees() if (e.get("status") or "Active") != "Inactive"]
    # map an employee's stored zone label to a short location tag
    zone_short = {}
    for z in list_zones():
        nm = (z["name"] or "")
        zone_short[nm] = "Factory" if ("factory" in nm.lower() or "long an" in nm.lower()) else "HQ"
    anchor = anchor or _date.today()
    rows = []
    for emp in emps:
        loc_base = zone_short.get(emp.get("zone") or "", "HQ")
        for d in range(weeks * 7):
            day = anchor - timedelta(days=d)
            if day.weekday() >= 5:  # weekend
                continue
            iso = day.isoformat()
            if conn.execute("SELECT 1 FROM attendance WHERE emp_id=? AND date=?",
                            (emp["id"], iso)).fetchone():
                continue
            roll = rng.random()
            if roll < 0.04:  # absent
                rows.append((emp["id"], emp.get("name"), emp.get("dept"), iso,
                             None, None, "absent", "", None))
                continue
            in_h, in_m = 8, rng.randint(0, 34)
            if rng.random() < 0.12:  # late
                in_h, in_m = 8, rng.randint(20, 55)
                status = "late"
            else:
                in_h, in_m = (7, rng.randint(45, 59)) if rng.random() < 0.5 else (8, rng.randint(0, 14))
                status = "on-time"
            cin = "%02d:%02d" % (in_h, in_m)
            out_h, out_m = 17, rng.randint(0, 50)
            cout = "%02d:%02d" % (out_h, out_m)
            loc = "Out of Zone" if rng.random() < 0.02 else loc_base
            rows.append((emp["id"], emp.get("name"), emp.get("dept"), iso,
                         cin, cout, status, _hrs_between(cin, cout), loc))
    conn.executemany(
        "INSERT INTO attendance (emp_id,name,dept,date,clock_in,clock_out,status,hrs,loc) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------

def list_leave(emp_id=None, status=None, emp_ids=None):
    sql = ("SELECT l.*, e.name AS emp_name, e.dept AS emp_dept, e.managerEmail AS emp_managerEmail "
           "FROM leave l LEFT JOIN employees e ON e.id = l.emp_id WHERE 1=1")
    params = []
    if emp_id:
        sql += " AND l.emp_id = ?"; params.append(emp_id)
    if emp_ids is not None:
        if not emp_ids:
            return []
        sql += " AND l.emp_id IN (%s)" % ",".join(["?"] * len(emp_ids))
        params.extend(emp_ids)
    if status:
        sql += " AND l.status = ?"; params.append(status)
    sql += " ORDER BY l.startDate DESC"
    return _rows(sql, params)


def list_reports(manager_email):
    """Employees whose direct manager is the given email."""
    if not manager_email:
        return []
    return _rows("SELECT * FROM employees WHERE LOWER(managerEmail) = LOWER(?)", (manager_email,))


def get_leave(leave_id):
    return _row("SELECT * FROM leave WHERE id = ?", (leave_id,))


def create_leave(data):
    import secrets
    token = secrets.token_urlsafe(24)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO leave (emp_id,type,startDate,endDate,days,status,reason,created_at,token) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (data["emp_id"], data.get("type"), data.get("startDate"), data.get("endDate"),
         data.get("days"), data.get("status", "pending"), data.get("reason"), now_iso(), token))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid, token


def get_leave_by_token(token):
    if not token:
        return None
    return _row("SELECT * FROM leave WHERE token = ?", (token,))


def set_leave_status(leave_id, status, note=None):
    conn = get_conn()
    conn.execute("UPDATE leave SET status = ?, note = ? WHERE id = ?", (status, note, leave_id))
    conn.commit()
    conn.close()


def append_leave_signature(leave_id, sig, new_status=None):
    """Append a 21 CFR Part 11 e-signature (dict) to a leave record, optionally set its status.
    Returns the row (dict) or None if not found."""
    row = _row("SELECT * FROM leave WHERE id = ?", (leave_id,))
    if not row:
        return None
    try:
        sigs = json.loads(row.get("signatures") or "[]")
    except Exception:
        sigs = []
    sigs.append(sig)
    conn = get_conn()
    if new_status is not None:
        conn.execute("UPDATE leave SET signatures = ?, status = ? WHERE id = ?",
                     (json.dumps(sigs), new_status, leave_id))
    else:
        conn.execute("UPDATE leave SET signatures = ? WHERE id = ?", (json.dumps(sigs), leave_id))
    conn.commit()
    conn.close()
    out = dict(row); out["signatures"] = sigs
    if new_status is not None:
        out["status"] = new_status
    return out


# ---------------------------------------------------------------------------
# 21 CFR Part 11 — signature PIN (second signing component)
#   Stored ONLY as a salted PBKDF2-HMAC-SHA256 hash. The plaintext PIN is never
#   written, logged or returned. Verification is constant-time; repeated failures
#   lock the credential; PINs age out and cannot be immediately reused.
# ---------------------------------------------------------------------------

_HAS_SCRYPT        = hasattr(hashlib, "scrypt")   # scrypt needs OpenSSL (present on the prod Ubuntu box)
SCRYPT_N           = 16384             # scrypt cost — ~16 MiB working set per derive
SCRYPT_R           = 8
SCRYPT_P           = 1
PIN_ITERATIONS     = 600_000           # PBKDF2 rounds (fallback when scrypt is unavailable)
PIN_ALGO           = "scrypt" if _HAS_SCRYPT else "pbkdf2_sha256"   # current KDF for new/changed PINs
PIN_COST           = SCRYPT_N if _HAS_SCRYPT else PIN_ITERATIONS    # cost stored alongside each hash
PIN_SALT_BYTES     = 16
PIN_DKLEN          = 32
PIN_MIN, PIN_MAX   = 6, 12
PIN_LOCK_THRESHOLD = 5
PIN_LOCK_SECONDS   = 15 * 60
PIN_MAX_AGE_DAYS   = 180
# Optional server-side pepper — kept OUTSIDE the database (env var). When set, a leak of the
# SQLite file alone cannot be brute-forced offline. Set TK_ESIGN_PEPPER to a long random string
# in production (e.g. `openssl rand -hex 32`). Empty = no pepper (still salted + slow KDF).
PIN_PEPPER         = os.environ.get("TK_ESIGN_PEPPER", "").encode("utf-8")


def _pin_pre(pin):
    """Fold in the server-side pepper (if configured) before the KDF."""
    pw = (pin or "").encode("utf-8")
    return hmac.new(PIN_PEPPER, pw, hashlib.sha256).digest() if PIN_PEPPER else pw


def _pin_derive(pin, salt_hex, algo=PIN_ALGO, cost=None):
    """Derive the hex key for a PIN + hex salt. Supports scrypt (memory-hard, current) and
    pbkdf2_sha256 (fallback + legacy rows)."""
    salt = bytes.fromhex(salt_hex)
    pw = _pin_pre(pin)
    if algo == "scrypt":
        n = int(cost or SCRYPT_N)
        return hashlib.scrypt(pw, salt=salt, n=n, r=SCRYPT_R, p=SCRYPT_P, maxmem=132 * 1024 * 1024, dklen=PIN_DKLEN).hex()
    return hashlib.pbkdf2_hmac("sha256", pw, salt, int(cost or PIN_ITERATIONS), dklen=PIN_DKLEN).hex()


def _pin_parse_iso(s):
    """Parse an ISO timestamp to an aware UTC datetime, or None if unparseable."""
    try:
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except Exception:
        return None


def _pin_norm(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def validate_pin_policy(emp, pin):
    """Return a machine reason string if the PIN violates policy, else None."""
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9A-Za-z]{%d,%d}" % (PIN_MIN, PIN_MAX), pin or ""):
        return "length"
    if len(set(pin)) == 1:
        return "all_same"
    low = pin.lower()

    def _seq(s, step):
        return len(s) > 1 and all(ord(s[i + 1]) - ord(s[i]) == step for i in range(len(s) - 1))
    if _seq(low, 1) or _seq(low, -1):
        return "sequential"
    if pin in ("1234", "0000", "1111", "2580", "123456", "654321", "111111", "000000", "121212", "abcdef"):
        return "trivial"
    np = _pin_norm(pin)
    if emp and len(np) >= 4:
        for f in ("id", "phone", "email", "dob", "taxId", "personalId"):
            v = emp.get(f) if isinstance(emp, dict) else None
            if not v:
                continue
            nv = _pin_norm(str(v).split("@")[0] if f == "email" else str(v))
            if nv and len(nv) >= 4 and (np == nv or np in nv):
                return "personal_info"
    return None


def get_pin_status(emp_id):
    """Public status for the owner's PIN. NEVER returns hash/salt material."""
    row = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if not row or not row.get("hash"):
        return {"enrolled": False}
    now = datetime.now(timezone.utc)
    locked = False
    lu = row.get("locked_until")
    if lu:
        d = _pin_parse_iso(lu)
        locked = (d is None) or (d > now)   # unparseable -> treat as locked (fail closed)
    age_days = None
    expired = False
    st = row.get("set_ts")
    if st:
        d = _pin_parse_iso(st)
        if d is None:
            expired = True                  # unparseable -> treat as expired (fail closed)
        else:
            age_days = (now - d).days
            expired = age_days > PIN_MAX_AGE_DAYS
    return {"enrolled": True, "status": row.get("status"),
            "revoked": row.get("status") == "revoked",
            "mustChange": bool(row.get("must_change")),
            "locked": locked, "lockedUntil": lu if locked else None,
            "expired": expired, "ageDays": age_days, "setAt": st}


def all_pin_statuses():
    """PIN status for every employee (manager governance view). Never returns hash/salt material."""
    out = []
    for e in list_employees():
        st = get_pin_status(e.get("id"))
        out.append({"empId": e.get("id"), "name": e.get("name"), "dept": e.get("dept"),
                    "title": e.get("title"), "email": e.get("email"),
                    "enrolled": st.get("enrolled", False), "setAt": st.get("setAt"),
                    "locked": st.get("locked", False), "expired": st.get("expired", False),
                    "revoked": st.get("revoked", False), "mustChange": st.get("mustChange", False)})
    return out


def set_pin(emp_id, new_pin, enrolled_via="M365 session", enrolled_oid=None):
    """Enroll or change the PIN (upsert). Blocks immediate reuse of the previous PIN.
    Returns (ok, reason)."""
    prev = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if prev and prev.get("hash") and prev.get("salt"):
        if hmac.compare_digest(_pin_derive(new_pin, prev["salt"], prev.get("algo") or "pbkdf2_sha256", prev.get("iterations")), prev["hash"]):
            return (False, "reuse")   # cannot re-set the identical current PIN
    salt_hex = secrets.token_bytes(PIN_SALT_BYTES).hex()
    h = _pin_derive(new_pin, salt_hex, PIN_ALGO, PIN_COST)
    ts = now_iso()
    conn = get_conn()
    if prev:
        conn.execute(
            "UPDATE esign_pin SET algo=?, iterations=?, salt=?, hash=?, prev_hash=?, status='active', "
            "updated_ts=?, set_ts=?, fail_count=0, last_fail_ts=NULL, locked_until=NULL, must_change=0, "
            "enrolled_via=?, enrolled_oid=? WHERE emp_id=?",
            (PIN_ALGO, PIN_COST, salt_hex, h, prev.get("hash"), ts, ts, enrolled_via, enrolled_oid, emp_id))
    else:
        conn.execute(
            "INSERT INTO esign_pin (emp_id, algo, iterations, salt, hash, status, created_ts, updated_ts, "
            "set_ts, fail_count, must_change, enrolled_via, enrolled_oid) "
            "VALUES (?,?,?,?,?, 'active', ?,?,?, 0, 0, ?, ?)",
            (emp_id, PIN_ALGO, PIN_COST, salt_hex, h, ts, ts, ts, enrolled_via, enrolled_oid))
    conn.commit()
    conn.close()
    return (True, None)


def verify_pin(emp_id, pin):
    """Constant-time PIN verification with lockout / expiry / revoke gates.
    Returns (ok, reason). reason in {None, no_pin, revoked, must_change, locked, expired, bad_pin}."""
    row = _row("SELECT * FROM esign_pin WHERE emp_id = ?", (emp_id,))
    if not row or not row.get("hash"):
        _pin_derive(pin or "", secrets.token_bytes(PIN_SALT_BYTES).hex())  # burn a derive (timing parity)
        return (False, "no_pin")
    if row.get("status") == "revoked":
        return (False, "revoked")
    if row.get("must_change"):
        return (False, "must_change")
    now = datetime.now(timezone.utc)
    lu = row.get("locked_until")
    if lu:
        d = _pin_parse_iso(lu)
        if d is None or d > now:        # unparseable -> treat as locked (fail closed)
            return (False, "locked")
    st = row.get("set_ts")
    if st:
        d = _pin_parse_iso(st)
        if d is None or (now - d).days > PIN_MAX_AGE_DAYS:   # unparseable -> treat as expired (fail closed)
            return (False, "expired")
    got = _pin_derive(pin or "", row["salt"], row.get("algo") or "pbkdf2_sha256", row.get("iterations"))
    ok = hmac.compare_digest(got, row["hash"])
    conn = get_conn()
    if ok:
        if row.get("algo") != PIN_ALGO or (row.get("iterations") or 0) != PIN_COST:
            ns = secrets.token_bytes(PIN_SALT_BYTES).hex()      # transparently upgrade the stored hash to the current KDF
            nh = _pin_derive(pin, ns, PIN_ALGO, PIN_COST)
            conn.execute("UPDATE esign_pin SET salt=?, hash=?, iterations=?, algo=?, fail_count=0, locked_until=NULL WHERE emp_id=?",
                         (ns, nh, PIN_COST, PIN_ALGO, emp_id))
        else:
            conn.execute("UPDATE esign_pin SET fail_count=0, locked_until=NULL WHERE emp_id=?", (emp_id,))
        conn.commit()
        conn.close()
        return (True, None)
    fc = (row.get("fail_count") or 0) + 1
    locked = fc >= PIN_LOCK_THRESHOLD
    if locked:
        lock_iso = (now + timedelta(seconds=PIN_LOCK_SECONDS)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE esign_pin SET fail_count=0, last_fail_ts=?, locked_until=? WHERE emp_id=?",
                     (now_iso(), lock_iso, emp_id))
    else:
        conn.execute("UPDATE esign_pin SET fail_count=?, last_fail_ts=? WHERE emp_id=?",
                     (fc, now_iso(), emp_id))
    conn.commit()
    conn.close()
    # Audit the unauthorized-use attempt (Part 11 §11.300(d) / §11.10(e)) — never records the PIN.
    try:
        emp = get_employee(emp_id) or {}
        put_collection_item("audit", {"actor": emp.get("name") or "System", "actorId": emp_id,
            "action": "E-signature PIN — " + ("locked" if locked else "failed attempt"),
            "target": "esign_pin/" + str(emp_id),
            "detail": ("locked for %d min after %d consecutive failures" % (PIN_LOCK_SECONDS // 60, PIN_LOCK_THRESHOLD)) if locked else ("consecutive failures=" + str(fc)),
            "ts": now_iso()})
    except Exception:
        pass
    return (False, "locked" if locked else "bad_pin")


def admin_reset_pin(emp_id):
    """Admin de-authorize: wipe the hash and force the owner to re-enroll. Cannot set a PIN value."""
    conn = get_conn()
    conn.execute("UPDATE esign_pin SET hash='', prev_hash=NULL, must_change=1, status='active', "
                 "fail_count=0, locked_until=NULL, updated_ts=? WHERE emp_id=?", (now_iso(), emp_id))
    conn.commit()
    conn.close()


def revoke_pin(emp_id):
    """Admin revoke: mark the credential revoked (owner must re-enroll to sign again)."""
    conn = get_conn()
    conn.execute("UPDATE esign_pin SET status='revoked', updated_ts=? WHERE emp_id=?", (now_iso(), emp_id))
    conn.commit()
    conn.close()


def remove_pin(emp_id):
    """Owner removes their own PIN entirely."""
    conn = get_conn()
    conn.execute("DELETE FROM esign_pin WHERE emp_id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def list_zones():
    return _rows("SELECT * FROM zones ORDER BY id")


def create_zone(data):
    conn = get_conn()
    # active defaults to 1 and dept to 'All' when the caller says nothing, so a zone created by any
    # older client still authorises everybody rather than silently authorising nobody.
    act = data.get("active")
    cur = conn.execute(
        "INSERT INTO zones (name,lat,lon,radius,active,dept,notes) VALUES (?,?,?,?,?,?,?)",
        (data.get("name"), data.get("lat"), data.get("lon"), data.get("radius"),
         0 if act in (0, "0", False, "false") else 1,
         (data.get("dept") or "All"), (data.get("notes") or "")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_zone(zone_id, data):
    sets, params = [], []
    for f in ("name", "lat", "lon", "radius", "active", "dept", "notes"):
        if f in data:
            sets.append("%s = ?" % f); params.append(_scalar(data[f]))
    if not sets:
        return
    params.append(zone_id)
    conn = get_conn()
    conn.execute("UPDATE zones SET %s WHERE id = ?" % ",".join(sets), params)
    conn.commit()
    conn.close()


def delete_zone(zone_id):
    conn = get_conn()
    conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    row = _row("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else default


def get_settings_prefix(prefix):
    """Every setting whose key starts with `prefix`, decoded, in ONE query.

    /api/portal read 35 settings one at a time — 35 SELECTs and 35 connection hand-outs for a 1.5 KB
    response, all of it before the login overlay comes down. They are one table and one prefix, so
    they are one statement.

    `_` and `%` are LIKE WILDCARDS, and the prefix this exists to serve is literally `portal_`.
    Unescaped it also matches `portalXsomething`, which is a quiet correctness bug rather than a
    crash: the caller gets a setting that is not theirs and cannot tell. Hence the ESCAPE clause.

    A row whose value will not decode is SKIPPED rather than raising, so one corrupt setting cannot
    take down every screen that reads its neighbours — the same thing get_setting's callers already
    get from `default`.
    """
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    out = {}
    for r in _rows("SELECT key, value FROM settings WHERE key LIKE ? ESCAPE '\\'", (esc + "%",)):
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            continue
    return out


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Document numbers
# ---------------------------------------------------------------------------

def next_doc_no(series, year, floor_fn=None):
    """Allocate the next number in a series, atomically. Returns the integer.

    BEGIN IMMEDIATE takes the write lock before the read, so two concurrent creates cannot both see
    the same `n` and both claim it. This is the whole point of the function: the arithmetic is
    trivial, the exclusion is not, and doing it in the browser is how the payment-request numbers
    ended up colliding by construction.

    `floor_fn` is called ONLY the first time a (series, year) is allocated, and returns the highest
    number the existing documents already show. That is how a live database is adopted without
    re-issuing a number a supplier or a customer is already holding a PDF of. It is a callable
    rather than a value so the scan does not run on every create for the rest of the year.
    """
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT n FROM doc_counters WHERE series = ? AND year = ?",
                           (series, int(year))).fetchone()
        if row is None:
            floor = 0
            if floor_fn is not None:
                try:
                    floor = int(floor_fn() or 0)
                except Exception:
                    floor = 0          # a bad scan must not block the document; it can only re-use
            nxt = max(0, floor) + 1    # a number, which the duplicate report will then surface
            conn.execute("INSERT INTO doc_counters (series, year, n) VALUES (?,?,?)",
                         (series, int(year), nxt))
        else:
            nxt = int(row["n"]) + 1
            conn.execute("UPDATE doc_counters SET n = ? WHERE series = ? AND year = ?",
                         (nxt, series, int(year)))
        conn.commit()
        return nxt
    finally:
        conn.close()


def peek_doc_no(series, year):
    """The last number issued, without allocating one. For the admin/health view only."""
    row = _row("SELECT n FROM doc_counters WHERE series = ? AND year = ?", (series, int(year)))
    return int(row["n"]) if row else 0


# ── Web Push subscriptions (OS notifications) ──
def push_sub_add(email, sub):
    """Store/refresh a browser's PushSubscription for a user (keyed by its endpoint)."""
    endpoint = (sub or {}).get("endpoint")
    if not endpoint:
        return
    conn = get_conn()
    # On conflict only refresh a row that already belongs to this user — a client cannot
    # re-point another person's (opaque) endpoint to itself.
    conn.execute("INSERT INTO push_subs (endpoint,email,sub,created) VALUES (?,?,?,?) "
                 "ON CONFLICT(endpoint) DO UPDATE SET sub = excluded.sub "
                 "WHERE push_subs.email = excluded.email",
                 (endpoint, (email or "").lower(), json.dumps(sub), now_iso()))
    conn.commit()
    conn.close()


def push_subs_for(emails):
    """Return [(endpoint, sub_dict), …] for the given list of user emails."""
    emails = [(e or "").lower() for e in (emails or []) if e]
    if not emails:
        return []
    ph = ",".join("?" * len(emails))
    rows = _rows("SELECT endpoint, sub FROM push_subs WHERE email IN (%s)" % ph, tuple(emails))
    out = []
    for r in rows:
        try:
            out.append((r["endpoint"], json.loads(r["sub"])))
        except (ValueError, TypeError):
            pass
    return out


def push_sub_remove(endpoint):
    if not endpoint:
        return
    conn = get_conn()
    conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()


def push_subs_count(email):
    row = _row("SELECT COUNT(*) AS n FROM push_subs WHERE email = ?", ((email or "").lower(),))
    return int((row or {}).get("n") or 0)


def push_subs_clear(email):
    """Drop every device subscription a person holds — offboarding. Returns how many went, because
    "we stopped their notifications" and "there was nothing to stop" are different sentences."""
    email = (email or "").lower()
    if not email:
        return 0
    n = push_subs_count(email)
    conn = get_conn()
    conn.execute("DELETE FROM push_subs WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return n


# ── Generic collections store (recruitment, onboarding, performance, etc.) ──
def list_collection(coll):
    rows = _rows("SELECT data FROM collections WHERE coll = ? ORDER BY id", (coll,))
    return [json.loads(r["data"]) for r in rows]


# The unread badge asks "how many messages in this project are newer than my watermark", and the
# watermark comparison in _pm_chat_summary is `str(ts) <= str(watermark)` — TEXT, not numeric. So the
# index has to be on the TEXT of the timestamp, or SQLite would compare by type affinity and the two
# would disagree about a number versus a numeric string.
#
# The CASE reproduces Python's `str(ts or "")` exactly for the values that occur: falsy (absent, null,
# 0, "", false) becomes NULL, which is never greater than anything and so is always skipped — the same
# thing `"" <= anything` does on the Python side. A JSON true becomes 'True', because that is what
# str() would produce. Anything else is its own text.
#
# A ts that is a JSON OBJECT or ARRAY is outside this equivalence — str({...}) is Python repr, not JSON
# text — and is left there deliberately: _coll_add stamps ts = _utc_now_ms() on every message, which
# tests/test_pm_chat_unread_index.py asserts, and the Python filter still runs over whatever this
# returns. The index narrows; it does not decide.
_PM_CHAT_TS = (
    "CASE json_type(data,'$.ts') "
    "WHEN 'null' THEN NULL WHEN 'false' THEN NULL WHEN 'true' THEN 'True' "
    "ELSE CASE WHEN json_extract(data,'$.ts') = 0 OR json_extract(data,'$.ts') = '' THEN NULL "
    "ELSE CAST(json_extract(data,'$.ts') AS TEXT) END END"
)
_PM_CHAT_PID = "json_extract(data,'$.projectId')"
# In the index too, both of them, so the common query never has to open the row. authorId excludes
# your own messages; the mentions LENGTH lets the mention count skip every message that mentions
# nobody, which is nearly all of them — without it SQLite reads and re-parses each candidate to run
# json_each over an empty array.
_PM_CHAT_AUTHOR = "IFNULL(json_extract(data,'$.authorId'),'')"
_PM_CHAT_MLEN = "IFNULL(json_array_length(data,'$.mentions'),0)"


def pm_chat_project_ids():
    """Every project id that has a chat message, off the index.

    INDEXED BY, not left to the planner: without ANALYZE it picks the primary key and scans every row
    (14.6 ms at 25,000 messages against 0.99 ms), and nothing in this deployment runs ANALYZE.
    """
    try:
        rows = _rows("SELECT DISTINCT %s AS pid FROM collections INDEXED BY idx_pm_chat_unread "
                     "WHERE coll = 'pm_chat'" % _PM_CHAT_PID)
        return [r["pid"] for r in rows]
    except Exception:
        return None                      # no index (or no JSON1): the caller falls back to a scan


def pm_chat_unread(pid, watermark, exclude_author, me):
    """(unread, mentioning-me) for ONE project, both counted inside SQLite.

    Counted, not listed. Returning the rows was the first version and it was barely faster than the
    scan it replaced: a project nobody has opened has EVERY message unread, so "the tail" was most of
    the collection — 18,750 rows of 25,000 in the benchmark. The badge only ever needed two numbers.

    This IS the filter, not a shortlist for one — re-checking the same expression in Python would
    only re-run the thing being trusted, so the equivalence is proved by differential test against
    the old loop instead (tests/test_pm_chat_unread_index.py) over ISO, absent, null, 0, "", false,
    integer, float and text timestamps.

    `watermark` must be the TEXT the Python side used — str(read.get(pid) or "") — and never None:
    `ts > NULL` is NULL, so a project with no watermark would report zero unread instead of all of
    it, which is the exact way this endpoint was never allowed to fail.

    The mentions test is guarded on json_type being an array, because json_each raises on anything
    else and a malformed row must not take the whole badge down with it.
    """
    wm = str(watermark or "")
    n = _row("SELECT COUNT(*) AS n FROM collections INDEXED BY idx_pm_chat_unread "
             "WHERE coll = 'pm_chat' AND %s = ? AND %s > ? AND %s <> ?"
             % (_PM_CHAT_PID, _PM_CHAT_TS, _PM_CHAT_AUTHOR),
             (pid, wm, exclude_author))["n"] or 0
    if not n:
        return 0, 0
    # Only the messages that mention SOMEBODY are opened, and only then to ask whether it was you.
    m = _row("SELECT COUNT(*) AS m FROM collections INDEXED BY idx_pm_chat_unread "
             "WHERE coll = 'pm_chat' AND %s = ? AND %s > ? AND %s <> ? AND %s > 0 "
             "AND EXISTS (SELECT 1 FROM json_each(data,'$.mentions') AS je "
             "            WHERE json_extract(je.value,'$.empId') = ?)"
             % (_PM_CHAT_PID, _PM_CHAT_TS, _PM_CHAT_AUTHOR, _PM_CHAT_MLEN),
             (pid, wm, exclude_author, me))["m"] or 0
    return n, m


def collection_fields(coll, paths):
    """A few top-level scalars from every row of a collection, without parsing the rows.

    list_collection json.loads the WHOLE record, and a chat message carries its text — so counting
    unread badges by loading every message spends nearly all of its time parsing bodies nobody looks
    at. Measured on 10,000 pm_chat rows: 35.7 ms to parse them all against a few ms to pull three
    scalars out in SQLite.

    `paths` are top-level field names. Returns one tuple per row, in `id` order, values in the order
    asked for, None where the field is absent.

    FALLS BACK to the full parse if SQLite has no JSON1. This host has it (3.54), but production runs
    a different Python in a container and nothing here can see which, and a badge count is not worth
    a 500 — so a host without it is slower and never wrong.
    """
    sel = ", ".join("json_extract(data, ?) AS f%d" % i for i in range(len(paths)))
    try:
        rows = _rows("SELECT " + sel + " FROM collections WHERE coll = ? ORDER BY id",
                     tuple("$." + p for p in paths) + (coll,))
        return [tuple(r["f%d" % i] for i in range(len(paths))) for r in rows]
    except Exception:
        return [tuple(it.get(p) for p in paths) for it in list_collection(coll)]


def get_collection_item(coll, item_id):
    """Fetch ONE item by id via the (coll,id) primary key — an indexed lookup, instead of loading and
    json.loads-ing the WHOLE collection just to find one row (the hot single-record path on every
    claim/payment/device edit). Returns the item dict or None. Mirrors list_collection's shape."""
    row = _row("SELECT data FROM collections WHERE coll = ? AND id = ?", (coll, item_id))
    return json.loads(row["data"]) if row else None


def collection_count(coll):
    row = _row("SELECT COUNT(*) AS n FROM collections WHERE coll = ?", (coll,))
    return row["n"] if row else 0


def _coll_write_txn(conn, coll, item, expect_rev=None):
    """Read-check-write for one collection row, INSIDE an already-open IMMEDIATE transaction.

    Returns the written item, or None when `expect_rev` was given and the stored rev has moved (the
    compare-and-swap lost). The caller owns the transaction: commit on a non-None return, roll back
    otherwise."""
    prev = conn.execute("SELECT data FROM collections WHERE coll = ? AND id = ?",
                        (coll, item["id"])).fetchone()
    cur_rev = 0
    if prev:
        try:
            cur_rev = int((json.loads(prev["data"]) or {}).get("_rev") or 0)
        except (ValueError, TypeError):
            cur_rev = 0
    if expect_rev is not None and cur_rev != int(expect_rev or 0):
        return None
    item["_rev"] = cur_rev + 1
    conn.execute("INSERT INTO collections (coll,id,data) VALUES (?,?,?) "
                 "ON CONFLICT(coll,id) DO UPDATE SET data = excluded.data",
                 (coll, item["id"], json.dumps(item)))
    return item


def _coll_write(coll, item, expect_rev=None):
    """Open an IMMEDIATE transaction and run _coll_write_txn in it.

    IMMEDIATE (not the default deferred) takes the write lock BEFORE the read, so the rev this write
    is based on cannot change underneath it. isolation_level=None hands transaction control to us
    rather than to the sqlite3 module's implicit BEGIN-before-DML, which would start its transaction
    only at the INSERT — after the read, which is exactly the window we are closing. busy_timeout is
    already 5s, so a contended write waits its turn instead of raising."""
    conn = get_conn()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            out = _coll_write_txn(conn, coll, item, expect_rev)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT" if out is not None else "ROLLBACK")
        return out
    finally:
        conn.close()


def put_collection_item(coll, item):
    """Insert or update one item (a dict). Generates an id if missing. Returns the item.

    Maintains a server-owned optimistic-concurrency counter `_rev`: every write monotonically bumps
    the STORED rev (new rows start at 1), ignoring whatever `_rev` the client sent — the client value
    is only ever a PRECONDITION checked in the API layer (If-Match), never the source of truth. This
    is how the blind full-document PATCH stops silently clobbering a concurrent edit: the record's rev
    moves on each save, so a second writer holding a stale rev is detected.

    That promise of "monotonically" used to be false. The rev was read in one statement and written in
    another with no transaction around them, so two concurrent writers both read rev N and both wrote
    N+1 — twelve concurrent writes landed on rev 8, not 13. A counter that repeats is not a version,
    and every If-Match check in the API rests on it. The write is now atomic.
    """
    if not item.get("id"):
        item["id"] = coll[:3] + "-" + uuid.uuid4().hex[:8]
    if coll == "audit":
        return _put_audit_chained(item)          # append-only + tamper-evident hash chain
    return _coll_write(coll, item)


def put_collection_item_if_rev(coll, item, expect_rev):
    """Compare-and-swap: write ONLY if the stored `_rev` is still `expect_rev`. Returns the written
    item, or None if the row moved and the caller must re-read and re-apply.

    This is the honest version of read-modify-write on a shared row. A Python-level "get the rev, check
    it, then call put_collection_item" has the same race it claims to fix — the check and the write are
    two transactions, and anything can land between them. Here the comparison happens inside the same
    IMMEDIATE transaction as the write, so nothing can.

    Not for `audit`: that collection is an append-only hash chain with its own writer."""
    if coll == "audit":
        raise ValueError("audit is append-only — use put_collection_item")
    if not item.get("id"):
        raise ValueError("compare-and-swap needs an existing id")
    return _coll_write(coll, item, expect_rev=expect_rev)


def _audit_link_hash(prev_hash, item):
    """One link's HMAC: keyed over the previous link's hash + the canonical (deterministic) JSON of this
    row, EXCLUDING its own `hash` field. Sorting keys makes it order-independent of dict insertion; the
    compact separators make it byte-stable. Binds id, seq, prevHash and all content into the digest."""
    canonical = json.dumps({k: v for k, v in item.items() if k != "hash"}, sort_keys=True, separators=(",", ":"))
    return hmac.new(AUDIT_KEY, ((prev_hash or "") + "|" + canonical).encode("utf-8"), hashlib.sha256).hexdigest()


def _audit_head_mac(seq, head_hash):
    """Authenticate the checkpoint itself. Without this, an attacker with DB write access could delete
    the newest rows and rewind the singleton to an earlier (seq, head_hash) — both values they can read
    in the clear — and verification would pass. Keying (seq | head_hash) means they cannot mint a valid
    checkpoint for a truncated prefix (or a wiped/genesis chain) without TK_AUDIT_PEPPER."""
    return hmac.new(AUDIT_KEY, ("%d|%s" % (seq, head_hash or "")).encode("utf-8"), hashlib.sha256).hexdigest()


def _audit_key_fp():
    """A non-secret fingerprint of the current key, so verify can tell 'the chain was sealed with a
    DIFFERENT TK_AUDIT_PEPPER' (→ reseal) apart from 'content was tampered'. Constant for a given key."""
    return hmac.new(AUDIT_KEY, b"audit-chain-key-fingerprint-v1", hashlib.sha256).hexdigest()[:16]


def _mint_audit_id(conn):
    """A fresh, unused audit id. 64 bits + a uniqueness check so a birthday collision can never silently
    drop an event via the id-already-exists path (audit ids are always server-minted, never client-set)."""
    for _ in range(12):
        cand = "aud-" + uuid.uuid4().hex[:16]
        if not conn.execute("SELECT 1 FROM collections WHERE coll='audit' AND id=?", (cand,)).fetchone():
            return cand
    raise RuntimeError("could not mint a unique audit id")   # 12 collisions is astronomically impossible


def _put_audit_chained(item):
    """Append one audit row as the next link in the hash chain. Under a lock so a concurrent writer can't
    read the same head and fork the chain. The row id is always freshly minted here (with a collision
    check), so an event is never silently dropped by an id clash; the append-only INSERT never rewrites
    an existing link. The checkpoint stores an authenticated head MAC + the sealing key's fingerprint."""
    with _AUDIT_LOCK:
        conn = get_conn()
        try:
            item["id"] = _mint_audit_id(conn)
            head = conn.execute("SELECT seq, head_hash FROM audit_chain WHERE id=1").fetchone()
            seq0, prev_hash = (head["seq"], head["head_hash"]) if head else (0, "")
            item["_rev"] = 1
            item["seq"] = seq0 + 1
            item["prevHash"] = prev_hash or ""
            item["hash"] = _audit_link_hash(item["prevHash"], item)
            conn.execute("INSERT INTO collections (coll,id,data) VALUES ('audit',?,?)",
                         (item["id"], json.dumps(item)))
            conn.execute("INSERT INTO audit_chain (id, seq, head_hash, head_mac, key_fp) VALUES (1, ?, ?, ?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET seq=excluded.seq, head_hash=excluded.head_hash, "
                         "head_mac=excluded.head_mac, key_fp=excluded.key_fp",
                         (item["seq"], item["hash"], _audit_head_mac(item["seq"], item["hash"]), _audit_key_fp()))
            conn.commit()
            return item
        finally:
            conn.close()


def reseal_audit_chain():
    """Re-seal the entire audit chain under the CURRENT TK_AUDIT_PEPPER: re-walk every row in seq order,
    recompute prevHash/hash and the checkpoint, and rewrite them. This is the deliberate recovery path
    for setting the pepper for the first time or rotating it (which otherwise makes verify report every
    pre-existing link as 'altered'). It re-hashes existing content as-is; it cannot un-tamper history."""
    with _AUDIT_LOCK:
        conn = get_conn()
        try:
            rows = [json.loads(r["data"]) for r in conn.execute(
                "SELECT data FROM collections WHERE coll='audit'").fetchall()]
            rows = [r for r in rows if isinstance(r.get("seq"), int)]
            rows.sort(key=lambda r: r["seq"])
            prev, seq = "", 0
            for r in rows:
                seq += 1
                r["seq"] = seq
                r["prevHash"] = prev
                r["hash"] = _audit_link_hash(prev, r)
                conn.execute("UPDATE collections SET data=? WHERE coll='audit' AND id=?",
                             (json.dumps(r), r["id"]))
                prev = r["hash"]
            conn.execute("INSERT INTO audit_chain (id, seq, head_hash, head_mac, key_fp) VALUES (1, ?, ?, ?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET seq=excluded.seq, head_hash=excluded.head_hash, "
                         "head_mac=excluded.head_mac, key_fp=excluded.key_fp",
                         (seq, prev, _audit_head_mac(seq, prev), _audit_key_fp()))
            conn.commit()
            return {"resealed": seq, "keyed": bool(AUDIT_KEY)}
        finally:
            conn.close()


def verify_audit_chain():
    """Recompute the audit hash chain from genesis and report the first break. Detects: edited content
    (hash mismatch), reordering / a deleted middle row (seq gap or prevHash mismatch), a row inserted
    out-of-band with no link (unchained), and — via the AUTHENTICATED head checkpoint (head_mac) —
    deletion/truncation of the newest rows or a wipe-to-genesis, which a keyless attacker cannot forge.
    A changed sealing key is reported distinctly (keyChanged → reseal) rather than as tampering.

    Residual limit (documented, needs an off-box anchor to close): an attacker who holds TK_AUDIT_PEPPER,
    or who can delete BOTH all rows AND the checkpoint singleton (letting init_db re-genesis a fresh empty
    chain), is not detected here — a co-located checkpoint cannot outrank an attacker who owns the file.
    Returns {ok, count, brokenAtSeq, reason, ...}."""
    with _AUDIT_LOCK:   # read rows + checkpoint under the same lock the writer holds → one consistent pair
        conn = get_conn()
        try:
            rows = [json.loads(r["data"]) for r in conn.execute("SELECT data FROM collections WHERE coll='audit'").fetchall()]
            head = conn.execute("SELECT seq, head_hash, head_mac, key_fp FROM audit_chain WHERE id=1").fetchone()
        finally:
            conn.close()
    # A different sealing key is an operational event (set/rotated pepper), not tampering — say so clearly.
    if head is not None and head["key_fp"] and head["key_fp"] != _audit_key_fp():
        return {"ok": False, "keyChanged": True, "count": None, "brokenAtSeq": None, "keyed": bool(AUDIT_KEY),
                "reason": "the audit chain was sealed with a different TK_AUDIT_PEPPER — reseal required (or restore the original key)"}
    chained = [r for r in rows if type(r.get("seq")) is int and r.get("hash")]   # bool is an int subclass — exclude it
    unchained = len(rows) - len(chained)
    chained.sort(key=lambda r: r["seq"])
    prev = ""
    for i, r in enumerate(chained):
        want = i + 1
        if r["seq"] != want:
            return {"ok": False, "count": len(chained), "brokenAtSeq": r["seq"],
                    "reason": "sequence gap or reordering near #%d (found seq %s) — a row may have been deleted or moved" % (want, r["seq"])}
        if (r.get("prevHash") or "") != prev:
            return {"ok": False, "count": len(chained), "brokenAtSeq": r["seq"],
                    "reason": "prevHash mismatch at #%d — the chain link was broken" % r["seq"]}
        if _audit_link_hash(prev, r) != r["hash"]:
            return {"ok": False, "count": len(chained), "brokenAtSeq": r["seq"],
                    "reason": "content was altered at #%d — recomputed hash does not match" % r["seq"]}
        prev = r["hash"]
    exp_seq = head["seq"] if head else 0
    exp_head = (head["head_hash"] if head else "") or ""
    if len(chained) != exp_seq or prev != exp_head:
        return {"ok": False, "count": len(chained), "brokenAtSeq": exp_seq,
                "reason": "chain head mismatch — %d entries present but the checkpoint records %d (newest rows may have been deleted)" % (len(chained), exp_seq)}
    # The checkpoint MAC must recompute — this is what makes a tail-truncation-plus-rewind (or a
    # wipe-to-genesis) detectable, since a keyless attacker cannot mint a valid MAC for the shorter head.
    # On a keyed chain the MAC is REQUIRED (a missing head_mac would otherwise be a bypass — an attacker
    # could NULL it to skip this check); on an unkeyed chain it carries no security value, so skip it.
    if head is not None and AUDIT_KEY:
        exp_mac = head["head_mac"]
        if not exp_mac or exp_mac != _audit_head_mac(exp_seq, exp_head):
            return {"ok": False, "count": len(chained), "brokenAtSeq": exp_seq,
                    "reason": "checkpoint authentication failed — the chain head was rewritten (truncation/rollback)"}
    if unchained:
        return {"ok": False, "count": len(chained), "brokenAtSeq": None,
                "reason": "%d audit row(s) are not part of the hash chain (inserted out-of-band?)" % unchained}
    return {"ok": True, "count": len(chained), "unchained": 0, "headHash": prev, "brokenAtSeq": None,
            "keyed": bool(AUDIT_KEY)}


def delete_collection_item(coll, item_id):
    conn = get_conn()
    conn.execute("DELETE FROM collections WHERE coll = ? AND id = ?", (coll, item_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# The general ledger
# ---------------------------------------------------------------------------
#
# gl.py owns the arithmetic; this owns the two rules that only a database can enforce, because both
# are about what ALREADY happened and neither can be checked by looking at the batch alone:
#
#   · the period is closed  — a check in application code races another request
#   · this document already posted — likewise, and the consequence is a doubled month
#
# Both are enforced inside one BEGIN IMMEDIATE, so two concurrent posts of the same pay run cannot
# both read "not yet posted" and both insert.

GL_PERIODS = "gl_periods"       # the close register — a signed document, so it lives in collections


def gl_closed_periods():
    """Every period that has been closed, newest first. Read from the collection register, which is
    where the closing signature and the person who applied it live."""
    out = {}
    for p in list_collection(GL_PERIODS):
        key = str(p.get("period") or "").strip()
        if key and str(p.get("status") or "").lower() == "closed":
            out[key] = p
    return out


def gl_is_closed(period):
    return str(period or "").strip() in gl_closed_periods()


def gl_post(batch, posted_by="", posted_by_id="", reverses=None):
    """Write one balanced batch, whole, or write nothing.

    `batch` is the output of `gl.batch()` — already normalised, already balanced, already refused if
    it was not. What is added here is exclusion and the two prior-state rules above.

    Returns the stored batch id. Raises ValueError with a sentence that names what to do instead:
    every one of these reaches somebody in the middle of closing a month, and "constraint failed"
    tells them nothing.
    """
    import gl as _gl                      # local: db.py must stay importable by tools that lack gl

    period = str(batch.get("period") or "").strip()
    if not _gl.period_valid(period):
        raise ValueError("'%s' is not a period." % period)

    bid = "GL-%s-%s" % (period.replace("-", ""), uuid.uuid4().hex[:10])
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")

        if gl_is_closed(period):
            raise ValueError(
                "%s is closed, so nothing further can be posted into it. This entry belongs to that "
                "month — it has not been moved into an open one, because that would misstate both. "
                "Re-open %s if it genuinely has to change." % (period, period))

        dup = conn.execute(
            "SELECT id, posted_at, posted_by FROM gl_batches WHERE source=? AND source_id=? AND kind=?",
            (batch["source"], batch["sourceId"], batch["kind"])).fetchone()
        if dup is not None:
            raise ValueError(
                "%s %s has already been posted (%s, by %s, batch %s). Posting it again would double "
                "every figure in it — and both sides would double, so the ledger would still balance "
                "and no report would say so. Reverse that batch if it was wrong."
                % (_gl.SOURCES.get(batch["source"], batch["source"]), batch["sourceId"],
                   str(dup["posted_at"])[:16].replace("T", " "), dup["posted_by"] or "?", dup["id"]))

        conn.execute(
            "INSERT INTO gl_batches (id, source, source_id, kind, period, doc_date, memo, posted_at,"
            " posted_by, posted_by_id, reverses, debit, credit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bid, batch["source"], batch["sourceId"], batch["kind"], period, batch.get("date") or "",
             batch.get("memo") or "", now_iso(), posted_by, posted_by_id, reverses,
             float(batch["debit"]), float(batch["credit"])))
        for i, ln in enumerate(batch["lines"], start=1):
            conn.execute(
                "INSERT INTO gl_entries (batch, seq, period, account, name, debit, credit, memo)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (bid, i, period, ln["account"], ln.get("name") or "",
                 float(ln.get("debit") or 0), float(ln.get("credit") or 0), ln.get("memo") or ""))
        conn.commit()
        return bid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def gl_batch(batch_id):
    row = _row("SELECT * FROM gl_batches WHERE id = ?", (batch_id,))
    if not row:
        return None
    out = dict(row)
    out["lines"] = [dict(r) for r in _rows(
        "SELECT seq, account, name, debit, credit, memo FROM gl_entries WHERE batch = ? ORDER BY seq",
        (batch_id,))]
    return out


def gl_batches(period=None, source=None, source_id=None, limit=500):
    sql = "SELECT * FROM gl_batches WHERE 1=1"
    args = []
    if period:
        sql += " AND period = ?"; args.append(str(period))
    if source:
        sql += " AND source = ?"; args.append(str(source))
    if source_id:
        sql += " AND source_id = ?"; args.append(str(source_id))
    sql += " ORDER BY posted_at DESC, id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in _rows(sql, tuple(args))]


def gl_rows(period=None, account=None, upto=None):
    """Ledger entries for a trial balance or an account enquiry.

    `upto` gives CUMULATIVE movement to the end of a period — what a balance sheet needs, since a
    liability is what is owed in total and not what moved this month.
    """
    sql = ("SELECT e.account, e.name, e.debit, e.credit, e.period, e.memo, e.seq,"
           " b.id AS batch, b.source, b.source_id, b.doc_date, b.kind, b.posted_at, b.posted_by"
           " FROM gl_entries e JOIN gl_batches b ON b.id = e.batch WHERE 1=1")
    args = []
    if period:
        sql += " AND e.period = ?"; args.append(str(period))
    if upto:
        sql += " AND e.period <= ?"; args.append(str(upto))
    if account:
        sql += " AND e.account = ?"; args.append(str(account))
    sql += " ORDER BY e.period, b.posted_at, e.seq"
    return [dict(r) for r in _rows(sql, tuple(args))]


def gl_periods_seen():
    """Every period that has ledger movement, oldest first."""
    return [r["period"] for r in _rows(
        "SELECT DISTINCT period FROM gl_entries ORDER BY period")]
