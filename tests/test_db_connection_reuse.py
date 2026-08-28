"""The connection is reused, and a reused one is indistinguishable from a fresh one.

Opening a SQLite connection costs 1-2 ms against 0.04 ms for the query inside it, so `get_conn()`
now keeps one per thread and `close()` hands it back instead of closing it. That is a change to the
single thing every other test in this suite sits on top of, and it is only safe if a handed-back
connection behaves exactly like a newly opened one.

Each test here is one way that could stop being true. They are deliberately about SEMANTICS, not
speed: a timing test would pass on the old code too on a fast enough machine, and would not notice
any of the four hazards below.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest      # noqa: E402

import db          # noqa: E402
import gl          # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _database():
    db.init_db()


# ── it is actually reused ───────────────────────────────────────────────────────────────────────

def test_two_calls_on_one_thread_get_the_same_connection():
    """The whole point. If this fails the change has achieved nothing."""
    a = db.get_conn()
    a.close()
    b = db.get_conn()
    b.close()
    assert a is b


def test_closing_it_does_not_actually_close_it():
    c = db.get_conn()
    c.close()
    # A really-closed connection raises ProgrammingError on use.
    assert c.execute("SELECT 1").fetchone()[0] == 1
    c.close()


def test_a_second_thread_gets_its_own_connection():
    """sqlite3 forbids using a connection from another thread, so sharing one would break the
    server outright — every request is its own thread."""
    seen = {}

    def grab(key):
        c = db.get_conn()
        seen[key] = c
        c.close()

    mine = db.get_conn()
    mine.close()
    t = threading.Thread(target=grab, args=("other",))
    t.start()
    t.join()
    assert seen["other"] is not mine


# ── a reused connection is indistinguishable from a fresh one ───────────────────────────────────

def test_uncommitted_work_is_rolled_back_on_release():
    """Closing a connection has always discarded uncommitted work. Handing it back must too —
    otherwise a half-finished write leaks into whatever the thread does next."""
    c = db.get_conn()
    c.execute("CREATE TABLE IF NOT EXISTS _reuse_probe (v TEXT)")
    c.commit()
    c.execute("DELETE FROM _reuse_probe")
    c.commit()
    c.close()

    c = db.get_conn()
    c.execute("INSERT INTO _reuse_probe (v) VALUES ('uncommitted')")
    assert c.in_transaction
    c.close()                      # the release: should roll back, as a real close would

    c2 = db.get_conn()
    assert not c2.in_transaction, "a transaction survived the release"
    rows = c2.execute("SELECT v FROM _reuse_probe").fetchall()
    c2.close()
    assert rows == [], "uncommitted work survived the release"


def test_isolation_level_is_restored_on_release():
    """_coll_write sets isolation_level = None and never puts it back. That was free when the
    connection was discarded; on a reused one it would silently strip the implicit transaction from
    every later write on this thread."""
    c = db.get_conn()
    c.isolation_level = None
    c.close()
    c2 = db.get_conn()
    lvl = c2.isolation_level
    c2.close()
    assert lvl == "", "isolation_level leaked out of a released connection (was %r)" % (lvl,)


def test_a_nested_close_does_not_end_the_outer_transaction():
    """THE one that would have broken document numbering. next_doc_no holds BEGIN IMMEDIATE and
    calls a floor_fn that does a full list_collection — a get_conn/close pair inside the open
    transaction. If the inner close released, the allocation would be rolled back."""
    outer = db.get_conn()
    outer.execute("CREATE TABLE IF NOT EXISTS _reuse_nested (v TEXT)")
    outer.commit()
    outer.execute("DELETE FROM _reuse_nested")
    outer.commit()
    outer.close()

    outer = db.get_conn()
    outer.isolation_level = None
    outer.execute("BEGIN IMMEDIATE")
    outer.execute("INSERT INTO _reuse_nested (v) VALUES ('outer')")

    inner = db.get_conn()                     # what floor_fn's list_collection does
    inner.execute("SELECT 1").fetchone()
    inner.close()                             # must NOT roll the outer transaction back

    assert outer.in_transaction, "the inner close ended the outer transaction"
    outer.execute("COMMIT")
    outer.isolation_level = ""
    outer.close()

    c = db.get_conn()
    rows = c.execute("SELECT v FROM _reuse_nested").fetchall()
    c.close()
    assert [r[0] for r in rows] == ["outer"], "the committed outer write was lost"


def test_the_real_document_numbering_path_keeps_its_transaction_open():
    """The same hazard through the actual code rather than a reconstruction of it: next_doc_no's
    floor_fn reads a whole collection from inside its open BEGIN IMMEDIATE.

    This asserts the transaction is STILL OPEN when the nested read returns, not merely that the
    right number came out. Those are different claims, and only the first one is about nesting: with
    the transaction rolled out from under it the allocation still yields 41 single-threaded, because
    the INSERT simply commits on its own. What is lost is atomicity — two concurrent allocations
    would both read the same counter — and a test that only checked the number was blind to it.
    Verified by mutation: removing the depth guard leaves the number correct and fails this.
    """
    year = 2031
    still_open = []

    def floor_fn():
        db.list_collection("sales_quotes")     # a real nested get_conn/close
        c = db.get_conn()
        still_open.append(c.in_transaction)
        c.close()
        return 40

    a = db.next_doc_no("ZZTEST", year, floor_fn)
    b = db.next_doc_no("ZZTEST", year, floor_fn)
    assert still_open, "floor_fn was never called, so this proved nothing about nesting"
    assert all(still_open), "the nested read rolled back next_doc_no's own transaction"
    assert (a, b) == (41, 42), "numbering did not survive the nested read: got %r, %r" % (a, b)


def test_the_ledger_post_keeps_its_transaction_through_its_nested_read():
    """The same nesting, on the path where getting it wrong costs money rather than a number.

    gl_post opens BEGIN IMMEDIATE and then calls gl_is_closed(period), which reads the period
    register through list_collection — a get_conn/close inside the open transaction. If that inner
    close released, the ledger batch would be written outside the exclusion it just checked.
    """
    seen = []
    real = db.gl_closed_periods

    def spy():
        out = real()                               # the nested whole-collection read
        c = db.get_conn()
        seen.append(c.in_transaction)
        c.close()
        return out

    batch = gl.batch(
        source=sorted(gl.SOURCES)[0],
        source_id="reuse-probe-" + uuid.uuid4().hex[:8],
        date="2031-01-15",
        lines=[{"account": "1111", "debit": 100.0, "credit": 0.0, "memo": "dr"},
               {"account": "3311", "debit": 0.0, "credit": 100.0, "memo": "cr"}],
        memo="connection reuse probe", actor="Admin User")

    db.gl_closed_periods = spy
    try:
        db.gl_post(batch, posted_by="Admin User", posted_by_id="HML-ADM")
    finally:
        db.gl_closed_periods = real

    assert seen, "gl_is_closed never reached the register, so this proved nothing about nesting"
    assert all(seen), "the nested read rolled back gl_post's own transaction"


# ── the leak backstop ───────────────────────────────────────────────────────────────────────────

def test_an_unbalanced_get_conn_is_cleaned_up_at_the_request_boundary():
    """The depth count is only as good as the balance of 40-odd call sites, and one function that
    takes a connection down an exception path without closing it would pin the depth above zero for
    the life of the thread. app.py calls end_thread_conn() in the finally of every request."""
    db.get_conn()                              # taken and never given back — the leak
    db.get_conn()
    db.end_thread_conn()

    c = db.get_conn()
    c.execute("CREATE TABLE IF NOT EXISTS _reuse_leak (v TEXT)")
    c.commit()
    c.execute("INSERT INTO _reuse_leak (v) VALUES ('x')")
    c.close()                                  # depth is back to a sane 0, so this must roll back
    c2 = db.get_conn()
    rows = c2.execute("SELECT v FROM _reuse_leak").fetchall()
    c2.close()
    assert rows == [], "the depth never recovered, so the release stopped rolling back"


def test_the_backstop_rolls_back_work_left_open_by_the_leak():
    c = db.get_conn()
    c.execute("CREATE TABLE IF NOT EXISTS _reuse_leak2 (v TEXT)")
    c.commit()
    c.close()

    leaked = db.get_conn()
    leaked.execute("INSERT INTO _reuse_leak2 (v) VALUES ('never committed')")
    db.end_thread_conn()                       # the request ended without anybody closing it

    c = db.get_conn()
    rows = c.execute("SELECT v FROM _reuse_leak2").fetchall()
    c.close()
    assert rows == [], "a leaked open transaction survived the end of the request"


def test_one_thread_serving_two_requests_does_not_leak_between_them():
    """The scope is a thread, not a request, and on a kept-alive socket those differ.

    BaseHTTPRequestHandler speaks HTTP/1.0 here but still honours `Connection: keep-alive`, so one
    thread can serve several requests in turn without ending. Request N+1 must inherit nothing from
    request N — which is why app.py releases in the finally of every request rather than leaving it
    to the thread dying.
    """
    c = db.get_conn()
    c.execute("CREATE TABLE IF NOT EXISTS _reuse_keepalive (v TEXT)")
    c.commit()
    c.close()

    def request_that_misbehaves():
        conn = db.get_conn()                       # taken, never given back
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO _reuse_keepalive (v) VALUES ('request one')")
        db.end_thread_conn()                       # what _serve_request's finally does

    def request_that_follows():
        conn = db.get_conn()
        state = (conn.in_transaction, conn.isolation_level)
        rows = conn.execute("SELECT v FROM _reuse_keepalive").fetchall()
        conn.close()
        return state, rows

    out = {}

    def one_thread():
        request_that_misbehaves()
        out["second"] = request_that_follows()

    t = threading.Thread(target=one_thread)         # both requests on the SAME thread
    t.start()
    t.join()

    (in_txn, iso), rows = out["second"]
    assert not in_txn, "the second request inherited an open transaction from the first"
    assert iso == "", "the second request inherited isolation_level=%r from the first" % (iso,)
    assert rows == [], "the first request's uncommitted write was visible to the second"


def test_the_backstop_is_safe_when_nothing_is_open():
    db.end_thread_conn()
    db.end_thread_conn()
    c = db.get_conn()
    assert c.execute("SELECT 1").fetchone()[0] == 1
    c.close()


# ── the database can move ───────────────────────────────────────────────────────────────────────

def test_pointing_db_path_somewhere_else_gives_a_new_connection():
    """Several tests reassign db.DB_PATH to a scratch file and back. A cached connection to the
    previous file would answer confidently from the wrong database."""
    saved = db.DB_PATH
    first = db.get_conn()
    first.close()
    try:
        db.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="tk-reuse-"), "other.db")
        other = db.get_conn()
        other.execute("CREATE TABLE probe (v TEXT)")
        other.commit()
        other.close()
        assert other is not first
    finally:
        db.DB_PATH = saved
    back = db.get_conn()
    back.close()
    # And back on the original database, the scratch table does not exist.
    with pytest.raises(sqlite3.OperationalError):
        back.execute("SELECT v FROM probe").fetchall()
