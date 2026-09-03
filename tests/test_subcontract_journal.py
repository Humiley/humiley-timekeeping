"""The obligation a subcontractor's certificate creates, reaching the accounts.

purchase_journal recognises buy-side cost when the money LEAVES, and documented why: nothing in the
portal booked a payable when the obligation arose, "so there is no 331 balance because nothing
accrues one. When a purchase invoice register exists, this becomes Dr 331 and the accrual carries
the expense instead."

A subcontractor payment certificate is that document, and until now it reached no account at all —
the back-to-back position reported billions payable that appeared nowhere in the trial balance.

The rule this file mostly guards is that the SAME MONEY MUST NOT POST TWICE. An incomplete ledger is
silent; a double-counted one is confidently wrong.
"""
import re

import pytest

import gl
import subcontract_journal as sj


def _c(**kw):
    return dict({"certNo": "IPC-002", "pkgNo": "PKG-001", "vendor": "Thanh Cong M&E",
                 "grossClaimed": 2_900_000_000, "retentionDeducted": 145_000_000,
                 "netCertified": 2_755_000_000, "status": "Certified",
                 "certDate": "2026-05-28"}, **kw)


def _by(lines, acc):
    return next((l for l in lines if l["account"] == acc), None)


# ── the entry ────────────────────────────────────────────────────────────────────────────────────

def test_the_certificate_books_the_cost_and_what_is_owed_for_it():
    e = sj.entries(_c())
    assert _by(e, "627")["debit"] == 2_900_000_000
    assert _by(e, "331")["credit"] == 2_755_000_000
    assert _by(e, "3388")["credit"] == 145_000_000


def test_it_balances():
    e = sj.entries(_c())
    assert sum(l["debit"] for l in e) == sum(l["credit"] for l in e)
    b = gl.batch(gl.SUBCERT, "subcert:x", "2026-05-28", e)
    assert b["debit"] == b["credit"] == 2_900_000_000


def test_retention_is_held_apart_from_ordinary_trade_payables():
    """It is owed and it is NOT due — half waits for practical completion and the rest for the end
    of the defects period. Inside 331 the balance sheet states the company owes it today."""
    e = sj.entries(_c())
    assert _by(e, "3388") is not None
    assert _by(e, "331")["credit"] == 2_755_000_000, "retention was folded into trade payables"


def test_a_certificate_with_no_retention_posts_two_lines_and_not_a_zero():
    """A nil line in a trial balance is a line somebody has to read and discard."""
    e = sj.entries(_c(retentionDeducted=0, netCertified=2_900_000_000))
    assert len(e) == 2 and _by(e, "3388") is None


def test_the_cost_carries_the_package_and_certificate_it_came_from():
    assert "PKG-001" in _by(sj.entries(_c()), "627")["memo"]
    assert "IPC-002" in _by(sj.entries(_c()), "627")["memo"]


# ── what it refuses ──────────────────────────────────────────────────────────────────────────────

def test_a_certificate_whose_own_figures_disagree_does_not_post():
    """gross less retention must equal the net somebody signed. Where it does not, one of the three
    is wrong, and posting any two of them puts a figure in the books that appears on no piece of
    paper. qsurvey.subcontract_position() reports the same disagreement without correcting it."""
    with pytest.raises(gl.LedgerError) as ex:
        sj.entries(_c(netCertified=2_000_000_000))
    assert "does not add up" in str(ex.value)
    assert "appears on no piece of paper" in str(ex.value)


def test_a_rounding_crumb_between_the_three_figures_is_not_a_disagreement():
    e = sj.entries(_c(netCertified=2_755_000_001))
    assert _by(e, "331")["credit"] == 2_755_000_000, "the DERIVED net posts, not the typed one"


def test_a_certificate_with_no_net_stated_is_posted_from_the_two_that_are():
    e = sj.entries(_c(netCertified=""))
    assert _by(e, "331")["credit"] == 2_755_000_000


def test_a_certificate_for_nothing_does_not_post():
    with pytest.raises(gl.LedgerError) as ex:
        sj.entries(_c(grossClaimed=0))
    assert "worth nil" in str(ex.value)


def test_retention_larger_than_the_certificate_does_not_post():
    with pytest.raises(gl.LedgerError) as ex:
        sj.entries(_c(retentionDeducted=3_000_000_000, netCertified=""))
    assert "negative amount" in str(ex.value)


def test_negative_retention_does_not_post():
    with pytest.raises(gl.LedgerError):
        sj.entries(_c(retentionDeducted=-1, netCertified=""))


def test_check_says_why_without_being_asked_to_build_the_entry():
    """A screen reporting "could not post" and not why sends somebody to the accountant with no
    question to ask."""
    assert sj.check(_c()) == ""
    assert "does not add up" in sj.check(_c(netCertified=1))


# ── the accounts are the accountant's decision ───────────────────────────────────────────────────

def test_every_account_is_overridable():
    a = {"cost": "154", "payable": "3311", "retention": "3312"}
    e = sj.entries(_c(), a)
    assert _by(e, "154")["debit"] == 2_900_000_000
    assert _by(e, "3311")["credit"] == 2_755_000_000
    assert _by(e, "3312")["credit"] == 145_000_000


def test_a_contractor_can_post_each_trade_to_its_own_account():
    e = sj.entries(_c(discipline="hvac"), {"byTrade": {"hvac": "6272"}})
    assert _by(e, "6272")["debit"] == 2_900_000_000


def test_a_trade_with_no_account_of_its_own_falls_to_the_default_and_is_named():
    e = sj.entries(_c(discipline="civil"), {"byTrade": {"hvac": "6272"}})
    assert _by(e, "627") is not None
    assert any("627" in w for w in sj.warnings(_c(discipline="civil"), {"byTrade": {"hvac": "6272"}}))


def test_the_default_accounts_are_flagged_as_the_accountants_decision_not_ours():
    w = " ".join(sj.warnings(_c()))
    assert "627, 154 or 632" in w and "your decision" in w
    assert "owed and not due" in w


def test_an_overridden_account_is_not_warned_about():
    assert not [x for x in sj.warnings(_c(), {"cost": "154", "retention": "3312"})
                if "your decision" in x or "owed and not due" in x]


def test_the_classes_a_trial_balance_needs_are_right():
    """627 is an expense, 331 and 3388 are liabilities. They classify on their first digit, so a
    company's own sub-accounts work without anybody maintaining a list."""
    assert gl.CLASSES["6"][0] == gl.EXPENSE
    assert gl.CLASSES["3"][0] == gl.LIABILITY


# ── the same money must not post twice ───────────────────────────────────────────────────────────

def test_paying_a_certificate_clears_the_payable_instead_of_recognising_the_cost_again():
    """The settlement category is the whole mechanism preventing a double count. Mapped anywhere in
    class 6 it would recognise the cost a second time."""
    import purchase_journal as pj
    acc, mapped = pj.expense_account("Subcontract settlement")
    assert acc == "331", "settling a certificate must debit the payable, not an expense"
    assert mapped is True
    assert gl.CLASSES[acc[0]][0] == gl.LIABILITY


def test_the_settlement_says_what_happens_when_nothing_accrued_it():
    import purchase_journal as pj
    w = " ".join(pj.warnings({"category": "Subcontract settlement", "bankSlip": "x"}))
    assert "does NOT recognise cost" in w or "not recognise cost" in w.lower()
    assert "331 goes into debit" in w


def test_the_module_names_the_two_things_it_will_not_post_and_why():
    joined = " ".join(sj.UNPOSTED)
    assert "pm_costs" in joined
    assert "count every one of them twice" in joined
    assert "worse than one that is incomplete" in joined
    assert "Subcontract settlement" in joined


def test_a_paid_certificate_still_accrues_and_says_what_the_payment_must_do():
    """The obligation does not stop existing because somebody has since paid it. A certificate that
    went straight to paid and never accrued would leave the settlement clearing a payable nothing
    ever credited."""
    assert "paid" in sj.POSTABLE and "certified" in sj.POSTABLE
    assert "submitted" not in sj.POSTABLE
    w = " ".join(sj.warnings(_c(status="Paid")))
    assert "Subcontract settlement" in w and "second time" in w


# ── the wiring ───────────────────────────────────────────────────────────────────────────────────

def _app():
    import io
    return io.open("app.py", encoding="utf-8").read()


def _spec():
    src = _app()
    i = src.index("gl.SUBCERT: {")
    return src[i:src.index("gl.CREDIT_NOTE: {", i)]


def test_the_certificate_is_a_ledger_source():
    src = _app()
    assert "gl.SUBCERT: {" in src
    spec = _spec()
    assert '"coll": "pm_procurement_payments"' in spec
    assert "subcontract_journal.entries" in spec and "subcontract_journal.warnings" in spec


def test_it_is_filed_by_the_certificate_date_and_never_by_today():
    """A posting dated by the day somebody pressed the button is money in a period it never
    happened in."""
    assert '"dates": ("certDate", "ts")' in _spec()


def test_a_submitted_certificate_is_not_a_liability():
    spec = _spec()
    assert '"status": ("certified", "paid")' in spec
    assert "submitted one is the" in spec


def test_a_paid_certificate_is_still_postable_through_the_shared_status_rule():
    """The status check was a single string comparison, so a tuple would have silently matched
    nothing and left every certificate unposted."""
    src = _app()
    i = src.index("def _gl_status_ok(")
    body = src[i:src.index("def _gl_subcert_doc(", i)]
    assert "isinstance(want, str)" in body
    assert "have in (" in body
    # And both call sites go through it — a second hand-rolled comparison is how the posting path
    # and the unposted list start disagreeing about what is postable.
    assert src.count('str(doc.get("status") or "").strip().lower() != spec["status"]') == 0
    assert src.count("self._gl_status_ok(spec,") == 2


def test_the_subcontract_accounts_are_their_own_map():
    """One shared dict would let a buy-side override leak into the sell side, which is the reason
    the other two are separate already."""
    src = _app()
    assert "portal_subcontractAccounts" in src
    i = src.index("if source == gl.SUBCERT:")
    body = src[i:i + 400]
    assert "self._gl_subcontract_accounts()" in body


def test_the_trade_is_resolved_from_the_package_and_not_guessed_inside_the_journal():
    """The journal is pure and takes one document; the trade lives on pm_procurement."""
    src = _app()
    i = src.index("def _gl_subcert_doc(")
    body = src[i:src.index("# Each sell-side source", i)]
    assert 'db.list_collection("pm_procurement")' in body
    assert 'p.get("projectId") == cert.get("projectId")' in body, \
        "a package number is only unique within a project"


def test_the_settlement_category_is_offered_on_the_payment_form():
    """Mapped in purchase_journal and absent from the form, it is a rule nobody can choose — the
    competence register shipped exactly that way."""
    import io
    html = io.open("templates/index.html", encoding="utf-8").read()
    i = html.index("const _PAY_CATS = [")
    assert "'Subcontract settlement'" in html[i:html.index("];", i)]


def test_pm_costs_is_not_and_must_not_become_a_ledger_source():
    """The project cost register is a MANAGEMENT record of the same money the certificates and the
    payment requests already carry. Posting it would count all of it twice."""
    src = _app()
    i = src.index("GL_SALES_SOURCES = {")
    body = src[i:src.index("def _gl_doc_date(", i)]
    assert '"pm_costs"' not in body, "pm_costs became a ledger source — that double-counts the job"


def test_the_unposted_list_sees_the_same_document_the_posting_will():
    """Called on the raw row, every certificate reported "no trade is recorded against this" even
    where its package carried one. A warning that is wrong is worse than no warning, because
    somebody acts on it. Found by running it, not by a test."""
    src = _app()
    i = src.index("pending.append({\"source\": src, \"sourceId\": sid")
    body = src[i - 500:i + 700]
    # Matched as a SHAPE, not as one exact spelling. The invariant is that the row is resolved
    # through _gl_subcert_doc and that the RESOLVED document is what the warnings and detail are
    # built from — not that the call takes exactly one argument. Pinning the literal line made this
    # fail on a change that preserved the behaviour completely (the summary now hands the helper a
    # prebuilt package index instead of making it re-read pm_procurement per certificate), and a
    # test that fails on a correct refactor teaches people to edit tests rather than read them.
    assert re.search(r"_d = self\._gl_subcert_doc\(d(?:,\s*\w+)?\)\s+if src == gl\.SUBCERT else d",
                     body), body[-500:]
    assert 'spec["warnings"](_d)' in body and 'spec["detail"](_d)' in body


def test_a_certificate_that_cannot_post_says_why_and_offers_no_button():
    """Offering a button that will always fail is worse than saying why it will."""
    src = _app()
    i = src.index("pending.append({\"source\": src, \"sourceId\": sid")
    assert '"blocked": (subcontract_journal.check(_d)' in src[i:i + 900]
    import io
    html = io.open("templates/index.html", encoding="utf-8").read()
    j = html.index("const pending = (r.pending || []).length")
    card = html[j:html.index("</div>').join('') + '</div>'", j)]
    assert "p.blocked" in card, "the reason is served and never rendered"
    assert "canPost && !r.closed && !p.blocked" in card, "a blocked document still offers the button"
