"""Taking a revision, through the real endpoint.

The unit tests prove the comparison is right. These prove the thing that WRITES revisions behaves —
because a revision that can be edited afterwards is not a record of what a tender said, it is a
second opinion about the past, and that is worse than having none.
"""
import db


def _epc(tid, unit=400000, extra=None):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": tid, "quoteNo": "QT-" + tid, "title": "Plant",
        "costingType": "epc", "status": "Draft", "vatPct": 10, "accuracyClass": "3"})
    db.put_collection_item("est_bom", {"id": tid + "-b1", "estId": tid, "costCentre": "CIV",
                                       "code": "CIV-01", "descEn": "Civil", "qty": 1,
                                       "unitCostUsd": unit})
    if extra:
        db.put_collection_item("est_bom", dict(extra, estId=tid))
    return tid


def _revs(tid):
    return sorted([r for r in db.list_collection("est_revs") if r.get("estId") == tid],
                  key=lambda r: r.get("rev", 0))


def test_a_revision_records_what_the_tender_says_now(api, tokens):
    tid = _epc("TND-REV-1")
    st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid, "note": "Rev A"})
    assert st == 200, r
    assert r["rev"] == 1 and r["net"] > 0
    rows = _revs(tid)
    assert len(rows) == 1
    assert rows[0]["note"] == "Rev A"
    assert rows[0]["lines"], "a revision with no lines cannot be diffed against anything"


def test_revisions_number_themselves_in_order(api, tokens):
    tid = _epc("TND-REV-2")
    for n in (1, 2, 3):
        st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid})
        assert st == 200 and r["rev"] == n


def test_the_second_revision_comes_back_with_what_moved(api, tokens):
    """The comparison is the point, not the archive."""
    tid = _epc("TND-REV-3")
    api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid, "note": "Rev A"})
    db.put_collection_item("est_bom", {"id": tid + "-b2", "estId": tid, "costCentre": "MEP",
                                       "code": "MEP-01", "descEn": "MEP", "qty": 1,
                                       "unitCostUsd": 250000})
    st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid, "note": "Rev B"})
    assert st == 200
    c = r["compare"]
    assert c is not None
    assert c["delta"] > 0
    assert any(x["status"] == "added" and "MEP" in x["desc"] for x in c["rows"])


def test_the_first_revision_has_nothing_to_compare_against(api, tokens):
    tid = _epc("TND-REV-4")
    _st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid})
    assert r["compare"] is None


def test_a_revision_is_built_from_the_rows_not_from_the_request(api, tokens):
    """A revision assembled out of whatever a client posted would record what somebody CLAIMED the
    tender said, which is the opposite of the point. The caller chooses only the note."""
    tid = _epc("TND-REV-5")
    st, r = api("POST", "/api/tender/revise", tokens["admin"],
                {"estId": tid, "net": 999_999_999_999, "lines": [{"id": "fake", "net": 1}],
                 "note": "n"})
    assert st == 200
    row = _revs(tid)[0]
    assert row["net"] != 999_999_999_999
    assert not any(l["id"] == "fake" for l in row["lines"])


def test_an_unpriced_tender_has_nothing_to_record(api, tokens):
    db.put_collection_item("est_projects", {"id": "TND-REV-EMPTY", "costingType": "epc",
                                            "status": "Draft", "vatPct": 10})
    st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": "TND-REV-EMPTY"})
    assert st == 400
    assert "nothing to record" in (r.get("error") or "").lower()
    assert _revs("TND-REV-EMPTY") == []


def test_a_boq_estimate_is_told_where_its_versioning_lives(api, tokens):
    db.put_collection_item("est_projects", {"id": "EST-BOQ-REV", "status": "Draft"})
    st, r = api("POST", "/api/tender/revise", tokens["admin"], {"estId": "EST-BOQ-REV"})
    assert st == 400
    assert "BoQ" in (r.get("error") or "")


# --- a record cannot be rewritten -------------------------------------------------------------

def test_a_revision_cannot_be_edited_through_the_generic_route(api, tokens):
    """One that can be edited afterwards is not a record of what a tender said."""
    tid = _epc("TND-REV-FROZEN")
    api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid})
    rid = _revs(tid)[0]["id"]
    before = _revs(tid)[0]["net"]
    st, r = api("PATCH", "/api/coll/est_revs/" + rid, tokens["admin"], {"net": 1})
    assert st == 409
    assert "record" in (r.get("error") or "").lower()
    assert _revs(tid)[0]["net"] == before


def test_a_revision_cannot_be_deleted(api, tokens):
    tid = _epc("TND-REV-DEL")
    api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid})
    rid = _revs(tid)[0]["id"]
    st, _r = api("DELETE", "/api/coll/est_revs/" + rid, tokens["admin"])
    assert st == 409
    assert len(_revs(tid)) == 1


def test_a_revision_cannot_be_forged_through_the_generic_route(api, tokens):
    st, r = api("POST", "/api/coll/est_revs", tokens["admin"],
                {"estId": "TND-REV-1", "net": 1, "rev": 99})
    assert st == 409
    assert not any(x.get("rev") == 99 for x in db.list_collection("est_revs"))


def test_revisions_are_still_readable(api, tokens):
    """FROZEN is not CONFIDENTIAL. The whole point is that people read them."""
    tid = _epc("TND-REV-READ")
    api("POST", "/api/tender/revise", tokens["admin"], {"estId": tid})
    st, r = api("GET", "/api/coll/est_revs", tokens["admin"])
    assert st == 200
    assert any(x.get("estId") == tid for x in (r.get("items") or []))
