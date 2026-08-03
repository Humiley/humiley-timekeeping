"""Payroll dual-control: a run is PREPARED by an Editor/Admin and only a Director (Management/Admin
level) e-signature finalises it. The preparer can never finalise their own run; status changes only
through /api/esign (never a plain PATCH); a finalised run is immutable. (User decision: the Managing
Director signs off payroll.)
"""
import app
import db


def _run(api, tok, period="January 2026"):
    # The client deliberately says 'Finalised' — the server must override it to a pending state.
    return api("POST", "/api/coll/payruns", tok,
               {"scope": "company", "period": period, "count": 3, "gross": 60_000_000, "net": 52_000_000,
                "ee": 6_000_000, "er": 14_000_000, "pit": 2_000_000, "erCost": 74_000_000, "status": "Finalised"})


def _get(pid):
    return db.get_collection_item("payruns", pid)


def test_payrun_is_created_pending_not_finalised(api, tokens):
    st, b = _run(api, tokens["editor"])
    assert st == 200, b
    row = _get(b["item"]["id"])
    assert row["status"] == "Pending Approval", "a run must be born pending, never finalised"
    assert row["preparedById"] == "HML-EDT"


def test_preparer_editor_cannot_finalise(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = _run(api, tokens["editor"], "February 2026")
    pid = b["item"]["id"]
    st, r = api("POST", "/api/esign", tokens["editor"],
                {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st != 200 and "director" in str(r).lower(), (st, r)
    assert _get(pid)["status"] == "Pending Approval"


def test_director_finalises_a_run_they_did_not_prepare(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = _run(api, tokens["editor"], "March 2026")
    pid = b["item"]["id"]
    st, r = api("POST", "/api/esign", tokens["management"],
                {"coll": "payruns", "id": pid, "meaning": "Payroll finalisation", "setStatus": "Finalised"})
    assert st == 200, r
    row = _get(pid)
    assert row["status"] == "Finalised" and row.get("finalisedBy")


def test_preparer_admin_cannot_finalise_own_run(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = _run(api, tokens["admin"], "April 2026")            # admin prepares
    pid = b["item"]["id"]
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st != 200 and "prepared" in str(r).lower(), (st, r)  # preparer != approver
    st2, _ = api("POST", "/api/esign", tokens["management"],
                 {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st2 == 200
    assert _get(pid)["status"] == "Finalised"


def test_patch_cannot_finalise_and_finalised_is_immutable(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = _run(api, tokens["editor"], "May 2026")
    pid = b["item"]["id"]
    # a plain PATCH must NOT finalise, but MAY amend a pending run's figures (full-object PATCH, as the UI sends)
    edit = dict(_get(pid), status="Finalised", gross=61_000_000)
    api("PATCH", "/api/coll/payruns/" + pid, tokens["editor"], edit)
    row = _get(pid)
    assert row["status"] == "Pending Approval" and row["gross"] == 61_000_000
    # after a Director finalises, the run is immutable to PATCH
    api("POST", "/api/esign", tokens["management"],
        {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    st, r = api("PATCH", "/api/coll/payruns/" + pid, tokens["editor"], dict(_get(pid), gross=999))
    assert st != 200 and "immutable" in str(r).lower(), (st, r)


def test_preparer_cannot_blank_or_spoof_preparedById_to_self_finalise(api, tokens, monkeypatch):
    # SoD-bypass regression: the preparer must not be able to clear/spoof preparedById via the blind
    # full-object PATCH and then finalise their OWN run (owner_id falsy/mismatched → the preparer!=signer
    # check would be skipped). The stored preparer identity is pinned, so the guard still fires.
    monkeypatch.setattr(app, "DEMO_MODE", True)
    _, b = _run(api, tokens["admin"], "June 2026")          # admin prepares
    pid = b["item"]["id"]
    assert _get(pid)["preparedById"] == "HML-ADM"
    # (a) try to BLANK preparedById via PATCH, then self-finalise
    api("PATCH", "/api/coll/payruns/" + pid, tokens["admin"], dict(_get(pid), preparedById="", preparedBy=""))
    assert _get(pid)["preparedById"] == "HML-ADM", "preparedById must be immutable via PATCH"
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st != 200 and "prepared" in str(r).lower(), (st, r)
    # (b) try to SPOOF preparedById to someone else, then self-finalise
    edit = dict(_get(pid)); edit.pop("preparedById", None)   # omit it entirely from the full-object body
    api("PATCH", "/api/coll/payruns/" + pid, tokens["admin"], edit)
    assert _get(pid)["preparedById"] == "HML-ADM"
    st2, r2 = api("POST", "/api/esign", tokens["admin"],
                  {"coll": "payruns", "id": pid, "meaning": "Finalise", "setStatus": "Finalised"})
    assert st2 != 200 and "prepared" in str(r2).lower(), (st2, r2)
    assert _get(pid)["status"] == "Pending Approval"
