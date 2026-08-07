"""The employer's legal identity.

The point of this module is that it never invents. The portal has always known the company as a
display name in a header, which is enough to brand a report and nowhere near enough to sign a
contract — so the tests that matter are the ones about what happens when a field is blank.
"""
import pytest

import company

FULL = {
    "legalNameVn": "Công ty TNHH Humiley Việt Nam",
    "legalNameEn": "Humiley Vietnam Co., Ltd",
    "regNo": "0316123456",
    "addressVn": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
    "phone": "028 1234 5678",
    "repName": "Nguyễn Văn A",
    "repTitle": "Giám đốc",
}


# ── it never invents ─────────────────────────────────────────────────────────────────────────────

def test_an_absent_field_comes_back_empty_rather_than_guessed():
    ident = company.identity({})
    assert all(ident[k] == "" for k in company.FIELD_KEYS)
    assert ident["signatory"] == "", "no name means no signature block, not a blank line to sign on"


def test_settings_that_are_not_settings_do_not_crash_the_identity():
    for bad in (None, {}, {"legalNameVn": None}):
        assert company.identity(bad)["legalNameVn"] == ""


def test_whitespace_is_not_a_value():
    assert company.identity({"repName": "   "})["repName"] == ""


# ── the two courtesy derivations ─────────────────────────────────────────────────────────────────

def test_the_english_name_falls_back_to_the_vietnamese_one_which_is_the_legal_one_anyway():
    ident = company.identity({"legalNameVn": "Công ty TNHH Humiley"})
    assert ident["displayNameEn"] == "Công ty TNHH Humiley"
    assert company.identity(FULL)["displayNameEn"] == "Humiley Vietnam Co., Ltd"


def test_the_signatory_line_states_the_title_because_art_21_requires_it():
    assert company.identity(FULL)["signatory"] == "Nguyễn Văn A — Giám đốc"


def test_a_name_with_no_title_still_produces_a_line_rather_than_a_dangling_dash():
    assert company.identity({"repName": "Nguyễn Văn A"})["signatory"] == "Nguyễn Văn A"


def test_signing_by_delegation_says_so_on_the_line():
    """Somebody signing under a power of attorney is not the registered representative, and a
    document that does not say which is the one that gets challenged."""
    ident = company.identity(dict(FULL, repName="Trần Thị B", repTitle="Phó Giám đốc",
                                  repAuthority="Giấy ủy quyền số 05/2026"))
    assert ident["signatory"] == "Trần Thị B — Phó Giám đốc (Giấy ủy quyền số 05/2026)"


# ── what blocks a document ───────────────────────────────────────────────────────────────────────

def test_a_complete_identity_can_issue_every_document():
    for doc in company.DOCUMENTS:
        assert company.can_issue(doc, FULL), doc


def test_an_empty_identity_blocks_the_contract_and_names_every_field():
    miss = company.missing_for("labour_contract", {})
    assert {m["key"] for m in miss} == set(company.DOCUMENTS["labour_contract"]["needs"])


def test_each_missing_field_says_what_breaks_rather_than_just_required():
    """"Required" has never persuaded anybody to go and find a registration certificate."""
    for m in company.missing_for("labour_contract", {}):
        assert len(m["why"]) > 40 and m["labelVn"]


def test_the_registration_number_blocks_a_contract_but_not_a_letter():
    """Circular 10/2020 puts it on the contract form. A confirmation letter has no such form."""
    without = dict(FULL, regNo="")
    assert not company.can_issue("labour_contract", without)
    assert company.can_issue("employment_letter", without)


def test_an_unnamed_signatory_blocks_everything():
    without = dict(FULL, repName="")
    assert all(not company.can_issue(d, without) for d in company.DOCUMENTS)


def test_the_optional_fields_block_nothing():
    """The English name, the phone, the SI code and the delegation basis are not legal requirements
    — treating them as blockers would stop a lawful contract for no reason."""
    bare = {k: FULL[k] for k in ("legalNameVn", "regNo", "addressVn", "repName", "repTitle")}
    assert company.can_issue("labour_contract", bare)


def test_an_unknown_document_is_an_error_not_a_silent_pass():
    """Returning "nothing missing" for a document nobody defined would read as permission."""
    with pytest.raises(ValueError):
        company.missing_for("mystery_document", FULL)


# ── the review ───────────────────────────────────────────────────────────────────────────────────

def test_the_review_says_which_documents_are_blocked_by_name():
    r = company.review({})
    assert r["filled"] == 0 and r["total"] == len(company.FIELD_KEYS)
    assert "Labour contract" in r["blocked"]
    assert all(not d["ready"] for d in r["documents"])


def test_a_complete_review_blocks_nothing_and_still_lists_the_documents():
    r = company.review(FULL)
    assert r["blocked"] == []
    assert len(r["documents"]) == len(company.DOCUMENTS)
    assert all(d["basis"] for d in r["documents"]), "each one says why those fields"


def test_the_review_counts_only_fields_that_were_actually_filled():
    r = company.review({"legalNameVn": "X", "phone": "  "})
    assert r["filled"] == 1, "whitespace is not a filled field"
