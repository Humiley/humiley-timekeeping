"""The no-movement sweep and the board field, through the real server.

tests/test_ahu_stalled.py proves the arithmetic. This proves the WIRING — that the sweep reaches a
recipient, that it does not shout twice about the same unit, that a dispatched unit is left alone,
and that the board reports the standing state so the alert is not the only way to see it.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db      # noqa: E402
import app     # noqa: E402
import ahu     # noqa: E402

TODAY = "2026-08-29"
LONG_AGO = "2026-06-01T08:00:00Z"


def _unit(uid, pin, status="In production", signed_at=LONG_AGO):
    db.put_collection_item("ahu_orders", {"id": "stall-ord", "poNumber": "PO-STALL",
                                          "productionLead": "Dept Manager"})
    db.put_collection_item("ahu_units", {
        "id": uid, "orderId": "stall-ord", "pin": pin, "tag": "T-" + pin,
        "family": "modular", "sectionCount": 4, "status": status})
    step = {"id": uid + "-WS-01", "unitId": uid, "code": "WS-01", "kind": "op", "seq": 10,
            "title": "Frame assembly", "status": "Complete", "signedBy": "Dept Manager"}
    if signed_at:
        step["signatures"] = [{"name": "Dept Manager", "ts": signed_at}]
    db.put_collection_item("ahu_steps", step)


def _sweep(threshold=7, today=TODAY):
    """Run the sweep with a capturing notifier; returns the messages it tried to send."""
    sent = []

    def capture(ctx, msg):
        sent.append(msg)
        return True

    app._ahu_stall_sweep(capture, today, threshold)
    return sent


def _clear_memory():
    db.set_setting("_ahuStallChased", "{}")


def test_a_unit_nobody_has_touched_raises_an_alert(api, tokens):
    _clear_memory()
    _unit("stall-a", "PIN-STALL-A")
    msgs = _sweep()
    mine = [m for m in msgs if "PIN-STALL-A" in (m.get("title") or "")]
    assert mine, "a unit untouched since June raised nothing"
    m = mine[0]
    assert m["event"] == "unit-stalled"
    assert "89 days" in m["body"], m["body"]
    assert "threshold 7" in m["body"]
    assert "WS-01" in m["body"], "the alert must name where it stopped"


def test_it_does_not_shout_about_the_same_unit_every_morning(api, tokens):
    """A daily alert that repeats daily is one people filter. The suppression window is what makes
    the sweep survivable."""
    _clear_memory()
    _unit("stall-b", "PIN-STALL-B")
    first = [m for m in _sweep() if "PIN-STALL-B" in (m.get("title") or "")]
    second = [m for m in _sweep() if "PIN-STALL-B" in (m.get("title") or "")]
    assert first and not second, "the same unit was chased twice in a row"


def test_a_dispatched_unit_is_left_alone(api, tokens):
    """It stopped because it SHIPPED. Alerting on that is how an alert loses its meaning."""
    _clear_memory()
    _unit("stall-c", "PIN-STALL-C", status="Dispatched")
    assert not [m for m in _sweep() if "PIN-STALL-C" in (m.get("title") or "")]


def test_a_unit_signed_yesterday_is_not_chased(api, tokens):
    _clear_memory()
    recent = time.strftime("%Y-%m-%dT08:00:00Z", time.gmtime(time.time() - 86400))
    _unit("stall-d", "PIN-STALL-D", signed_at=recent)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    assert not [m for m in _sweep(today=today) if "PIN-STALL-D" in (m.get("title") or "")]


def test_a_unit_that_cannot_be_aged_is_recorded_rather_than_ignored(api, tokens):
    """It is never alerted on per unit — that would punish whoever has to fix the data — but it must
    leave a standing count, or the sweep gets QUIETER as the records get worse."""
    _clear_memory()
    _unit("stall-e", "PIN-STALL-E", signed_at="last Tuesday")
    before = len(db.list_collection("audit"))
    _sweep()
    lines = [a for a in db.list_collection("audit")
             if "no-movement sweep" in str(a.get("action") or "")]
    assert lines, "an undateable unit left no trace at all"
    assert len(db.list_collection("audit")) > before


def test_the_board_reports_what_has_stopped(api, tokens):
    """On the screen, not only in the mail — an alert whose standing state cannot be seen is one
    people learn to delete."""
    _clear_memory()
    _unit("stall-f", "PIN-STALL-F")
    st, r = api("GET", "/api/ahu/board", tokens["admin"])
    assert st == 200
    assert "stalled" in r, "the board does not report no-movement at all"
    pins = [x["pin"] for x in r["stalled"]["stalled"]]
    assert "PIN-STALL-F" in pins, pins
    assert r["stalled"]["threshold"] == 7


def test_a_zero_threshold_is_refused_rather_than_honoured(api, tokens):
    """Zero would report every unit as stalled the moment it was signed — a way of turning the alert
    off by making it worthless."""
    assert app._ahu_stall_days("0") == 7
    assert app._ahu_stall_days("-3") == 7
    assert app._ahu_stall_days("") == 7
    assert app._ahu_stall_days("14") == 14
