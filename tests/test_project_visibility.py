"""Being on a project Team must actually let you see the project.

The bug, as an engineer hit it: Nguyen Van Trung — Senior Civil Engineer, PMC — had the Projects app
switched on, opened it, and got "You are not assigned to any projects yet". That empty state then told
him the remedy: *"A manager can add you to a project Team (Resources tab) or set you as its Project
Manager."*

The first half of that sentence was false. `_pmAssigned` decided visibility from exactly two things:

    (p.manager || '').toLowerCase() === me || _pmMembers(p).includes(me)

`p.members` is never populated — `grep -c "k: 'members'"` over the whole frontend returns **0**, so no
form can write it. And the Resources tab writes `pm_resources` rows, which this function never read.
So adding somebody to the project Team changed nothing at all, and the only route to seeing a project
was to BE its Project Manager. A whole engineering team could be staffed onto a job and every one of
them would see an empty screen, with the app confidently telling their manager to do the one thing
that could not work.

The fix reads the Team. These tests pin both halves: that membership grants access, and that it grants
access to that project only.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _fn(src, name):
    """Pull one top-level `function name(...) {...}` out by brace matching. Handles `async` too."""
    for prefix in ("\nfunction %s(", "\nasync function %s("):
        at = src.find(prefix % name)
        if at >= 0:
            i = at + 1
            break
    else:
        raise AssertionError("no top-level function " + name)
    depth, j, started = 0, i, False
    while j < len(src):
        if src[j] == "{":
            depth += 1
            started = True
        elif src[j] == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unterminated function " + name)


def _run(js, level="staff", me="Nguyen Van Trung"):
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    harness = (
        "const _LEVELS = ['staff','manager','management','editor','admin'];\n"
        "function _lvlRank(l){const i=_LEVELS.indexOf(l);return i<0?1:i+1;}\n"
        "let _userLevel = %s;\n"
        "const TK = { user: { id: 'HML-TRUNG', name: %s, email: 'trung.nguyen@humiley.com' } };\n"
        "const _HR = { pm_projects: [], pm_resources: [] };\n" % (json.dumps(level), json.dumps(me))
        + "\n".join(_fn(src, n) for n in ("_pmSeeAll", "_pmMembers", "_pmAssigned", "_pmMine"))
        + "\n" + js
    )
    p = os.path.join(tempfile.mkdtemp(prefix="tk-pmvis-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


PROJECTS = """
  _HR.pm_projects = [
    { id: 'P1', code: 'PMC-004', manager: 'Tony Nguyen' },
    { id: 'P2', code: 'PMC-011', manager: 'Tony Nguyen' },
    { id: 'P3', code: 'PMC-014', manager: 'Nguyen Van Trung' }
  ];
"""
OUT = "console.log(JSON.stringify(_pmMine(_HR.pm_projects).map(p => p.code)));"


# ── the bug ───────────────────────────────────────────────────────────────────────────────────────

def test_a_team_member_sees_the_project_they_are_staffed_on():
    """THE test. A manager adds them via the Resources tab — which is what the empty state instructs —
       and the project appears."""
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r1', projectId: 'P1', name: 'Nguyen Van Trung',
                            projectRole: 'Senior Civil Engineer', allocationPct: 60 }];
    """ + OUT)
    assert "PMC-004" in out, "being on the project Team still does not let you see it"


def test_without_a_team_row_they_only_see_what_they_manage():
    """The state Trung was actually in: app enabled, on no team, so only his own project."""
    out = _run(PROJECTS + "_HR.pm_resources = [];" + OUT)
    assert out == ["PMC-014"]


def test_being_the_project_manager_still_works():
    out = _run(PROJECTS + "_HR.pm_resources = [];" + OUT)
    assert "PMC-014" in out


def test_a_seeded_members_list_still_works():
    """`members` cannot be written by any form, but records seeded or imported with it must not
       silently lose visibility."""
    out = _run("""
      _HR.pm_projects = [{ id: 'P9', code: 'PMC-SEED', manager: 'Tony Nguyen',
                           members: 'Son Nguyen, Nguyen Van Trung' }];
      _HR.pm_resources = [];
    """ + OUT)
    assert out == ["PMC-SEED"]


def test_names_are_matched_forgivingly():
    """Whether somebody can do their job must not turn on a stray space or a capital letter — the
       Resources 'Member' field is a picker, but rows arrive from imports and older data too."""
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r2', projectId: 'P2', name: '  nguyen van TRUNG ' }];
    """ + OUT)
    assert "PMC-011" in out


# ── and grants nothing more ───────────────────────────────────────────────────────────────────────

def test_somebody_elses_team_row_grants_nothing():
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r3', projectId: 'P1', name: 'Son Nguyen' }];
    """ + OUT)
    assert out == ["PMC-014"], "another person's team row opened a project"


def test_a_team_row_with_no_project_opens_nothing():
    """A malformed row must not become a skeleton key across the whole portfolio."""
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r4', name: 'Nguyen Van Trung' }];
    """ + OUT)
    assert out == ["PMC-014"]


def test_membership_is_per_project_not_global():
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r5', projectId: 'P1', name: 'Nguyen Van Trung' }];
    """ + OUT)
    assert sorted(out) == ["PMC-004", "PMC-014"], "one team row exposed unrelated projects"


def test_an_anonymous_session_sees_nothing():
    out = _run(PROJECTS + """
      _HR.pm_resources = [{ id: 'r6', projectId: 'P1', name: '' }];
    """ + OUT, me="")
    assert out == []


def test_a_manager_still_sees_everything():
    """Team membership is the route in for people BELOW manager. It must not narrow anyone."""
    out = _run(PROJECTS + "_HR.pm_resources = [];" + OUT, level="manager")
    assert sorted(out) == ["PMC-004", "PMC-011", "PMC-014"]


# ── the loader has to supply the data the check needs ─────────────────────────────────────────────

def test_the_projects_list_loads_the_team_for_users_who_need_it():
    """_pmAssigned reads _HR.pm_resources, so the list must fetch it — otherwise the check runs
       against an empty array and every project looks unassigned, which is the original bug wearing a
       different hat. Managers see everything anyway, so their five-request paint is unchanged."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    core = _fn(src, "_pmLoadCore")
    assert "_pmSeeAll()" in core and "'pm_resources'" in core, \
        "the Projects list does not load the team it now depends on"
    assert "_PM_CORE_COLLS = ['pm_projects', 'pm_deliverables', 'pm_tasks', 'pm_risks', 'pm_costs']" in src, \
        "the manager's lean core set changed — check the list still paints in five requests"


def test_the_empty_state_still_describes_a_route_that_works():
    """It tells the user a manager can add them to the Team. That sentence was false for the life of
       the feature; if the Team check is ever removed again, this fails."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    assert "Resources tab" in src, "the empty state's instruction disappeared"
    assert "pm_resources" in _fn(src, "_pmAssigned"), \
        "the empty state promises the Resources tab works, and it does not"
