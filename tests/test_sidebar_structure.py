"""The sidebar's nav items must be siblings, never nested inside one another.

A single missing `</div>` in the AHU section put every later section — Estimating, HR, Finance,
System Setting — INSIDE the "Production Standard" nav item. Nothing looked wrong: the sidebar
rendered correctly, because a `.nav-item` containing more markup still lays out as a row. But a
click on any of those buried rows bubbled to the enclosing AHU item, whose `onclick` ran last and
won, so choosing Estimating from the app board landed on AHU Production.

That is why the assertion here is STRUCTURAL rather than visual. The thing that broke is
invisible to rendering and invisible to reading the file — the indentation was still right — and
only shows up if you ask the parser who somebody's parent is.

`_sbWrap()` depends on the same contract: it collects each label's following SIBLINGS up to the
next label. Nested items are not siblings, so they land in the wrong group, and `tkOpenApp()`
then clicks the wrong app's first row.
"""
import io
import os
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "templates", "index.html")

# Tags that never nest: an unclosed one of these is a parse artefact, not a real container.
VOID = {"img", "br", "hr", "input", "meta", "link", "path", "circle", "rect", "line",
        "polyline", "polygon", "use", "source", "ellipse", "stop", "area", "col", "embed"}


class Sidebar(HTMLParser):
    """Records the depth of every element inside .sidebar-scroll, and what is left open."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.stack = []
        self.found = []          # (depth, tag, class, data-appgrp, onclick)

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        cls = at.get("class", "") or ""
        if "sidebar-section-label" in cls or "nav-item" in cls:
            self.found.append((self.depth, tag, cls, at.get("data-appgrp"),
                               at.get("onclick") or ""))
        if tag not in VOID:
            self.depth += 1
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in VOID:
            self.depth -= 1
            if self.stack:
                self.stack.pop()


def _parse(src):
    a = src.index('<div class="sidebar-scroll">')
    b = src.index("</div><!-- /sidebar-scroll -->")
    p = Sidebar()
    p.feed(src[a:b] + "</div>")
    return p


def _current():
    return io.open(HTML, encoding="utf-8").read()


def test_every_nav_item_and_section_label_is_a_direct_child_of_the_scroll_area():
    """The contract _sbWrap() and tkOpenApp() both rest on. Depth 1 = a sibling of the labels."""
    p = _parse(_current())
    buried = [(cls, oc[:60]) for depth, _t, cls, _g, oc in p.found if depth != 1]
    assert not buried, (
        "%d sidebar rows are nested instead of siblings — a click on them will bubble to the "
        "enclosing nav item and navigate somewhere else:\n  %s"
        % (len(buried), "\n  ".join("%s %s" % b for b in buried)))


def test_the_sidebar_markup_closes_everything_it_opens():
    p = _parse(_current())
    assert p.stack == [], "unclosed inside .sidebar-scroll: %s" % p.stack


def test_every_app_group_owns_at_least_one_nav_item():
    """A section label with no rows under it is an app the board cannot open — tkOpenApp() finds
    no items and refuses."""
    p = _parse(_current())
    groups, cur = {}, None
    for depth, _t, cls, grp, _oc in p.found:
        if depth != 1:
            continue
        if "sidebar-section-label" in cls:
            cur = grp
            groups.setdefault(cur, 0)
        elif cur is not None:
            groups[cur] += 1
    assert groups, "no section labels found at all"
    empty = [g for g, n in groups.items() if n == 0]
    assert not empty, "app groups with no nav items: %s" % empty


def test_this_guard_actually_catches_the_bug_it_was_written_for():
    """Run the check against the defect, not only against the fix.

    Reproduces the exact shape of the regression — a nav item left unclosed before the next
    section label — and asserts the structural check fails on it. Without this, the guard could be
    asserting nothing and would pass just as happily.
    """
    broken = _current().replace(
        "    <span class=\"nav-label\">Production Standard</span>\n  </div>\n",
        "    <span class=\"nav-label\">Production Standard</span>\n", 1)
    assert broken != _current(), "fixture did not reproduce the defect — the anchor moved"
    p = _parse(broken)
    buried = [c for d, _t, c, _g, _o in p.found if d != 1]
    assert buried, "the guard would NOT have caught the unclosed nav item"
    assert p.stack != [], "the balance check would NOT have caught it either"
