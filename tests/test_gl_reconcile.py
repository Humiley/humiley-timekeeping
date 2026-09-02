"""The registers against the books.

A trial balance is correct about the entries it has and silent about the ones nobody posted, so
"the books are complete" is precisely the claim it cannot make. Driven by hand against the seeded
job, the subcontract registers and the ledger agreed TO THE DONG once every certificate was posted
— which is what makes a difference worth reporting: it is not noise, it is a list of documents.
"""
import pytest

import gl_reconcile as gr


def _c(**kw):
    """A job where everything has been posted, so both sides agree."""
    return dict({"registerGross": 8_345_000_000, "registerNet": 7_956_750_000,
                 "registerRetention": 388_250_000,
                 "ledgerCost": 8_345_000_000, "ledgerPayable": 7_956_750_000,
                 "ledgerRetention": 388_250_000, "unposted": []}, **kw)


def _r(**kw):
    return gr.subcontract_reconciliation(_c(**kw))


def _codes(r):
    return {w["code"] for w in r["warnings"]}


def _row(r, code):
    return next(x for x in r["rows"] if x["code"] == code)


# ── agreement ────────────────────────────────────────────────────────────────────────────────────

def test_a_fully_posted_job_agrees_on_every_line_and_says_nothing():
    r = _r()
    assert r["agrees"] is True and r["differenceTotal"] == 0
    assert r["warnings"] == []


def test_all_three_figures_are_compared_and_not_just_the_total():
    """A gross that matches while the split between payable and retention is wrong is two errors
    that cancel, and one number cannot see it."""
    assert {x["code"] for x in _r()["rows"]} == {"gross", "payable", "retention"}
    for x in _r()["rows"]:
        assert x["account"], "%s does not say which account it is against" % x["code"]


def test_a_rounding_crumb_is_not_a_missing_document():
    assert _r(ledgerPayable=7_956_750_000.4)["agrees"] is True


# ── the difference explained ─────────────────────────────────────────────────────────────────────

def test_a_difference_that_is_exactly_the_unposted_documents_says_so():
    r = _r(ledgerCost=8_045_000_000, ledgerPayable=7_671_750_000, ledgerRetention=373_250_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000}])
    assert r["agrees"] is False
    w = [x for x in r["warnings"] if x["code"] == "difference_is_unposted"][0]
    assert "Post them" in w["msg"] and w["unposted"] == ["IPC-007"]


def test_the_unposted_total_is_compared_on_the_SAME_BASIS_as_the_difference():
    """Found by running it. The unposted list carries documents at their GROSS; the payable moves
    by the NET. An unposted ₫300,000,000 certificate shifts the payable ₫285,000,000 and the
    retention ₫15,000,000, so testing the payable row against a gross total reported a perfectly
    healthy month as an unexplained discrepancy."""
    r = _r(ledgerCost=8_045_000_000, ledgerPayable=7_671_750_000, ledgerRetention=373_250_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000}])
    assert "difference_unexplained" not in _codes(r)
    assert _row(r, "gross")["difference"] == 300_000_000
    assert _row(r, "payable")["difference"] == 285_000_000, "the net moves by less than the gross"
    assert _row(r, "retention")["difference"] == 15_000_000


def test_a_difference_the_unposted_documents_do_not_account_for_is_the_serious_one():
    r = _r(ledgerCost=6_000_000_000, ledgerPayable=5_700_000_000, ledgerRetention=300_000_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000}])
    w = [x for x in r["warnings"] if x["code"] == "difference_unexplained"][0]
    assert w["severity"] == "high"
    assert "One side is recording something the other is not" in w["msg"]


def test_a_difference_with_nothing_outstanding_is_unexplained_not_explained_by_zero():
    r = _r(ledgerCost=6_000_000_000, unposted=[])
    assert "difference_unexplained" in _codes(r)
    assert "difference_is_unposted" not in _codes(r)


# ── agreement is not proof ───────────────────────────────────────────────────────────────────────

def test_agreement_while_documents_are_outstanding_is_reported_as_a_problem():
    """Two figures that match while something is missing from one of them are two figures that are
    wrong together. This is the finding a reconciliation exists to catch and the one it is most
    tempting to render as a green tick."""
    r = _r(unposted=[{"label": "IPC-009", "amount": 95_000_000}])
    assert r["agrees"] is True
    w = [x for x in r["warnings"] if x["code"] == "agrees_with_documents_outstanding"][0]
    assert w["severity"] == "high" and "wrong together" in w["msg"]


def test_the_note_says_agreement_is_not_proof():
    assert "both sides can be wrong together" in _r()["note"]


# ── what it will not do ──────────────────────────────────────────────────────────────────────────

def test_it_never_adjusts_either_side():
    """A reconciliation that writes a balancing entry is not a reconciliation."""
    r = _r(ledgerCost=6_000_000_000)
    assert _row(r, "gross")["register"] == 8_345_000_000
    assert _row(r, "gross")["ledger"] == 6_000_000_000
    assert "adjustment" not in r and "correction" not in r
    assert "never adjusted" in r["note"] or "Nothing here is adjusted" in r["note"]


def test_the_difference_comes_back_as_the_documents_that_cause_it():
    r = _r(ledgerCost=8_045_000_000, ledgerPayable=7_671_750_000, ledgerRetention=373_250_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000}])
    assert r["unposted"] == [{"label": "IPC-007", "amount": 300_000_000, "blocked": ""}]
    assert r["unpostedTotal"] == 300_000_000 and r["unpostedCount"] == 1


def test_a_certificate_that_cannot_post_at_all_is_named_separately():
    """Posting the others will not close this gap, so "post them and the two sides meet" would be
    an instruction that does not work."""
    r = _r(ledgerCost=8_045_000_000, ledgerPayable=7_671_750_000, ledgerRetention=373_250_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000,
                      "blocked": "This certificate does not add up."}])
    w = [x for x in r["warnings"] if x["code"] == "documents_cannot_post"][0]
    assert w["severity"] == "high" and "corrected" in w["msg"]
    assert w["blocked"] == ["IPC-007"]


# ── settlements ──────────────────────────────────────────────────────────────────────────────────

def test_money_already_paid_out_is_added_back_before_comparing():
    """The ledger's payable has had settlements taken out of it; the register's figure is everything
    ever certified. Comparing them raw would report every payment the company has made as a
    discrepancy, which is the fastest way to make a reconciliation ignored."""
    r = _r(ledgerPayable=5_956_750_000, settledOut=2_000_000_000)
    assert _row(r, "payable")["agrees"] is True
    assert r["settledOut"] == 2_000_000_000


def test_without_settlements_the_comparison_is_unchanged():
    assert _r()["settledOut"] == 0


def test_an_empty_job_reconciles_rather_than_erroring():
    r = gr.subcontract_reconciliation({})
    assert r["agrees"] is True and r["unpostedCount"] == 0


# ── the third state: posted, reversed, and unable to go back ─────────────────────────────────────

def test_a_reversed_document_explains_the_difference_just_as_an_unposted_one_does():
    """`gl_batches` carries a UNIQUE (source, source_id, kind), so a document posted and then
    reversed can never be posted again. It is out of the books exactly as a never-posted one is —
    and until this existed a reversal left the month short by the whole document with NOTHING on
    any screen saying so: not in the ledger, and not in the "not in the ledger" list either."""
    r = _r(ledgerCost=8_250_000_000, ledgerPayable=7_866_500_000, ledgerRetention=383_500_000,
           reversedOut=[{"label": "IPC-009", "amount": 95_000_000}])
    assert r["agrees"] is False
    assert r["reversedOutCount"] == 1 and r["reversedOutTotal"] == 95_000_000
    w = [x for x in r["warnings"] if x["code"] == "difference_is_unposted"][0]
    assert "cannot be posted again" in w["msg"]
    assert "manual journal, not a click" in w["msg"]
    assert w["reversedOut"] == ["IPC-009"]


def test_the_two_kinds_of_missing_document_are_counted_together_and_listed_apart():
    """Both leave the books short, so both explain the difference. The FIX differs — one is a
    click, the other is a journal — so they are never merged into one list."""
    r = _r(ledgerCost=7_950_000_000, ledgerPayable=7_581_500_000, ledgerRetention=368_500_000,
           unposted=[{"label": "IPC-007", "amount": 300_000_000}],
           reversedOut=[{"label": "IPC-009", "amount": 95_000_000}])
    assert r["missingTotal"] == 395_000_000
    assert r["unpostedTotal"] == 300_000_000 and r["reversedOutTotal"] == 95_000_000
    assert "difference_is_unposted" in _codes(r)
    assert [u["label"] for u in r["unposted"]] == ["IPC-007"]
    assert [u["label"] for u in r["reversedOut"]] == ["IPC-009"]


def test_a_reversal_is_not_offered_a_post_button_it_could_never_use():
    """It is reported, not queued. Offering an action that cannot succeed is worse than saying why
    it cannot — the same rule the QS gate follows for a blocked certificate."""
    import io as _io
    src = _io.open("app.py", encoding="utf-8").read()
    i = src.index("reversed_out = [")
    block = src[i:src.index("]\n", i)]
    assert "gl.REVERSE" in block, "the list is not built from reversal batches"
    assert "pending.append" not in block, "a reversed document was queued as postable"
    # And the reason it cannot be re-posted is written where somebody changing this will read it.
    why = src[max(0, i - 1000):i]
    assert "UNIQUE (source, source_id, kind)" in why, \
        "nothing says WHY a reversed document is reported rather than offered a button"


def test_agreement_while_a_document_sits_reversed_out_is_still_reported():
    r = _r(reversedOut=[{"label": "IPC-009", "amount": 95_000_000}])
    assert r["agrees"] is True
    assert "agrees_with_documents_outstanding" in _codes(r)
