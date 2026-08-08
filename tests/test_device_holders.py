"""Everybody holding a shared item must be able to see it.

One stock line can be signed out to several people at once. The row keeps two legacy mirror fields —
`empId` and `assignedTo` — for the FIRST holder, and `assignedTo` becomes a comma-joined display
string once there are several. Staff reads were scoped on those mirrors alone, so from the second
assignment onward a holder's own device vanished from their My Devices: the register had them signed
for the kit, and the app told them they had none. They could not acknowledge it, dispute it, or see
it on their offboarding checklist.
"""
import app
import db


def _device(api, tokens, **kw):
    body = {"name": kw.pop("name", "Máy khoan"), "category": "Tool", "qty": kw.pop("qty", 5)}
    body.update(kw)
    st, b = api("POST", "/api/coll/devices", tokens["admin"], body)
    assert st == 200, b
    return b["item"]


def _mine(api, token):
    st, b = api("GET", "/api/coll/devices", token)
    assert st == 200, b
    return b.get("items", [])


def test_the_first_holder_sees_their_device(api, tokens):
    _device(api, tokens, name="First holder", empId="HML-STF", assignedTo="Staff One", status="Assigned",
            assignments=[{"id": "a1", "empId": "HML-STF", "name": "Staff One", "qty": 2}])
    assert any(d["name"] == "First holder" for d in _mine(api, tokens["staff"]))


def test_the_second_holder_sees_it_too(api, tokens):
    """THE bug. Two people hold the same line; the row's mirror fields name only the first."""
    _device(api, tokens, name="Shared drill", qty=5, empId="HML-STF",
            assignedTo="Staff One, Other Staff", status="Assigned",
            assignments=[{"id": "a1", "empId": "HML-STF", "name": "Staff One", "qty": 2},
                         {"id": "a2", "empId": "HML-OTH", "name": "Other Staff", "qty": 1}])
    got = [d["name"] for d in _mine(api, tokens["other"])]
    assert "Shared drill" in got, "the second holder was told they hold nothing"


def test_somebody_who_holds_none_of_it_still_cannot_see_it(api, tokens):
    """Widening the read must not turn a self-service list into a company-wide one."""
    _device(api, tokens, name="Not mine", qty=3, empId="HML-STF", assignedTo="Staff One", status="Assigned",
            assignments=[{"id": "a1", "empId": "HML-STF", "name": "Staff One", "qty": 3}])
    assert "Not mine" not in [d["name"] for d in _mine(api, tokens["other"])]


def test_an_unassigned_line_is_not_visible_to_staff(api, tokens):
    _device(api, tokens, name="In the store", qty=9, status="Available")
    assert "In the store" not in [d["name"] for d in _mine(api, tokens["staff"])]


def test_a_holder_matched_only_by_name_still_sees_it(api, tokens):
    """Imported rows often have no employee id — only a typed name."""
    _device(api, tokens, name="Imported kit", qty=2, status="Assigned",
            assignments=[{"id": "a1", "empId": "", "name": "Other Staff", "qty": 1}])
    assert "Imported kit" in [d["name"] for d in _mine(api, tokens["other"])]


def test_a_blank_id_and_a_different_name_does_not_leak(api, tokens):
    _device(api, tokens, name="Somebody else's", qty=2, status="Assigned",
            assignments=[{"id": "a1", "empId": "", "name": "Staff One", "qty": 1}])
    assert "Somebody else's" not in [d["name"] for d in _mine(api, tokens["other"])]


def test_a_manager_still_sees_the_whole_register(api, tokens):
    _device(api, tokens, name="Manager view check", qty=1, status="Available")
    assert "Manager view check" in [d["name"] for d in _mine(api, tokens["mgr"])]
