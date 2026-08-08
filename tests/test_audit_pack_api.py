"""The client social-compliance audit pack.

Nine sections, assembled from the registers that already hold them. The two things these tests are
here to hold down:

  · the pack does not RECOMPUTE anything — it calls the same review functions the screens call, so
    the pack and the screen can never tell a client two different things;
  · a section with no data says so, and says which register would fill it. An empty section that
    reads like a pass is the failure this is built to avoid, and it is the failure an auditor is
    most likely to catch.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    before = {e["id"]: dict(e) for e in db.list_employees()}

    def wipe():
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll IN "
                     "('incidents','concerns','decisions','contracts','certificates','payruns')")
        conn.execute("DELETE FROM attendance")
        conn.commit()
        conn.close()
    wipe()
    db.set_setting("portal_wageRegion", "")
    db.set_setting("portal_speakupHandlers", None)
    yield
    wipe()
    db.set_setting("portal_wageRegion", "")
    db.set_setting("portal_speakupHandlers", None)
    for eid, v in before.items():
        db.update_employee(eid, v)


SECTIONS = ("contracts", "hours", "wages", "insurance", "leave",
            "safety", "young", "voice", "discipline")


# ── who may assemble it ──────────────────────────────────────────────────────────────────────────

def test_it_contains_every_wage_and_date_of_birth_so_it_is_management_and_above(api, tokens):
    assert api("GET", "/api/hr/audit-pack", tokens["staff"])[0] == 403
    assert api("GET", "/api/hr/audit-pack", tokens["mgr"])[0] == 403
    assert api("GET", "/api/hr/audit-pack", tokens["management"])[0] == 200


def test_it_needs_a_session(api, tokens):
    assert api("GET", "/api/hr/audit-pack", None)[0] == 401


# ── all nine sections, always ────────────────────────────────────────────────────────────────────

def test_every_section_is_present_even_with_an_empty_database(api, tokens):
    """Four of the nine had no export at all before this. A pack that quietly omits the sections it
    cannot answer is how a company discovers the gap in front of the auditor."""
    code, r = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    assert code == 200, r
    assert [s["key"] for s in r["sections"]] == list(SECTIONS)


def test_every_section_names_the_law_it_answers_to(api, tokens):
    _, r = api("GET", "/api/hr/audit-pack", tokens["management"])
    for s in r["sections"]:
        assert s["basis"], s["key"]
        assert s["labelVn"], s["key"]


def test_a_section_with_nothing_behind_it_says_which_register_would_fill_it(api, tokens):
    _, r = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    ins = [s for s in r["sections"] if s["key"] == "insurance"][0]
    assert "No signed pay run" in ins["statement"]
    assert ins["findings"], "and it is a finding, not a blank"
    assert "Payroll" in ins["emptyHint"]


def test_the_pack_carries_a_caveat_that_an_empty_section_is_not_a_pass(api, tokens):
    _, r = api("GET", "/api/hr/audit-pack", tokens["management"])
    assert "it is not evidence that there is nothing to report" in r["caveat"]
    assert r["caveatVn"]


# ── the sections agree with the registers they came from ─────────────────────────────────────────

def test_the_wage_section_is_the_wage_register_not_a_second_calculation(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"wageRegion": "I", "salary": 4_000_000})
    _, pack = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    _, reg = api("GET", "/api/hr/minwage?asOf=2026-08-08", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "wages"][0]
    assert sec["statement"] == reg["statement"]
    assert sec["data"]["below"] == reg["below"]


def test_the_safety_section_is_the_accident_register(api, tokens):
    api("POST", "/api/hr/incidents", tokens["mgr"],
        {"class": "fatal", "occurredOn": "2026-08-01", "notifiedOn": "2026-08-01",
         "empId": "HML-STF", "injuredCount": 1,
         "what": "Fell from the second lift of the scaffold while fitting supply duct."})
    _, pack = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "safety"][0]
    assert "1 accident(s) recorded" in sec["statement"]
    assert any("must be declared" in f for f in sec["findings"])


def test_the_young_worker_section_is_the_article_144_register(api, tokens):
    for e in db.list_employees():
        db.update_employee(e["id"], {"dob": "1990-01-01"})
    db.update_employee("HML-STF", {"dob": "2010-01-01"})
    _, pack = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    _, reg = api("GET", "/api/hr/minors?asOf=2026-08-08", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "young"][0]
    assert sec["statement"] == reg["statement"]
    assert sec["data"]["minors"] == reg["minors"] == 1


# ── the speak-up section reports the CHANNEL, never the concerns ─────────────────────────────────

def test_the_speak_up_section_never_carries_what_anybody_said(api, tokens):
    """An audit asks whether a channel exists and is answered in time, not what was reported. The
    concerns themselves are the one thing in this company nobody assembles into a pack."""
    db.set_setting("portal_speakupHandlers", "HML-MGT,HML-EDT")
    api("POST", "/api/hr/speakup", tokens["staff"],
        {"category": "pay", "detail": "On 3 August the site supervisor told me to work through my "
                                      "rest day without recording it."})
    _, pack = api("GET", "/api/hr/audit-pack", tokens["management"])
    import json
    body = json.dumps(pack, ensure_ascii=False)
    assert "work through my rest day" not in body
    assert "handlerNotes" not in body
    sec = [s for s in pack["sections"] if s["key"] == "voice"][0]
    assert sec["data"]["designatedHandlers"] == 2


def test_one_designated_handler_is_a_finding_because_a_concern_about_them_has_nowhere_to_go(api, tokens):
    db.set_setting("portal_speakupHandlers", "HML-MGT")
    _, pack = api("GET", "/api/hr/audit-pack", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "voice"][0]
    assert any("nowhere independent to go" in f for f in sec["findings"])


def test_designating_nobody_is_a_finding_of_its_own(api, tokens):
    """The channel still works — it falls back to the HR admins — but a company cannot evidence a
    channel as independent when it never decided who staffs it."""
    db.set_setting("portal_speakupHandlers", None)
    _, pack = api("GET", "/api/hr/audit-pack", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "voice"][0]
    assert any("No speak-up handler is designated" in f for f in sec["findings"])
    assert sec["data"]["designatedHandlers"] == 0


def test_two_handlers_clears_it(api, tokens):
    db.set_setting("portal_speakupHandlers", "HML-MGT,HML-EDT")
    _, pack = api("GET", "/api/hr/audit-pack", tokens["management"])
    sec = [s for s in pack["sections"] if s["key"] == "voice"][0]
    assert sec["findings"] == []


# ── the headline ─────────────────────────────────────────────────────────────────────────────────

def test_the_pack_counts_its_own_findings(api, tokens):
    _, r = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    assert r["findings"] == sum(len(s["findings"]) for s in r["sections"])
    assert "9 section(s)" in r["statement"]


def test_it_names_the_company_it_is_about(api, tokens):
    _, r = api("GET", "/api/hr/audit-pack", tokens["management"])
    assert "company" in r and "headcount" in r


def test_an_inactive_employee_is_not_counted_in_the_headcount(api, tokens):
    _, before = api("GET", "/api/hr/audit-pack", tokens["management"])
    db.update_employee("HML-STF", {"status": "Inactive"})
    try:
        _, after = api("GET", "/api/hr/audit-pack", tokens["management"])
        assert after["headcount"] == before["headcount"] - 1
    finally:
        db.update_employee("HML-STF", {"status": "Active"})


def test_a_section_nobody_could_measure_never_renders_as_nothing_outstanding(api, tokens):
    """Caught in the browser, not by a test: the wages section showed "nothing outstanding" in
    green while its own statement said no employee could be checked. A section is coloured by its
    finding count, so an unmeasured section with no findings reads as a pass — the exact thing this
    pack exists to prevent, and the first thing an auditor would seize on."""
    for e in db.list_employees():
        db.update_employee(e["id"], {"wageRegion": "", "salary": 9_000_000})
    db.set_setting("portal_wageRegion", "")
    _, r = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    sec = [s for s in r["sections"] if s["key"] == "wages"][0]
    assert "could not be checked" in sec["statement"]
    assert sec["findings"], "an unmeasured section must never be empty-and-green"
    assert "could not be checked against any wage floor" in sec["findings"][0]


def test_a_genuinely_clean_wage_section_has_no_findings(api, tokens):
    """…and the guard above must not make every section permanently amber."""
    for e in db.list_employees():
        db.update_employee(e["id"], {"wageRegion": "I", "salary": 9_000_000})
    _, r = api("GET", "/api/hr/audit-pack?asOf=2026-08-08", tokens["management"])
    sec = [s for s in r["sections"] if s["key"] == "wages"][0]
    assert sec["findings"] == []
    assert "at or above" in sec["statement"]
