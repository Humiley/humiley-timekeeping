"""A price above the company's threshold leaves the building only with a name on it.

The rule the tests exist for is the second one: a signature signs a PRICE. Sign at ₫900m, re-price
a line to ₫1.4bn, and the signature is still on the record — real name, real timestamp — now
standing behind a number nobody approved. That is the failure that looks completely fine.
"""
import tender


def Q(gross=1000, **kw):
    q = {"subtotal": gross, "discount": 0, "discountPct": 0, "net": gross, "vat": 0,
         "gross": gross, "lineCount": 1, "lines": [], "grossMarginPct": 20.0}
    q.update(kw)
    return q


def T(**kw):
    t = {"quoteNo": "QT-1", "client": "Acme", "clientTaxCode": "0123456789",
         "issueDate": "2026-01-05", "validUntil": "2026-02-05", "exclusions": "Crane hire"}
    t.update(kw)
    return t


def SIG(meaning=None, signed_for=None, name="Director"):
    s = {"name": name, "email": "d@humiley.com", "ts": "2026-01-05T10:00:00Z",
         "meaning": meaning if meaning is not None else tender.ISSUE_MEANING,
         "method": "Microsoft 365 re-authentication"}
    if signed_for is not None:
        s["signedFor"] = signed_for
    return s


# ── the threshold ────────────────────────────────────────────────────────────────────────────────

def test_below_the_threshold_nothing_changes():
    """Most quotations are routine. A control that fires on all of them is one people route around."""
    chk = tender.issue_check(T(), Q(500), sign_threshold=1000)
    assert chk["canIssue"] is True
    assert not chk["signature"]["required"]


def test_at_or_above_the_threshold_an_unsigned_quotation_cannot_be_issued():
    chk = tender.issue_check(T(), Q(1000), sign_threshold=1000)
    assert chk["canIssue"] is False
    assert any("electronic signature" in m for m in chk["missing"]), chk["missing"]


def test_the_refusal_names_both_numbers():
    """'Not ready to issue' with no figures leaves somebody guessing which rule fired."""
    chk = tender.issue_check(T(), Q(2500), sign_threshold=1000)
    msg = " ".join(chk["missing"])
    assert "2,500" in msg and "1,000" in msg


def test_a_signed_quotation_above_the_threshold_may_be_issued():
    chk = tender.issue_check(T(signatures=[SIG(signed_for=1000)]), Q(1000), sign_threshold=1000)
    assert chk["canIssue"] is True, chk["missing"]


def test_no_threshold_set_means_no_signature_is_demanded():
    """The company has not turned this on. It must not block every quotation by default."""
    for off in (0, "", None, "0"):
        chk = tender.issue_check(T(), Q(999999), sign_threshold=off)
        assert chk["canIssue"] is True, (off, chk["missing"])


# ── a signature signs a price ────────────────────────────────────────────────────────────────────

def test_a_signature_given_for_a_different_total_does_not_authorise_this_one():
    """THE finding. Signed at 900, re-priced to 1400 — the document leaving is not the one approved."""
    chk = tender.issue_check(T(signatures=[SIG(signed_for=900)]), Q(1400), sign_threshold=1000)
    assert chk["canIssue"] is False
    assert any("fresh electronic signature" in m for m in chk["missing"]), chk["missing"]


def test_the_stale_refusal_names_what_was_signed_and_what_it_is_now():
    chk = tender.issue_check(T(signatures=[SIG(signed_for=900)]), Q(1400), sign_threshold=1000)
    msg = " ".join(chk["missing"])
    assert "900" in msg and "1,400" in msg


def test_a_price_that_went_DOWN_after_signing_is_also_stale():
    """Cheaper is not automatically approved: the discount that got it there was nobody's decision."""
    chk = tender.issue_check(T(signatures=[SIG(signed_for=1400)]), Q(1100), sign_threshold=1000)
    assert chk["canIssue"] is False


def test_a_signature_matching_the_current_total_is_not_stale():
    st = tender.issue_signature_state(T(signatures=[SIG(signed_for=1400)]), Q(1400), 1000)
    assert st["signed"] and not st["stale"]


def test_a_signature_from_before_the_price_was_stamped_is_not_called_stale():
    """Older records carry no signedFor. Treating a missing stamp as a mismatch would invalidate
    every signature taken before this rule existed — and the record does not say they are wrong."""
    st = tender.issue_signature_state(T(signatures=[SIG()]), Q(1400), 1000)
    assert st["signed"] is True and st["stale"] is False
    assert tender.issue_check(T(signatures=[SIG()]), Q(1400), sign_threshold=1000)["canIssue"]


# ── which signature counts ───────────────────────────────────────────────────────────────────────

def test_a_signature_applied_for_some_other_purpose_is_not_an_issue_signature():
    """est_projects can carry approval signatures too. One of those must not open the door."""
    other = SIG(meaning="Reviewed", signed_for=1000)
    chk = tender.issue_check(T(signatures=[other]), Q(1000), sign_threshold=1000)
    assert chk["canIssue"] is False
    assert tender.issue_signature(T(signatures=[other])) is None


def test_the_issue_signature_is_found_among_others():
    sigs = [SIG(meaning="Reviewed"), SIG(signed_for=1000), SIG(meaning="Approved")]
    got = tender.issue_signature(T(signatures=sigs))
    assert got is not None and got["signedFor"] == 1000


def test_the_meaning_is_matched_case_insensitively_but_not_loosely():
    assert tender.issue_signature(T(signatures=[SIG(meaning="issued to customer")])) is not None
    assert tender.issue_signature(T(signatures=[SIG(meaning="Issued")])) is None


def test_no_signatures_at_all_is_not_a_crash():
    for empty in ({}, {"signatures": []}, {"signatures": None}):
        assert tender.issue_signature(empty) is None


# ── the state the screen draws ───────────────────────────────────────────────────────────────────

def test_the_state_carries_who_signed_and_when():
    st = tender.issue_signature_state(T(signatures=[SIG(signed_for=1000)]), Q(1000), 1000)
    assert st["signer"] == "Director" and st["signedAt"].startswith("2026-01-05")
    assert st["signedFor"] == 1000 and st["threshold"] == 1000


def test_issue_check_reports_the_signature_state_even_when_it_is_not_required():
    """The screen needs to say 'no signature needed' as much as 'one is'."""
    chk = tender.issue_check(T(), Q(10), sign_threshold=1000)
    assert chk["signature"]["required"] is False and chk["signature"]["signed"] is False


def test_the_other_issue_rules_still_fire_alongside_it():
    """A new blocking rule must not become the only one that reports."""
    chk = tender.issue_check({"exclusions": "Crane"}, Q(5000), sign_threshold=1000)
    assert "Quotation number" in chk["missing"]
    assert any("electronic signature" in m for m in chk["missing"])


def test_a_threshold_typed_with_separators_still_works():
    """Portal settings are strings, and money is typed with commas."""
    chk = tender.issue_check(T(), Q(2000), sign_threshold="1,000")
    assert chk["canIssue"] is False
