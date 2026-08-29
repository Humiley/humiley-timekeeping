"""How good is this number, and what was it a price for.

A budgetary figure worked up from three supplier emails and a firm price built from signed
quotations looked IDENTICAL on screen: same currency, same tabular numerals, same confidence.
Nothing recorded which one anybody was reading.

That gap does not need a bug to cost money. Somebody quotes an early number, the client treats it
as a commitment, and the difference between -50% and -10% arrives as a loss six months later. The
estimate was never wrong; it was never told how right it was.

The five classes are AACE International 18R-97, which is what the industry already reads. The
ranges are that practice's own, kept as a BAND rather than a single tolerance because an estimate
is not symmetrical — the ways a job costs more outnumber the ways it costs less, which is why
every low bound is tighter than its high one.
"""
import pytest

import tender


NET = 1_032_397_641_000


def _q(net=NET):
    return {"net": net, "cogs": int(net * 0.8), "lineCount": 1, "vat": 0, "discount": 0,
            "discountPct": 0, "grossMarginPct": 20,
            "lines": [{"unitCost": 100, "itemCode": "A", "desc": "a"}]}


def _issuable(**kw):
    return dict({"costingType": tender.EPC, "quoteNo": "Q1", "client": "X", "clientTaxCode": "1",
                 "issueDate": "2026-01-01", "validUntil": "2026-02-01",
                 # `_issuable` means issuable, and that now includes saying what is excluded.
                 "exclusions": "Crane hire"}, **kw)


# --- the class, and what it means in money ------------------------------------------------------

def test_every_class_produces_a_range_around_the_price():
    for key, _label, lo, hi, _m, _n in tender.ACCURACY_CLASSES:
        a = tender.accuracy({"accuracyClass": key}, _q())
        assert a["stated"]
        assert a["low"] == tender.vnd(NET * (1 + lo / 100.0))
        assert a["high"] == tender.vnd(NET * (1 + hi / 100.0))
        assert a["low"] < NET < a["high"]


def test_a_later_class_is_tighter_than_an_earlier_one():
    """That is the entire point of the scale: the number does not change, the confidence does."""
    spreads = [tender.accuracy({"accuracyClass": k}, _q())["spread"]
               for k, _l, _lo, _hi, _m, _n in tender.ACCURACY_CLASSES]
    assert spreads == sorted(spreads, reverse=True), "classes 5→1 must narrow, not widen"


def test_the_band_is_asymmetric_because_overruns_outnumber_underruns():
    for key, _label, lo, hi, _m, _n in tender.ACCURACY_CLASSES:
        assert abs(lo) < hi, "class %s is symmetrical; jobs do not overrun and underrun equally" % key


def test_an_unstated_class_is_reported_as_unstated_not_defaulted_to_something_comfortable():
    """Silence about maturity is the condition this exists to end. Defaulting it to a middle class
    would answer the question with a guess and stop anybody asking."""
    a = tender.accuracy({}, _q())
    assert a["stated"] is False
    assert a["key"] == tender.UNSTATED
    assert a["low"] == a["high"] == NET, "an unstated class must not invent a range"


def test_an_unknown_class_is_not_believed():
    assert tender.accuracy({"accuracyClass": "9"}, _q())["stated"] is False
    assert tender.accuracy({"accuracyClass": "gold"}, _q())["stated"] is False


def test_the_class_carries_its_maturity_so_it_can_be_argued_with():
    """"Class 3" is a label somebody nods at. "10–40% defined" is a claim about the drawings that
    a reader can check."""
    for key, _l, _lo, _hi, maturity, _n in tender.ACCURACY_CLASSES:
        assert tender.accuracy({"accuracyClass": key}, _q())["maturity"] == maturity
        assert "%" in maturity


# --- basis of estimate ---------------------------------------------------------------------------

def test_an_empty_basis_reports_every_section_as_empty_rather_than_hiding_them():
    """"We did not say" and "there is nothing to say" are different states, and only one is safe."""
    b = tender.basis_of_estimate({})
    assert b["stated"] == 0 and b["total"] == len(tender.BASIS_SECTIONS)
    assert all(not s["stated"] for s in b["sections"])
    assert all(s["prompt"] for s in b["sections"]), "an empty section must still say what belongs in it"


def test_a_partly_filled_basis_counts_only_what_was_written():
    b = tender.basis_of_estimate({"basis": {"exclusions": "Permits, client crane.",
                                            "assumptions": "FX 25,500."}})
    assert b["stated"] == 2
    assert b["exclusionsStated"] is True


def test_whitespace_is_not_a_statement():
    b = tender.basis_of_estimate({"basis": {"exclusions": "   \n  "}})
    assert b["exclusionsStated"] is False


def test_exclusions_are_singled_out():
    """Everything else describes what was done. This one describes what a client will assume was
    done unless told otherwise."""
    assert tender.basis_of_estimate({"basis": {"inclusions": "Everything"}})["exclusionsStated"] is False


# --- what the issue check says --------------------------------------------------------------------

def test_issuing_without_an_accuracy_class_warns_but_does_not_block():
    """A screening number is a legitimate thing to send. The module's job is to make sure somebody
    CHOSE to send it, not to decide for them."""
    r = tender.issue_check(_issuable(), _q())
    assert r["canIssue"] is True
    assert any("Accuracy class not stated" in w for w in r["warnings"])


def test_an_early_class_warns_with_the_actual_numbers():
    """"Class 4" does not change behaviour. "as low as X or as high as Y" does."""
    r = tender.issue_check(_issuable(accuracyClass="4"), _q())
    w = " ".join(r["warnings"])
    assert "Class 4" in w and "as low as" in w and "as high as" in w


def test_a_firm_class_does_not_warn_about_its_range():
    r = tender.issue_check(_issuable(accuracyClass="1", basis={"exclusions": "Permits."}), _q())
    assert not any("as low as" in w for w in r["warnings"])


def test_missing_exclusions_are_warned_about():
    r = tender.issue_check(_issuable(accuracyClass="1"), _q())
    assert any("excluded in writing" in w for w in r["warnings"])


def test_a_complete_tender_raises_neither_warning():
    r = tender.issue_check(_issuable(accuracyClass="2", basis={"exclusions": "Permits, crane."}), _q())
    assert not any("Accuracy class" in w or "excluded in writing" in w for w in r["warnings"])


def test_the_classes_are_the_published_ones_not_invented():
    """AACE 18R-97 is what a client's own estimator reads. Renumbering it would make the label
    look official and mean something else."""
    keys = [k for k, _l, _lo, _hi, _m, _n in tender.ACCURACY_CLASSES]
    assert keys == ["5", "4", "3", "2", "1"]
    assert tender.ACCURACY_BY_KEY["1"][1] == -3.0 and tender.ACCURACY_BY_KEY["1"][2] == 10.0
    assert tender.ACCURACY_BY_KEY["5"][1] == -20.0 and tender.ACCURACY_BY_KEY["5"][2] == 50.0


def test_the_range_never_reads_backwards():
    """The class percentages run low-to-high, which orders the MONEY only while the money is
    positive. On a negative net — a credit, a line entered with a minus — a -20%/+50% band came out
    as "as low as -80m, as high as -150m" under exactly those two labels, with a negative spread
    beneath it. Nothing errors; it just says the opposite of what it means."""
    seen = 0
    for net in (1_000_000_000, 0, -100_000_000):
        for row in tender.ACCURACY_CLASSES:
            a = tender.accuracy({"accuracyClass": row[0]}, {"net": net})
            # Without this, an unrecognised key would return the 'unstated' shape, where low and
            # high are both the net — and every assertion below would pass while testing nothing.
            assert a["stated"] is True, "the loop is not feeding accuracy() real classes"
            assert a["low"] <= a["high"], (row[0], net, a["low"], a["high"])
            assert a["spread"] >= 0, (row[0], net, a["spread"])
            seen += 1
    assert seen == 3 * len(tender.ACCURACY_CLASSES) >= 15
