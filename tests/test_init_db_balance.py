"""init_db() must hand its connection back, on every path.

Since connection reuse landed, `close()` does not close — it returns the connection to the thread
and decrements a depth count. A function that takes one and never gives it back pins the thread
above depth 0 for the rest of its life: no rollback of uncommitted work and no isolation_level
restore, for every later caller on that thread.

`init_db` runs on the MAIN thread, which never passes through `_serve_request` and so never reaches
the `end_thread_conn()` backstop. Nothing would ever clean up a leak here.

The path that leaked: the `TK_AUDIT_RESEAL=1` branch released inside its `try`, so a `commit()` that
raised jumped to the except and took a second connection without giving the first one back.

These assert on the DEPTH, not on any observable behaviour, because at depth 1 nothing is visibly
wrong yet — the damage is to every future caller on the thread. That is exactly the kind of latent
state a test has to name directly.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest   # noqa: E402

import db       # noqa: E402


def _depth():
    return db._local.__dict__.get("depth", 0)


class _ScratchDb:
    """Point db at a throwaway file, and put everything back afterwards.

    DB_PATH is reassigned rather than the env var, because db read the env once at import — the same
    approach tests/test_migration.py uses.
    """

    def __init__(self, reseal=False):
        self.reseal = reseal

    def __enter__(self):
        self.saved_path = db.DB_PATH
        self.saved_reseal = os.environ.get("TK_AUDIT_RESEAL")
        db.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="tk-initbal-"), "b.db")
        if self.reseal:
            os.environ["TK_AUDIT_RESEAL"] = "1"
        else:
            os.environ.pop("TK_AUDIT_RESEAL", None)
        return self

    def __exit__(self, *exc):
        db.DB_PATH = self.saved_path
        if self.saved_reseal is None:
            os.environ.pop("TK_AUDIT_RESEAL", None)
        else:
            os.environ["TK_AUDIT_RESEAL"] = self.saved_reseal
        # The scratch database's connection is cached on this thread; drop it so the rest of the
        # suite does not keep talking to a deleted file.
        db.end_thread_conn()
        c = db._local.__dict__.get("conn")
        if c is not None:
            db._drop(c)
        return False


@pytest.fixture(autouse=True)
def _start_clean():
    """Whatever ran before, begin at depth 0 — otherwise this measures the previous test."""
    db.end_thread_conn()
    assert _depth() == 0
    yield
    db.end_thread_conn()


def test_init_db_gives_its_connection_back():
    with _ScratchDb():
        db.init_db()
        assert _depth() == 0, "init_db left the thread's connection held at depth %d" % _depth()


def test_init_db_gives_it_back_on_the_reseal_path_too():
    with _ScratchDb(reseal=True):
        db.init_db()
        assert _depth() == 0, "the TK_AUDIT_RESEAL branch leaked depth %d" % _depth()


def test_a_reseal_that_raises_still_gives_the_connection_back(monkeypatch):
    """A failed reseal must not abort startup — and must not cost the release either."""
    def boom():
        raise RuntimeError("reseal exploded")

    monkeypatch.setattr(db, "reseal_audit_chain", boom)
    with _ScratchDb(reseal=True):
        db.init_db()
        assert _depth() == 0, "a failing reseal leaked depth %d" % _depth()


def test_a_commit_that_raises_still_gives_the_connection_back(monkeypatch):
    """THE path that leaked. The old code released inside the try, so a raising commit skipped the
    release and then opened a second connection."""
    real_commit = db._ReusableConn.commit
    state = {"first": True}

    def flaky_commit(self):
        if state["first"]:
            state["first"] = False
            raise db.sqlite3.OperationalError("commit exploded")
        return real_commit(self)

    monkeypatch.setattr(db._ReusableConn, "commit", flaky_commit)
    with _ScratchDb(reseal=True):
        db.init_db()
        assert _depth() == 0, "a failing commit leaked depth %d" % _depth()
    assert state["first"] is False, "the flaky commit never fired — this test proved nothing"
