"""Re-pricing a tender against the rate library: what it must never touch.

The dangerous direction here is doing too much. A hand-priced resource is a negotiated number —
usually the most reliable figure on the bill and the one nobody could reconstruct — and a re-price
that quietly averaged it away would be very hard to notice and impossible to undo.
"""
import rate_reprice as rp


LIB = [
    {"id": "rt-1", "code": "LAB-01", "desc": "Fitter", "unitCost": 120000,
     "effectiveFrom": "2026-08-01", "source": "2026 rate card"},
    {"id": "rt-2", "code": "MAT-01", "desc": "Duct steel", "unitCost": 90000,
     "effectiveFrom": "2026-08-01", "source": "Supplier list"},
]


def R(rid, rate_id=None, cost=0, **kw):
    d = {"id": rid, "unitCost": cost, "qtyPer": 1}
    if rate_id:
        d["rateId"] = rate_id
    d.update(kw)
    return d


# ── what it changes ──────────────────────────────────────────────────────────────────────────────

def test_a_library_rate_that_moved_is_brought_up_to_date():
    res = {"it-1": [R("rs-1", "rt-1", 100000)]}
    new, changes, counts = rp.plan(res, LIB, today="2026-08-29")
    assert new["it-1"][0]["unitCost"] == 120000
    assert counts["changed"] == 1
    assert changes[0]["was"] == 100000 and changes[0]["now"] == 120000
    assert changes[0]["deltaPct"] == 20.0


def test_the_snapshot_fields_move_with_the_rate():
    """Otherwise the drift check keeps comparing against the price this row used to carry, and the
    tender reports drift that has just been fixed."""
    res = {"it-1": [R("rs-1", "rt-1", 100000, ratePricedOn="2025-01-01", rateSource="old card")]}
    new, _, _ = rp.plan(res, LIB, today="2026-08-29")
    r = new["it-1"][0]
    assert r["ratePricedOn"] == "2026-08-01"
    assert r["rateSource"] == "2026 rate card"


def test_what_it_was_before_is_kept_on_the_row():
    res = {"it-1": [R("rs-1", "rt-1", 100000)]}
    new, _, _ = rp.plan(res, LIB, today="2026-08-29")
    assert new["it-1"][0]["repricedFrom"] == 100000
    assert new["it-1"][0]["repricedOn"] == "2026-08-29"


def test_a_rate_that_went_DOWN_is_applied_too():
    res = {"it-1": [R("rs-1", "rt-2", 150000)]}
    new, changes, _ = rp.plan(res, LIB, today="")
    assert new["it-1"][0]["unitCost"] == 90000
    assert changes[0]["deltaPct"] == -40.0


# ── what it must never touch ─────────────────────────────────────────────────────────────────────

def test_a_hand_priced_resource_is_left_completely_alone():
    """THE rule. No rateId means somebody negotiated this — a supplier quote, a phone call. It is
    usually the most reliable number on the bill and the one nobody could reconstruct."""
    hand = R("rs-9", None, 777000, desc="Crane hire, quoted")
    res = {"it-1": [hand]}
    new, changes, counts = rp.plan(res, LIB, today="")
    assert new["it-1"][0] == hand
    assert counts["handPriced"] == 1 and counts["changed"] == 0
    assert changes == []


def test_a_rate_that_has_gone_from_the_library_leaves_the_row_at_its_price():
    """Substituting anything else would be inventing a rate."""
    res = {"it-1": [R("rs-1", "rt-GONE", 55000)]}
    new, changes, counts = rp.plan(res, LIB, today="")
    assert new["it-1"][0]["unitCost"] == 55000
    assert counts["goneFromLibrary"] == 1 and not changes


def test_a_rate_that_has_not_moved_is_not_rewritten():
    """A row rewritten with the same number still looks edited, and 'nothing changed' is a real and
    useful answer."""
    res = {"it-1": [R("rs-1", "rt-1", 120000)]}
    new, changes, counts = rp.plan(res, LIB, today="")
    assert "repricedFrom" not in new["it-1"][0]
    assert counts["unchanged"] == 1 and not changes


def test_the_original_rows_are_not_mutated():
    """The caller prices the CURRENT set and the planned set and compares them. Mutating in place
    would make both sides the same and the preview would report no change at all."""
    orig = R("rs-1", "rt-1", 100000)
    res = {"it-1": [orig]}
    rp.plan(res, LIB, today="")
    assert orig["unitCost"] == 100000
    assert "repricedFrom" not in orig


# ── shape and reporting ──────────────────────────────────────────────────────────────────────────

def test_every_resource_survives_the_plan():
    """A dropped build-up is a line that silently loses its cost."""
    res = {"it-1": [R("rs-1", "rt-1", 100000), R("rs-2", None, 5000)],
           "it-2": [R("rs-3", "rt-2", 90000), R("rs-4", "rt-GONE", 1)]}
    new, _, counts = rp.plan(res, LIB, today="")
    assert sorted(r["id"] for rows in new.values() for r in rows) == \
        ["rs-1", "rs-2", "rs-3", "rs-4"]
    assert sum(counts.values()) == 4


def test_the_item_a_resource_hangs_off_is_preserved():
    res = {"it-1": [R("rs-1", "rt-1", 1)], "it-2": [R("rs-2", "rt-2", 1)]}
    new, _, _ = rp.plan(res, LIB, today="")
    assert [r["id"] for r in new["it-1"]] == ["rs-1"]
    assert [r["id"] for r in new["it-2"]] == ["rs-2"]


def test_the_biggest_move_is_listed_first():
    """An estimator scanning eleven rows should not have to hunt for the one that matters."""
    res = {"it-1": [R("rs-small", "rt-1", 119000),      # +1,000
                    R("rs-big", "rt-2", 10000)]}        # +80,000
    _, changes, _ = rp.plan(res, LIB, today="")
    assert [c["resourceId"] for c in changes] == ["rs-big", "rs-small"]


def test_changed_rows_returns_exactly_what_has_to_be_saved():
    res = {"it-1": [R("rs-1", "rt-1", 100000), R("rs-2", None, 5000),
                    R("rs-3", "rt-2", 90000)]}
    new, changes, _ = rp.plan(res, LIB, today="")
    rows = rp.changed_rows(new, changes)
    assert [r["id"] for r in rows] == ["rs-1"]


def test_changed_rows_is_empty_when_nothing_moved():
    res = {"it-1": [R("rs-1", "rt-1", 120000)]}
    new, changes, _ = rp.plan(res, LIB, today="")
    assert rp.changed_rows(new, changes) == []


def test_a_row_an_EARLIER_reprice_touched_is_not_reported_as_changed_again():
    """The marker `repricedFrom` is written to the database and stays there. Selecting on it would
    match every row a previous run had touched — reporting a tender as freshly re-priced when
    nothing had moved. Caught by the API test that re-applied twice."""
    already = R("rs-1", "rt-1", 120000, repricedFrom=90000, repricedOn="2026-01-01")
    res = {"it-1": [already]}
    new, changes, counts = rp.plan(res, LIB, today="2026-08-29")
    assert counts["unchanged"] == 1 and changes == []
    assert rp.changed_rows(new, changes) == []


def test_an_empty_tender_is_not_a_crash():
    for empty in (None, {}, {"it-1": []}, {"it-1": None}):
        new, changes, counts = rp.plan(empty, LIB, today="")
        assert changes == [] and counts["changed"] == 0


def test_an_empty_library_changes_nothing():
    res = {"it-1": [R("rs-1", "rt-1", 100000)]}
    new, changes, counts = rp.plan(res, [], today="")
    assert new["it-1"][0]["unitCost"] == 100000
    assert counts["goneFromLibrary"] == 1


def test_money_typed_with_separators_is_compared_as_money_not_text():
    """'120,000' and 120000 are the same rate. Comparing them as strings would rewrite every row on
    every re-price and report drift that does not exist."""
    res = {"it-1": [R("rs-1", "rt-1", "120,000")]}
    new, changes, counts = rp.plan(res, LIB, today="")
    assert counts["unchanged"] == 1 and not changes
