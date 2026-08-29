"""Duplicating a tender: the bill comes with it, the original's history does not.

Two failures here would be silent, which is why they get most of the tests:

  * a build-up still pointing at the ORIGINAL tender's bill line — the copy prices nothing, the
    original prices everything twice, and both screens look ordinary;
  * a copy that inherits `adoptedProjectId` and is therefore FROZEN from the moment it is created.
"""
import est_copy


def _ids():
    n = [0]

    def mk():
        n[0] += 1
        return "new-%d" % n[0]
    return mk


SRC = {
    "id": "est-old", "title": "Hanoi plant AHUs", "estNo": "EST-0007", "quoteNo": "QT-2025-0007",
    "client": "Acme", "clientTaxCode": "0123456789", "costingType": "trading",
    "status": "Lost", "issueDate": "2025-03-01", "validUntil": "2025-04-01",
    "amountInWords": "One billion dong", "approvedBy": "Director",
    "overheadPct": 8, "riskPct": 5, "profitPct": 12, "profitBasis": "markup",
    "scope": "Supply 2x AHU", "exclusions": "Crane hire",
}


def _rows(**kw):
    base = {"est_items": [], "est_resources": [], "est_landed": [], "est_local": [],
            "est_bom": [], "est_wbs": [], "est_quote": [], "est_risks": [], "est_revs": []}
    base.update(kw)
    return base


# --- the thing that must not go wrong -----------------------------------------------------------

def test_a_build_up_follows_its_line_into_the_copy():
    """THE finding. Copy both without re-pointing and the resource still names the original's line."""
    rows = _rows(
        est_items=[{"id": "it-1", "estId": "est-old", "desc": "AHU"}],
        est_resources=[{"id": "rs-1", "estId": "est-old", "itemId": "it-1", "desc": "Coil"}])
    head, out, rep = est_copy.duplicate(SRC, rows, "est-new", _ids())
    new_item = out["est_items"][0]
    new_res = out["est_resources"][0]
    assert new_res["itemId"] == new_item["id"]
    assert new_res["itemId"] != "it-1"          # not the original's line
    assert new_res["estId"] == "est-new"


def test_each_build_up_follows_its_OWN_line():
    """Two lines, two build-ups. A remap that pairs them by position rather than by id would pass a
    single-line test and silently swap the rates here."""
    rows = _rows(
        est_items=[{"id": "it-1", "estId": "est-old", "desc": "AHU"},
                   {"id": "it-2", "estId": "est-old", "desc": "Ductwork"}],
        est_resources=[{"id": "rs-1", "estId": "est-old", "itemId": "it-2", "desc": "Sheet steel"},
                       {"id": "rs-2", "estId": "est-old", "itemId": "it-1", "desc": "Coil"}])
    _, out, _ = est_copy.duplicate(SRC, rows, "est-new", _ids())
    by_desc = {i["desc"]: i["id"] for i in out["est_items"]}
    got = {r["desc"]: r["itemId"] for r in out["est_resources"]}
    assert got["Sheet steel"] == by_desc["Ductwork"]
    assert got["Coil"] == by_desc["AHU"]


def test_an_orphan_build_up_is_dropped_not_left_pointing_at_the_original():
    """Its line was deleted, so it prices nothing and never reached a total. Carrying it over with
    the old itemId is the one outcome that looks fine and is not."""
    rows = _rows(
        est_items=[{"id": "it-1", "estId": "est-old"}],
        est_resources=[{"id": "rs-1", "estId": "est-old", "itemId": "it-1"},
                       {"id": "rs-9", "estId": "est-old", "itemId": "it-GONE"}])
    _, out, rep = est_copy.duplicate(SRC, rows, "est-new", _ids())
    assert len(out["est_resources"]) == 1
    assert rep["orphansDropped"] == 1
    assert all(r["itemId"] != "it-GONE" for r in out["est_resources"])


def test_a_build_up_attached_to_no_line_at_all_survives():
    """Blank itemId is not a dangling pointer — it never claimed to price a line."""
    rows = _rows(est_resources=[{"id": "rs-1", "estId": "est-old", "itemId": ""}])
    _, out, rep = est_copy.duplicate(SRC, rows, "est-new", _ids())
    assert len(out["est_resources"]) == 1 and rep["orphansDropped"] == 0


# --- a copy must be usable ----------------------------------------------------------------------

def test_the_copy_is_not_born_frozen():
    """adoptedProjectId makes a tender the untouchable budget of a live project. Inherited, the copy
    is read-only from the instant it exists."""
    src = dict(SRC, adoptedProjectId="pm-1", adoptedAt="2025-06-01", adoptedBy="Director")
    head, _, _ = est_copy.duplicate(src, _rows(), "est-new", _ids())
    assert "adoptedProjectId" not in head
    assert "adoptedAt" not in head and "adoptedBy" not in head


def test_the_copy_starts_as_a_draft_whatever_the_original_ended_as():
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    assert head["status"] == "Draft"        # SRC was Lost


def test_the_document_numbers_are_not_inherited():
    """A number is issued to a document. Two tenders citing QT-2025-0007 is a filing problem that
    reaches the customer."""
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    assert "estNo" not in head and "quoteNo" not in head


def test_the_originals_dates_and_approval_do_not_come_along():
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    for k in ("issueDate", "validUntil", "amountInWords", "approvedBy"):
        assert k not in head, k


def test_a_copy_does_not_claim_to_price_a_running_project():
    src = dict(SRC, pmProjectId="pm-42")
    head, _, _ = est_copy.duplicate(src, _rows(), "est-new", _ids())
    assert "pmProjectId" not in head


# --- what IS worth copying ----------------------------------------------------------------------

def test_the_pricing_survives():
    """The whole point. If the mark-ups did not come across, retyping them is where a margin is lost."""
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    for k in ("client", "clientTaxCode", "costingType", "overheadPct", "riskPct",
              "profitPct", "profitBasis", "scope", "exclusions"):
        assert head[k] == SRC[k], k


def test_every_child_collection_travels():
    rows = _rows(**{c: [{"id": c + "-1", "estId": "est-old"}] for c in est_copy.CHILDREN})
    _, out, rep = est_copy.duplicate(SRC, rows, "est-new", _ids())
    for c in est_copy.CHILDREN:
        assert len(out[c]) == 1, c
        assert out[c][0]["estId"] == "est-new", c
        assert out[c][0]["id"] != c + "-1", c
        assert rep["copied"][c] == 1, c


def test_the_revision_history_stays_with_the_original():
    """Copied onto a new tender it would assert approvals this document has never been through."""
    rows = _rows(est_revs=[{"id": "rev-1", "estId": "est-old", "rev": "B"}])
    _, out, _ = est_copy.duplicate(SRC, rows, "est-new", _ids())
    assert "est_revs" not in out
    assert "est_revs" in est_copy.NOT_COPIED


def test_another_tenders_rows_are_not_swept_in():
    """The filter is by estId. Without it a duplicate would absorb the whole company's bill lines."""
    rows = _rows(est_items=[{"id": "it-1", "estId": "est-old"},
                            {"id": "it-x", "estId": "est-OTHER"}])
    _, out, _ = est_copy.duplicate(SRC, rows, "est-new", _ids())
    assert len(out["est_items"]) == 1


def test_the_copy_says_where_it_came_from():
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids(), today="2026-08-29")
    assert head["copiedFrom"] == "est-old"
    assert head["copiedFromNo"] == "EST-0007"
    assert head["copiedAt"] == "2026-08-29"


def test_nothing_shares_a_row_object_with_the_original():
    """A shallow reference means editing the copy edits the tender it came from."""
    rows = _rows(est_items=[{"id": "it-1", "estId": "est-old", "desc": "AHU"}])
    _, out, _ = est_copy.duplicate(SRC, rows, "est-new", _ids())
    out["est_items"][0]["desc"] = "CHANGED"
    assert rows["est_items"][0]["desc"] == "AHU"
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    head["client"] = "Someone else"
    assert SRC["client"] == "Acme"


# --- naming -------------------------------------------------------------------------------------

def test_the_default_name_reads_as_unfinished_on_purpose():
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids())
    assert head["title"] == "Copy of Hanoi plant AHUs"


def test_a_given_name_wins():
    head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids(), title="  Danang plant AHUs  ")
    assert head["title"] == "Danang plant AHUs"


def test_a_blank_given_name_falls_back_rather_than_producing_an_untitled_tender():
    for blank in ("", "   ", None):
        head, _, _ = est_copy.duplicate(SRC, _rows(), "est-new", _ids(), title=blank)
        assert head["title"] == "Copy of Hanoi plant AHUs"


def test_a_source_with_no_id_is_refused():
    """Every child is filtered by estId. A blank one would match rows whose estId is also blank."""
    for bad in ({}, {"id": ""}, {"id": None}):
        try:
            est_copy.duplicate(bad, _rows(), "est-new", _ids())
        except ValueError:
            continue
        raise AssertionError("a tender with no id was copied: %r" % (bad,))


def test_an_id_is_minted_once_per_row_and_never_repeated():
    rows = _rows(est_items=[{"id": "it-%d" % i, "estId": "est-old"} for i in range(5)],
                 est_bom=[{"id": "bm-%d" % i, "estId": "est-old"} for i in range(3)])
    _, out, _ = est_copy.duplicate(SRC, rows, "est-new", _ids())
    got = [r["id"] for c in out for r in out[c]]
    assert len(got) == len(set(got)) == 8
