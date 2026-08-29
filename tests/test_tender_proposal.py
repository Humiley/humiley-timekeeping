"""What the customer actually receives: the scope, the exclusions, and where to pay.

Three findings from the tender review, all of them about the document rather than the price:

  1. `scope` and `exclusions` were captured, stored, fed into the basis of estimate — and dropped
     before the letter was assembled. The most valuable commercial protection in a contractor's
     proposal did not print.
  4. The company's own receiving bank was a TENDER field, retyped per quotation, with no single
     place to change it when the bank changed.

(2, the customer autofill, is browser-side and covered by the page gates.)
"""
import pytest

import company
import tender


QUOTE = {"subtotal": 0, "discount": 0, "discountPct": 0, "net": 0, "vat": 0, "gross": 0,
         "lineCount": 1, "lines": [], "grossMarginPct": 20.0}


# --- the scope and the exclusions reach the document ------------------------------------------------

def test_scope_and_exclusions_reach_the_customer_document():
    """The whole finding. Before this they existed on the tender and nowhere on the letter."""
    d = tender.document({"scope": "Supply 2x AHU\nCommissioning",
                         "exclusions": "Crane hire\nCivil works"}, QUOTE)
    assert d["scope"] == ["Supply 2x AHU", "Commissioning"]
    assert d["exclusions"] == ["Crane hire", "Civil works"]


@pytest.mark.parametrize("typed,expected", [
    ("- Crane hire\n- Civil works", ["Crane hire", "Civil works"]),
    ("• Crane hire\n• Civil works", ["Crane hire", "Civil works"]),
    ("* Crane hire", ["Crane hire"]),
    ("1. Crane hire\n2. Civil works", ["Crane hire", "Civil works"]),
    ("1) Crane hire", ["Crane hire"]),
    ("Crane hire\n\n\nCivil works", ["Crane hire", "Civil works"]),
    ("   Crane hire   ", ["Crane hire"]),
])
def test_however_the_estimator_types_a_list_it_reads_the_same(typed, expected):
    """People type bullets five ways. The renderer draws its own, and two bullets on one line reads
    as a mistake on a document a customer is judging you by."""
    assert tender._prose_lines(typed) == expected


def test_a_single_paragraph_stays_one_item():
    text = "The price covers supply, delivery DDP site and commissioning of two units."
    assert tender._prose_lines(text) == [text]


def test_nothing_typed_is_an_empty_list_not_a_blank_line():
    for empty in ("", None, "   ", "\n\n"):
        assert tender._prose_lines(empty) == []


def test_a_number_inside_a_sentence_is_not_treated_as_a_bullet():
    """'2 x AHU units excluded' must not lose its leading 2."""
    assert tender._prose_lines("2 x AHU units excluded") == ["2 x AHU units excluded"]


# --- an empty exclusions list has to be a decision -----------------------------------------------------

def _tender(**kw):
    return dict({"quoteNo": "QT-1", "client": "Acme", "clientTaxCode": "0123456789",
                 "issueDate": "2026-01-05", "validUntil": "2026-02-05"}, **kw)


def test_a_quotation_with_no_exclusions_cannot_be_issued():
    """A quotation with none is either one that genuinely excludes nothing, or one where nobody
    wrote them down. Those are completely different documents to defend, and the difference cannot
    be recovered afterwards."""
    chk = tender.issue_check(_tender(), QUOTE)
    assert any("excludes" in m for m in chk["missing"]), chk["missing"]
    assert chk["canIssue"] is False


def test_writing_exclusions_clears_it():
    chk = tender.issue_check(_tender(exclusions="Crane hire"), QUOTE)
    assert not any("excludes" in m for m in chk["missing"])


def test_saying_nothing_is_excluded_ALSO_clears_it():
    """The point is that a person decided, not that they typed. An estimator who genuinely excludes
    nothing must be able to say so and move on."""
    chk = tender.issue_check(_tender(exclusionsNone="Nothing is excluded from this price"), QUOTE)
    assert not any("excludes" in m for m in chk["missing"])


def test_the_document_records_which_it_was():
    d = tender.document(_tender(exclusionsNone="Nothing is excluded from this price"), QUOTE)
    assert d["exclusions"] == [] and d["exclusionsNone"] is True
    d2 = tender.document(_tender(exclusions="Crane hire"), QUOTE)
    assert d2["exclusions"] == ["Crane hire"] and d2["exclusionsNone"] is False


def test_the_other_issue_checks_still_work():
    """A new blocking rule must not be the ONLY one that fires — the earlier ones matter too."""
    chk = tender.issue_check({"exclusions": "Crane"}, QUOTE)
    assert "Quotation number" in chk["missing"]
    assert "Customer name" in chk["missing"]


# --- where the customer pays ----------------------------------------------------------------------------

def test_the_bank_comes_from_the_company_record():
    """It is a fact about the company, not about the tender. Retyping it per quotation is how a
    quotation goes out with last year's account on it."""
    ident = company.identity({"legalNameVn": "Cong ty Humiley", "bankName": "Vietcombank",
                              "bankAccount": "0123456789", "bankSwift": "BFTVVNVX"})
    bank = tender.document({}, QUOTE, ident)["bank"]
    assert bank["bank"] == "Vietcombank"
    assert bank["account"] == "0123456789"
    assert bank["swift"] == "BFTVVNVX"


def test_a_tender_may_still_override_it():
    """A project occasionally is paid into a dedicated account. The override survives; nobody has to
    type the normal case."""
    ident = company.identity({"legalNameVn": "Humiley", "bankName": "Vietcombank",
                              "bankAccount": "0123456789"})
    bank = tender.document({"bankName": "BIDV", "bankAccount": "999"}, QUOTE, ident)["bank"]
    assert bank["bank"] == "BIDV" and bank["account"] == "999"


def test_the_beneficiary_defaults_to_the_company_name():
    ident = company.identity({"legalNameVn": "Cong ty Humiley"})
    assert tender.document({}, QUOTE, ident)["bank"]["beneficiary"] == "Cong ty Humiley"


def test_a_differently_named_account_holder_can_be_stated():
    ident = company.identity({"legalNameVn": "Cong ty Humiley",
                              "bankBeneficiary": "HUMILEY ENGINEERING JSC"})
    assert tender.document({}, QUOTE, ident)["bank"]["beneficiary"] == "HUMILEY ENGINEERING JSC"


def test_the_company_record_now_holds_the_bank_fields():
    """Registered on the company identity, so there is one place to change when the bank changes."""
    for key in ("bankName", "bankAccount", "bankSwift", "bankBeneficiary"):
        assert key in company.FIELD_KEYS, key


def test_a_company_with_no_bank_recorded_prints_blanks_not_invention():
    bank = tender.document({}, QUOTE, company.identity({"legalNameVn": "Humiley"}))["bank"]
    assert bank["bank"] == "" and bank["account"] == "" and bank["swift"] == ""
