"""The speak-up channel.

The form is the easy part. These tests are about the three things that make it a channel rather
than a suggestion box: it never routes a concern to the person it is about, it does not promise an
anonymity it cannot deliver, and it has a clock.
"""
import grievance as g


# ── routing: who must NOT see it ─────────────────────────────────────────────────────────────────

def test_a_concern_never_routes_to_somebody_named_in_it():
    """A concern about your manager landing in your manager's queue identifies you to the person
    you were afraid of. That is worse than having no channel at all."""
    out = g.handlers_for({"category": "pay", "about": ["HR1"]}, ["HR1", "HR2"])
    assert out == ["HR2"]


def test_when_every_handler_is_named_it_routes_to_nobody_rather_than_to_them():
    """Returning the subject as a fallback is the failure this exists to prevent."""
    assert g.handlers_for({"category": "pay", "about": ["HR1", "HR2"]}, ["HR1", "HR2"]) == []


def test_that_refusal_is_a_blocker_with_an_instruction_not_a_silent_drop():
    out = g.blockers({"category": "pay", "detail": "x" * 40, "about": ["HR1"]}, ["HR1"])
    assert out and "Everybody who could handle this is named in it" in out[0]
    assert "outside this system" in out[0]


def test_the_reporter_cannot_be_the_handler_of_their_own_concern():
    assert g.handlers_for({"category": "pay", "raisedById": "HR1"}, ["HR1", "HR2"]) == ["HR2"]


def test_matching_is_case_insensitive_so_a_capitalised_id_does_not_slip_through():
    assert g.handlers_for({"category": "pay", "about": ["hr1"]}, ["HR1", "HR2"]) == ["HR2"]


def test_a_serious_category_narrows_to_the_senior_handlers():
    """Harassment and fraud through the ordinary HR queue is too wide a circle."""
    assert g.handlers_for({"category": "harassment"}, ["HR1", "HR2"], senior_ids=["MD"]) == ["MD"]
    assert g.handlers_for({"category": "fraud"}, ["HR1", "HR2"], senior_ids=["MD"]) == ["MD"]
    assert g.handlers_for({"category": "pay"}, ["HR1", "HR2"], senior_ids=["MD"]) == ["HR1", "HR2"]


def test_with_no_senior_designated_a_serious_concern_still_reaches_somebody():
    """Falling back is right here: an unrouted harassment report helps nobody."""
    assert g.handlers_for({"category": "harassment"}, ["HR1"], senior_ids=[]) == ["HR1"]


def test_exactly_two_categories_are_treated_as_serious():
    assert {c["key"] for c in g.CATEGORIES if c["serious"]} == {"harassment", "fraud"}
    assert all(c["labelVn"] for c in g.CATEGORIES)


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

C = {"raisedById": "E1", "routedTo": ["HR1"], "anonymous": False, "category": "pay"}


def test_the_reporter_and_the_routed_handler_may_read_it():
    assert g.may_read(C, "E1", ["HR1", "HR2"]) is True
    assert g.may_read(C, "HR1", ["HR1", "HR2"]) is True


def test_another_handler_it_was_not_routed_to_may_not():
    """Being a handler in general is not being a handler of THIS one."""
    assert g.may_read(C, "HR2", ["HR1", "HR2"]) is False


def test_being_an_administrator_is_not_a_way_in():
    """That is the whole point of the channel. An admin with database access can of course read the
    row; what this stops is the PRODUCT handing it to them."""
    assert g.may_read(C, "ADMIN", ["HR1"]) is False


def test_an_anonymous_concern_does_not_open_to_the_person_who_raised_it():
    """It cannot: the record deliberately does not know who they are. The reference code is how
    they follow up instead — see public_view."""
    assert g.may_read(dict(C, anonymous=True), "E1", ["HR1"]) is False


def test_a_missing_user_id_is_never_a_match():
    assert g.may_read(C, "", ["HR1"]) is False
    assert g.may_read(C, None, ["HR1"]) is False


# ── the reference view ───────────────────────────────────────────────────────────────────────────

FULL = {"ref": "SPK-4F2A", "category": "harassment", "status": g.CLOSED, "raisedOn": "2026-07-01",
        "closedOn": "2026-07-10", "outcome": "Upheld; a written warning was issued.",
        "detail": "the account of what happened", "raisedById": "E1",
        "routedTo": ["MD"], "handlerNotes": "interviewed three people"}


def test_the_reference_view_returns_the_status_and_the_outcome():
    v = g.public_view(FULL, "2026-08-07")
    assert v["ref"] == "SPK-4F2A" and v["status"] == g.CLOSED
    assert v["outcome"].startswith("Upheld")


def test_the_reference_view_leaks_nothing_else():
    """A lucky guess at a reference must not expose somebody's account of events, the handler, or
    the investigation notes."""
    v = g.public_view(FULL, "2026-08-07")
    blob = repr(v)
    for secret in ("the account of what happened", "E1", "MD", "interviewed three people"):
        assert secret not in blob, secret


def test_an_outcome_is_only_shown_once_the_case_is_closed():
    """A half-formed conclusion shown mid-investigation is how a reporter learns the wrong thing."""
    v = g.public_view(dict(FULL, status=g.INVESTIGATING), "2026-08-07")
    assert v["outcome"] == ""


# ── the clock ────────────────────────────────────────────────────────────────────────────────────

def test_the_ordinary_deadline_is_thirty_days_and_a_serious_one_fourteen():
    assert g.resolve_days("pay") == 30
    assert g.resolve_days("harassment") == 14 and g.resolve_days("fraud") == 14


def test_acknowledgement_and_resolution_dates_are_computed_from_the_day_it_was_raised():
    d = g.due({"raisedOn": "2026-07-01", "category": "pay"}, "2026-07-02")
    assert d["ackBy"] == "2026-07-04" and d["resolveBy"] == "2026-07-31"
    assert d["ackLate"] is False and d["overdue"] is False


def test_an_unacknowledged_concern_past_its_date_is_late():
    d = g.due({"raisedOn": "2026-07-01", "category": "pay"}, "2026-07-10")
    assert d["ackLate"] is True and d["acknowledged"] is False


def test_acknowledging_late_is_still_recorded_as_late():
    """Otherwise the number improves by doing the thing late rather than on time."""
    d = g.due({"raisedOn": "2026-07-01", "category": "pay", "acknowledgedOn": "2026-07-20"},
              "2026-08-07")
    assert d["acknowledged"] is True and d["ackLate"] is True


def test_a_closed_concern_stops_counting_days_open():
    d = g.due({"raisedOn": "2026-07-01", "category": "pay", "closedOn": "2026-07-08"}, "2026-08-07")
    assert d["closed"] is True and d["overdue"] is False and d["daysOpen"] == 7


def test_the_deadline_says_it_is_the_companys_own_commitment_not_a_statute():
    assert "not a statutory period" in g.due({"raisedOn": "2026-07-01"}, "2026-07-02")["basis"]


def test_a_concern_with_no_raised_date_has_no_clock_rather_than_a_wrong_one():
    assert g.due({"category": "pay"}, "2026-08-07") is None


# ── what it refuses to record ────────────────────────────────────────────────────────────────────

def test_a_concern_needs_a_category_because_it_decides_who_sees_it_and_how_fast():
    out = g.blockers({"detail": "x" * 40}, ["HR1"])
    assert out and "decides who may see it" in out[0]


def test_a_line_with_no_facts_in_it_is_refused():
    out = g.blockers({"category": "pay", "detail": "it is unfair"}, ["HR1"])
    assert out and "cannot be investigated" in out[0]


def test_with_no_handler_designated_it_says_so_rather_than_swallowing_the_concern():
    out = g.blockers({"category": "pay", "detail": "x" * 40}, [])
    assert out and "No speak-up handler has been designated" in out[0]


def test_a_complete_concern_has_no_blockers():
    assert g.blockers({"category": "safety", "detail": "x" * 40}, ["HR1"]) == []


# ── the promise made to the reporter ─────────────────────────────────────────────────────────────

def test_the_anonymity_notice_does_not_promise_what_the_system_cannot_deliver():
    """Every request carries an authenticated session. Promising true anonymity would be a lie, and
    a speak-up channel that lies about this is worse than none."""
    assert "cannot promise" in g.ANONYMITY_NOTICE
    assert "outside this system" in g.ANONYMITY_NOTICE
    assert g.ANONYMITY_NOTICE_VN and "ẩn danh" in g.ANONYMITY_NOTICE_VN


def test_the_non_retaliation_statement_exists_in_both_languages():
    assert "Retaliation" in g.NO_RETALIATION and "Trả đũa" in g.NO_RETALIATION_VN


# ── the number an auditor asks for ───────────────────────────────────────────────────────────────

def test_the_summary_states_raised_closed_open_and_overdue():
    cs = [
        {"raisedOn": "2026-01-05", "category": "pay", "status": g.CLOSED, "closedOn": "2026-01-10"},
        {"raisedOn": "2026-07-01", "category": "harassment", "status": g.INVESTIGATING},
        {"raisedOn": "2026-08-05", "category": "safety", "status": g.OPEN},
    ]
    s = g.summary(cs, "2026-08-07")
    assert s["total"] == 3 and s["closed"] == 1 and s["live"] == 2
    assert s["overdue"] == 1, "the July harassment case is past its 14 days"
    assert s["unacknowledged"] == 2
    assert "3 concern(s) raised" in s["statement"]


def test_the_summary_groups_by_category_for_the_audit_table():
    s = g.summary([{"raisedOn": "2026-08-01", "category": "safety"},
                   {"raisedOn": "2026-08-02", "category": "safety"},
                   {"raisedOn": "2026-08-03", "category": "pay"}], "2026-08-07")
    assert s["byCategory"][0]["category"] == "safety" and s["byCategory"][0]["count"] == 2
    assert s["byCategory"][0]["label"]


def test_an_empty_channel_reports_zero_rather_than_failing():
    s = g.summary([], "2026-08-07")
    assert s["total"] == 0 and s["overdue"] == 0 and "0 concern(s) raised" in s["statement"]
