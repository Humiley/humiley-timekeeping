"""Reverse traceability: which units got this component.

The failure mode worth testing for is a search that returns everything — a blank query selecting the
whole register, or a match so loose that every unit appears. Both produce a recall list nobody can
act on, which is the same as having none.
"""
import ahu_recall as R


TRACE = [
    {"id": "t1", "unitId": "u1", "component": "Fan", "maker": "ebm-papst",
     "serial": "EB-2026-0091", "batch": "B-2026-14", "recordedOn": "2026-07-02"},
    {"id": "t2", "unitId": "u2", "component": "Fan", "maker": "ebm-papst",
     "serial": "EB-2026-0092", "batch": "B-2026-14", "recordedOn": "2026-07-03"},
    {"id": "t3", "unitId": "u3", "component": "Coil", "maker": "Kaori",
     "serial": "KO-771", "batch": "C-99", "recordedOn": "2026-07-04"},
    {"id": "t4", "unitId": "u1", "component": "Motor", "maker": "WEG",
     "serial": "WG-5", "batch": "M-1", "recordedOn": "2026-07-05"},
]
UNITS = {"u1": {"id": "u1", "pin": "PIN-01", "tag": "AHU-A"},
         "u2": {"id": "u2", "pin": "PIN-02", "tag": "AHU-B"},
         "u3": {"id": "u3", "pin": "PIN-03", "tag": "AHU-C"}}
ORDERS = {"u1": {"poNumber": "PO-1", "customer": "Acme", "deliveryDate": "2026-09-01"}}
DISPATCH = [{"unitId": "u1", "dispatchedOn": "2026-08-01", "consignee": "Acme Site 2"}]


# ── finding things ───────────────────────────────────────────────────────────────────────────────

def test_a_batch_finds_every_unit_that_received_it():
    """The question a supplier's recall notice asks."""
    m = R.search(TRACE, "B-2026-14", UNITS)
    assert sorted(x["pin"] for x in m) == ["PIN-01", "PIN-02"]


def test_a_serial_finds_the_one_unit():
    m = R.search(TRACE, "EB-2026-0092", UNITS)
    assert [x["pin"] for x in m] == ["PIN-02"]


def test_a_maker_finds_everything_they_supplied():
    assert len(R.search(TRACE, "ebm-papst", UNITS)) == 2


def test_the_match_survives_case_and_stray_spaces():
    """A serial is typed by a person at a workstation, not scanned into a form."""
    for q in ("b-2026-14", "  B-2026-14 ", "B-2026-14"):
        assert len(R.search(TRACE, q, UNITS)) == 2, q


def test_a_partial_serial_still_matches():
    """Somebody who remembers half the number still needs an answer."""
    assert len(R.search(TRACE, "2026-009", UNITS)) == 2


def test_every_row_says_which_field_matched():
    """A list you cannot audit gets ignored wholesale. Broad matching is only safe if a person can
    see WHY each row is there and discard the false ones quickly."""
    m = R.search(TRACE, "Fan", UNITS)
    assert all("component" in x["matchedOn"] for x in m)


# ── not finding things ───────────────────────────────────────────────────────────────────────────

def test_an_empty_query_returns_nothing_rather_than_everything():
    """THE test. A blank search box that silently selects the whole register is how somebody recalls
    a factory."""
    for q in ("", None, "   "):
        assert R.search(TRACE, q, UNITS) == [], q


def test_a_query_matching_nothing_returns_nothing():
    assert R.search(TRACE, "NO-SUCH-PART", UNITS) == []


def test_an_empty_register_does_not_raise():
    assert R.search(None, "anything") == []
    assert R.search([], "anything") == []


def test_a_unit_the_register_does_not_know_still_reports_its_id():
    """A trace row pointing at a deleted unit must not vanish from a recall list."""
    m = R.search([{"id": "t9", "unitId": "gone", "serial": "X-1"}], "X-1", UNITS)
    assert m[0]["pin"] == "gone"


# ── the list somebody acts on ────────────────────────────────────────────────────────────────────

def test_matches_collapse_to_one_row_per_unit():
    g = R.group_by_unit(R.search(TRACE, "ebm-papst", UNITS))
    assert [x["pin"] for x in g] == ["PIN-01", "PIN-02"]
    assert all(x["count"] == 1 for x in g)


def test_a_unit_matching_twice_is_listed_once_with_both_components():
    # "-" appears in every serial and batch here, so u1 matches on both its fan and its motor.
    g = R.group_by_unit(R.search(TRACE, "-", UNITS))
    row = next(x for x in g if x["pin"] == "PIN-01")
    assert row["count"] == 2 and len(row["components"]) == 2


def test_the_customer_comes_with_the_unit_where_it_is_known():
    """The question after "which units" is always "and who has them"."""
    g = R.group_by_unit(R.search(TRACE, "ebm-papst", UNITS), ORDERS)
    row = next(x for x in g if x["pin"] == "PIN-01")
    assert row["customer"] == "Acme" and row["poNumber"] == "PO-1"


# ── has it left the building ─────────────────────────────────────────────────────────────────────

def test_a_dispatched_unit_is_reported_as_gone():
    d = R.dispatch_state("u1", DISPATCH)
    assert d["shipped"] is True and "2026-08-01" in d["where"] and "Acme Site 2" in d["where"]


def test_a_unit_with_no_dispatch_record_is_still_in_the_factory():
    assert R.dispatch_state("u2", DISPATCH)["shipped"] is False


def test_a_dispatch_record_with_no_date_is_not_read_as_shipped():
    """Derived from the record rather than assumed. "We think it went" is not an answer to give a
    customer, and it is not one to withhold a warning on either."""
    d = R.dispatch_state("u9", [{"unitId": "u9"}])
    assert d["shipped"] is False and "cannot be read" in d["where"]


def test_the_summary_splits_shipped_from_still_here():
    s = R.summarise(R.search(TRACE, "ebm-papst", UNITS), DISPATCH)
    assert s["units"] == 2
    assert s["shipped"] == ["PIN-01"] and s["inFactory"] == ["PIN-02"]


def test_the_summary_counts_each_unit_once():
    s = R.summarise(R.search(TRACE, "-", UNITS), DISPATCH)
    assert s["units"] == 3
