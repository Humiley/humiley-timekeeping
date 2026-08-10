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


def _method_body(name):
    """Just that one method — sliced to the next def at the same indentation.

    Slicing to a named later method is how this test quietly started reading a neighbour's code:
    a method inserted in between put `"kind": "advance"` (a stored receipt's type, not a trail step)
    inside the window, and the check failed on something it was never meant to see."""
    a = APP.find("    def %s(" % name)
    assert a >= 0, name
    b = APP.find("\n    def ", a + 1)
    return APP[a:b if b > 0 else len(APP)]


TRACE = _method_body("_trace_ep")


def test_the_trace_body_was_actually_found():
    assert TRACE and '"kind": "quotation"' in TRACE, "the trace endpoint moved — re-point these"


def test_every_gap_code_the_server_can_emit_has_a_bilingual_entry_on_the_screen():
    """The server's `why` is English. A code with no entry here falls back to it and tells a
    Vietnamese reader in English what is wrong with their order."""
    codes = set(re.findall(r'"what": "([a-z\-]+)"', TRACE))
    table = INDEX[INDEX.find("const _TR_GAP"):INDEX.find("async function crmTrace")]
    assert table, "the gap table moved — re-point this test"
    missing = [c for c in codes if ("'%s'" % c) not in table]
    assert not missing, "no bilingual entry for: %s" % ", ".join(sorted(missing))
    assert len(codes) >= 6, codes


def test_every_step_kind_the_trail_can_emit_has_a_bilingual_label():
    """Same rule as the gap codes. A kind with no entry falls back to the raw machine string, so a
    Vietnamese reader gets "po" instead of "Đơn đặt hàng của khách"."""
    kinds = set(re.findall(r'"kind": "([a-z\-]+)"', TRACE))
    table = INDEX[INDEX.find("const _TR_STEP"):INDEX.find("const _TR_GAP")]
    assert table, "the step table moved — re-point this test"
    missing = [k for k in kinds if (k + ":") not in table]
    assert not missing, "no bilingual label for: %s" % ", ".join(sorted(missing))
    assert len(kinds) >= 7, kinds


def test_the_purchase_order_and_the_deposit_are_on_the_contract_screen():
    ct = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    assert "_ctPoBlock(c, id)" in ct and "_ctDepositBlock(c, id, draft)" in ct


def test_the_deposit_is_no_longer_a_single_percentage_box():
    """One "Advance %" box forced anybody with a "₫200,000,000 on signing" PO to convert it into a
    percentage by hand, and the recovery was then wrong by whatever the rounding lost."""
    ct = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    assert "num('advancePct'" not in ct
    assert "advanceSchedule: _ctDepositRead()" in INDEX


def test_the_vat_treatment_can_be_filled_in_from_a_screen():
    """It named two tax questions for weeks and offered nowhere to answer them."""
    assert re.search(r"^async function crmRenderVatSettings\(\)", INDEX, re.M)
    assert 'id="crm-vat-box"' in INDEX
    assert "crmSaveVatSettings()" in INDEX


def test_the_rate_can_be_overridden_where_a_real_contract_would_differ():
    """Company default, contract, single claim — an export-processing-zone job is 0% on a contract
    whose company default is 10%."""
    ct = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    cf = INDEX[INDEX.find("async function crmClaimForm"):INDEX.find("async function crmClaimSave")]
    assert 'id="ct-vatRate"' in ct
    assert 'id="sap-vatRate"' in cf and 'id="sap-vatBase"' in cf


def test_the_claim_shows_its_tax_line_or_says_there_is_none():
    cl = INDEX[INDEX.find("async function crmOpenClaim"):INDEX.find("async function crmClaimCertify")]
    assert "a.vatSet" in cl and "grossPayable" in cl
    assert "Ex-VAT" in cl, "a claim with no rate must say so rather than looking tax-free"


def test_the_variation_is_reachable_from_the_contract_it_changes():
    ct = INDEX[INDEX.find("async function crmOpenContract"):INDEX.find("async function crmContractAct")]
    assert "_ctVariationBlock(c)" in ct
    assert re.search(r"^async function crmOpenVariation\(", INDEX, re.M)


def test_applying_a_variation_goes_through_the_e_signature_not_a_save():
    """If it were a plain POST the contract value would move on an unsigned click."""
    fn = INDEX[INDEX.find("function crmVoApply"):INDEX.find("function crmVoApply") + 900]
    assert "tkESign({" in fn and "setStatus: 'applied'" in fn
    assert "/api/sales/variation" not in fn


def test_the_credit_note_is_reachable_from_the_claim_it_reverses():
    cl = INDEX[INDEX.find("async function crmOpenClaim"):INDEX.find("async function crmClaimCertify")]
    assert "crmOpenCredit(" in cl
    assert re.search(r"^async function crmOpenCredit\(", INDEX, re.M)


def test_applying_a_credit_note_goes_through_the_e_signature():
    fn = INDEX[INDEX.find("function crmCnApply"):INDEX.find("function crmCnApply") + 800]
    assert "tkESign({" in fn and "setStatus: 'applied'" in fn


def test_certifying_a_claim_goes_through_the_e_signature():
    """The last consequential sell-side act that was still a plain POST."""
    fn = INDEX[INDEX.find("function crmClaimCertify"):INDEX.find("function crmClaimCertify") + 900]
    assert "tkESign({" in fn and "setStatus: 'certified'" in fn
    assert "/api/sales/application" not in fn


def test_every_act_that_moves_money_on_the_sell_side_is_signed():
    """Certify a claim, apply a variation, apply a credit note — one rule, three documents."""
    for fn_name, status in (("crmClaimCertify", "certified"), ("crmVoApply", "applied"),
                            ("crmCnApply", "applied")):
        at = INDEX.find("function " + fn_name)
        assert at > 0, fn_name
        body = INDEX[at:at + 900]
        assert "tkESign({" in body, fn_name
        assert ("setStatus: '%s'" % status) in body, fn_name
