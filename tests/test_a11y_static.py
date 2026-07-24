"""Static accessibility guards for the single-file frontend — cheap regression gates (no browser)
that pin the a11y fixes so a future edit can't silently undo them."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "templates", "index.html")


def _src():
    with open(HTML, encoding="utf-8") as f:
        return f.read()


def test_no_anchor_onclick_without_href():
    """<a onclick> with no href is not keyboard-focusable — these were converted to <button>.
    Guard against reintroducing them (regex allows an href anywhere in the tag)."""
    bad = [m.group(0)[:80] for m in re.finditer(r"<a\b(?![^>]*\bhref=)[^>]*\bonclick=", _src())]
    assert not bad, "clickable <a> without href (use a <button>): " + " | ".join(bad[:5])


def test_all_images_have_alt_text():
    """Every <img> needs alt (or aria-hidden) so screen readers describe or skip it."""
    missing = [m.group(0)[:90] for m in re.finditer(r"<img\b[^>]*>", _src())
               if "alt=" not in m.group(0) and "aria-hidden" not in m.group(0)]
    assert not missing, "<img> without alt/aria-hidden: " + " | ".join(missing[:5])


def test_landmarks_and_focus_scaffolding_present():
    """The skip-link, the aria-live toast region, the main landmark, and the global focus ring must
    all be present — the load-bearing pieces of keyboard/screen-reader support."""
    s = _src()
    assert re.search(r'class="skip-link"', s), "skip-to-content link missing"
    assert re.search(r'id="toast"[^>]*aria-live', s), "toast is not an aria-live region"
    assert re.search(r'id="content"[^>]*role="main"', s), "#content main landmark missing"
    assert ":focus-visible{" in s, "global :focus-visible ring missing"
    assert "@media (prefers-reduced-motion:reduce)" in s, "reduced-motion guard missing"
