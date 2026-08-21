"""The alert plumbing: who a name resolves to, and what the aging sweep actually decides.

ahu_notify decides the message; these tests cover the half that touches the database — turning a
role holder's NAME into a person, and walking the open non-conformances. Both have the same failure
shape: doing nothing, successfully, and reporting a number that looks like a normal quiet day.
"""
import json
from datetime import date

import app
import db


def _mk_unit(pin="PIN-N-01", **kw):
    u = {"id": "unit-" + pin, "pin": pin, "family": "modular", "orderId": "ord-n"}
    u.update(kw)
    return db.put_collection_item("ahu_units", u)


def _mk_ncr(nid, unit_id, raised, status="Open", kind="ncr", **kw):
    n = {"id": nid, "unitId": unit_id, "raisedOn": raised, "status": status, "kind": kind,
         "ncrNo": nid.upper()}
    n.update(kw)
    return db.put_collection_item("ahu_ncr", n)


def _collect():
    """A notify() stand-in that records instead of pushing, so the sweep can be read back."""
    seen = []

    def notify(ctx, msg):
        seen.append(msg)
        return {"sent": 1}
    return notify, seen


def _fresh_register():
    """Empty the NCR register and forget who has been chased.

    The harness shares one database across the whole session, so without this each sweep would also
    find the previous test's non-conformances — and a test that asserts "nothing was chased" would
    be failed by someone else's fixture rather than by the behaviour it is about.
    """
    for n in db.list_collection("ahu_ncr"):
        db.delete_collection_item("ahu_ncr", n.get("id"))
    db.set_setting("_ahuNcrChased", json.dumps({}))


# ── name → person ────────────────────────────────────────────────────────────────────────────────

def test_a_role_holder_named_exactly_resolves_to_their_email(base_url):
    emails, matched = app.Handler._ahu_people_for(["Admin User"])
    assert "admin@humiley.com" in emails
    assert matched == ["Admin User"]


def test_a_name_in_the_other_order_still_resolves(base_url):
    """Production records name people the way the factory says them. An exact match would leave the
    QC inspector unreachable on half the units in the register."""
    emails, matched = app.Handler._ahu_people_for(["User Admin"])
    assert "admin@humiley.com" in emails and matched == ["User Admin"]


def test_a_name_nobody_holds_resolves_to_nothing_and_is_reported(base_url):
    """The load-bearing one. The caller must be able to tell "unreachable" from "nobody subscribed"."""
    import ahu_notify
    chosen = ["Admin User", "Nguyen Thi Nobody"]
    emails, matched = app.Handler._ahu_people_for(chosen)
    assert ahu_notify.unresolved(chosen, matched) == ["Nguyen Thi Nobody"]


def test_an_inactive_employee_is_not_a_recipient(base_url):
    db.create_employee({"id": "HML-GONE", "name": "Departed Person", "email": "gone@humiley.com",
                        "role": "staff", "level": "staff", "status": "Inactive"})
    emails, matched = app.Handler._ahu_people_for(["Departed Person"])
    assert "gone@humiley.com" not in emails
    assert matched == []            # and therefore reported as unreachable, not silently dropped


def test_blank_and_missing_names_are_skipped_without_raising(base_url):
    assert app.Handler._ahu_people_for(["", None, "   "]) == ([], [])
    assert app.Handler._ahu_people_for(None) == ([], [])


# ── the aging sweep ──────────────────────────────────────────────────────────────────────────────

def test_an_ncr_older_than_the_threshold_is_chased(base_url):
    _fresh_register()
    _mk_unit("PIN-N-01", qcInspector="Admin User")
    _mk_ncr("ncr-old", "unit-PIN-N-01", "2026-08-01")
    notify, seen = _collect()
    sent = app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5)
    assert sent == 1
    assert "NCR-OLD" in seen[0]["body"] and "20 days" in seen[0]["body"]


def test_a_young_ncr_is_left_alone(base_url):
    _fresh_register()
    _mk_unit("PIN-N-02")
    _mk_ncr("ncr-young", "unit-PIN-N-02", "2026-08-20")
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5) == 0
    assert seen == []


def test_a_closed_ncr_is_not_chased(base_url):
    _fresh_register()
    _mk_unit("PIN-N-03")
    _mk_ncr("ncr-closed", "unit-PIN-N-03", "2026-07-01", status="Closed")
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5) == 0


def test_a_punch_list_item_is_not_a_non_conformance(base_url):
    """Snagging and non-conformance are different things with different urgency. Chasing punch items
    through the NCR alert would swamp the alert that means a unit cannot ship."""
    _fresh_register()
    _mk_unit("PIN-N-04")
    _mk_ncr("ncr-punch", "unit-PIN-N-04", "2026-07-01", kind="punch")
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5) == 0


def test_the_same_ncr_is_not_chased_again_the_next_day(base_url):
    _fresh_register()
    _mk_unit("PIN-N-05")
    _mk_ncr("ncr-rep", "unit-PIN-N-05", "2026-08-01")
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5) == 1
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 22), 5) == 0


def test_an_ncr_with_no_readable_raised_date_is_reported_rather_than_skipped(base_url):
    """The silent-skip trap. An undated NCR would otherwise never be chased and nothing would say
    so — the sweep would report a clean run on a register it had not fully examined."""
    _fresh_register()
    _mk_unit("PIN-N-06")
    _mk_ncr("ncr-undated", "unit-PIN-N-06", "")
    # Found by ACTION, not by slicing the tail of the trail: db.list_collection orders rows by
    # their random uuid, so "everything after index N" is not "everything written since". A slice
    # here passes on its own and fails the moment the suite writes other audit rows first.
    def _sweep_notes():
        return [r for r in db.list_collection("audit")
                if str(r.get("action") or "") == "AHU alert — ncr-aging sweep"]
    before = len(_sweep_notes())
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 5) == 0
    rows = _sweep_notes()
    assert len(rows) == before + 1
    assert any("could not be aged" in str(r.get("detail") or "") for r in rows)


def test_the_threshold_the_message_states_is_the_one_that_decided_it(base_url):
    _fresh_register()
    _mk_unit("PIN-N-07")
    _mk_ncr("ncr-th", "unit-PIN-N-07", "2026-08-10")
    notify, seen = _collect()
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 20) == 0     # 11 days, threshold 20
    assert app._ahu_ncr_sweep(notify, date(2026, 8, 21), 10) == 1     # 11 days, threshold 10
    assert "threshold 10" in seen[0]["body"]
