"""The four things this portal must never claim about the money it earns — enforced, not promised.

A policy note in a docstring is a promise. These are the same rules written as tests over the actual
source, so that adding the capability breaks the build rather than quietly shipping.

The one that matters most: a Vietnamese VAT invoice (hoá đơn GTGT) is the provider-issued, digitally
signed XML under Decree 123/2020 and Circular 78/2021. This portal cannot issue one and must not
look as though it can. That is enforced here as an ABSENCE OF CAPABILITY — no code path may exist
that mints a ký hiệu or a số hóa đơn — because a policy that lives only in prose gets coded around
by the next person in a hurry.
"""
import pathlib
import re

import pytest

import account
import doc_number
import sales_contract

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_FILES = sorted(p for p in ROOT.glob("*.py") if p.name != "conftest.py")
INDEX = (ROOT / "templates" / "index.html").read_text()


def _src(*names):
    return {p.name: p.read_text() for p in PY_FILES if not names or p.name in names}


# ── 1. It cannot mint a legal invoice number ─────────────────────────────────────────────────────

def test_no_document_series_is_a_legal_vat_invoice():
    """The portal's own numbers (QT, SO, IN…) are INTERNAL references. A ký hiệu and a số hóa đơn
    come from the e-invoice provider and are stored, never generated — so no series here may be
    named or described as one."""
    for prefix, meta in doc_number.SERIES.items():
        blob = (meta.get("name", "") + " " + meta.get("nameVn", "")).lower()
        assert "gtgt" not in blob, prefix
        assert "ký hiệu" not in blob and "ky hieu" not in blob, prefix
        assert "số hóa đơn" not in blob, prefix


def test_the_ar_invoice_series_is_described_as_an_internal_reference_only():
    """IN exists so a receivable can be tracked. It must not read as though the portal issues the
    legal document."""
    meta = doc_number.SERIES["IN"]
    assert "vat" not in meta["name"].lower()


def test_nothing_generates_a_ky_hieu_or_a_so_hoa_don():
    """The absence IS the control. If somebody adds a generator, this fails."""
    banned = re.compile(r"def\s+\w*(ky_hieu|kyhieu|so_hoa_don|sohoadon|vat_invoice_no|einv_no)\w*\s*\(",
                        re.I)
    for name, text in _src().items():
        hit = banned.search(text)
        assert not hit, "%s defines %s — the portal must not mint a legal invoice number" % (name, hit.group(0))


def test_the_frontend_has_no_issue_vat_invoice_control():
    """No button may offer it, because a button is a claim."""
    for phrase in ("Issue VAT invoice", "Phát hành hóa đơn GTGT", "Xuất hóa đơn GTGT"):
        assert phrase not in INDEX, phrase


# ── 2. It cannot state a VAT figure it has not been told how to compute ─────────────────────────

def test_a_contract_refuses_a_vat_figure_until_the_tax_points_are_recorded():
    v = sales_contract.vat_ready({"value": 1_000_000})
    assert v["ready"] is False
    assert "must not choose" in v["why"]


def test_the_two_blocking_questions_are_named_in_full():
    v = sales_contract.vat_ready({})
    qs = " ".join(m["question"] for m in v["missing"])
    assert "retention" in qs and "advance" in qs


def test_the_quotation_vat_rate_is_a_list_not_a_literal():
    """Four hardcoded `* 0.10` sites meant a quotation could only be right when 10% happened to be
    right. Vietnam has run 8% alongside 10%, and an export-processing customer is 0%."""
    assert "_CRM_VAT_RATES" in INDEX
    for rate in ("10", "8", "5", "0"):
        assert ("{ v: %s," % rate) in INDEX, rate
    # the picker is built FROM the list, so the list is the single source of order and of notes
    ed = INDEX[INDEX.find("async function crmOpenQuote"):INDEX.find("function crmQtAddRow")]
    assert "_CRM_VAT_RATES.map" in ed
    assert "'<option value=\"5\"" not in ed, "a rate tacked on outside the list will drift from it"


def test_the_deal_side_quotation_builder_is_retired():
    """It wrote lines back onto the DEAL with its own revisions and its own numbering — a second
    quoting path alongside the register. Two ways to quote is the opposite of what a CRM is for."""
    for gone in ("function crmQuoteBuilder", "function crmQBTotals", "function crmQBSave"):
        assert gone not in INDEX, gone
    assert "async function crmQuoteFromDeal" in INDEX, "and the deal must still be able to start one"


def test_no_bare_ten_percent_multiplier_survives_anywhere_in_the_crm():
    """The original point of this test, no longer tied to a function that has been deleted: a
    quotation could only be right when 10% happened to be right."""
    crm = INDEX[INDEX.find("const _CRM_TABS"):INDEX.find("/* ═══ Sales Compliance ══")]
    assert crm, "the CRM block moved — re-point this test"
    for bad in ("* 0.10", "*0.10", "* 0.1;", "*0.1;"):
        assert bad not in crm, bad


# ── 3. It cannot state a customer's identity it does not hold ───────────────────────────────────

def test_a_customer_with_no_tax_code_cannot_be_billed():
    assert account.invoice_readiness({"legalNameVn": "X", "regAddress": "Y"})["ready"] is False


def test_the_mst_check_digit_is_declared_unimplemented_rather_than_faked():
    """A false rejection stops a real invoice for a real customer, which costs more than the typo it
    would catch. Format is checked and stated; the arithmetic is not claimed."""
    assert "MST check digit" in {u["topic"] for u in account.UNVERIFIED}
    banned = re.compile(r"(checksum|check_digit|luhn)", re.I)
    assert not banned.search(account.__doc__ or ""), "the docstring now claims a checksum"


# ── 4. Every open question travels with the answer ──────────────────────────────────────────────

@pytest.mark.parametrize("mod", [account, sales_contract])
def test_each_module_carries_its_unsettled_questions(mod):
    """The pattern established by working_time.py: an unresolved rule is DATA somebody must supply,
    never a silent default. A pack that sounds certain about an open question is worse than one that
    says the question is open, because only the second gets asked."""
    unresolved = getattr(mod, "UNRESOLVED", None) or getattr(mod, "UNVERIFIED", None)
    assert unresolved, mod.__name__
    for u in unresolved:
        assert u.get("topic") and u.get("action"), u


def test_the_contract_module_states_that_its_figures_are_ex_vat():
    r = sales_contract.application({"value": 100, "recoveryRule": "prorata"}, 10)
    assert "exclusive of VAT" in r["taxNote"]
