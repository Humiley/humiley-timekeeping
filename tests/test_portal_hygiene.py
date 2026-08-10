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


def test_the_contract_rule_dropdowns_offer_exactly_the_codes_the_engine_READS():
    """The select in index.html and the tuples in sales_contract.py are two copies of one list.

    They are matched by exact string, and the engine now REFUSES a rule it cannot read rather than
    silently recovering nothing. That makes drift expensive in a new way: rename a code in Python,
    leave the dropdown alone, and every contract signed afterwards cannot be claimed at all. Cheap
    to check, so check it.
    """
    import sales_contract as SC
    html = INDEX
    for const, rules, what in (("_SCT_RECOVERY", SC.RECOVERY_RULES, "advance recovery"),
                               ("_SCT_RELEASE", SC.RELEASE_RULES, "retention release")):
        m = re.search(r"const %s\s*=\s*\[(.*?)\];" % const, html)
        assert m, "%s is not defined in index.html" % const
        offered = set(re.findall(r"\['([a-z_]+)'", m.group(1)))
        known = {r["code"] for r in rules}
        assert offered == known, ("the %s dropdown offers %s but the engine reads %s"
                                  % (what, sorted(offered), sorted(known)))


def _email_builder():
    """The approval-request email body, sliced out of index.html."""
    i = INDEX.index("function _tkApprovalEmailHtml")
    return INDEX[i:INDEX.index("\nasync function tkEmailApprovalRequest", i)]


def test_the_approval_email_uses_the_REVERSE_mark_on_its_navy_header():
    """The header is #205090. The full-colour logo is an emerald H beside a NAVY wordmark, so on
    navy only the H survives and the company's name vanishes from its own approval email."""
    body = _email_builder()
    assert "_LH.logoWhite" in body, "the email header must take the reverse (white) mark"
    assert "_LH.logo\b" not in body and "_LH.logo " not in body and "_LH.logo)" not in body, \
        "the full-colour letterhead logo belongs on paper, not on the navy email header"
    assert "#205090" in body or "navy" in body


def test_no_email_style_depends_on_a_CSS_VARIABLE():
    """Outlook, Gmail and Apple Mail do not resolve custom properties, and none of these
    declarations carries a fallback. `background:var(--card)` left the card with NO background —
    it only looked right because the client's default happened to be white, and went dark behind
    dark ink in a dark-mode mailbox. This markup is read by mail clients, not by our stylesheet.
    """
    body = _email_builder()
    leaks = re.findall(r"[a-z-]+:\s*var\(--[a-z-]+\)", body)
    assert not leaks, "CSS variables cannot be resolved by a mail client: %s" % leaks
