"""The accident register, end to end.

osh_incident.py proves the law. This proves the part only the server can: that an accident record
cannot be filed by somebody with no standing to file it, that the account of what happened cannot be
quietly rewritten afterwards, that a fatal accident reaches the people who have to ring the
inspectorate today, and that the frequency rate is computed from real hours or not at all.

The generic /api/coll route is tested explicitly. Every law check in this module would be one URL
away from irrelevant if that route accepted an accident record with no class and no date.
"""
import pytest

import db
import osh_incident as o


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll = 'incidents'")
        conn.commit()
        conn.close()
    wipe()
    yield
    wipe()


WHAT = "Fell from the second lift of the scaffold while fitting supply duct in the corridor."


def _file(api, tokens, who="mgr", **kw):
    body = dict({"class": "serious", "occurredOn": "2026-08-01", "notifiedOn": "2026-08-01",
                 "empId": "HML-STF", "what": WHAT, "injuredCount": 1, "daysLost": 3}, **kw)
    return api("POST", "/api/hr/incidents", tokens[who], body)


# ── who may file, and who may read ───────────────────────────────────────────────────────────────

def test_a_site_manager_can_file_their_own_crews_accident(api, tokens):
    """The person who was there is the one who knows what happened. Waiting for HR loses hours."""
    code, b = _file(api, tokens, "mgr")
    assert code == 200, b
    assert b["incident"]["ref"].startswith("TN-2026-")


def test_staff_cannot_file_or_read_the_register(api, tokens):
    """An accident record names who was hurt and how badly. That is health data."""
    assert _file(api, tokens, "staff")[0] == 403
    assert api("GET", "/api/hr/incidents", tokens["staff"])[0] == 403


def test_it_needs_a_session_at_all(api, tokens):
    assert api("GET", "/api/hr/incidents", None)[0] == 401


# ── what it refuses to record ────────────────────────────────────────────────────────────────────

def test_a_record_with_no_class_is_refused_with_the_reason(api, tokens):
    code, b = _file(api, tokens, **{"class": ""})
    assert code == 400 and "declared today" in b["error"]
    assert b["blockers"]


def test_a_one_line_description_is_refused(api, tokens):
    code, b = _file(api, tokens, what="fell")
    assert code == 400 and "follow it" in b["error"]


def test_a_subcontractor_who_is_not_on_the_payroll_can_still_be_recorded(api, tokens):
    """Your site, your accident — whoever employs the person who was hurt."""
    code, b = _file(api, tokens, empId="", personName="Nguyễn Văn B (subcontractor, Anh Phát)")
    assert code == 200, b
    assert "subcontractor" in b["incident"]["personName"]


def test_the_generic_collection_route_cannot_be_used_to_skip_every_check(api, tokens):
    """The law checks above are worth nothing if there is a second door with no lock on it."""
    code, _ = api("POST", "/api/coll/incidents",
                  tokens["mgr"], {"class": "", "what": "x"})
    assert code in (400, 403), "an accident with no class and no date must not be storable"


# ── the duty that is measured in hours ───────────────────────────────────────────────────────────

def test_filing_a_fatal_accident_returns_the_instruction_not_a_flag(api, tokens):
    _, b = _file(api, tokens, **{"class": "fatal"})
    d = b["declare"]
    assert d["required"] is True
    assert any("police" in t.lower() for t in d["to"])
    assert any("Department of Labour" in t for t in d["to"])
    assert "fastest means" in d["how"]


def test_a_serious_accident_injuring_one_does_not_claim_the_immediate_duty(api, tokens):
    _, b = _file(api, tokens, injuredCount=1)
    assert b["declare"]["required"] is False


def test_the_deadline_comes_back_with_the_record(api, tokens):
    _, b = _file(api, tokens, **{"class": "fatal"})
    assert b["deadline"]["days"] == 30
    assert b["deadline"]["due"] == "2026-08-31"


def test_an_undeclared_fatal_accident_is_the_first_thing_the_register_says(api, tokens):
    _file(api, tokens, **{"class": "minor", "daysLost": 0})
    _, filed = _file(api, tokens, **{"class": "fatal", "occurredOn": "2026-08-02",
                                     "notifiedOn": "2026-08-02"})
    _, r = api("GET", "/api/hr/incidents?asOf=2026-08-07", tokens["mgr"])
    assert [u["ref"] for u in r["undeclared"]] == [filed["incident"]["ref"]]
    assert r["rows"][0]["ref"] == filed["incident"]["ref"]


def test_recording_the_declaration_clears_it(api, tokens):
    _, b = _file(api, tokens, **{"class": "fatal"})
    code, _ = api("POST", "/api/hr/incidents/" + b["incident"]["id"], tokens["mgr"],
                  {"declaredOn": "2026-08-01"})
    assert code == 200
    _, r = api("GET", "/api/hr/incidents?asOf=2026-08-07", tokens["mgr"])
    assert r["undeclared"] == []


# ── the record is evidence, not a draft ──────────────────────────────────────────────────────────

def test_the_account_of_what_happened_cannot_be_rewritten_afterwards(api, tokens):
    """A later hand tidying up the description is what an investigator looks for first."""
    _, b = _file(api, tokens)
    iid = b["incident"]["id"]
    api("POST", "/api/hr/incidents/" + iid, tokens["mgr"],
        {"what": "Tripped, no injury.", "class": "minor", "occurredOn": "2026-01-01"})
    _, r = api("GET", "/api/hr/incidents?asOf=2026-08-07", tokens["mgr"])
    row = r["rows"][0]
    assert row["what"] == WHAT
    assert row["class"] == "serious" and row["occurredOn"] == "2026-08-01"


def test_the_follow_up_facts_can_be_added_as_they_become_known(api, tokens):
    _, b = _file(api, tokens)
    code, upd = api("POST", "/api/hr/incidents/" + b["incident"]["id"], tokens["mgr"],
                    {"reportPublishedOn": "2026-08-06", "daysLost": 11,
                     "rootCause": "No edge protection on the second lift.",
                     "correctiveAction": "Guard rails fitted; toolbox talk 7 Aug."})
    assert code == 200
    assert upd["incident"]["daysLost"] == 11
    assert upd["deadline"]["late"] is False, "published on the 6th, due the 8th"


def test_updating_something_that_does_not_exist_is_a_404_not_a_new_record(api, tokens):
    assert api("POST", "/api/hr/incidents/inc-nope", tokens["mgr"], {"daysLost": 1})[0] == 404


def test_both_filing_and_updating_land_in_the_audit_log(api, tokens):
    _, b = _file(api, tokens, **{"class": "fatal"})
    api("POST", "/api/hr/incidents/" + b["incident"]["id"], tokens["mgr"], {"declaredOn": "2026-08-01"})
    # By this record's own ref — the audit chain is append-only and carries every other test's rows.
    rows = [r for r in db.list_collection("audit")
            if str(r.get("target") or "") == "incidents/" + b["incident"]["ref"]]
    assert len(rows) == 2
    assert any("MUST BE DECLARED" in str(r.get("detail")) for r in rows)


# ── the register ─────────────────────────────────────────────────────────────────────────────────

def test_the_register_reports_the_next_statutory_filing_date(api, tokens):
    _, r = api("GET", "/api/hr/incidents?asOf=2026-03-01", tokens["mgr"])
    assert r["nextReport"]["due"] == "2026-07-05"


def test_an_empty_register_is_a_real_answer_not_an_error(api, tokens):
    code, r = api("GET", "/api/hr/incidents", tokens["mgr"])
    assert code == 200 and r["total"] == 0 and r["undeclared"] == []


def test_it_counts_days_lost_and_open_investigations(api, tokens):
    _file(api, tokens, daysLost=3, **{"class": "minor"})
    _file(api, tokens, daysLost=12, occurredOn="2026-08-03", notifiedOn="2026-08-03")
    _, r = api("GET", "/api/hr/incidents?asOf=2026-08-20", tokens["mgr"])
    assert r["daysLost"] == 15 and r["open"] == 2 and r["lateInvestigations"] == 2


def test_the_frequency_rate_is_refused_unless_the_hours_are_real(api, tokens):
    """The one figure a client's safety audit compares across contractors."""
    _file(api, tokens)
    _, r = api("GET", "/api/hr/incidents?asOf=2026-08-07", tokens["mgr"])
    if r["frequency"]["rate"] is None:
        assert "guessed denominator" in r["frequency"]["why"]
        assert "No attendance hours" in r["hoursBasis"]
    else:
        assert r["frequency"]["hours"] > 0
        assert "from recorded attendance" in r["hoursBasis"]


def test_a_nonsense_asOf_falls_back_to_today_rather_than_crashing(api, tokens):
    code, r = api("GET", "/api/hr/incidents?asOf=yesterday", tokens["mgr"])
    assert code == 200 and len(r["asOf"]) == 10


def test_the_classes_come_from_the_server_so_the_form_cannot_invent_one(api, tokens):
    _, r = api("GET", "/api/hr/incidents", tokens["mgr"])
    assert [c["key"] for c in r["classes"]] == [o.MINOR, o.SERIOUS, o.FATAL]
    assert all(c["labelVn"] for c in r["classes"])
