"""The shop-floor board must not get slower with every unit the factory builds.

`ahu.load_ctx` reads six whole collections. Calling it once per unit — which `board()`, the capacity
chart, the KPI table and the labour analysis all used to do — makes the work quadratic, because the
collections themselves grow with the number of units. Measured before the fix: 0.06 s at 10 units,
1.98 s at 100, ~32 s extrapolated at 400. The board is the screen people leave open on a wall and
the front end polls it, so this was on its way to being the slowest thing in the portal.

These tests count COLLECTION READS rather than seconds. A timing assertion on a shared CI box is a
coin flip; the invariant that actually matters is structural and exact — reading a collection once
per unit is the bug, and reading it a bounded number of times is the fix. A stopwatch test would
also pass on a fast machine while the quadratic loop was still there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest      # noqa: E402

import db          # noqa: E402
import ahu         # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _database():
    """These tests need the schema, not the HTTP server — conftest already points TK_DB_PATH at a
    throwaway file."""
    db.init_db()


class _CountingReads:
    """Counts db.list_collection calls per collection while the block runs."""

    def __enter__(self):
        self.counts = {}
        self._real = db.list_collection

        def spy(coll):
            self.counts[coll] = self.counts.get(coll, 0) + 1
            return self._real(coll)

        db.list_collection = spy
        return self

    def __exit__(self, *exc):
        db.list_collection = self._real
        return False


def _seed(n, prefix):
    """n units of the same order, each with a full instantiated route."""
    order = {"id": prefix + "-ord", "poNumber": "PO-" + prefix}
    db.put_collection_item("ahu_orders", order)
    for i in range(n):
        unit = {"id": "%s-u%d" % (prefix, i), "orderId": order["id"],
                "pin": "%s-PIN-%d" % (prefix, i), "tag": "%s-T%d" % (prefix, i),
                "family": "modular", "sectionCount": 4, "status": "In production"}
        db.put_collection_item("ahu_units", unit)
        for r in ahu.instantiate(unit, order):
            r.setdefault("id", "%s-%s" % (unit["id"], r["code"]))
            db.put_collection_item("ahu_steps", r)


def test_the_board_reads_each_collection_a_fixed_number_of_times():
    """THE regression. Not "fewer reads" — the same number of reads at 4 units as at 24, which is
    the only shape that stays flat as the factory fills up."""
    _seed(4, "cost-a")
    with _CountingReads() as small:
        ahu.board()
    _seed(20, "cost-b")
    with _CountingReads() as large:
        ahu.board()

    assert large.counts == small.counts, (
        "the board's collection reads changed with the unit count — %s at 4 units, %s at 24"
        % (small.counts, large.counts))
    assert small.counts.get("ahu_steps") == 1, (
        "ahu_steps should be read exactly once per board render, was %r"
        % small.counts.get("ahu_steps"))


def test_a_single_unit_context_still_works_without_an_index():
    """`load_ctx(uid)` with no index is the single-unit path every write goes through. The index is
    an optimisation for the many-unit case and must not become mandatory."""
    _seed(2, "cost-c")
    ctx = ahu.load_ctx("cost-c-u0")
    assert ctx["unit"]["pin"] == "cost-c-PIN-0"
    assert ctx["steps"] and all(s.get("unitId") == "cost-c-u0" for s in ctx["steps"])


def test_the_indexed_context_is_identical_to_the_unindexed_one():
    """The whole fix rests on this: a faster route to the SAME context. If the two ever diverge,
    the board is quietly rendering something the single-unit screens do not agree with."""
    _seed(3, "cost-d")
    idx = ahu.ctx_index()
    for uid in ("cost-d-u0", "cost-d-u1", "cost-d-u2"):
        assert ahu.load_ctx(uid, idx) == ahu.load_ctx(uid), uid


def test_an_unknown_unit_reads_as_empty_through_the_index_too():
    """The index is a dict of what exists; a miss must behave like the database miss it stands in
    for, not raise a KeyError halfway through a board render."""
    idx = ahu.ctx_index()
    ctx = ahu.load_ctx("no-such-unit", idx)
    assert ctx["unit"] == {} and ctx["steps"] == [] and ctx["order"] == {}
