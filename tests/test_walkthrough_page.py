# -*- coding: utf-8 -*-
"""docs/daily-report-walkthrough.html stays bilingual and stays readable in both themes.

It is a single self-contained page that gets sent to clients, so the two ways it rots are invisible
to everybody who last looked at it in their own language and their own theme:

  * a paragraph edited in English and not in Vietnamese — the toggle hides the English and nothing
    replaces it, so the block simply vanishes for half the audience;
  * a colour added to the light palette and not the dark one — which renders light text on a light
    ground for a reader whose OS is set to dark.

Neither shows up in a diff, and neither is something the author is positioned to notice.
"""
import io
import os
import re
from html.parser import HTMLParser

import pytest

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs", "daily-report-walkthrough.html")
VOID = {"br", "hr", "img", "input", "link", "meta", "source", "col", "area", "base", "wbr"}


@pytest.fixture(scope="module")
def src():
    return io.open(PAGE, encoding="utf-8").read()


class _Tree(HTMLParser):
    """Just enough DOM to ask what an element's next sibling is."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = {"tag": "#root", "lang": None, "line": 0, "kids": []}
        self.path = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
            return
        if self.skip or tag in VOID:
            return
        cls = dict(attrs).get("class", "").split()
        node = {"tag": tag, "line": self.getpos()[0], "kids": [],
                "lang": "en" if "en" in cls else ("vi" if "vi" in cls else None)}
        self.path[-1]["kids"].append(node)
        self.path.append(node)

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID:
            return
        for i in range(len(self.path) - 1, 0, -1):
            if self.path[i]["tag"] == tag:
                del self.path[i:]
                return


def test_every_english_block_has_a_vietnamese_one(src):
    """Adjacency, not counts. One element with two `.vi` siblings and another with none balances
    perfectly and still renders a hole — which is exactly what a half-finished edit looks like."""
    t = _Tree()
    t.feed(src)
    problems, pairs = [], 0

    def visit(node):
        langs = [k for k in node["kids"] if k["lang"]]
        i = 0
        while i < len(langs):
            cur = langs[i]
            nxt = langs[i + 1] if i + 1 < len(langs) else None
            if cur["lang"] == "en":
                if not nxt or nxt["lang"] != "vi":
                    problems.append("line %d: <%s class=en> has no .vi sibling"
                                    % (cur["line"], cur["tag"]))
                    i += 1
                    continue
                i += 2
            else:
                problems.append("line %d: <%s class=vi> with no .en before it"
                                % (cur["line"], cur["tag"]))
                i += 1
        for k in node["kids"]:
            visit(k)

    visit(t.root)
    # Guards the guard: if the pairing markup were ever refactored away, every assertion above
    # would pass on a page it was no longer looking at.
    assert src.count('class="en"') > 50, "the page no longer uses paired en/vi blocks"
    assert not problems, "\n".join(problems[:20])


def _tokens(css, pattern):
    m = re.search(pattern, css, re.S)
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", m.group(1))) if m else set()


def test_both_themes_resolve(src):
    css = src[src.index("<style>"):src.index("</style>")]
    root = _tokens(css, r":root\{(.*?)\n\}")
    media = _tokens(css, r"@media \(prefers-color-scheme:dark\)\{\s*"
                         r":root:not\(\[data-theme=\"light\"\]\)\{(.*?)\n  \}")
    stamp = _tokens(css, r":root\[data-theme=\"dark\"\]\{(.*?)\n\}")

    assert root and media and stamp, "one of the three theme blocks is missing entirely"

    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
    assert not used - root, "var() with no definition: %s" % sorted(used - root)

    # A token defined only inside a dark block never applies in the DEFAULT "system" state, which
    # stamps no data-theme at all — the state most viewers are actually in.
    assert not (media | stamp) - root, "dark-only token: %s" % sorted((media | stamp) - root)

    colour = {t for t in root if re.search(
        r"navy|ink|mut|faint|paper|ground|sunk|line|good|warn|stop|site|fill|header", t)}
    assert not colour - (media & stamp), \
        "colour with no dark value: %s" % sorted(colour - (media & stamp))
    assert not media ^ stamp, \
        "the OS default and the explicit toggle disagree: %s" % sorted(media ^ stamp)

    assert re.search(r"body\{[^}]*background:var\(", css), \
        "body must paint its own background or it borrows the host's"


def test_the_page_is_self_contained(src):
    """It gets emailed and opened offline. Google Fonts may fail to load — everything else must not
    be there to fail."""
    hosts = set(re.findall(r"""(?:src|href)=["'](https?://[^/"']+)""", src))
    assert hosts <= {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}, \
        "external dependency: %s" % sorted(hosts)
    assert "font-family:var(--body)" in src and "Arial" in src, "fonts need a real fallback stack"
