"""Document numbers — the format, the sequence, and the collision that existed by construction.

Two documents may never share a number, and a number that has been printed may never be re-issued.
The tests that matter are the ones that would have caught what was actually shipped: a browser
computing max(the rows it can see) + 1 on a SELF_OWNED collection, and a quotation reference derived
from a 9000-slot hash of the deal id.
"""
import threading

import pytest

import db
import doc_number as dn


# ── the format ───────────────────────────────────────────────────────────────────────────────────

def test_the_number_looks_like_the_one_already_in_use():
    """Existing payment requests are PR-2026-001. Changing the shape would orphan every printed
    reference and every regex that reads one."""
    assert dn.format_no("PR", 2026, 1) == "PR-2026-001"
    assert dn.format_no("PR", 2026, 42) == "PR-2026-042"


def test_padding_never_truncates():
    """The worst available failure: PR-2026-001 for both the 1st and the 1001st document, a
    collision that looks like a formatting choice."""
    assert dn.format_no("PR", 2026, 1000) == "PR-2026-1000"
    assert dn.format_no("PR", 2026, 12345) == "PR-2026-12345"


def test_each_series_carries_its_own_width():
    assert dn.format_no("QT", 2026, 7) == "QT-2026-0007", "sales documents are 4 wide"
    assert dn.format_no("PR", 2026, 7) == "PR-2026-007"


def test_round_trip():
    for prefix, n in (("PR", 1), ("QT", 9999), ("IN", 12345)):
        assert dn.parse_no(dn.format_no(prefix, 2026, n))["n"] == n


@pytest.mark.parametrize("bad", ["", None, "nope", "PR-26-001", "PR-2026-", "2026-001",
                                 "HML-QT-2026-1234", "PR/2026/001"])
def test_the_parser_is_strict(bad):
    """A loose parser is how a foreign reference seeds the counter and skips the sequence forward by
    thousands. Anything that is not one of our numbers is not one of our numbers."""
    assert dn.parse_no(bad) is None


# ── adopting a live database ─────────────────────────────────────────────────────────────────────

def test_the_highest_existing_number_is_found_across_junk():
    got = dn.highest(["PR-2026-004", "junk", "", None, "PR-2026-011", "PR-2025-099"], "PR", 2026)
    assert got == 11


def test_another_year_and_another_series_do_not_count():
    assert dn.highest(["PR-2025-500", "QT-2026-800"], "PR", 2026) == 0


def test_nothing_yet_is_zero_not_an_error():
    assert dn.highest([], "PR", 2026) == 0


def test_numbers_are_pulled_out_of_real_rows():
    rows = [{"reqNo": "PR-2026-003"}, {"reqNo": ""}, {}, None, {"reqNo": "PR-2026-009"}]
    assert dn.numbers_in(rows) == ["PR-2026-003", "PR-2026-009"]


def test_the_series_registry_and_the_collection_map_cannot_disagree():
    """BY_COLL is derived from SERIES, so a new document type cannot be half-registered."""
    assert dn.series_for("payments") == "PR"
    assert dn.series_for("crm_deals") is None
    for coll, prefix in dn.BY_COLL.items():
        assert dn.SERIES[prefix]["coll"] == coll


def test_duplicates_are_reportable():
    """A register that cannot see its own collisions is how they survive for years."""
    d = dn.duplicates(["PR-2026-001", "pr-2026-001", "PR-2026-002"])
    assert d and d[0]["number"] == "PR-2026-001" and d[0]["count"] == 2
    assert dn.duplicates(["PR-2026-001", "PR-2026-002"]) == []


# ── the allocation, which is a database property ─────────────────────────────────────────────────

@pytest.fixture
def series(base_url):
    """A private series so these never touch the app's real counters.

    Depends on base_url only because that is where this suite runs init_db() — the counter table is
    created by the schema, so a database that has never been initialised has nowhere to count.
    """
    name = "ZZ"
    conn = db.get_conn()
    conn.execute("DELETE FROM doc_counters WHERE series = ?", (name,))
    conn.commit(); conn.close()
    yield name
    conn = db.get_conn()
    conn.execute("DELETE FROM doc_counters WHERE series = ?", (name,))
    conn.commit(); conn.close()


def test_numbers_come_out_in_order(series):
    assert [db.next_doc_no(series, 2026) for _ in range(3)] == [1, 2, 3]


def test_each_year_starts_again(series):
    db.next_doc_no(series, 2026); db.next_doc_no(series, 2026)
    assert db.next_doc_no(series, 2027) == 1
    assert db.next_doc_no(series, 2026) == 3, "and the old year carries on where it left off"


def test_the_first_allocation_starts_above_what_the_data_already_shows(series):
    """Adopting a live database. Numbers 1-17 are already on documents people are holding; the
    counter must not hand out 1 again."""
    assert db.next_doc_no(series, 2026, lambda: 17) == 18


def test_the_floor_is_asked_for_only_once(series):
    calls = []

    def floor():
        calls.append(1)
        return 5
    assert db.next_doc_no(series, 2026, floor) == 6
    assert db.next_doc_no(series, 2026, floor) == 7
    assert len(calls) == 1, "scanning the collection on every create for a year would be waste"


def test_a_broken_scan_still_issues_a_number(series):
    """A number that might duplicate is recoverable and the duplicate report finds it. A create
    that 500s because a scan threw is a person who cannot submit their expense claim."""
    def floor():
        raise RuntimeError("collection unreadable")
    assert db.next_doc_no(series, 2026, floor) == 1


def test_peek_does_not_allocate(series):
    db.next_doc_no(series, 2026)
    assert db.peek_doc_no(series, 2026) == 1
    assert db.peek_doc_no(series, 2026) == 1
    assert db.next_doc_no(series, 2026) == 2


def test_concurrent_allocation_never_hands_out_the_same_number_twice(series):
    """THE POINT OF THE MODULE. The arithmetic is trivial; the exclusion is not. Doing this in the
    browser is exactly how the payment-request numbers collided — and this is a ThreadingHTTPServer,
    so two submits really do run at once."""
    got, lock = [], threading.Lock()

    def take():
        n = db.next_doc_no(series, 2026)
        with lock:
            got.append(n)

    threads = [threading.Thread(target=take) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == list(range(1, 13)), "no duplicates and no holes: %r" % sorted(got)
