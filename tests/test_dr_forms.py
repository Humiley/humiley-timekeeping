"""The generated forms, lists and flow must all name the same things.

This file exists for ONE invariant, and it is the whole reason dr_forms.py is a module rather than a
page of documentation:

    a SharePoint list built to dr_forms' specification must be fully readable by
    dr_sharepoint.automap — the code that actually reads it during a sync.

Three artefacts have to agree exactly: the Microsoft Form question title, the SharePoint column it
is written into, and the name the sync looks for. They are built by different people in different
tools, and nothing connects them but a string. When one is wrong the sync reports SUCCESS and the
section prints empty — which is indistinguishable from a quiet day on site.

`test_a_list_built_from_the_spec_is_fully_readable` closes that loop by construction. Everything
else here guards the ways a generated form could be unusable while still looking right: a choice
question with nothing to choose from, a headcount question that does not match the contractor's own
table, or the photo question that Microsoft Forms will not put on an anonymous form.
"""
import pytest

import daily_report
import dr_forms
import dr_sharepoint as sp


TAIKISHA = {
    "id": "C-TAI", "name": "Taikisha", "projectId": "P-MEGA",
    "mgmtRoles": ["Admin", "Cad Staff", "Project Manager Electrical", "Safety man",
                  "Site Manager", "Storage man", "Supervisor"],
    "workerTrades": ["Electrical Works", "Fire Fighting Works", "HVAC", "Other Works",
                     "Plumbing Works"],
    "categories": ["Electrical Works", "Fire Fighting Works", "HVAC Works", "Other Works",
                   "Plumbing Works", "Utility Works"],
}


@pytest.fixture
def pkg():
    return dr_forms.build(TAIKISHA)


def _columns(form):
    """The list's columns as `automap` receives them from Graph: a display title, and an internal
    name that is NOT the title. Modelled that way on purpose — SharePoint derives the internal name
    from the title at creation and then freezes it, and a test that passed the title as both would
    not be testing the thing that actually breaks."""
    return [{"title": c["name"],
             "name": "".join(ch for ch in c["name"] if ch.isalnum())[:32] or "f"}
            for c in form["columns"]]


# ── the invariant ────────────────────────────────────────────────────────────────────────────────
def test_a_list_built_from_the_spec_is_fully_readable(pkg):
    """Every list this module specifies, run through the mapper that reads it during a sync.

    If this fails, an admin can follow the build sheet perfectly and still get an empty section.
    """
    bad = []
    for form in pkg["forms"]:
        m = sp.automap(form["kind"], _columns(form),
                       roles=TAIKISHA["mgmtRoles"], trades=TAIKISHA["workerTrades"])
        if m["missing"]:
            bad.append("%s is missing %s" % (form["listName"], ", ".join(m["missing"])))
    assert not bad, (
        "these generated lists cannot be read back by dr_sharepoint.automap, so a correctly built "
        "form would still import nothing: " + "; ".join(bad))


def test_the_mapper_claims_every_column_the_spec_emits(pkg):
    """Not just the required ones. A column nothing claims is a question somebody answers every day
    whose answer never reaches the report — worse than a missing question, because the site believes
    it is being read."""
    orphans = []
    for form in pkg["forms"]:
        m = sp.automap(form["kind"], _columns(form),
                       roles=TAIKISHA["mgmtRoles"], trades=TAIKISHA["workerTrades"])
        for title in m["unused"]:
            orphans.append("%s: %s" % (form["listName"], title))
    assert not orphans, (
        "these generated columns are read by nothing, so what the site types into them is "
        "discarded: " + "; ".join(orphans))


def test_every_list_kind_the_sync_knows_has_a_form(pkg):
    """A kind the sync can read but nobody can submit to is a section that is always empty."""
    got = {f["kind"] for f in pkg["forms"]}
    assert got == set(sp.LIST_KINDS), (
        "forms and list kinds disagree — only in forms: %s; only in the sync: %s"
        % (sorted(got - set(sp.LIST_KINDS)), sorted(set(sp.LIST_KINDS) - got)))


def test_the_flow_mapping_pairs_each_question_with_the_column_it_writes(pkg):
    """The Power Automate step is built by hand from this. A pair that disagreed would put an
    answer in the wrong column, which reads as corrupt data rather than as a setup mistake."""
    for form in pkg["forms"]:
        titles = {q["title"] for q in form["questions"]}
        cols = {c["name"] for c in form["columns"]}
        assert titles == cols, form["listName"]
        for m in form["flow"]:
            assert m["question"] == m["column"], form["listName"]
        assert len(form["flow"]) == len(form["questions"])


# ── the ways a generated form can be unusable while looking right ────────────────────────────────
def test_every_form_asks_for_the_date_and_the_contractor(pkg):
    """The two that attach a row to a day and a company. A row without a readable date is not
    imported at all — see dr_sharepoint.assemble."""
    for form in pkg["forms"]:
        fields = [q["field"] for q in form["questions"]]
        assert fields[0] == "date" and fields[1] == "contractor", form["listName"]
        assert form["questions"][0]["required"], form["listName"]


def test_a_choice_question_with_no_choices_is_reported_not_emitted_silently(pkg):
    """A Category question on a contractor with no categories is a question nobody can answer. The
    generator still emits it — the admin may be about to add the categories — but it says so."""
    bare = dr_forms.build({"id": "C-NEW", "name": "New Co"})
    needs = [(f["listName"], q["title"]) for f in bare["forms"]
             for q in f["questions"] if q["needsConfig"]]
    assert needs, "a contractor with no categories must raise something"
    said = " ".join(n["msg"] for n in bare["notes"])
    assert "categories" in said and "roles" in said
    # And with the configuration present, nothing is flagged except what genuinely has no list.
    assert not [q for f in pkg["forms"] for q in f["questions"]
                if q["needsConfig"] and q["field"] in ("category", "contractor", "item")]


def test_the_headcount_questions_are_named_as_the_contractors_own_tables_name_them(pkg):
    """The header form asks one number per role and per trade, and `automap` finds those by matching
    the CONTRACTOR's lists — not a fixed table. So the question titles have to be those names
    exactly, or table 2.1 prints zeroes over a form somebody filled in."""
    header = dr_forms.BY_KIND["header"]
    form = [f for f in pkg["forms"] if f["kind"] == "header"][0]
    titles = {q["title"] for q in form["questions"]}
    for name in TAIKISHA["mgmtRoles"] + TAIKISHA["workerTrades"]:
        assert name in titles, name
    m = sp.automap("header", _columns(form),
                   roles=TAIKISHA["mgmtRoles"], trades=TAIKISHA["workerTrades"])
    assert set(m["roles"]) == set(TAIKISHA["mgmtRoles"] + TAIKISHA["workerTrades"])
    assert header["roles"] is True


def test_the_headcount_questions_are_numbers(pkg):
    form = [f for f in pkg["forms"] if f["kind"] == "header"][0]
    for q in form["questions"]:
        if q["field"].startswith("role:"):
            assert q["type"] == "Text (number)", q["title"]


def test_the_safety_choices_are_the_contractors_own_checklist():
    """Section 10 lists the checks the CONTRACTOR is asked about. A form offering the eleven
    defaults to a contractor with its own list would collect answers the report never shows."""
    con = dict(TAIKISHA, safetyChecklist=["Barricade & Warning Sign Check",
                                          "Confined Space Entry Check"])
    form = [f for f in dr_forms.build(con)["forms"] if f["kind"] == "safety"][0]
    item = [q for q in form["questions"] if q["field"] == "item"][0]
    assert item["choices"] == ["Barricade & Warning Sign Check", "Confined Space Entry Check"]
    # And a contractor with no list of its own is offered the eleven shipped checks.
    plain = [f for f in dr_forms.build(TAIKISHA)["forms"] if f["kind"] == "safety"][0]
    plain_item = [q for q in plain["questions"] if q["field"] == "item"][0]
    assert plain_item["choices"] == list(daily_report.SAFETY_DEFAULTS)


def test_the_document_groups_are_the_four_the_report_prints():
    """Section 7 prints four fixed headings. If the form offered a fifth, its rows would be filed
    under "Other Submissions" and nobody would know why."""
    form = [f for f in dr_forms.build(TAIKISHA)["forms"] if f["kind"] == "documents"][0]
    grp = [q for q in form["questions"] if q["field"] == "group"][0]
    assert grp["choices"] == list(daily_report.DOC_GROUPS)


def test_the_photo_question_is_flagged_as_impossible_on_an_anonymous_form(pkg):
    """The constraint that shapes the whole setup. Microsoft Forms offers a file-upload question
    ONLY when responses are restricted to the organisation, so on the "Anyone can respond" form the
    site needs, it cannot exist. Emitted WITH the flag rather than omitted, so the build sheet can
    explain the upload-link route instead of an admin finding a hole later."""
    photos = [f for f in pkg["forms"] if f["kind"] == "photos"][0]
    assert photos["anonymousBlocked"] is True
    blocked = [q for q in photos["questions"] if q["signedInOnly"]]
    assert [q["field"] for q in blocked] == ["photo"]
    # And no OTHER form claims to be blocked — only the one with a file question.
    assert [f["kind"] for f in pkg["forms"] if f["anonymousBlocked"]] == ["photos"]


def test_the_setup_notes_state_the_anonymous_requirement_every_time(pkg):
    """It is the thing that most easily goes wrong and cannot be detected afterwards: a form left
    on the default "Only people in my organisation" simply refuses the site, with no clue at our end."""
    said = " ".join(n["msg"] for n in pkg["notes"])
    assert "Anyone can respond" in said
    assert "upload link" in said or "SharePoint upload" in said


# ── the artefacts ────────────────────────────────────────────────────────────────────────────────
def test_the_graph_body_carries_the_choices_for_a_choice_column(pkg):
    form = [f for f in pkg["forms"] if f["kind"] == "documents"][0]
    body = dr_forms.graph_list_body(form)
    assert body["displayName"] == "Daily Document Exchange"
    grp = [c for c in body["columns"] if c["name"] == "Group"][0]
    assert grp["choice"]["choices"] == list(daily_report.DOC_GROUPS)
    dates = [c for c in body["columns"] if c["name"] == "ReportDate"][0]
    assert dates["dateTime"]["format"] == "dateOnly"


def test_the_powershell_script_creates_every_list_and_every_column(pkg):
    ps = dr_forms.powershell(pkg, "https://humiley.sharepoint.com/sites/Mega")
    for form in pkg["forms"]:
        assert 'New-PnPList -Title "%s"' % form["listName"] in ps, form["listName"]
        for c in form["columns"]:
            assert '-DisplayName "%s"' % c["name"] in ps, (form["listName"], c["name"])
    # Idempotent, because an admin WILL run it twice.
    assert "Get-PnPList" in ps and "SilentlyContinue" in ps


def test_a_quote_in_a_category_cannot_break_the_generated_script():
    """The categories are typed by a person. A stray quote would otherwise end the PowerShell
    string and turn the rest of the line into commands."""
    con = dict(TAIKISHA, categories=['He said "go"', "O'Brien Works"])
    ps = dr_forms.powershell(dr_forms.build(con), "https://x.sharepoint.com/sites/S")
    assert '"go"' not in ps.replace('`"go`"', "")     # the quotes are escaped, not raw
    assert "`\"" in ps


def test_the_flow_is_three_steps_and_names_the_list_it_writes_to(pkg):
    form = [f for f in pkg["forms"] if f["kind"] == "progress"][0]
    steps = dr_forms.flow_steps(form)
    assert [s["step"] for s in steps] == [1, 2, 3]
    assert "Create item" in steps[2]["action"]
    assert steps[2]["detail"].endswith("Daily Work Progress")
    assert {f["column"] for f in steps[2]["fields"]} == {c["name"] for c in form["columns"]}


def test_the_checklist_puts_configuration_before_form_building(pkg):
    """Order matters and is easy to get wrong: the forms are generated FROM the contractor's roles
    and categories, so building forms first means building them twice."""
    steps = dr_forms.checklist(pkg)
    assert "Report Setup" in steps[0]
    assert any("Anyone can respond" in s for s in steps)
    assert any("Check the lists" in s for s in steps)
    assert any("Request files" in s for s in steps)


def test_the_package_serialises(pkg):
    import json
    assert json.loads(dr_forms.as_json(pkg))["contractor"] == "Taikisha"
