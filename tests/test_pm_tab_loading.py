"""Opening a project must not fetch the whole module.

The workspace used to await NINETEEN /api/coll requests before it painted anything — every tab's data
whether or not you were looking at that tab. On a small VPS behind a single-threaded-ish Python server
those queue behind each other, which is why the screen sat on a skeleton.

Each tab now declares what it reads and fetches that on the way in. The declaration IS the contract:
a collection missing from a tab's `need` list does not raise, it renders that register as empty. So
these tests read the actual render functions and check that everything they touch is declared.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(ROOT, "templates", "index.html")


def _src():
    with open(IDX, encoding="utf-8") as fh:
        return fh.read()


def _tabs(src):
    m = re.search(r"const _PM_TABS = \[(.*?)\n\];", src, re.S)
    assert m, "the tab table moved"
    out = []
    for line in m.group(1).splitlines():
        k = re.search(r"\{ k: '([^']+)'.*?fn: '([^']+)'", line)
        if not k:
            continue
        need = re.search(r"need: \[([^\]]*)\]", line)
        out.append({"k": k.group(1), "fn": k.group(2),
                    "need": re.findall(r"'([^']+)'", need.group(1)) if need else []})
    return out


def _fn_body(src, name):
    for prefix in ("\nfunction %s(", "\nasync function %s("):
        at = src.find(prefix % name)
        if at >= 0:
            i = at + 1
            break
    else:
        return ""
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
    return src[i:]


# ── the contract ──────────────────────────────────────────────────────────────────────────────────

def test_every_tab_declares_what_it_reads():
    for t in _tabs(_src()):
        assert t["need"], "tab '%s' declares no collections — it will render empty" % t["k"]


def test_a_tab_declares_every_collection_its_own_render_function_touches():
    """The direct reads, which is the half a reviewer can check mechanically. Anything reached through
       a helper is covered by the per-tab lists being derived from a full call-graph read."""
    src = _src()
    problems = []
    for t in _tabs(src):
        body = _fn_body(src, t["fn"])
        if not body:
            problems.append("%s: render function %s not found" % (t["k"], t["fn"]))
            continue
        touched = set(re.findall(r"_HR\.(pm_\w+)", body))
        touched |= set(re.findall(r"_pmScopeFor\('(pm_\w+)'", body))
        touched |= set(re.findall(r"_HR\[['\"](pm_\w+)['\"]\]", body))
        missing = touched - set(t["need"])
        if missing:
            problems.append("%s reads %s but does not declare it" % (t["k"], sorted(missing)))
    assert not problems, "\n".join(problems)


def test_the_shell_no_longer_loads_everything():
    """The regression this whole change exists to prevent: pmRenderWorkspace awaiting every
       collection would put the 19-request stall straight back."""
    body = _fn_body(_src(), "pmRenderWorkspace")
    assert "_pmLoadAll" not in body, "the workspace is loading every collection again"
    assert "_pmNeed(" in body, "the workspace does not declare what it needs"
    assert "'pm_projects'" in body


def test_the_shell_asks_for_at_most_two_collections():
    """One project record, plus the team rows the below-manager access check reads. Anything more
       belongs to a tab."""
    body = _fn_body(_src(), "pmRenderWorkspace")
    call = re.search(r"_pmNeed\((.*?)\);", body, re.S)
    assert call, "no _pmNeed call in the workspace shell"
    names = set(re.findall(r"'(pm_\w+)'", call.group(1)))
    assert names <= {"pm_projects", "pm_resources"}, "the shell got heavier: %s" % sorted(names)


def test_the_load_everything_helpers_are_gone():
    """_pmReady/_pmLoadAll were the old machinery. Leaving them around invites a future tab to await
       the whole module again by habit."""
    src = _src()
    assert "async function _pmLoadAll" not in src
    assert "async function _pmReady" not in src
    assert "_PM_LATE_TABS" not in src, "the old negative wait-list is still there"


def test_a_tab_that_cannot_load_says_so():
    """A failed fetch and an empty register render identically. tkLoadColl swallows its errors, so
       without this an offline phone shows a project with no risks and no explanation."""
    body = _fn_body(_src(), "pmTab")
    assert "_failed" in body and "Could not load this tab" in body


def test_the_one_click_documents_fetch_their_own_data():
    """The closeout pack spans every register. It used to work only because opening the project had
       already loaded everything — with per-tab loading it has to ask."""
    body = _fn_body(_src(), "pmCloseoutPDF")
    assert "_pmNeed(" in body, "the closeout pack would export empty sections"


def test_chat_declares_the_mention_roster():
    """pm_resources is the @-mention list. Without it the picker silently reports that nobody is on
       the project — the exact silent-starvation failure this table is meant to prevent."""
    chat = [t for t in _tabs(_src()) if t["k"] == "chat"][0]
    assert "pm_resources" in chat["need"]
    assert "pm_chat" in chat["need"]
