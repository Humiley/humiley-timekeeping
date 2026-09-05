"""Which collections does /api/coll serve to everybody, and is that on purpose?

Reads here are DEFAULT-ALLOW. A collection joins COLLECTIONS and, unless something names it, every
authenticated account with the owning app is served every row. That is a reasonable default for a
single-office portal full of shared operational registers — and it is silent, which is the problem.

eng_refusals sat in that set while tests/test_eng_commission_boundary.py said in prose that "the
read is management-only". The sentence was never true and never checked. Measured before it was
fixed, every account — including one on none of the commissions — was served every refusal in the
office, each naming a colleague and repeating what they were told when they were stopped.

Nothing was careless. There was simply no place where the question "who can read this?" had to be
answered out loud, so for a new collection the answer was whatever the default happened to be.

This is that place. Every collection is either reached by one of the scope mechanisms below, or
listed in SHARED with a reason. Adding a collection and running the suite forces the choice; it
does not decide it. A shared register inside one office is a legitimate answer — "nobody thought
about it" is not, and those two used to look identical.
"""
import re

import pytest

import app


H = app.Handler


def _src():
    with open(app.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
        return fh.read()


# ── the mechanisms that can scope a read ────────────────────────────────────────
#
# Five class-level sets, plus the per-name branches inside _coll_list. The branch names are written
# out here rather than parsed, because a regex over a method body is exactly the kind of instrument
# that keeps reporting a clean sheet after the thing it greps for was renamed. _the_named_branches_
# _are_still_there asserts the list against the source, so it cannot drift quietly either way.
NAMED_IN_COLL_LIST = {
    "certificates",   # health data — scoped to the caller's own crew below management
    "audit",          # non-admins get the e-signature subset only
    "pm_chat",        # scoped to the projects you can open — people write candidly there
    "hrdocs",         # audience rule re-checked server-side; bytes served separately
    "contracts",      # your own is yours to read (Art. 13(1)); nobody else's
    "decisions",
    "hrletters",
    "payruns",        # your own payslip line from finalised runs only
    "candidates",     # CV bytes stripped from the list
    "eng_refusals",   # scoped by design authority — see the module docstring above
}


def _scope_mechanisms():
    covered = set(H.READ_MIN) | set(getattr(H, "CONFIDENTIAL", ())) \
        | set(getattr(H, "SELF_OWNED", ())) | set(getattr(H, "TEAM_SCOPED", ())) \
        | set(getattr(H, "SALES_SCOPED", ())) | NAMED_IN_COLL_LIST
    # crm_ is scoped by prefix (salesperson -> department -> all), except the shared catalogue.
    covered |= {c for c in H.COLLECTIONS if c.startswith("crm_") and c != "crm_products"}
    return covered


# ── collections served to every account with the owning app, and why ────────────
#
# Grouped by the reason, not alphabetically, because the reason is the part a reviewer has to agree
# with. Moving a name OUT of here means adding a scope; moving one IN means writing why.
SHARED = {
    # Shared catalogues. No personal data, and every account needs them to render a form.
    "courses", "learningpaths", "benefits", "schedules", "crm_products",
    # Project delivery registers. The office runs projects together; a task list, an issue log and
    # a site report are meant to be visible across the team. pm_costs / pm_procurement /
    # pm_procurement_payments are NOT here — they carry commercial terms and are manager-gated.
    "pm_projects", "pm_settings", "pm_deliverables", "pm_tasks", "pm_detail", "pm_schedules",
    "pm_quality", "pm_quality_itp", "pm_resources", "pm_comms",
    "pm_issues", "pm_risks", "pm_changes", "pm_lessons", "pm_stakeholders", "pm_rfis",
    "pm_sitereports", "pm_weekreports",
    # Hồ sơ nghiệm thu. Same class as pm_quality and pm_quality_itp beside it, and shared for a
    # stronger reason than convenience: an acceptance dossier is the document the client and the
    # supervision consultant are ENTITLED to see, and Nghị định 06/2021 Điều 26 requires the set to
    # be assembled and kept. A site engineer who cannot read what was accepted upstream cannot tell
    # whether their own work may be covered up. There is no personal data on any of the five — a
    # signatory's NAME is on the minute, but a name printed on a document a third party signs is
    # not the same thing as the HR record the SELF_OWNED mechanism exists for.
    #
    # Deliberately NOT manager-gated the way pm_costs is: nothing here carries a price. The reason
    # pm_costs is scoped is commercial terms, and an acceptance minute has none.
    "pm_acc", "pm_acc_items", "pm_acc_plans", "pm_acc_forms", "pm_acc_defects",
    # pm_acc_drawings is the marked-up drawing the minute points at, so it is part of the same
    # document and shares its answer. The one thing it adds is BYTES — a dozen A3 rasters — and
    # that is a size question, answered by _strip_file_bytes on the list read, not a scope one.
    "pm_acc_drawings",
    # pm_acc_index is the completion dossier's table of contents — the document the client and the
    # construction authority work through at handover. Everyone on the project needs to see what is
    # still missing from it; that is the entire purpose of the list. It holds no personal data: a
    # declaration carries the declarer's NAME, which is the point of an attestation and is printed
    # on the sheet anyway.
    "pm_acc_index",
    #
    # pm_execNotes, pm_portfolioSnapshots and pm_quality_itp_items used to be listed here. They
    # were registered and reached by nothing — no endpoint, no screen, no test — and are now
    # de-registered entirely, the tables having been confirmed empty. De-registering does not
    # delete rows; it stops /api/coll serving the name at all, which is why the confirmation
    # mattered and why it was not done on my own judgement.
    #
    # Worth keeping visible: while they sat here, pm_quality_itp_items was in this list TWICE —
    # once among the live project registers and once in the block that called it dead. Both
    # statements were in the same set literal, which dedupes, so nothing failed. A file written to
    # stop a claim about who-can-read going unchecked had a contradictory claim inside it for a
    # week. The lesson is not "be careful"; it is that prose in a list is only as good as the test
    # beside it, and there was no test on this one until now.
    # Design control. Measured and recorded in test_eng_commission_boundary.py: a staff account
    # sees every commission's registers. Workable inside one design office where everyone is
    # staff; NOT a boundary a client-facing view can be built on. eng_refusals was pulled out of
    # this set because it is a record about people rather than about drawings.
    "eng_projects", "eng_team", "eng_stages", "eng_inputs", "eng_deliverables", "eng_revisions",
    "eng_reviews", "eng_comments", "eng_changes", "eng_tq", "eng_idc", "eng_standards",
    "eng_deviations", "eng_risks", "eng_chases", "eng_timelogs", "eng_competence", "eng_holds",
    "eng_transmittals",
    # The baseline is a record of the PLAN, not of a person. Everyone working the commission is
    # measured against it, so everyone on it should be able to see what it says — a schedule
    # judgement people cannot inspect is one they cannot dispute. Writes are refused for every
    # account through ISSUED_ONLY; only the server takes one.
    "eng_baselines",
    # Production floor. An operator has to see the order, the unit, the route and the parts to do
    # the next step; a QC inspector has to see the whole trail.
    "ahu_orders", "ahu_units", "ahu_steps", "ahu_bom", "ahu_docs", "ahu_trace", "ahu_ncr",
    "ahu_dispatch", "ahu_instruments", "ahu_complaints", "ahu_quals",
}


def test_every_collection_has_an_answer_to_who_can_read_it():
    """The whole point. A new collection is scoped, or it is listed above with a reason."""
    unclassified = sorted(H.COLLECTIONS - _scope_mechanisms() - SHARED)
    assert not unclassified, (
        "These collections are served in full to every account with the owning app, and nothing "
        "says whether that is intended:\n  %s\n\n"
        "Decide, then record the decision. Either give it a read scope (READ_MIN, SELF_OWNED, "
        "TEAM_SCOPED, CONFIDENTIAL, or a branch in _coll_list — and add it to NAMED_IN_COLL_LIST "
        "here), or add it to SHARED above with the reason it is shared. Both are legitimate; "
        "leaving the question unanswered is what produced the eng_refusals leak."
        % "\n  ".join(unclassified))


# The three collections that were registered and reached by nothing are now de-registered. They
# are named here rather than simply forgotten, because "the name is gone" and "nobody has re-added
# it" are different facts and only the second stays true on its own.
GONE = ("pm_execNotes", "pm_portfolioSnapshots", "pm_quality_itp_items")


def test_the_de_registered_collections_stay_gone():
    """Re-adding one to COLLECTIONS would put an unowned, unreadable-by-design name back on
    /api/coll — reachable, writable in one case, and read by no screen. If it comes back it should
    come back with a reader and a reason, and this failing is how that conversation starts."""
    back = sorted(c for c in GONE if c in H.COLLECTIONS)
    assert not back, (
        "de-registered collection(s) are in COLLECTIONS again: %s. If one is genuinely needed, "
        "give it a screen and a line in SHARED saying who reads it — it was removed because it "
        "had neither." % ", ".join(back))


def test_nothing_still_writes_to_them(api, tokens):
    """The API must not serve the name at all — not 403, not an empty list. A 404 is what tells a
    caller the collection does not exist, and an empty 200 would read as "there is nothing in it"."""
    for name in GONE:
        st, _ = api("GET", "/api/coll/" + name, tokens["admin"])
        assert st == 404, "%s still answers GET with %s" % (name, st)
        st, _ = api("POST", "/api/coll/" + name, tokens["admin"], {"x": 1})
        assert st == 404, "%s still accepts a POST (%s)" % (name, st)


def test_nothing_is_listed_as_shared_and_scoped_at_once():
    """A stale SHARED entry is worse than a missing one: it states, in writing, that a collection
    is open to everybody when it is not — and the next person reads that instead of the code."""
    both = sorted(SHARED & _scope_mechanisms())
    assert not both, (
        "Now scoped, but still listed as shared above — remove from SHARED:\n  %s"
        % "\n  ".join(both))


def test_shared_does_not_name_a_collection_that_no_longer_exists():
    ghosts = sorted(SHARED - H.COLLECTIONS)
    assert not ghosts, "SHARED names collections that are gone: %s" % ", ".join(ghosts)


def test_the_named_branches_are_still_there():
    """NAMED_IN_COLL_LIST is written out by hand, so it can rot in both directions: a branch
    deleted from _coll_list would leave this file asserting a scope that no longer runs."""
    src = _src()
    i = src.index("    def _coll_list(self, u, name):")
    j = src.index("\n    def ", i + 10)
    body = src[i:j]
    missing = sorted(c for c in NAMED_IN_COLL_LIST if '"%s"' % c not in body)
    assert not missing, (
        "NAMED_IN_COLL_LIST claims _coll_list scopes these, and it does not mention them:\n  %s"
        % "\n  ".join(missing))


# ── and the map has to match the behaviour ──────────────────────────────────────
#
# Everything above is static. A static map of who-can-read agreeing with itself is worth very
# little — the eng_refusals docstring agreed with itself for months. These two go through the API.

@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def test_a_collection_listed_as_shared_really_is(api, tokens):
    """Characterisation, not approval. If this ever fails, the register was scoped and SHARED was
    not updated — which is the drift this file exists to catch."""
    st, b = api("POST", "/api/coll/pm_tasks", tokens["admin"],
                {"projectId": "SCOPE-PRJ", "name": "A task somebody else owns"})
    assert st == 200, b
    st, b = api("GET", "/api/coll/pm_tasks", tokens["other"])
    assert st == 200, b
    assert any(x.get("id") == "SCOPE-PRJ" or x.get("projectId") == "SCOPE-PRJ"
               for x in b["items"]), "pm_tasks is listed as shared but did not reach a staff account"


def test_a_collection_that_is_scoped_really_is(api, tokens):
    """The other direction, on the collection that started this. A staff account on no design
    commission must get nothing — not a 403 it can distinguish, just no rows.

    Two ways this went wrong before it worked, both worth keeping written down.

    It first asserted an empty list and nothing else, and PASSED against the unfixed code: the log
    was empty in a fresh database, and `[] == []` is true whether the scope exists or not. A check
    examining nothing, in the file written to stop checks that examine nothing. So a refusal is
    provoked, and the admin read is asserted non-empty, before any absence is claimed.

    Then it asserted "Other Staff sees NO refusals", which passed alone and failed in the full run.
    The database is shared across the session and another file makes Other Staff the lead of its
    own commission — so they legitimately see refusals, just not these. The assertion is therefore
    about THIS gate, selected by id. "Sees nothing at all" was never the rule; "sees nothing from a
    commission they are not on" is.
    """
    proj = api("POST", "/api/coll/eng_projects", tokens["admin"], {
        "name": "Scope probe", "code": "SCP26", "client": "A Client",
        "designManager": "Dept Manager", "leadEngineer": "Staff One",
        "status": "Active", "currentStage": "Detail", "members": "Staff One"})[1]["item"]
    api("POST", "/api/coll/eng_holds", tokens["staff"], {
        "projectId": proj["id"], "kind": "hold", "ref": "H-SCOPE", "title": "Open",
        "status": "open"})
    gate = api("POST", "/api/coll/eng_stages", tokens["staff"], {
        "projectId": proj["id"], "stage": "Detail", "status": "At gate"})[1]["item"]
    st, _ = api("POST", "/api/esign", tokens["staff"], {
        "coll": "eng_stages", "id": gate["id"], "meaning": "probe", "setStatus": "Passed"})
    assert st != 200, "expected the open hold to refuse this gate"

    st, b = api("GET", "/api/coll/eng_refusals", tokens["admin"])
    assert st == 200, b
    assert [x for x in b["items"] if x.get("recordId") == gate["id"]], \
        "nothing was logged for this gate — the assertion below would prove nothing"

    st, b = api("GET", "/api/coll/eng_refusals", tokens["other"])
    assert st == 200, b
    leaked = [x for x in b["items"] if x.get("recordId") == gate["id"]]
    assert not leaked, (
        "a refusal on a commission this account is not on was served to it: %r" % (leaked[0],))
    assert all(x.get("projectId") != proj["id"] for x in b["items"]), \
        "and nothing else from that commission should reach them either"
