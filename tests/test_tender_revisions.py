"""What moved between one price and the next, and why.

A tender gets priced three or four times before it is won, and the only record of the previous
price was the previous price — a number in an email, with no way to say which lines produced it.
"It went up 8%" is not something anybody can check, argue with, or explain to a client.

The comparison is the point, not the archive. Storing old totals so they can be listed is a filing
cabinet; storing old LINES so a difference can be attributed is a reason the price changed.
"""
import pytest

import tender


A = tender.assumptions()

REV_A = [{"costCentre": "CIV", "code": "CIV-01", "descEn": "Civil works", "qty": 1, "unitCostUsd": 400000},
         {"costCentre": "MEP", "code": "MEP-01", "descEn": "MEP package", "qty": 1, "unitCostUsd": 300000},
         {"costCentre": "CLR", "code": "CLR-01", "descEn": "Cleanroom", "qty": 1, "unitCostUsd": 120000},
         {"costCentre": "QCL", "code": "QCL-01", "descEn": "QC lab", "qty": 1, "unitCostUsd": 60000}]
REV_B = [{"costCentre": "CIV", "code": "CIV-01", "descEn": "Civil works", "qty": 1, "unitCostUsd": 400000},
         {"costCentre": "MEP", "code": "MEP-01", "descEn": "MEP package", "qty": 1, "unitCostUsd": 345000},
         {"costCentre": "CLR", "code": "CLR-01", "descEn": "Cleanroom", "qty": 2, "unitCostUsd": 120000},
         {"costCentre": "WHS", "code": "WHS-01", "descEn": "Warehouse", "qty": 1, "unitCostUsd": 80000}]


def _rev(bom, note="", **kw):
    t = dict({"costingType": tender.EPC, "vatPct": 10, "assump": {}, "id": "T1",
              "quoteNo": "QT-1", "accuracyClass": "3"}, **kw)
    r = tender.bom_rollup(bom, A)
    q = tender.quotation(t, rollup=r)
    return tender.revision(t, q, tender.cost_elements(t, rollup=r), note=note)


# --- a revision is a copy -------------------------------------------------------------------------

def test_a_revision_freezes_the_price_it_was_taken_at():
    """A revision that recomputed itself from today's rows would not be a record of what was sent;
    it would be a second opinion about it, changing every time somebody edited a line."""
    rev = _rev(REV_A)
    later = _rev(REV_B)
    assert rev["net"] != later["net"]
    assert rev["lines"][0]["net"] == _rev(REV_A)["lines"][0]["net"], "the frozen copy moved"


def test_a_revision_carries_what_a_diff_needs_and_not_more():
    rev = _rev(REV_A)
    assert set(rev["lines"][0]) == {"id", "desc", "qty", "unitCost", "net"}
    for key in ("net", "cogs", "grossMarginPct", "accuracyClass", "quoteNo"):
        assert key in rev


def test_the_note_survives_because_why_is_the_point():
    assert _rev(REV_A, note="Rev A — issued to client")["note"] == "Rev A — issued to client"


# --- the comparison --------------------------------------------------------------------------------

def test_the_headline_says_how_much_and_which_way():
    c = tender.compare_revisions(_rev(REV_A), _rev(REV_B))
    assert c["delta"] > 0
    assert c["deltaPct"] == pytest.approx(21.11, abs=0.05)
    assert c["nowNet"] - c["wasNet"] == c["delta"]


def test_every_kind_of_movement_is_reported():
    c = tender.compare_revisions(_rev(REV_A), _rev(REV_B))
    by = {r["desc"].split(" ")[0]: r for r in c["rows"]}
    assert by["Cleanroom"]["status"] == "changed"
    assert by["Warehouse"]["status"] == "added"
    assert by["QC"]["status"] == "removed"
    assert "Civil" not in by, "an unchanged line must not appear in a list of what moved"


def test_the_biggest_mover_comes_first():
    """The question is "why did the price change", and the answer is almost always two or three
    lines. An alphabetical list of forty rows, thirty-seven unchanged, buries it."""
    rows = tender.compare_revisions(_rev(REV_A), _rev(REV_B))["rows"]
    deltas = [abs(r["delta"]) for r in rows]
    assert deltas == sorted(deltas, reverse=True)


def test_unchanged_lines_are_counted_but_not_listed():
    c = tender.compare_revisions(_rev(REV_A), _rev(REV_B))
    assert c["unchanged"] == 1          # civil
    assert c["changed"] == len(c["rows"]) == 4


def test_the_line_movements_add_up_to_the_price_movement():
    c = tender.compare_revisions(_rev(REV_A), _rev(REV_B))
    assert c["explainedByLines"] == c["delta"]
    assert c["unexplained"] == 0


# --- the movement no line explains -------------------------------------------------------------------

def test_a_document_level_discount_is_surfaced_as_unexplained():
    """A price that moved without a line moving came from somewhere else. Rounding it into the line
    list would lose the one difference actually worth looking at."""
    before = _rev(REV_B)
    after = _rev(REV_B, discountPct=5)
    c = tender.compare_revisions(before, after)
    assert c["changed"] == 0, "no line was touched"
    assert c["delta"] < 0
    assert c["explainedByLines"] == 0
    assert c["unexplained"] == c["delta"]


def test_margin_movement_is_reported_beside_the_price():
    """A price that went up while the margin went down is a different conversation from one where
    both rose."""
    before = _rev(REV_B)
    after = _rev(REV_B, discountPct=10)
    c = tender.compare_revisions(before, after)
    assert c["marginMoved"] < 0


# --- what qty/rate mean, per engine -------------------------------------------------------------------

def test_for_epc_a_scope_change_arrives_as_the_lot_rate_moving():
    """EPC quotes one LOT per cost centre. Doubling a cleanroom's BOM quantity shows here as the
    lot's rate moving, because at the level the customer is quoted there is still one cleanroom.

    Pinned so nobody later "corrects" this into reaching through to the BOM and reporting something
    the quotation does not say."""
    c = tender.compare_revisions(_rev(REV_A), _rev(REV_B))
    clr = next(r for r in c["rows"] if r["desc"].startswith("Cleanroom"))
    assert clr["rateMoved"] is True
    assert clr["qtyMoved"] is False


def test_for_trading_qty_and_rate_mean_what_they_say():
    """Trading quotes per product, so the distinction is real there: a line that doubled in
    quantity and one whose supplier put the rate up are different problems."""
    L = {"exwUnit": 100000, "currency": "USD", "mfnDutyPct": 10}
    t = {"costingType": tender.TRADING, "vatPct": 10, "assump": {}, "id": "T2"}

    def rev(qty, unit):
        imports = [dict(L, id="L1", desc="Pump", qty=qty, exwUnit=unit)]
        m = tender.cost_master(imports, [], A)
        return tender.revision(t, tender.quotation(t, master=m))

    more_qty = tender.compare_revisions(rev(1, 100000), rev(2, 100000))["rows"][0]
    assert more_qty["qtyMoved"] is True and more_qty["rateMoved"] is False

    dearer = tender.compare_revisions(rev(1, 100000), rev(1, 130000))["rows"][0]
    assert dearer["rateMoved"] is True and dearer["qtyMoved"] is False


# --- edges ---------------------------------------------------------------------------------------------

# --- keying: two ways the diff used to lose a line -------------------------------------------------

def _rev_of(net, lines, margin=10.0):
    return {"net": net, "grossMarginPct": margin, "lines": lines}


def test_two_lines_sharing_an_id_do_not_collapse_into_one():
    """`{l["id"]: l for l in lines}` keeps the LAST row with a given id and discards the rest. An
    import run twice, or a package copied, silently became one row — and the diff then compared the
    wrong pair while reporting a confident attribution. Duplicates aggregate: for the purpose of
    "what moved", two rows in the same position are one position, and their money adds up."""
    before = _rev_of(100, [{"id": "L1", "desc": "Pump", "qty": 1, "unitCost": 50, "net": 50},
                           {"id": "L1", "desc": "Pump again", "qty": 1, "unitCost": 50, "net": 50}])
    after = _rev_of(60, [{"id": "L1", "desc": "Pump", "qty": 1, "unitCost": 60, "net": 60}])
    idx = tender._diff_index(before)
    assert idx["L1"]["net"] == 100, "the duplicate row's money was dropped"
    assert idx["L1"]["aggregated"] is True
    assert idx["L1"]["unitCost"] is None, "an aggregate of two rates is not a rate anybody quoted"
    c = tender.compare_revisions(before, after)
    assert c["explainedByLines"] == c["delta"]
    assert c["unexplained"] == 0


def test_a_line_without_an_id_is_still_diffed():
    """It used to be skipped entirely, so a whole line could vanish between two revisions with no
    row saying so. The movement then surfaced as `unexplained` — the signal reserved for a discount
    or a changed mark-up — which is worse than silence: it is a specific wrong answer."""
    before = _rev_of(100, [{"id": "", "desc": "Nameless package", "qty": 1,
                            "unitCost": 100, "net": 100}])
    after = _rev_of(0, [])
    c = tender.compare_revisions(before, after)
    assert c["changed"] == 1, "the vanished line produced no row"
    assert c["rows"][0]["status"] == "removed"
    assert c["rows"][0]["desc"] == "Nameless package"
    assert c["unexplained"] == 0, "a removed line was blamed on something other than the lines"


def test_an_id_less_line_is_keyed_by_description_not_position():
    """Description survives reordering; position does not. A line that merely moved up the page
    must not read as one line removed and another added."""
    a = _rev_of(150, [{"id": "", "desc": "Alpha", "qty": 1, "unitCost": 100, "net": 100},
                      {"id": "", "desc": "Beta", "qty": 1, "unitCost": 50, "net": 50}])
    b = _rev_of(150, [{"id": "", "desc": "Beta", "qty": 1, "unitCost": 50, "net": 50},
                      {"id": "", "desc": "Alpha", "qty": 1, "unitCost": 100, "net": 100}])
    c = tender.compare_revisions(a, b)
    assert c["rows"] == [], "reordering was reported as lines added and removed"


def test_a_line_with_neither_id_nor_description_still_appears():
    """Falling through to position is the last resort, but it must not be a hole."""
    before = _rev_of(80, [{"id": "", "desc": "", "qty": 1, "unitCost": 80, "net": 80}])
    after = _rev_of(0, [])
    c = tender.compare_revisions(before, after)
    assert c["changed"] == 1 and c["unexplained"] == 0


def test_comparing_a_revision_with_itself_reports_nothing_moved():
    r = _rev(REV_A)
    c = tender.compare_revisions(r, r)
    assert c["rows"] == [] and c["delta"] == 0 and c["unexplained"] == 0


def test_a_first_revision_has_nothing_to_compare_against():
    c = tender.compare_revisions(None, _rev(REV_A))
    assert all(r["status"] == "added" for r in c["rows"])
    assert c["wasNet"] == 0


def test_an_empty_tender_produces_an_empty_revision_rather_than_raising():
    t = {"costingType": tender.EPC, "vatPct": 10, "assump": {}, "id": "T3"}
    r = tender.bom_rollup([], A)
    rev = tender.revision(t, tender.quotation(t, rollup=r))
    assert rev["lines"] == [] and rev["net"] == 0
