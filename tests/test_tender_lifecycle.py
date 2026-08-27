"""One tender, all the way through, on each of the three engines.

Every other test in this module checks a stage. This walks the whole route a real tender takes —
priced, turned into a letter, written to a workbook, adopted as a project budget, revised, and
compared against its own earlier self — and asserts that the SAME money survives each handover.

The failures it exists to catch are the ones that live BETWEEN two correct functions, which is
where this module's expensive defects have actually been: a workbook that recomputed a discount its
letter had already computed and landed a dong away, and a diff that called the discount unexplained
because the lines it compared were frozen on the other side of it. Neither function was wrong on
its own, and no test of either one could have found it.
"""
import io
import re
import zipfile

import pytest

import quote_xlsx
import tender as T


A = T.assumptions()

IMPORTS = [dict(qty=2, exwUnit=100000, currency="USD", mfnDutyPct=10, id="L1", desc="Pump"),
           dict(qty=5, exwUnit=45000, currency="USD", mfnDutyPct=5, id="L2", desc="Fan")]
BOM = [{"costCentre": "CIV", "code": "CIV-01", "descEn": "Civil", "qty": 1, "unitCostUsd": 400000},
       {"costCentre": "MEP", "code": "MEP-01", "descEn": "MEP", "qty": 1, "unitCostUsd": 300000}]
PACKAGES = [{"id": "1", "code": "WP-1", "name": "Qualification",
             "effort": [{"grade": "CON", "days": 12}, {"grade": "ENG", "days": 8}],
             "travelPeople": 2, "travelTrips": 3, "travelNights": 4},
            {"id": "2", "code": "WP-2", "name": "Validation",
             "effort": [{"grade": "SME", "days": 6}],
             "travelPeople": 1, "travelTrips": 1, "travelNights": 2}]

ENGINES = [T.TRADING, T.EPC, T.SERVICES]


def _priced(kind, **over):
    """A complete, sendable tender of the given kind — deliberately carrying a discount, because
    that is the state in which the handovers between stages actually go wrong."""
    t = dict({"costingType": kind, "vatPct": 10, "assump": {}, "id": "T1", "quoteNo": "QT-1",
              "accuracyClass": "3", "discountPct": 6, "client": "Khách hàng", "title": "Nhà máy",
              "validUntil": "2026-12-31", "preparedBy": "Sales", "durationMonths": 12}, **over)
    if kind == T.TRADING:
        kw = dict(master=T.cost_master(IMPORTS, [], A))
    elif kind == T.EPC:
        kw = dict(rollup=T.bom_rollup(BOM, A))
    else:
        kw = dict(rollup=T.services_rollup(PACKAGES, A))
    return t, T.quotation(t, **kw), kw


def _reworked(kind):
    """The same tender after somebody re-priced its largest line."""
    if kind == T.TRADING:
        return dict(master=T.cost_master([dict(IMPORTS[0], exwUnit=130000), IMPORTS[1]], [], A))
    if kind == T.EPC:
        return dict(rollup=T.bom_rollup([dict(BOM[0], unitCostUsd=520000), BOM[1]], A))
    return dict(rollup=T.services_rollup(
        [dict(PACKAGES[0], effort=[{"grade": "CON", "days": 18}, {"grade": "ENG", "days": 8}]),
         PACKAGES[1]], A))


def _sheet_numbers(doc):
    """Every numeric cell value in the generated workbook — the bytes, not the writer's intent."""
    z = zipfile.ZipFile(io.BytesIO(quote_xlsx.build(doc)))
    name = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")][0]
    xml = z.read(name).decode("utf-8")
    return {float(m.group(1)) for m in re.finditer(r"<v>(-?\d+(?:\.\d+)?)</v>", xml)}


# --- the price is internally consistent -----------------------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_the_quotation_adds_up(kind):
    _t, q, _kw = _priced(kind)
    assert q["lineCount"], "an engine that priced nothing cannot prove anything below"
    assert sum(l["net"] for l in q["lines"]) == q["subtotal"]
    assert q["net"] == q["subtotal"] - q["discount"]
    assert q["gross"] == q["net"] + q["vat"]
    assert sum(l["vat"] for l in q["lines"]) == q["vat"]
    assert sum(l["discount"] for l in q["lines"]) == q["discount"], \
        "the pro-rata discount lost or gained a dong across the lines"


# --- the letter carries the same figures ------------------------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_the_letter_is_the_quotation(kind):
    t, q, _kw = _priced(kind)
    tot = T.document(t, q)["totals"]
    assert (tot["subtotal"], tot["discount"], tot["net"], tot["vat"], tot["gross"]) == \
           (q["subtotal"], q["discount"], q["net"], q["vat"], q["gross"])


@pytest.mark.parametrize("kind", ENGINES)
def test_the_letter_has_a_column_for_every_cell_and_a_description_for_every_line(kind):
    t, q, _kw = _priced(kind)
    doc = T.document(t, q)
    assert len(doc["columns"]) == 7
    assert all(str(l.get("desc") or "").strip() for l in doc["lines"]), \
        "a line the customer reads with no description"


# --- and so does the workbook -------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_the_workbook_prints_the_letters_figures(kind):
    t, q, _kw = _priced(kind)
    nums = _sheet_numbers(T.document(t, q))
    for label in ("subtotal", "discount", "vat", "gross"):
        assert float(q[label]) in nums, "%s is not the letter's in the workbook" % label


@pytest.mark.parametrize("kind", ENGINES)
def test_no_negative_money_reaches_a_customers_file(kind):
    t, q, _kw = _priced(kind)
    assert not [n for n in _sheet_numbers(T.document(t, q)) if n < 0]


# --- the budget a project inherits ---------------------------------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_the_budget_is_the_cost_base_not_the_price(kind):
    t, q, kw = _priced(kind)
    b = T.budget_lines(t, q, **kw)
    assert b["total"] < q["net"], "a project would be measured against the selling price"
    assert all(x.get("category") and x.get("amount") is not None for x in b["lines"])


@pytest.mark.parametrize("kind", ENGINES)
def test_discounting_the_price_does_not_move_the_budget(kind):
    """What we are paid changed; what delivery costs did not."""
    totals = set()
    for pct in (0, 20, 100):
        t, q, kw = _priced(kind, discountPct=pct)
        totals.add(T.budget_lines(t, q, **kw)["total"])
    assert len(totals) == 1, "the budget followed the discount: %r" % sorted(totals)


# --- revisions -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_a_revision_compared_with_itself_reports_no_movement(kind):
    t, q, kw = _priced(kind)
    rev = T.revision(t, q, T.cost_elements(t, **kw))
    c = T.compare_revisions(rev, rev)
    assert c["rows"] == [] and c["delta"] == 0 and c["unexplained"] == 0


@pytest.mark.parametrize("kind", ENGINES)
def test_every_dong_of_a_re_price_is_attributed(kind):
    """The whole point of the revision record. On a discounted tender the lines are frozen
    pre-discount while the header is post-discount, so this used to leave a residual on every
    ordinary re-price — reported under the heading reserved for a change nothing accounts for."""
    t, q, kw = _priced(kind)
    before = T.revision(t, q, T.cost_elements(t, **kw))
    kw2 = _reworked(kind)
    q2 = T.quotation(t, **kw2)
    after = T.revision(t, q2, T.cost_elements(t, **kw2))

    c = T.compare_revisions(before, after)
    assert c["delta"] != 0, "the fixture did not move the price, so this proves nothing"
    assert c["changed"], "no line was reported as having moved"
    assert c["discountKnown"] is True
    assert c["discountMoved"] != 0, "the discount moved with the subtotal; that is the case here"
    assert c["unexplained"] == 0, "an explainable movement was filed as unexplained"
    assert c["explainedByLines"] + c["discountEffect"] == c["delta"]


# --- nothing about a healthy tender trips the pre-send checks ----------------------------------------------

@pytest.mark.parametrize("kind", ENGINES)
def test_a_healthy_tender_raises_none_of_the_money_warnings(kind):
    """False positives are how a warning panel gets ignored, and an ignored panel is worse than
    no panel — it was there, and nobody read it."""
    t, q, _kw = _priced(kind)
    noisy = [w for w in T.issue_check(t, q)["warnings"]
             if any(k in w for k in ("share of the price", "rate of zero", "no money",
                                     "amount in words"))]
    assert noisy == [], noisy
