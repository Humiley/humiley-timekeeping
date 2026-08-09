"""Every sell-side endpoint is reachable from a screen, and the Billing screen is really in the DOM.

Twice on this build I shipped machinery with no door: /api/sales/compliance and
/api/sales/accounts/review existed for a whole stage with nothing in the browser that called them,
and then /api/sales/application, /einvoice, /receipt and /receivables did the same. A check nobody
can reach is a check nobody runs, and a claim nobody can raise means the contract balances sit at
their opening figures for ever while the real ones live in somebody's spreadsheet.

So the rule is a test, not a habit. The second group is the other half of the same lesson: a
function can exist and still be unreachable if it is trapped inside a string, so the screen has to
be proved present in the actual DOM and wired into the router, not merely defined somewhere.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_text()
INDEX = (ROOT / "templates" / "index.html").read_text()

ROUTES = sorted(set(re.findall(r'path == "(/api/sales/[a-z\-/]+)"', APP)))


def test_the_routes_were_actually_found():
    """If the route-declaration style changes, this file must be re-pointed rather than silently
    passing over an empty list."""
    assert len(ROUTES) >= 10, ROUTES


def _called_from_a_screen(route):
    """A call site is the path in a quoted string, closed or continued by a query string —
    tkApi('/api/sales/trace?id=' + id) is a call, and so is tkApi('/api/sales/retention')."""
    return re.search(r"""['"]%s(\?|['"])""" % re.escape(route), INDEX) is not None


def test_every_sell_side_endpoint_has_something_that_calls_it():
    orphans = [r for r in ROUTES if not _called_from_a_screen(r)]
    assert not orphans, "no screen calls: %s" % ", ".join(orphans)


def test_the_orphan_check_can_actually_fail():
    """The guard is worth nothing if it matches anything. A route nobody has ever written must not
    look called."""
    assert not _called_from_a_screen("/api/sales/does-not-exist")


# ── the Billing screen is present, not merely defined ───────────────────────────────────────────

def _script_ranges(html):
    out, i = [], 0
    while True:
        a = html.find("<script", i)
        if a < 0:
            return out
        b = html.find("</script>", a)
        if b < 0:
            return out + [(a, len(html))]
        out.append((a, b))
        i = b + 9


def _in_markup(needle):
    """True only if `needle` sits in the document's markup, not inside a <script> block.

    This is the check that would have caught the modals that lived for weeks inside a demo popup's
    template literal: present in the file, greppable, and never once in the DOM."""
    at = INDEX.find(needle)
    assert at >= 0, needle
    return not any(a < at < b for a, b in _script_ranges(INDEX))


def test_the_billing_view_container_is_in_the_document_body():
    """Not inside a template literal, not inside a function that builds a modal — in the HTML."""
    assert _in_markup('id="view-crm-billing"')
    assert _in_markup('id="crm-billing-root"')


def test_the_check_can_fail__a_container_that_only_exists_in_a_string_is_caught():
    """The guard above is worth nothing if it passes on everything. A root div that a renderer only
    writes into innerHTML lives inside a <script> block, and must come back False."""
    assert _in_markup("crm-billing-root") is True
    assert _in_markup("document.getElementById('crm-billing-root')") is False


def test_the_tab_bar_offers_it_and_the_router_renders_it():
    assert "['crm-billing', 'Billing']" in INDEX
    assert "'crm-billing': 'Billing & Cash'" in INDEX
    assert "'crm-billing'," in INDEX.split("_CRM_HUB_VIEWS")[1][:400]
    assert "if (id === 'crm-billing') { try { crmRenderBilling();" in INDEX


def test_the_render_function_is_declared_at_top_level():
    """A function defined inside another function's string is invisible to the router that names it."""
    assert re.search(r"^async function crmRenderBilling\(\)", INDEX, re.M)


def test_the_screen_says_the_portal_does_not_issue_the_invoice():
    """The one sentence on this screen that stops it being read as an invoicing module."""
    assert "This portal does not issue the invoice" in INDEX
    assert "UNVERIFIED" in INDEX


def test_the_three_clocks_are_not_added_up_on_the_screen_either():
    """The backend refuses to sum them; the screen must not helpfully do it instead."""
    strip = INDEX[INDEX.find("async function crmRenderBilling"):INDEX.find("async function crmNewClaim")]
    assert strip, "the billing renderer moved — re-point this test"
    assert "retentionHeldByCustomers" in strip and "advanceOwedBack" in strip
    assert re.search(r"retentionHeldByCustomers\s*\+\s*", strip) is None
    assert "whyNotOneNumber" in strip, "the reason travels with the three figures"


def test_the_claim_statement_is_composed_from_the_stored_figures():
    """Not echoed from the stored sentence. A claim certified before the money formatting changed
    still carries "277225000.00 payable" in its statement field; the figures beside it are the
    record, and the sentence has to agree with them and be readable in either language."""
    modal = INDEX[INDEX.find("async function crmOpenClaim"):INDEX.find("async function crmClaimCertify")]
    assert modal, "the claim modal moved — re-point this test"
    assert "_crmEsc(a.statement)" not in modal
    assert "certified, less %a advance recovery" in modal


def test_the_unverified_note_speaks_the_readers_language():
    """The server's note is the record and is English. The sentence on the screen is composed from
    the flag, so a Vietnamese user is not told in English that their invoice is unverified."""
    modal = INDEX[INDEX.find("async function crmOpenClaim"):INDEX.find("async function crmClaimCertify")]
    assert "_crmEsc(a.einvNote" not in modal
    assert "CHƯA XÁC MINH" in modal


def test_the_retention_screen_is_present_and_wired():
    assert _in_markup('id="view-crm-retention"')
    assert "['crm-retention', 'Retention']" in INDEX
    assert "if (id === 'crm-retention') { try { crmRenderRetention();" in INDEX
    assert re.search(r"^async function crmRenderRetention\(\)", INDEX, re.M)


def test_the_two_retention_actions_are_reachable_from_the_contract():
    """Recording acceptance and recording a release both live on the contract modal — the screen
    where somebody is already looking at the money."""
    modal = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    assert "crmContractAccept(" in modal and "crmReleaseRetention(" in modal


def test_the_undateable_group_is_shown_rather_than_filtered_out():
    """A contract holding money whose release date cannot be computed is the one most likely to be
    lost. Hiding it because it doesn't fit the table is how it stays lost."""
    r = INDEX[INDEX.find("async function crmRenderRetention"):INDEX.find("async function crmContractAccept")]
    assert "undateable" in r and "cannot yet be dated" in r


def test_the_trail_is_reachable_from_both_places_a_person_would_look_for_it():
    ct = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    cl = INDEX[INDEX.find("async function crmOpenClaim"):INDEX.find("async function crmClaimCertify")]
    assert "crmTrace(" in ct and "crmTrace(" in cl


def test_the_trail_shows_the_gaps_before_the_documents():
    """A list of documents is reassuring. The thing worth reading is what is missing from it, so it
    goes first."""
    fn = INDEX[INDEX.find("async function crmTrace"):INDEX.find("\n/* ═══ Retention ══")]
    assert fn, "the trail moved — re-point this test"
    assert fn.index("gapBox +") < fn.index("(r.steps || []).map(step)")


def test_every_gap_code_the_server_can_emit_has_a_bilingual_entry_on_the_screen():
    """The server's `why` is English. A code with no entry here falls back to it and tells a
    Vietnamese reader in English what is wrong with their order."""
    codes = set(re.findall(r'"what": "([a-z\-]+)"', APP))
    table = INDEX[INDEX.find("const _TR_GAP"):INDEX.find("async function crmTrace")]
    assert table, "the gap table moved — re-point this test"
    missing = [c for c in codes if ("'%s'" % c) not in table]
    assert not missing, "no bilingual entry for: %s" % ", ".join(sorted(missing))
    assert len(codes) >= 6, codes
