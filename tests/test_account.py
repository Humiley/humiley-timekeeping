"""The account master — one customer, one identity.

The customer exists four times as a free-text string today, and the join between those copies is the
SPELLING. The tests that matter most here are the ones that stop the cure being worse than the
disease: a merge that fuses two genuinely different companies, or a tax-code check that rejects a
real customer's real MST and stops an invoice going out.
"""
import pytest

import account as A


# ── the tax code ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,kind", [
    ("0123456789", A.ENTITY),
    ("0123 456 789", A.ENTITY),        # spaces are how people type it
    ("0123.456.789", A.ENTITY),
    ("0123456789-001", A.BRANCH),      # a dependent unit
    ("0123456789 - 001", A.BRANCH),
])
def test_a_real_tax_code_is_accepted_however_it_was_typed(raw, kind):
    r = A.check_mst(raw)
    assert r["ok"] is True, r
    assert r["kind"] == kind
    assert r["normalised"] in ("0123456789", "0123456789-001")


@pytest.mark.parametrize("raw", ["123", "01234567890", "0123456789-01", "0123456789-0001"])
def test_a_length_that_cannot_be_right_is_refused(raw):
    assert A.check_mst(raw)["ok"] is False


def test_a_blank_tax_code_says_it_is_missing_not_that_it_is_wrong():
    """Different problem, different person, different fix."""
    for blank in ("", "   ", None):
        r = A.check_mst(blank)
        assert r["code"] == "empty" and r["ok"] is False


def test_something_typed_that_is_not_a_number_is_not_reported_as_blank():
    """Saying 'no tax code recorded' about a field somebody filled in sends them looking for an
    empty box that is not empty."""
    r = A.check_mst("to be confirmed")
    assert r["code"] == "bad_format"
    assert "contains no digits" in r["why"]


def test_a_bad_tax_code_never_blocks():
    """It should stop somebody and make them look, not stop the business. A false rejection on a
    real customer's real MST costs more than the typo it was trying to catch."""
    for v in ("", "123", "nonsense", "0123456789"):
        assert A.check_mst(v)["blocking"] is False


def test_the_check_digit_is_declared_unimplemented_rather_than_guessed():
    """The weighting circulating in blog posts was not verified against a primary source. Encoding
    it would reject valid tax codes with total confidence."""
    topics = {u["topic"] for u in A.UNVERIFIED}
    assert "MST check digit" in topics


# ── payment terms ────────────────────────────────────────────────────────────────────────────────

def test_known_terms_resolve_to_days():
    assert A.terms_days("NET30") == 30
    assert A.terms_days("net45") == 45


def test_an_unknown_terms_code_is_None_not_zero():
    """Zero means 'due on receipt', a real and aggressive term. Inventing it for an account nobody
    configured would show every invoice as instantly overdue."""
    assert A.terms_days("NET-WHATEVER") is None
    assert A.terms_days("") is None
    assert A.terms_days(None, fallback=30) == 30


def test_the_due_date_is_counted_from_the_date_given():
    assert A.due_date("2026-08-01", 30) == "2026-08-31"
    assert A.due_date("2026-08-01", 0) == "2026-08-01"


def test_a_due_date_with_nothing_to_count_from_is_blank_not_today():
    """Falling back to today would put a date on a document that nobody chose."""
    for a, b in (("", 30), ("2026-08-01", None), ("oops", 30), (None, None)):
        assert A.due_date(a, b) == ""


def test_all_three_ways_the_clock_can_start_are_offered():
    """AP-receipt is common in Vietnam and quietly adds weeks to every payment."""
    codes = {b["code"] for b in A.DUE_BASIS}
    assert codes == {A.BASIS_INVOICE, A.BASIS_ACCEPTANCE, A.BASIS_AP_RECEIPT}


# ── can this customer be billed at all? ──────────────────────────────────────────────────────────

def test_a_complete_account_is_ready():
    acc = {"legalNameVn": "Công ty TNHH ABC", "mst": "0123456789", "regAddress": "12 Nguyễn Huệ, HCM"}
    assert A.invoice_readiness(acc)["ready"] is True


def test_an_empty_account_names_every_missing_field():
    r = A.invoice_readiness({})
    assert r["ready"] is False
    assert [m["field"] for m in r["missing"]] == ["legalNameVn", "mst", "regAddress"]
    assert "Cannot bill yet" in r["why"]


def test_a_malformed_tax_code_blocks_billing_even_though_the_field_is_filled():
    acc = {"legalNameVn": "Cty ABC", "mst": "123", "regAddress": "HCM"}
    r = A.invoice_readiness(acc)
    assert r["ready"] is False and not r["missing"], "the field is present but wrong"


def test_readiness_survives_a_None_account():
    assert A.invoice_readiness(None)["ready"] is False


# ── the duplicates that already exist ────────────────────────────────────────────────────────────

def test_the_spellings_of_one_company_fold_together():
    for a, b in (("ABC Corp", "ABC Corp."), ("ABC  Corp", "abc corp"),
                 ("Công ty TNHH ABC", "CONG TY ABC"), ("ABC Co., Ltd", "ABC")):
        assert A.fold_name(a) == A.fold_name(b), (a, b)


def test_different_companies_do_not_fold_together():
    assert A.fold_name("ABC Corp") != A.fold_name("ABD Corp")


def test_a_shared_tax_code_is_the_strongest_duplicate_signal():
    accs = [{"id": "1", "name": "XYZ Vietnam", "mst": "0123456789"},
            {"id": "2", "name": "XYZ VN", "mst": "0123 456 789"}]
    g = A.duplicate_groups(accs)
    assert g and g[0]["reason"] == "mst"
    assert {a["id"] for a in g[0]["accounts"]} == {"1", "2"}


def test_the_same_trading_name_with_DIFFERENT_tax_codes_is_not_a_duplicate():
    """Two real companies can share a trading name. Grouping them would invite somebody to fuse two
    customers' contracts into one account."""
    accs = [{"id": "1", "name": "ABC", "mst": "0123456789"},
            {"id": "2", "name": "ABC", "mst": "9876543210"}]
    assert A.duplicate_groups(accs) == []


def test_an_already_merged_account_is_not_offered_again():
    accs = [{"id": "1", "name": "ABC"}, {"id": "2", "name": "ABC.", "mergedInto": "1"}]
    assert A.duplicate_groups(accs) == []


def test_no_duplicates_is_an_empty_list_not_a_group_of_one():
    assert A.duplicate_groups([{"id": "1", "name": "Solo"}]) == []


# ── merging, without losing anything ─────────────────────────────────────────────────────────────

def test_a_merge_repoints_the_children_and_says_how_many():
    plan = A.merge_plan({"id": "1", "name": "ABC Corp"},
                        {"id": "2", "name": "ABC Corp."},
                        {"crm_deals": [{"id": "d1", "company": "ABC Corp."},
                                       {"id": "d2", "company": "Other"}],
                         "pm_projects": [{"id": "p1", "account": "ABC Corp."}]})
    assert plan["ok"] is True
    assert plan["movedTotal"] == 2
    assert {m["coll"] for m in plan["moves"]} == {"crm_deals", "pm_projects"}


def test_the_duplicate_is_kept_as_a_tombstone_never_deleted():
    """A link, a report or a printed document that names the old account must still resolve."""
    plan = A.merge_plan({"id": "1", "name": "A"}, {"id": "2", "name": "A."}, {})
    assert "tombstone" in plan["why"] and "never deleted" in plan["why"]


def test_two_different_legal_entities_cannot_be_merged():
    """THE dangerous case. Merging on a name match would fuse two customers' contracts."""
    plan = A.merge_plan({"id": "1", "name": "ABC", "mst": "0123456789"},
                        {"id": "2", "name": "ABC", "mst": "9876543210"}, {})
    assert plan["ok"] is False and "different legal entities" in plan["why"]


def test_an_account_cannot_be_merged_into_itself():
    assert A.merge_plan({"id": "1", "name": "A"}, {"id": "1", "name": "A"}, {})["ok"] is False


def test_a_tombstone_cannot_be_merged_again():
    assert A.merge_plan({"id": "1", "name": "A"},
                        {"id": "2", "name": "A.", "mergedInto": "3"}, {})["ok"] is False
    assert A.merge_plan({"id": "1", "name": "A", "mergedInto": "9"},
                        {"id": "2", "name": "A."}, {})["ok"] is False


def test_the_survivor_inherits_details_it_was_missing():
    """Usually the reason the duplicate was created: somebody had the tax code and the other record
    did not."""
    plan = A.merge_plan({"id": "1", "name": "ABC"},
                        {"id": "2", "name": "ABC.", "mst": "0123456789", "regAddress": "HCM"}, {})
    assert plan["fills"]["mst"] == "0123456789"
    assert plan["fills"]["regAddress"] == "HCM"


def test_the_survivor_keeps_its_own_details_over_the_duplicates():
    plan = A.merge_plan({"id": "1", "name": "ABC", "regAddress": "Keep me"},
                        {"id": "2", "name": "ABC.", "regAddress": "Overwrite me"}, {})
    assert "regAddress" not in plan["fills"]


def test_a_merge_needs_two_real_accounts():
    assert A.merge_plan({}, {"id": "2"}, {})["ok"] is False
    assert A.merge_plan({"id": "1"}, {}, {})["ok"] is False


# ── the qualification pack ───────────────────────────────────────────────────────────────────────

def test_a_lapsed_certificate_is_found():
    r = A.qualification_status({"prequal": {"iso9001": {"expires": "2020-01-01"}}}, "2026-08-09")
    assert [i["code"] for i in r["expired"]] == ["iso9001"]
    assert r["ok"] is False


def test_a_certificate_about_to_lapse_is_flagged_before_it_does():
    """An expired certificate on a pharma customer's file is a thing that stops you invoicing, and
    it expires quietly."""
    r = A.qualification_status({"prequal": {"iso9001": {"expires": "2026-09-01"}}}, "2026-08-09")
    assert [i["code"] for i in r["expiring"]] == ["iso9001"]


def test_never_had_it_is_not_the_same_as_it_ran_out():
    """Different actions, different people. One red badge for both loses that."""
    r = A.qualification_status({"prequal": {"iso9001": {"expires": "2020-01-01"}}}, "2026-08-09")
    assert "iso9001" in [i["code"] for i in r["expired"]]
    assert "nda" in [i["code"] for i in r["absent"]]


def test_a_full_pack_is_clean():
    pack = {q["code"]: {"expires": "2030-01-01"} for q in A.QUALIFICATIONS}
    r = A.qualification_status({"prequal": pack}, "2026-08-09")
    assert r["ok"] is True and r["why"] == "Qualification pack complete."


def test_an_unreadable_date_counts_as_absent_not_valid():
    r = A.qualification_status({"prequal": {"iso9001": {"expires": "soon"}}}, "2026-08-09")
    assert "iso9001" in [i["code"] for i in r["absent"]]


def test_no_today_refuses_rather_than_reporting_everything_valid():
    assert A.qualification_status({}, "")["ok"] is False


# ── resolving a free-text name to an account ─────────────────────────────────────────────────────

ACCS = [{"id": "a1", "name": "ABC Corp"},
        {"id": "a2", "name": "XYZ Ltd"},
        {"id": "a3", "name": "ABC Corp.", "mergedInto": "a1"}]


def test_an_exact_name_resolves():
    assert A.resolve_name("ABC Corp", ACCS)["accountId"] == "a1"


def test_a_different_spelling_resolves_when_it_is_unambiguous():
    r = A.resolve_name("abc  corp", ACCS)
    assert r["accountId"] == "a1" and r["how" if "how" in r else "status"] in ("folded", "exact")


def test_a_name_that_points_at_a_tombstone_follows_it_to_the_survivor():
    """That is what the tombstone is for — an old document naming the merged account still lands."""
    assert A.resolve_name("ABC Corp.", ACCS)["accountId"] == "a1"


def test_two_live_accounts_with_the_same_name_refuse_to_resolve():
    """Merge them first. Picking one would bake the wrong join in permanently."""
    accs = [{"id": "x", "name": "Same"}, {"id": "y", "name": "Same"}]
    r = A.resolve_name("Same", accs)
    assert r["status"] == "ambiguous" and r["accountId"] is None
    assert {c["id"] for c in r["candidates"]} == {"x", "y"}


def test_an_unknown_name_is_unmatched_not_guessed():
    assert A.resolve_name("Nobody Ltd", ACCS)["status"] == "unmatched"


def test_a_blank_name_is_its_own_answer():
    assert A.resolve_name("", ACCS)["status"] == "blank"
    assert A.resolve_name(None, ACCS)["status"] == "blank"


def test_the_backfill_plan_separates_what_it_can_do_from_what_a_human_must():
    children = {"crm_deals": [{"id": "d1", "company": "ABC Corp"},
                              {"id": "d2", "company": "Nobody Ltd"},
                              {"id": "d3", "company": "", },
                              {"id": "d4", "company": "XYZ Ltd", "accountId": "a2"}]}
    plan = A.backfill_plan(ACCS, children)
    assert [x["id"] for x in plan["link"]] == ["d1"]
    assert [x["id"] for x in plan["exceptions"]] == ["d2"]
    assert plan["alreadyLinked"] == 1 and plan["noName"] == 1


def test_the_plan_never_invents_a_link_for_an_ambiguous_name():
    accs = [{"id": "x", "name": "Same"}, {"id": "y", "name": "Same"}]
    plan = A.backfill_plan(accs, {"crm_deals": [{"id": "d1", "company": "Same"}]})
    assert plan["link"] == []
    assert plan["exceptions"][0]["reason"] == "ambiguous"
