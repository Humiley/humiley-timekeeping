"""Revoking a leaver's access, end to end.

access_revoke.py proves the timing and the completeness rules. This proves the parts only the server
can answer: that it actually shuts the portal account, the signature credential, the phone and the
Microsoft tenant; that a refusal from Graph is recorded as a refusal; and that nobody can use it to
lock out a super-admin or themselves.

Graph is stubbed throughout — the real tenant is never touched by a test run.
"""
import pytest

import access_revoke as ar
import app
import db

ROLES = ["Mail.Send", "Sites.ReadWrite.All", "User.ReadWrite.All"]


@pytest.fixture(autouse=True)
def _isolate(tokens, monkeypatch):
    """Revocation deactivates people and ends sessions — both of which would leak into every later
    test in the run. Snapshot and put back."""
    emps = {e["id"]: {"status": e.get("status"), "endDate": e.get("endDate")}
            for e in db.list_employees()}
    sessions = dict(app.SESSIONS)
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'exits'")
    conn.execute("DELETE FROM esign_pin")
    conn.execute("DELETE FROM push_subs")
    conn.commit()
    conn.close()
    monkeypatch.setitem(app.M365, "clientId", "test-client")
    monkeypatch.setitem(app.M365, "clientSecret", "test-secret")
    monkeypatch.setitem(app.M365, "tenantId", "test-tenant")
    monkeypatch.setattr(app, "_graph_granted_roles", lambda force=False: list(ROLES))
    monkeypatch.setattr(app, "_graph_user",
                        lambda upn: {"found": True, "enabled": True, "id": "oid-1", "error": ""})
    monkeypatch.setattr(app, "_graph_revoke_sessions", lambda upn: True)
    monkeypatch.setattr(app, "_graph_block_signin", lambda upn: True)
    yield
    app.SESSIONS.clear()
    app.SESSIONS.update(sessions)
    for eid, v in emps.items():
        db.update_employee(eid, v)
    conn = db.get_conn()
    conn.execute("DELETE FROM collections WHERE coll = 'exits'")
    conn.execute("DELETE FROM esign_pin")
    conn.execute("DELETE FROM push_subs")
    conn.commit()
    conn.close()


def _exit(api, tokens, emp_id="HML-OTH", last_day="2020-01-31"):
    st, b = api("POST", "/api/coll/exits", tokens["admin"],
                {"empId": emp_id, "name": "Other Staff", "lastDay": last_day, "type": "Resignation",
                 "status": "Clearance"})
    assert st == 200, b
    return b["item"]["id"]


def _steps(plan):
    return {s["key"]: s for s in plan["steps"]}


# ── the preview ──────────────────────────────────────────────────────────────────────────────────

def test_the_preview_says_what_is_open_and_what_it_would_cost_to_leave_it(api, tokens):
    xid = _exit(api, tokens)
    st, b = api("GET", "/api/hr/exit/%s/revoke" % xid, tokens["admin"])
    assert st == 200, b
    s = _steps(b["plan"])
    assert s["m365_account"]["done"] is False
    assert "sign in to email" in s["m365_account"]["exposure"]
    assert b["plan"]["state"] == "exposed", "the last day was years ago"


def test_the_preview_reports_the_tenant_s_own_answer_not_our_checklist(api, tokens):
    """A ticked box proves nothing. An account that still answers proves everything."""
    xid = _exit(api, tokens)
    _, b = api("GET", "/api/hr/exit/%s/revoke" % xid, tokens["admin"])
    assert b["plan"]["m365"]["enabled"] is True


def test_a_missing_graph_consent_is_named_in_the_preview(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "_graph_granted_roles", lambda force=False: ["Mail.Send"])
    xid = _exit(api, tokens)
    _, b = api("GET", "/api/hr/exit/%s/revoke" % xid, tokens["admin"])
    assert "User.ReadWrite.All" in _steps(b["plan"])["m365_account"]["blocked"]
    assert "m365_account" not in b["plan"]["canRunNow"]


def test_an_unconnected_tenant_does_not_stop_the_portal_side(api, tokens, monkeypatch):
    monkeypatch.setitem(app.M365, "clientId", "")
    xid = _exit(api, tokens)
    _, b = api("GET", "/api/hr/exit/%s/revoke" % xid, tokens["admin"])
    assert "portal" in b["plan"]["canRunNow"]
    assert "not connected" in _steps(b["plan"])["m365_account"]["blocked"]


def test_an_exit_that_does_not_exist_is_a_404(api, tokens):
    st, _ = api("GET", "/api/hr/exit/nope/revoke", tokens["admin"])
    assert st == 404


# ── performing it ────────────────────────────────────────────────────────────────────────────────

def test_it_actually_shuts_the_portal_account_the_signature_and_the_phone(api, tokens):
    db.set_pin("HML-OTH", "748213")
    db.push_sub_add("other@humiley.com", {"endpoint": "https://push.example/abc", "keys": {}})
    ghost = app.new_session("HML-OTH", "staff")
    xid = _exit(api, tokens)

    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 200, b
    assert b["failed"] == []
    assert db.get_employee("HML-OTH")["status"] == "Inactive"
    assert db.get_pin_status("HML-OTH")["revoked"] is True
    assert db.push_subs_count("other@humiley.com") == 0
    assert app.session_user(ghost) is None, "their signed-in phone is signed out"
    assert b["plan"]["state"] == "exposed", "the two manual steps are still somebody's job"


def test_ending_their_sessions_is_a_real_act_not_a_side_effect_of_deactivation(api, tokens):
    """session_user already turns an Inactive employee away on their next request, so an all-steps
    run proves nothing about this one — the deactivation would carry it either way. Running the
    session step ALONE, with the account left active, is what proves the token is actually gone.
    Without this the step could be a no-op and every other test here would still pass."""
    ghost = app.new_session("HML-OTH", "staff")
    assert app.session_user(ghost) is not None
    xid = _exit(api, tokens)
    _, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"],
               {"steps": ["portal_sessions"]})
    assert db.get_employee("HML-OTH")["status"] != "Inactive", "the account is deliberately untouched"
    assert app.session_user(ghost) is None
    # The count, not a fixed number: this person may hold more than one live session in a full run.
    assert int(b["done"][0]["note"].split()[0]) >= 1


def test_the_microsoft_sessions_are_revoked_before_the_account_is_blocked(api, tokens, monkeypatch):
    """The other order leaves issued refresh tokens live with no way left to reach them."""
    calls = []
    monkeypatch.setattr(app, "_graph_revoke_sessions", lambda upn: calls.append("sessions") or True)
    monkeypatch.setattr(app, "_graph_block_signin", lambda upn: calls.append("block") or True)
    xid = _exit(api, tokens)
    api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert calls == ["sessions", "block"]


def test_each_step_records_who_did_it_and_what_happened(api, tokens):
    xid = _exit(api, tokens)
    api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    rec = db.get_collection_item("exits", xid)
    step = rec["revoked"]["m365_account"]
    assert step["at"] and "Admin User" in step["by"]
    assert "sign-in blocked" in step["note"]


def test_a_refusal_from_graph_is_recorded_as_a_refusal_and_retried_next_time(api, tokens, monkeypatch):
    """The failure mode this whole feature replaces is a step that looks done because nothing
    contradicted it. "Graph said no" and "nobody has been here yet" must not look the same."""
    def _boom(upn):
        raise Exception("Insufficient privileges to complete the operation.")
    monkeypatch.setattr(app, "_graph_block_signin", _boom)
    xid = _exit(api, tokens)
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 200
    assert [f["key"] for f in b["failed"]] == ["m365_account"]
    assert "Insufficient privileges" in b["failed"][0]["why"]
    assert "m365_account" in b["plan"]["outstanding"]

    monkeypatch.setattr(app, "_graph_block_signin", lambda upn: True)
    _, again = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert [d["key"] for d in again["done"]] == ["m365_account"]


def test_one_step_failing_does_not_abandon_the_others(api, tokens, monkeypatch):
    def _boom(upn):
        raise Exception("tenant unreachable")
    monkeypatch.setattr(app, "_graph_revoke_sessions", _boom)
    xid = _exit(api, tokens)
    _, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert "portal" in [d["key"] for d in b["done"]]
    assert db.get_employee("HML-OTH")["status"] == "Inactive"


def test_running_it_again_with_nothing_left_is_refused_rather_than_pretending(api, tokens):
    xid = _exit(api, tokens)
    api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 400 and "nothing left" in (b.get("error") or "")
    assert b["plan"]["outstanding"], "and it still says what a human has to finish"


def test_a_single_step_can_be_run_on_its_own(api, tokens):
    xid = _exit(api, tokens)
    _, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {"steps": ["portal_pin"]})
    assert [d["key"] for d in b["done"]] == ["portal_pin"]
    assert db.get_employee("HML-OTH")["status"] != "Inactive"


# ── the notice period ────────────────────────────────────────────────────────────────────────────

def test_cutting_somebody_off_during_their_notice_period_needs_a_reason(api, tokens):
    """Thirty days of notice is thirty days of work. Revoking on the day HR types the resignation in
    would take somebody's email away while they are still handing over."""
    xid = _exit(api, tokens, last_day="2099-12-31")
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 400 and b["needsReason"] is True
    assert db.get_employee("HML-OTH")["status"] != "Inactive"


def test_with_a_reason_an_early_revocation_goes_through_and_the_reason_is_on_the_record(api, tokens):
    """A dismissal for cause serves no notice. The portal allows it and names it."""
    xid = _exit(api, tokens, last_day="2099-12-31")
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"],
                {"reason": "Summary dismissal — Art. 125 gross misconduct"})
    assert st == 200, b
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Access revoked on exit"]
    assert any("EARLY" in a["detail"] and "Art. 125" in a["detail"] for a in trail)


def test_after_the_last_working_day_no_reason_is_needed(api, tokens):
    xid = _exit(api, tokens, last_day="2020-01-31")
    st, _ = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 200


# ── who may do it, and to whom ───────────────────────────────────────────────────────────────────

def test_a_super_admin_can_never_be_revoked_from_here(api, tokens, monkeypatch):
    """One mistaken click must not be able to lock the whole company out of its own portal."""
    monkeypatch.setattr(app.Handler, "ADMIN_EMAILS", {"editor@humiley.com"})
    xid = _exit(api, tokens, emp_id="HML-EDT")
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    assert st == 403 and "protected super-admin" in (b.get("error") or "")
    assert db.get_employee("HML-EDT")["status"] != "Inactive"


def test_nobody_can_revoke_their_own_access(api, tokens):
    xid = _exit(api, tokens, emp_id="HML-MGT")
    st, b = api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["management"], {})
    assert st == 403 and "your own access" in (b.get("error") or "")


def test_a_line_manager_cannot_revoke_anybody(api, tokens):
    xid = _exit(api, tokens)
    assert api("GET", "/api/hr/exit/%s/revoke" % xid, tokens["mgr"])[0] == 403
    assert api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["mgr"], {})[0] == 403


def test_revoking_is_written_to_the_audit_chain(api, tokens):
    xid = _exit(api, tokens)
    api("POST", "/api/hr/exit/%s/revoke" % xid, tokens["admin"], {})
    trail = [a for a in db.list_collection("audit") if a.get("action") == "Access revoked on exit"]
    assert any("other@humiley.com" in a["detail"] for a in trail)


# ── the chase list ───────────────────────────────────────────────────────────────────────────────

def test_a_former_employee_whose_signature_still_works_is_listed(api, tokens):
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2024-03-31"})
    db.set_pin("HML-OTH", "748213")
    st, b = api("GET", "/api/hr/access-review", tokens["admin"])
    assert st == 200, b
    row = [r for r in b["rows"] if r["empId"] == "HML-OTH"]
    assert row and any(f["key"] == "portal_pin" for f in row[0]["findings"])


def test_somebody_never_offboarded_through_the_portal_is_found(api, tokens):
    """No exit record at all — the ghosts from before any of this existed."""
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2019-06-30"})
    _, b = api("GET", "/api/hr/access-review", tokens["admin"])
    row = [r for r in b["rows"] if r["empId"] == "HML-OTH"][0]
    assert any(f["key"] == "norecord" for f in row["findings"])
    assert row["severity"] == "open"


def test_current_employees_are_never_on_the_list(api, tokens):
    _, b = api("GET", "/api/hr/access-review", tokens["admin"])
    assert "HML-STF" not in [r["empId"] for r in b["rows"]]


def test_the_protected_admin_is_never_listed_as_a_finding(api, tokens, monkeypatch):
    """Their account is deliberately exempt from revocation, so reporting it as unshut every day
    would train everybody to ignore the list."""
    monkeypatch.setattr(app.Handler, "ADMIN_EMAILS", {"editor@humiley.com"})
    db.update_employee("HML-EDT", {"status": "Inactive"})
    _, b = api("GET", "/api/hr/access-review", tokens["admin"])
    assert "HML-EDT" not in [r["empId"] for r in b["rows"]]


def test_the_shallow_list_does_not_call_graph_once_per_leaver(api, tokens, monkeypatch):
    """One call per former employee is fine when somebody asks for it, and not fine on every page
    load of the offboarding register."""
    calls = []
    monkeypatch.setattr(app, "_graph_user", lambda upn: calls.append(upn) or
                        {"found": True, "enabled": True, "id": "", "error": ""})
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2024-03-31"})
    _, b = api("GET", "/api/hr/access-review", tokens["admin"])
    assert calls == [] and b["m365Checked"] == 0


def test_asking_deeply_checks_the_tenant_and_reports_a_live_account(api, tokens):
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2024-03-31"})
    _, b = api("GET", "/api/hr/access-review?m365=1", tokens["admin"])
    row = [r for r in b["rows"] if r["empId"] == "HML-OTH"][0]
    assert any(f["key"] == "m365_account" for f in row["findings"])
    assert b["m365Checked"] >= 1


def test_a_tenant_that_cannot_be_reached_is_unknown_never_an_all_clear(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "_graph_user",
                        lambda upn: {"found": False, "enabled": None, "id": "",
                                     "error": "Service unavailable"})
    _exit(api, tokens)          # they WERE offboarded — the tenant is the only open question
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2024-03-31"})
    _, b = api("GET", "/api/hr/access-review?m365=1", tokens["admin"])
    row = [r for r in b["rows"] if r["empId"] == "HML-OTH"][0]
    assert row["severity"] == "unknown"


def test_an_account_the_tenant_has_never_heard_of_is_not_a_finding(api, tokens, monkeypatch):
    """A 404 from Graph means there is nothing left to shut — the cleanest possible answer."""
    monkeypatch.setattr(app, "_graph_user",
                        lambda upn: {"found": False, "enabled": False, "id": "", "error": ""})
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2024-03-31"})
    _, b = api("GET", "/api/hr/access-review?m365=1", tokens["admin"])
    row = [r for r in b["rows"] if r["empId"] == "HML-OTH"]
    assert not row or not any(f["key"].startswith("m365") for f in row[0]["findings"])


def test_a_line_manager_cannot_read_the_access_review(api, tokens):
    assert api("GET", "/api/hr/access-review", tokens["mgr"])[0] == 403
    assert api("GET", "/api/hr/access-review", tokens["staff"])[0] == 403


def test_the_summary_is_what_a_director_asks_for(api, tokens):
    db.update_employee("HML-OTH", {"status": "Inactive", "endDate": "2019-06-30"})
    _, b = api("GET", "/api/hr/access-review", tokens["admin"])
    assert b["summary"]["total"] >= 1 and b["summary"]["oldestDays"] > 2000
