"""Cutting off access when somebody leaves: the timing and the completeness.

These are the two ways offboarding actually fails. Too early locks somebody out of a notice period
they are still working; too late leaves a mailbox answering months after they have gone. And a
checklist that says "done" proves nothing — only an account that no longer answers does.
"""
import access_revoke as ar


def _exit(last_day="2026-08-31", **kw):
    return dict({"id": "X1", "empId": "HML-STF", "name": "Staff One", "lastDay": last_day}, **kw)


# The permissions Microsoft actually requires for app-only calls, not the ones I first assumed.
ROLES = ["Mail.Send", "User.RevokeSessions.All", "User.EnableDisableAccount.All", "User.Read.All"]


# ── timing ───────────────────────────────────────────────────────────────────────────────────────

def test_revocation_is_due_at_the_end_of_the_last_working_day():
    assert ar.due_on(_exit("2026-08-31")).isoformat() == "2026-08-31"


def test_the_last_working_day_itself_is_still_theirs():
    """Somebody serving notice works their last day. Revoking that morning takes their email away
    while they are still handing over."""
    assert ar.overdue_days(_exit("2026-08-31"), "2026-08-31") == 0
    assert ar.is_early(_exit("2026-08-31"), "2026-08-31") is True


def test_it_is_overdue_from_the_day_after():
    assert ar.overdue_days(_exit("2026-08-31"), "2026-09-01") == 1
    assert ar.overdue_days(_exit("2026-08-31"), "2026-09-30") == 30
    assert ar.is_early(_exit("2026-08-31"), "2026-09-01") is False


def test_a_month_of_notice_is_not_overdue_on_the_day_it_is_recorded():
    """The resignation lands on 1 August for a 31 August leaving date. Nothing is late."""
    p = ar.plan(_exit("2026-08-31"), today="2026-08-01", granted_roles=ROLES)
    assert p["overdueDays"] == 0 and p["state"] == "scheduled" and p["early"] is True


def test_an_exit_with_no_last_working_day_is_flagged_rather_than_treated_as_never_due():
    p = ar.plan(_exit(""), today="2026-09-01", granted_roles=ROLES)
    assert p["state"] == "nodate" and p["dueOn"] == ""
    assert ar.overdue_days(_exit(""), "2030-01-01") == 0


# ── what is still open ───────────────────────────────────────────────────────────────────────────

def test_everything_outstanding_after_the_last_day_reads_as_exposed():
    p = ar.plan(_exit("2026-08-31"), today="2026-09-05", granted_roles=ROLES)
    assert p["state"] == "exposed"
    assert "m365_account" in p["outstanding"] and "portal" in p["outstanding"]


def test_a_finished_revocation_reads_as_complete_however_late_it_was():
    rec = _exit("2026-08-31")
    for s in ar.STEPS:
        rec = ar.record(rec, s["key"], "HR", at="2026-09-02T09:00:00Z")
    p = ar.plan(rec, today="2026-12-01", granted_roles=ROLES)
    assert p["state"] == "complete" and p["outstanding"] == []


def test_a_partly_done_revocation_is_still_exposed():
    """The half that gets done is the portal half. The half that matters is the mailbox."""
    rec = ar.record(_exit("2026-08-31"), "portal", "HR", at="2026-09-01T09:00:00Z")
    p = ar.plan(rec, today="2026-09-02", granted_roles=ROLES)
    assert p["state"] == "exposed" and "m365_account" in p["outstanding"]


def test_every_step_says_what_stays_open_if_it_is_skipped():
    """A checklist of API calls tells an HR officer nothing. Each line has to name the risk."""
    p = ar.plan(_exit(), granted_roles=ROLES)
    assert all(s["exposure"] for s in p["steps"])
    sessions = [s for s in p["steps"] if s["key"] == "m365_sessions"][0]
    assert "refresh token" in sessions["exposure"]


# ── what the portal can and cannot do ────────────────────────────────────────────────────────────

def test_a_missing_graph_consent_is_named_before_anybody_presses_the_button():
    """Failing at the moment of use, on the day somebody left, is the worst time to discover this."""
    p = ar.plan(_exit(), granted_roles=["Mail.Send"])
    m365 = [s for s in p["steps"] if s["key"] == "m365_account"][0]
    assert m365["missing"] and "User.ReadWrite.All" in m365["blocked"]
    assert "m365_account" not in p["canRunNow"]


def test_user_readwrite_all_does_NOT_let_the_portal_revoke_microsoft_sessions():
    """The correction. I first declared both Microsoft steps as needing User.ReadWrite.All. For
    app-only revokeSignInSessions, Microsoft's permissions table gives Application: least privileged
    "User.RevokeSessions.All", higher privileged "Not available." — User.ReadWrite.All is a DELEGATED
    answer only. Under the old declaration the portal reported the step as runnable, so an owner
    would have granted the wrong permission and hit a 403 at the button on the day somebody left:
    exactly the failure this whole design exists to prevent."""
    p = ar.plan(_exit(), granted_roles=["User.ReadWrite.All"])
    sessions = [s for s in p["steps"] if s["key"] == "m365_sessions"][0]
    assert sessions["missing"] == ["User.RevokeSessions.All"]
    assert "m365_sessions" not in p["canRunNow"]
    # ...while the account step IS satisfied by it, so the two must not share one answer.
    assert "m365_account" in p["canRunNow"]


def test_the_least_privileged_route_is_accepted_and_is_the_one_recommended():
    """Blocking sign-in accepts several permission sets. When none is held, the advice must be the
    set closest to complete — sending somebody to Directory.ReadWrite.All when they are one granular
    permission short of the least-privileged answer is bad security advice."""
    assert "m365_account" in ar.plan(
        _exit(), granted_roles=["User.EnableDisableAccount.All", "User.Read.All"])["canRunNow"]
    near = [s for s in ar.plan(_exit(), granted_roles=["User.Read.All"])["steps"]
            if s["key"] == "m365_account"][0]
    assert near["missing"] == ["User.EnableDisableAccount.All"], "one short, so ask for that one"


def test_blocking_sign_in_admits_it_cannot_verify_the_directory_role():
    """Microsoft requires an app-only caller to ALSO hold a privileged directory role for this
    property. Directory roles are not in the token's `roles` claim, so no amount of reading the token
    can confirm it. Claiming a green light we cannot see would be the tick-box failure again."""
    step = [s for s in ar.plan(_exit(), granted_roles=ROLES)["steps"] if s["key"] == "m365_account"][0]
    assert "directory role" in step["roleCaveat"]
    assert "User Administrator" in step["roleCaveat"]


def test_the_reason_a_step_is_blocked_comes_back_as_a_code_as_well_as_prose():
    """The prose has a permission name glued into the middle of it, so it cannot be translated as a
    unit. The code lets the Vietnamese UI say the same thing in Vietnamese."""
    p = ar.plan(_exit(), granted_roles=["Mail.Send"])
    assert [s for s in p["steps"] if s["key"] == "m365_account"][0]["blockedCode"] == "consent"
    p = ar.plan(_exit(), granted_roles=[], m365_configured=False)
    assert [s for s in p["steps"] if s["key"] == "m365_account"][0]["blockedCode"] == "unconfigured"
    p = ar.plan(_exit(), granted_roles=ROLES)
    assert all(not s["blockedCode"] for s in p["steps"])


def test_with_consent_granted_the_microsoft_steps_can_run():
    p = ar.plan(_exit(), granted_roles=ROLES)
    assert "m365_account" in p["canRunNow"] and "m365_sessions" in p["canRunNow"]


def test_the_portal_steps_never_depend_on_microsoft_being_connected():
    """A tenant outage must not stop the company deactivating its own portal account."""
    p = ar.plan(_exit(), granted_roles=[], m365_configured=False)
    assert set(p["canRunNow"]) == {"portal", "portal_sessions", "portal_pin", "portal_push"}


def test_the_manual_steps_are_never_claimed_as_automatic():
    """Releasing a licence and delegating a mailbox are somebody's job. Reporting them as done
    because the portal ran is exactly the tick-box this replaces."""
    p = ar.plan(_exit(), granted_roles=ROLES)
    manual = [s["key"] for s in p["steps"] if not s["auto"]]
    assert manual and not (set(manual) & set(p["canRunNow"]))


def test_sessions_are_revoked_before_the_account_is_blocked():
    """The other order leaves issued tokens live with no way left to reach them."""
    order = ar.runnable(_exit(), granted_roles=ROLES)
    assert order.index("m365_sessions") < order.index("m365_account")


def test_asking_for_one_step_runs_only_that_step():
    assert ar.runnable(_exit(), keys=["portal_pin"], granted_roles=ROLES) == ["portal_pin"]


def test_a_step_already_done_is_not_run_again():
    rec = ar.record(_exit(), "portal", "HR", at="2026-09-01T09:00:00Z")
    assert "portal" not in ar.runnable(rec, granted_roles=ROLES)


def test_a_step_that_failed_is_recorded_as_failed_not_as_untouched():
    """"Graph refused" and "nobody has been here yet" need different answers from HR."""
    rec = ar.record(_exit(), "m365_account", "HR", note="Graph said 403", at="2026-09-01T09:00:00Z",
                    ok=False)
    step = [s for s in ar.plan(rec, granted_roles=ROLES)["steps"] if s["key"] == "m365_account"][0]
    assert step["done"] is False
    assert step["note"] == "Graph said 403"
    assert "m365_account" in ar.runnable(rec, granted_roles=ROLES), "and it is retried"


def test_recording_does_not_mutate_the_record_it_was_given():
    original = _exit()
    ar.record(original, "portal", "HR", at="2026-09-01T09:00:00Z")
    assert "revoked" not in original


# ── the chase list ───────────────────────────────────────────────────────────────────────────────

def _person(**kw):
    return dict({"empId": "HML-A", "name": "A Person", "dept": "Engineering",
                 "status": "Inactive", "lastDay": "2026-06-30", "exitId": "X1",
                 "live": {"pin": False, "push": 0, "m365": False}}, **kw)


def test_somebody_who_has_not_left_is_not_on_the_list():
    rows = ar.review([_person(status="Active", lastDay="2026-12-31", exitId="")], today="2026-09-01")
    assert rows == []


def test_a_live_microsoft_account_months_after_somebody_left_is_the_top_finding():
    rows = ar.review([_person(live={"pin": False, "push": 0, "m365": True})], today="2026-09-01")
    assert rows[0]["severity"] == "open"
    assert rows[0]["daysSince"] == 63
    assert any(f["key"] == "m365_account" for f in rows[0]["findings"])


def test_a_clean_leaver_does_not_appear_at_all():
    assert ar.review([_person()], today="2026-09-01") == []


def test_somebody_who_was_never_offboarded_through_the_portal_is_found():
    """The ghost this exists for: set to Inactive by hand years ago, no exit record, nobody ever
    touched the mailbox."""
    rows = ar.review([_person(exitId="", live={"pin": True, "push": 2, "m365": True})],
                     today="2026-09-01")
    assert any(f["key"] == "norecord" for f in rows[0]["findings"])
    assert rows[0]["severity"] == "open"


def test_an_unreachable_tenant_is_reported_as_unknown_never_as_clear():
    """The dangerous answer is silence read as an all-clear."""
    rows = ar.review([_person(live={"pin": False, "push": 0, "m365": None})], today="2026-09-01")
    assert rows[0]["severity"] == "unknown"
    assert "could not be checked" in rows[0]["findings"][0]["why"]


def test_a_leftover_push_subscription_is_not_painted_the_same_red_as_a_live_mailbox():
    """If everything is urgent the list stops being read."""
    rows = ar.review([_person(live={"pin": False, "push": 3, "m365": False})], today="2026-09-01")
    assert rows[0]["severity"] == "residual"


def test_an_e_signature_credential_that_still_works_is_a_finding():
    rows = ar.review([_person(live={"pin": True, "push": 0, "m365": False})], today="2026-09-01")
    assert any(f["key"] == "portal_pin" for f in rows[0]["findings"])


def test_a_last_day_in_the_past_counts_as_departed_even_while_the_record_says_active():
    """Somebody whose last day was three weeks ago and whose account nobody touched."""
    rows = ar.review([_person(status="Active", lastDay="2026-08-10",
                              live={"pin": False, "push": 0, "m365": False})], today="2026-09-01")
    assert any(f["key"] == "portal" for f in rows[0]["findings"])


def test_the_worst_and_the_oldest_come_first():
    rows = ar.review([
        _person(empId="RESID", name="Residual", live={"pin": False, "push": 1, "m365": False}),
        _person(empId="NEW", name="Recent", lastDay="2026-08-30",
                live={"pin": False, "push": 0, "m365": True}),
        _person(empId="OLD", name="Ancient", lastDay="2024-01-31",
                live={"pin": False, "push": 0, "m365": True}),
    ], today="2026-09-01")
    assert [r["empId"] for r in rows] == ["OLD", "NEW", "RESID"]


def test_the_summary_counts_what_management_asks_about():
    rows = ar.review([
        _person(empId="A", live={"pin": False, "push": 0, "m365": True}),
        _person(empId="B", lastDay="2024-01-01", live={"pin": False, "push": 1, "m365": False}),
    ], today="2026-09-01")
    s = ar.summary(rows)
    assert s["open"] == 1 and s["residual"] == 1 and s["total"] == 2
    assert s["oldestDays"] == 974
