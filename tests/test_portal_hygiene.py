"""Whole-portal hygiene: nothing orphaned, nothing unparseable, nothing half-translated.

These are the checks that stop a big single-file frontend rotting quietly. Every one of them exists
because the equivalent mistake was actually made in this codebase: a function whose only caller was
deleted, a screen defined but never in the DOM, a Vietnamese screen with an English sentence in it.
"""
import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "templates" / "index.html").read_text()
SCRIPTS = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", INDEX, re.S)


def test_every_inline_script_block_parses():
    """A syntax error in a 2.4MB single-file app takes the WHOLE portal down, not one screen."""
    assert SCRIPTS, "no inline script found — re-point this test"
    for i, block in enumerate(SCRIPTS):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(block)
            path = f.name
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, "script block %d does not parse:\n%s" % (i, r.stderr[:400])


def test_no_sell_side_function_is_defined_without_a_caller():
    """Retiring a UI orphans its helpers. Six were left behind by the deal-side quotation builder
    and by making the VAT rate optional; this is what stops the seventh."""
    body = max(SCRIPTS, key=len)
    names = set(re.findall(r"\n(?:async )?function (_?(?:crm|qt)[A-Za-z0-9_]+)\s*\(", body))
    orphans = [n for n in sorted(names) if len(re.findall(r"\b%s\b" % re.escape(n), INDEX)) <= 1]
    assert not orphans, "defined but never called: %s" % ", ".join(orphans)


def test_every_view_container_the_router_renders_actually_exists():
    """A router entry pointing at a container that is not in the document is a screen that silently
    renders nothing — the failure mode is a blank page, which reads as "no data"."""
    rendered = set(re.findall(r"if \(id === '([a-z0-9-]+)'\) \{ try \{", INDEX))
    missing = [v for v in sorted(rendered) if ('id="view-%s"' % v) not in INDEX]
    assert not missing, "router renders views with no container: %s" % ", ".join(missing)


def test_the_sell_side_screens_carry_no_untranslated_sentence():
    """A screen is not bilingual because its labels are: the explanatory lines are the ones that
    make somebody act, and they were the last English leak on an otherwise Vietnamese page."""
    start = INDEX.find("/* ═══ Billing & cash ══")
    end = INDEX.find("/* ═══ Sales Compliance ══")
    assert start > 0 and end > start, "the sell-side block moved — re-point this test"
    block = INDEX[start:end]
    # every user-facing sentence goes through _t2(en, vn) or _crmEsc(_t2(...))
    singles = re.findall(r"_t\('([^']{25,})'\)", block)
    assert not singles, "single-language sentences on a bilingual screen: %s" % singles[:3]


def test_no_screen_prints_a_raw_float_as_money():
    """"277225000.00" beside a column reading ₫277,225,000 happened twice — once on the claim, once
    on the customer statement. Money is formatted, or it is not money."""
    for name in ("crmRenderBilling", "crmRenderRetention", "crmStatement", "crmOpenClaim"):
        at = INDEX.find("function " + name)
        assert at > 0, name
        body = INDEX[at:at + 6000]
        assert ".toFixed(2)" not in body, "%s formats money by hand" % name
