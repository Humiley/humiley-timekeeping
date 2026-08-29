"""The supplier as one identity, and the bank account that identity owns.

Most of this file is about ONE control: noticing that a payment names a different bank account from
the one this supplier has been paid at before. Invoice-redirection fraud — "our bank details have
changed", often from a genuine but compromised mailbox — is among the most common frauds against a
company this size, and the entire defence is being able to notice.

A warning that fires on every second payment is worse than no warning, because it gets ignored. So
half these tests are about NOT crying wolf.
"""
import pytest

import account
import supplier as sp


ACME = {"id": "S1", "name": "Acme Co", "mst": "0123456789",
        "bankName": "Vietcombank", "bankAcc": "0123 4567 8901", "bankHolder": "ACME CO LTD"}


# --- identity is not reimplemented ------------------------------------------------------------------

def test_identity_comes_from_the_customer_master_not_a_second_copy():
    """A second implementation of "are these the same company" would drift from the first. This
    codebase has already paid for that once, when the tender revision diff and its on-screen twin
    were keyed differently and disagreed about what a price change was."""
    assert sp.fold_name is account.fold_name
    assert sp.normalise_mst is account.normalise_mst
    assert sp.check_mst is account.check_mst
    assert sp.resolve_name is account.resolve_name
    assert sp.duplicate_groups is account.duplicate_groups


def test_two_spellings_of_one_supplier_are_found_as_duplicates():
    groups = sp.duplicate_groups([dict(ACME), dict(ACME, id="S2", name="ACME CO., LTD")])
    assert groups and len(groups[0]["accounts"]) == 2


# --- the bank account IS part of the identity ----------------------------------------------------------

def test_the_same_account_typed_three_ways_is_one_account():
    """'0123 4567 8901', '0123-4567-8901' and '0123456789 01' are three people writing one number."""
    for typed in ("0123-4567-8901", "0123456789 01", "0123 4567 8901", "0123.4567.8901"):
        v = sp.bank_verdict(ACME, {"bankAcc": typed, "bankName": "Vietcombank"})
        assert v["status"] == sp.MATCHES, (typed, v)


def test_case_and_spacing_in_the_bank_name_do_not_raise_an_alarm():
    for bank in ("VIETCOMBANK", "  vietcombank ", "Vietcombank"):
        v = sp.bank_verdict(ACME, {"bankAcc": "0123456789 01", "bankName": bank})
        assert v["status"] == sp.MATCHES, bank


def test_the_holder_name_is_deliberately_not_part_of_the_key():
    """It is abbreviated, transliterated and cased differently constantly. A key that changed when
    somebody wrote CTY TNHH instead of CONG TY TNHH would cry wolf on every second payment — and a
    warning that fires that often is one nobody reads."""
    v = sp.bank_verdict(ACME, {"bankAcc": "0123456789 01", "bankName": "Vietcombank",
                               "bankHolder": "CTY TNHH ACME"})
    assert v["status"] == sp.MATCHES


def test_a_different_account_number_is_reported_as_CHANGED():
    v = sp.bank_verdict(ACME, {"bankAcc": "9999 8888 77", "bankName": "Techcombank"})
    assert v["status"] == sp.CHANGED
    assert "0123 4567 8901" in v["message"], "the message must name the account ON FILE"
    assert "9999 8888 77" in v["message"], "…and the one being asked for"


def test_the_same_digits_at_a_different_bank_is_a_different_account():
    """The number alone is not an identity — the same digits at two banks are two accounts."""
    v = sp.bank_verdict(ACME, {"bankAcc": "0123456789 01", "bankName": "BIDV"})
    assert v["status"] == sp.CHANGED


def test_the_changed_message_says_how_to_confirm_it_safely():
    """The one instruction that matters: ring a number you already had. Confirming a bank change
    against the email that asked for it is how the fraud succeeds."""
    v = sp.bank_verdict(ACME, {"bankAcc": "9999", "bankName": "X"})
    assert "ringing a number you already had" in v["message"]
    assert "never one from the email" in v["message"]


def test_a_first_payment_records_the_account_and_says_to_check_it():
    v = sp.bank_verdict({"id": "S9", "name": "New Co"}, {"bankAcc": "555", "bankName": "ACB"})
    assert v["status"] == sp.FIRST_TIME
    assert "not against the email" in v["message"]


def test_a_payment_with_no_account_says_there_is_nothing_to_compare():
    v = sp.bank_verdict(ACME, {"bankAcc": "", "bankName": "Vietcombank"})
    assert v["status"] == sp.INCOMPLETE


def test_an_unlinked_payment_says_so_rather_than_passing_silently():
    """No supplier means no comparison — and a silent pass would read as 'checked and fine'."""
    v = sp.bank_verdict(None, {"bankAcc": "123", "bankName": "ACB"})
    assert v["status"] == sp.UNKNOWN_SUPPLIER


def test_the_verdict_never_blocks():
    """Every status is advisory. The answer belongs to a person who can ring the supplier, and a
    system that refused would simply be worked around."""
    for payment in ({"bankAcc": "9999"}, {"bankAcc": ""}, {}):
        v = sp.bank_verdict(ACME, payment)
        assert "status" in v and "message" in v


# --- the backfill ---------------------------------------------------------------------------------------

def _pay(pid, name, acc="111", bank="ACB", **kw):
    return dict({"id": pid, "reqNo": pid, "payeeCompany": name, "bankAcc": acc,
                 "bankName": bank, "amount": 1_000_000, "status": "Paid"}, **kw)


def test_a_name_matching_exactly_one_supplier_is_linked():
    plan = sp.backfill_plan([_pay("P1", "Acme Co")], [ACME])
    assert plan["counts"]["link"] == 1
    assert plan["link"][0]["supplierId"] == "S1"


def test_a_name_matching_nothing_becomes_a_proposed_record():
    plan = sp.backfill_plan([_pay("P1", "Brand New Ltd")], [ACME])
    assert plan["counts"]["create"] == 1
    assert plan["create"][0]["name"] == "Brand New Ltd"


def test_an_ambiguous_name_is_left_alone_with_its_candidates():
    """Replacing free text with a confident WRONG join is worse than the free text, which at least
    looks uncertain."""
    twins = [dict(ACME, id="S1"), dict(ACME, id="S2")]
    plan = sp.backfill_plan([_pay("P1", "Acme Co")], twins)
    assert plan["counts"]["ambiguous"] == 1
    assert plan["counts"]["link"] == 0
    assert len(plan["ambiguous"][0]["candidates"]) == 2


def test_payments_already_linked_are_left_alone():
    plan = sp.backfill_plan([_pay("P1", "Acme Co", supplierId="S1")], [ACME])
    assert plan["counts"] == {"link": 0, "create": 0, "ambiguous": 0}


def test_several_payments_to_one_new_name_propose_ONE_record():
    plan = sp.backfill_plan([_pay("P1", "Brand New Ltd"), _pay("P2", "Brand New Ltd"),
                             _pay("P3", "BRAND NEW LTD")], [])
    assert plan["counts"]["create"] == 1
    assert plan["create"][0]["payments"] == 3


def test_payments_to_one_name_at_two_bank_accounts_are_flagged():
    """Either two suppliers wearing one name, or an account that changed at some point. Both are
    worth a human look before a record is created that picks one."""
    plan = sp.backfill_plan([_pay("P1", "Brand New Ltd", acc="111"),
                             _pay("P2", "Brand New Ltd", acc="222")], [])
    assert plan["create"][0].get("bankConflict") is True


def test_a_payment_with_no_payee_at_all_is_skipped_not_guessed():
    plan = sp.backfill_plan([_pay("P1", "")], [ACME])
    assert plan["counts"] == {"link": 0, "create": 0, "ambiguous": 0}


# --- the question that had no answer -----------------------------------------------------------------------

def test_spend_by_supplier_totals_what_was_actually_paid():
    payments = [_pay("P1", "Acme Co", supplierId="S1"),
                dict(_pay("P2", "Acme Co", supplierId="S1"), amount=2_000_000),
                dict(_pay("P3", "Acme Co", supplierId="S1"), amount=9_000_000,
                     status="Approved")]          # a commitment, not money that has left
    out = sp.spend_by_supplier(payments, [ACME])
    assert out["rows"][0]["total"] == 3_000_000
    assert out["rows"][0]["payments"] == 2
    assert out["complete"] is True


def test_unlinked_payments_are_reported_rather_than_dropped():
    """A spend report that silently omits a third of the payments is worse than one that says it is
    incomplete."""
    out = sp.spend_by_supplier([_pay("P1", "Acme Co", supplierId="S1"),
                                _pay("P2", "Nobody Ltd")], [ACME])
    assert out["unlinkedPayments"] == 1
    assert out["unlinkedTotal"] == 1_000_000
    assert out["complete"] is False


def test_a_link_to_a_supplier_that_no_longer_exists_counts_as_unlinked():
    out = sp.spend_by_supplier([_pay("P1", "Ghost", supplierId="S404")], [ACME])
    assert out["unlinkedPayments"] == 1 and out["complete"] is False


def test_an_unparseable_amount_does_not_take_the_report_down():
    out = sp.spend_by_supplier([dict(_pay("P1", "Acme Co", supplierId="S1"), amount="lots")],
                               [ACME])
    assert out["rows"][0]["total"] == 0


def test_the_status_filter_is_explicit_and_can_be_widened():
    payments = [dict(_pay("P1", "Acme Co", supplierId="S1"), status="Approved")]
    assert sp.spend_by_supplier(payments, [ACME])["rows"] == []
    widened = sp.spend_by_supplier(payments, [ACME], statuses=("paid", "approved"))
    assert widened["rows"][0]["total"] == 1_000_000
