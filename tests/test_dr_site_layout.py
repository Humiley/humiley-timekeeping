# -*- coding: utf-8 -*-
"""The site form on a phone, an iPad and a laptop.

Layout itself needs a browser and these tests do not pretend otherwise. What they pin are the
source-level facts that silently break it — the ones that look fine in a diff and are only visible
as a wrong-shaped page somebody on a building site will not report.
"""
import io
import os
import re

import pytest

PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "templates", "dr_site.html")


@pytest.fixture(scope="module")
def css():
    s = io.open(PAGE, encoding="utf-8").read()
    return s[s.index("<style>"):s.index("</style>")]


@pytest.fixture(scope="module")
def page():
    return io.open(PAGE, encoding="utf-8").read()


def test_the_responsive_rules_come_after_the_rules_they_override(css):
    """The bug this file was written for. The media queries were placed next to `.wrap`, which read
    well and did nothing: `.sections` is `display:flex` in a base rule further down, and a media
    query of the SAME specificity appearing EARLIER loses the cascade. The iPad stayed one column,
    every source-level check passed, and only opening it at 768px showed it."""
    for override in (".sections", ".bar", ".g2", ".doc .mk"):
        base = css.index(override + "{") if (override + "{") in css else css.index(override)
        for width in ("min-width:700px", "min-width:1024px"):
            mq = css.index("@media (" + width + ")")
            assert mq > base, \
                "@media (%s) is above the base rule for %s, so it cannot override it" % (
                    width, override)


def test_every_breakpoint_the_brief_named_is_present(css):
    """Phone, iPad, desktop. A missing breakpoint is not a crash — it is a page that merely looks
    unfinished on one of the three devices it was asked to work on."""
    for q in ("max-width:400px", "min-width:700px", "min-width:1024px"):
        assert "@media (" + q + ")" in css, "no rules for %s" % q


def test_form_text_stays_at_sixteen_pixels(css):
    """Not a style choice: anything smaller and iOS Safari zooms the whole page the moment a field
    takes focus, which on a form of fourteen sections is a page the site fights all day."""
    m = re.search(r"input,select,textarea\{([^}]*)\}", css, re.S)
    assert m, "the shared field rule is gone"
    assert "font:16px" in m.group(1), "fields are not 16px: %r" % m.group(1)


def test_the_page_handles_the_notch(page, css):
    """iPhone. Without the viewport flag and the insets the header sits under the status bar and the
    save bar under the home indicator."""
    assert "viewport-fit=cover" in page
    assert "env(safe-area-inset-top)" in css
    assert "env(safe-area-inset-bottom)" in css


def test_touch_targets_are_not_pointer_sized(css):
    assert "@media (hover:none)" in css, "no touch-specific sizing at all"
    m = re.search(r"@media \(hover:none\)\{(.*?)\n  \}", css, re.S)
    assert m and "min-height" in m.group(1), "touch devices get no minimum target size"


def test_the_page_fetches_nothing(page):
    """It is opened by people with no portal account, often on a plant-room connection. Every
    external request is another chance for the form not to appear — and a form that does not appear
    is a report somebody emails as a photo of a notebook instead."""
    hosts = re.findall(r"""(?:src|href)=["'](https?:)?//""", page)
    assert not hosts, "the page reaches off-origin: %s" % hosts
    assert "<link" not in page.lower(), "an external stylesheet or font would block first paint"


def test_the_three_marks_are_drawn_on_a_white_ground(css):
    """Owner, Humiley and contractor. Most of this artwork is dark on transparent, so on any
    coloured ground about half of it disappears — looking exactly like a logo nobody set."""
    row = re.search(r"\.doc \.marks\{([^}]*)\}", css, re.S)
    assert row, "no .doc .marks rule"
    assert "background:#fff" in row.group(1).replace(" ", ""), \
        "the masthead marks have no white ground: %r" % row.group(1)

    mk = re.search(r"\.doc \.mk\{([^}]*)\}", css, re.S)
    assert mk, "no .doc .mk rule"
    assert "display:none" in mk.group(1), \
        "a mark must be hidden until there is a logo to show, or it reserves an empty box"
    assert ".doc .mk.on{display:flex}" in css.replace("\n", " "), \
        "nothing turns a mark on"


def test_the_platform_palette_is_the_platforms(css):
    """This page and the portal must not drift apart on the brand. These are index.html's values."""
    for token, value in (("--navy", "#205090"), ("--emerald", "#00B060"),
                         ("--danger", "#C00000"), ("--line", "#dde2ee")):
        assert re.search(re.escape(token) + r":\s*" + re.escape(value), css, re.I), \
            "%s is not the platform's %s" % (token, value)


def test_headings_on_the_navy_bar_set_their_colour_explicitly(css):
    """The base rule paints headings navy, which is right on every white card and catastrophic on
    the navy bar — it painted the title navy-on-navy and left it barely readable. A colour that
    arrives only by inheritance is one a later rule can take away without touching the element it
    belongs to."""
    m = re.search(r"header h1\{([^}]*)\}", css, re.S)
    assert m, "no header h1 rule"
    assert "color:#fff" in m.group(1).replace(" ", ""), \
        "the header title relies on inherited colour: %r" % m.group(1)


def test_there_is_one_focus_colour(css):
    """`input:focus` (0,1,1) outranks `:focus-visible` (0,1,0), so a page can end up with two focus
    treatments — fields one colour, buttons another — without anybody choosing that. It did."""
    rules = re.findall(r"([^{}]*focus[^{}]*)\{([^}]*)\}", css, re.S)
    colours = set()
    for _sel, body in rules:
        m = re.search(r"outline:[^;]*solid\s+var\((--[a-z-]+)\)", body)
        if m:
            colours.add(m.group(1))
    assert colours, "nothing sets a focus outline at all"
    assert colours == {"--emerald"}, \
        "focus is not one accent colour: %s" % sorted(colours)


def test_elevation_is_a_ring_and_not_a_smudge(css):
    """HML-BG-002: flat and engineered, no heavy drop shadows. The page had a 34px soft drop under
    every card, which on a phone in daylight reads as a smudge rather than an edge."""
    m = re.search(r"--shadow-card:([^;]*);", css)
    assert m, "no --shadow-card token"
    blur = [int(x) for x in re.findall(r"(\d+)px", m.group(1))]
    assert max(blur) <= 24, "the card shadow is heavier than the system allows: %s" % m.group(1)
    assert "--ring:inset 0 0 0 1px" in css.replace(" ", " "), \
        "no hairline ring token — the card edge is a shadow again"
