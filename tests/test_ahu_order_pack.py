"""The review pack for a whole order.

A customer buys N units and reviews the ORDER. The portal only ever answered per unit, so reviewing
a package of eight meant opening eight dossiers.

The arithmetic is trivial. These tests are about the refusals, and one of them is the reason the
module exists in the shape it does:

  * an order with NO units is NOT ready — `all([])` is True, and the obvious implementation reports
    an empty order as ready to hand over
  * a unit whose route cannot be built BLOCKS, it is never skipped
  * readiness needs EVERY unit, and there is no percentage to round the problem away with
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ahu_order_pack as P   # noqa: E402


def _row(pin, progress=100, dispatched=True, ncr=(), failed=(), unsigned_gate=None,
         route_error=None, status="Dispatched"):
    steps = []
    for c in failed:
        steps.append({"code": c, "kind": "test", "status": "Failed"})
    steps.append({"code": "G6", "kind": "gate",
                  "status": "Pending" if unsigned_gate == "G6" else "Passed"})
    return {
        "unit": {"id": pin, "pin": pin, "tag": "T-" + pin, "family": "modular", "status": status},
        "steps": steps,
        "ncr": list(ncr),
        "dispatch": [{"dispatchedOn": "2026-08-20"}] if dispatched else [],
        "state": {"progress": progress, "stage": 7, "stageTitle": "Dispatch",
                  "routeError": route_error},
    }


def _by(out):
    return {u["pin"]: u for u in out["units"]}


# ── THE refusal: the empty order ────────────────────────────────────────────────────────────────

def test_an_order_with_no_units_is_not_ready_to_hand_over():
    """`all([])` is True. Written the obvious way this returns READY — the most confident possible
    answer about nothing at all, from a rule that never looked at a unit."""
    out = P.pack({"poNumber": "PO-1"}, [])
    assert out["ready"] is False
    assert out["status"] == P.NOTHING_TO_REVIEW
    assert out["unitCount"] == 0
    assert any("nothing to review" in w for w in out["why"])


def test_an_empty_order_is_told_apart_from_a_blocked_one():
    """Different problems with different owners: one is a sales/registration gap, the other is the
    floor's. Both are 'not ready' and reporting them the same way sends the wrong person."""
    empty = P.pack({}, [])
    blocked = P.pack({}, [_row("P1", dispatched=False)])
    assert empty["status"] == P.NOTHING_TO_REVIEW
    assert blocked["status"] == P.NOT_READY


# ── the ordinary answer ─────────────────────────────────────────────────────────────────────────

def test_an_order_whose_every_unit_is_clean_is_ready():
    out = P.pack({"poNumber": "PO-1"}, [_row("P1"), _row("P2")])
    assert out["ready"] is True and out["status"] == P.READY
    assert out["why"] == []
    assert out["counts"]["ready"] == 2 and out["counts"]["blocked"] == 0


def test_one_blocked_unit_blocks_the_whole_order():
    """A package is handed over whole. Seven ready and one stuck is not a partial handover."""
    out = P.pack({}, [_row("P1"), _row("P2"), _row("P3", dispatched=False, status="In production")])
    assert out["ready"] is False
    assert out["counts"]["ready"] == 2 and out["counts"]["blocked"] == 1


def test_every_reason_is_named_against_the_unit_it_belongs_to():
    """A reviewer works through this list. "Something is wrong" is not a work instruction."""
    out = P.pack({}, [_row("P1"), _row("P2", dispatched=False, status="In production",
                                       ncr=[{"status": "Open", "kind": "NCR"}])])
    assert any("P2 — Not dispatched." in w for w in out["why"])
    assert any("P2 — 1 non-conformance(s) still open." in w for w in out["why"])
    assert not any(w.startswith("P1 —") for w in out["why"]), "a clean unit needs no line"


# ── the unroutable unit ─────────────────────────────────────────────────────────────────────────

def test_a_unit_whose_route_cannot_be_built_blocks_rather_than_being_skipped():
    """Skipping it would let an unreadable unit ride along inside a package somebody signs for."""
    out = P.pack({}, [_row("P1"), _row("P2", route_error="unknown family 'kappa'")])
    assert out["ready"] is False
    assert out["counts"]["unroutable"] == 1
    assert any("route cannot be built" in w and "P2" in w for w in out["why"])


# ── the decisions it keeps apart ────────────────────────────────────────────────────────────────

def test_a_closed_non_conformance_does_not_block():
    out = P.pack({}, [_row("P1", ncr=[{"status": "Closed", "kind": "NCR"}])])
    assert out["ready"] is True


def test_a_punch_item_does_not_block_a_handover():
    """Snagging, not a non-conformance — the same rule the sweeps and gate checks already apply."""
    out = P.pack({}, [_row("P1", ncr=[{"status": "Open", "kind": "punch"}])])
    assert out["ready"] is True


def test_an_unsigned_gate_blocks_and_is_named():
    out = P.pack({}, [_row("P1", unsigned_gate="G6")])
    assert out["ready"] is False
    assert _by(out)["P1"]["unsignedGates"] == ["G6"]
    assert any("Gates not signed: G6" in w for w in out["why"])


def test_a_failed_step_blocks_and_is_named():
    out = P.pack({}, [_row("P1", failed=["T7"])])
    assert out["ready"] is False
    assert any("Failed or held: T7" in w for w in out["why"])


def test_a_unit_marked_shipped_with_no_dispatch_record_is_flagged_not_accepted():
    """The status and the evidence disagree. That IS the finding — resolving it silently either way
    would either hide a missing packing record or call a shipped unit unshipped."""
    out = P.pack({}, [_row("P1", dispatched=False, status="Dispatched")])
    assert out["ready"] is False
    assert any("no dispatch record" in w for w in out["why"])


# ── what it refuses to average ──────────────────────────────────────────────────────────────────

def test_there_is_no_order_completeness_percentage():
    """Seven finished units and one stuck at framing is not 87% of a handover. A single figure is
    exactly what lets somebody round the problem away."""
    rows = [_row("P%d" % i) for i in range(7)] + [_row("P7", dispatched=False,
                                                       status="In production")]
    out = P.pack({}, rows)
    assert "pct" not in out and "percent" not in out and "completeness" not in out
    assert out["ready"] is False
    assert out["counts"]["ready"] == 7 and out["counts"]["blocked"] == 1


def test_the_verdict_carries_the_number_of_units_it_was_computed_over():
    """So a reader can see what "ready" was decided from, rather than trusting the word."""
    out = P.pack({}, [_row("P1"), _row("P2")])
    assert out["unitCount"] == 2


def test_the_note_says_every_unit_is_required():
    out = P.pack({}, [_row("P1")])
    assert "Every unit must be ready, not most" in out["note"]


def test_nothing_here_raises_on_missing_pieces():
    out = P.pack(None, [{"unit": {}, "steps": None, "ncr": None, "dispatch": None, "state": None}])
    assert out["unitCount"] == 1 and out["ready"] is False


# ── through the endpoint ────────────────────────────────────────────────────────────────────────

def _seed_order(oid, po, units):
    """units = [(pin, status, has_dispatch)]"""
    import db
    import ahu
    db.put_collection_item("ahu_orders", {"id": oid, "poNumber": po, "customer": "Acme",
                                          "deliveryDate": "2026-09-30"})
    for pin, status, shipped in units:
        uid = "%s-%s" % (oid, pin)
        unit = {"id": uid, "orderId": oid, "pin": pin, "tag": "T-" + pin,
                "family": "modular", "sectionCount": 4, "status": status}
        db.put_collection_item("ahu_units", unit)
        for r in ahu.instantiate(unit, {"id": oid}):
            r.setdefault("id", "%s-%s" % (uid, r["code"]))
            db.put_collection_item("ahu_steps", r)
        if shipped:
            db.put_collection_item("ahu_dispatch", {"id": uid + "-d", "unitId": uid,
                                                    "dispatchedOn": "2026-08-20"})


def test_the_endpoint_answers_for_a_whole_order(api, tokens):
    _seed_order("op-a", "PO-OP-A", [("OPA-1", "In production", False),
                                    ("OPA-2", "In production", False)])
    st, r = api("GET", "/api/ahu/order/op-a/pack", tokens["admin"])
    assert st == 200, r
    assert r["unitCount"] == 2
    assert r["ready"] is False, "unfinished units cannot be ready to hand over"
    assert {u["pin"] for u in r["units"]} == {"OPA-1", "OPA-2"}
    assert r["why"], "a not-ready order must say why"


def test_the_pack_covers_only_the_units_on_THAT_order(api, tokens):
    """The obvious bug: sweeping every unit in the factory into one order's pack."""
    _seed_order("op-b", "PO-OP-B", [("OPB-1", "In production", False)])
    _seed_order("op-c", "PO-OP-C", [("OPC-1", "In production", False),
                                    ("OPC-2", "In production", False)])
    st, r = api("GET", "/api/ahu/order/op-b/pack", tokens["admin"])
    assert st == 200
    assert r["unitCount"] == 1, [u["pin"] for u in r["units"]]
    assert {u["pin"] for u in r["units"]} == {"OPB-1"}


def test_an_order_that_exists_with_no_units_is_answered_not_404(api, tokens):
    """'This order has nothing registered against it' is a real finding, not an error — and it must
    never come back as ready."""
    import db
    db.put_collection_item("ahu_orders", {"id": "op-empty", "poNumber": "PO-EMPTY"})
    st, r = api("GET", "/api/ahu/order/op-empty/pack", tokens["admin"])
    assert st == 200
    assert r["ready"] is False and r["unitCount"] == 0
    assert r["status"] == "NOTHING_TO_REVIEW"


def test_an_order_that_does_not_exist_is_a_404(api, tokens):
    st, _ = api("GET", "/api/ahu/order/no-such-order/pack", tokens["admin"])
    assert st == 404
