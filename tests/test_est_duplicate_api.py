"""/api/est/duplicate — copying a tender through the real boundary.

`test_est_copy` proves the RULES (the itemId remap, the freeze that must not be inherited). This
file proves the endpoint applies them to rows that are really in the database, and that the copy a
person then opens is the one the rules described — not the plan the pure module returned.
"""
import db


def _tender(tid="TND-DUP", **kw):
    row = {"id": tid, "estNo": "EST-2026-500", "quoteNo": "QT-2026-500",
           "title": "Hanoi plant AHUs", "costingType": "boq", "status": "Lost",
           "client": "ABC Manufacturing Co., Ltd.", "clientTaxCode": "0123456789",
           "issueDate": "2026-03-01", "validUntil": "2026-04-01",
           "amountInWords": "One billion dong", "approvedBy": "Director",
           "overheadPct": 8, "riskPct": 5, "profitPct": 12, "profitBasis": "markup",
           "scope": "Supply 2x AHU", "exclusions": "Crane hire"}
    row.update(kw)
    db.put_collection_item("est_projects", row)
    return tid


def _bill(tid, n=2):
    """A bill with build-ups hanging off it — the shape the remap exists for."""
    ids = []
    for i in range(n):
        iid = "%s-it%d" % (tid, i)
        db.put_collection_item("est_items", {
            "id": iid, "estId": tid, "seq": str(i + 1), "kind": "item",
            "desc": "Line %d" % i, "unit": "set", "qty": 2})
        db.put_collection_item("est_resources", {
            "id": "%s-rs%d" % (tid, i), "estId": tid, "itemId": iid,
            "kind": "material", "desc": "Resource %d" % i, "qtyPer": 1, "unitCost": 1000000})
        ids.append(iid)
    return ids


def _rows(coll, est_id):
    return [r for r in db.list_collection(coll) if r.get("estId") == est_id]


# ── the boundary ─────────────────────────────────────────────────────────────────────────────────

def test_staff_cannot_duplicate_a_tender(api, tokens):
    """A tender holds the company's cost and margin. Copying one is a way of READING one."""
    tid = _tender("TND-DUP-ACL")
    st, r = api("POST", "/api/est/duplicate", tokens["staff"], {"estId": tid})
    assert st == 403
    assert "manager" in (r.get("error") or "").lower()


def test_staff_cannot_read_the_copy_through_the_collection_route_either(api, tokens):
    tid = _tender("TND-DUP-ACL2")
    _bill(tid)
    api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    for coll in ("est_projects", "est_items", "est_resources"):
        st, _ = api("GET", "/api/coll/" + coll, tokens["staff"])
        assert st == 403, coll


def test_duplicating_a_tender_that_does_not_exist_is_a_404(api, tokens):
    st, _ = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": "ghost"})
    assert st == 404


def test_a_blank_id_is_refused_rather_than_matching_everything(api, tokens):
    """Children are filtered by estId. A blank one that reached the filter would match every row
    whose estId is also blank."""
    st, _ = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": ""})
    assert st in (400, 404)


# ── the copy is real ─────────────────────────────────────────────────────────────────────────────

def test_the_bill_and_its_build_ups_are_really_written(api, tokens):
    tid = _tender("TND-DUP-1")
    _bill(tid, 3)
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    assert st == 200, r
    new = r["id"]
    assert len(_rows("est_items", new)) == 3
    assert len(_rows("est_resources", new)) == 3
    # and the original is untouched
    assert len(_rows("est_items", tid)) == 3


def test_the_build_ups_in_the_DATABASE_point_at_the_copy_s_own_lines(api, tokens):
    """The finding, checked against stored rows rather than the returned plan. A resource still
    naming the original's line leaves the copy with a bill that prices nothing."""
    tid = _tender("TND-DUP-2")
    old_items = _bill(tid, 2)
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    assert st == 200
    new = r["id"]
    new_item_ids = {i["id"] for i in _rows("est_items", new)}
    for res in _rows("est_resources", new):
        assert res["itemId"] in new_item_ids
        assert res["itemId"] not in old_items


def test_each_copied_build_up_keeps_the_line_it_priced(api, tokens):
    tid = _tender("TND-DUP-3")
    _bill(tid, 2)
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    new = r["id"]
    items = {i["id"]: i["desc"] for i in _rows("est_items", new)}
    for res in _rows("est_resources", new):
        # 'Resource 1' was built up under 'Line 1' — a remap that paired by position would swap them
        assert items[res["itemId"]].split()[-1] == res["desc"].split()[-1]


def test_the_copy_is_a_draft_with_no_document_numbers(api, tokens):
    tid = _tender("TND-DUP-4")
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    new = next(e for e in db.list_collection("est_projects") if e["id"] == r["id"])
    assert new["status"] == "Draft"
    assert not new.get("estNo") and not new.get("quoteNo")
    assert not new.get("issueDate") and not new.get("approvedBy")
    assert new["copiedFrom"] == tid


def test_a_copy_of_an_adopted_tender_is_not_frozen(api, tokens):
    """The original is the budget of a live project. The copy must be editable from the start —
    otherwise the estimator is told to raise a revision of a tender they just created."""
    tid = _tender("TND-DUP-5", adoptedProjectId="pm-1", adoptedAt="2026-06-01", status="Won")
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    new = next(e for e in db.list_collection("est_projects") if e["id"] == r["id"])
    assert not new.get("adoptedProjectId")


def test_the_pricing_travels(api, tokens):
    """Named values, not 'is not None'. Retyping a mark-up is where a margin quietly changes, so
    this has to compare what the copy holds with what the original held."""
    tid = _tender("TND-DUP-6")
    src = next(e for e in db.list_collection("est_projects") if e["id"] == tid)
    st, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    new = next(e for e in db.list_collection("est_projects") if e["id"] == r["id"])
    for k in ("client", "clientTaxCode", "costingType", "overheadPct", "riskPct",
              "profitPct", "profitBasis", "scope", "exclusions"):
        assert new.get(k) == src[k], "%s: %r != %r" % (k, new.get(k), src[k])
    assert new["profitPct"] == 12 and new["exclusions"] == "Crane hire"


def test_the_copy_can_be_priced_immediately(api, tokens):
    """The point of copying. If the summary endpoint cannot price the copy, the duplicate produced
    a tender that looks right on a list and is empty when opened."""
    tid = _tender("TND-DUP-7")
    _bill(tid, 2)
    _, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    st, s = api("GET", "/api/est/summary?id=" + r["id"], tokens["admin"])
    assert st == 200, s
    assert s["summary"]["lineCount"] == 2
    # and it costs the same as the tender it came from — the build-ups arrived attached
    _, orig = api("GET", "/api/est/summary?id=" + tid, tokens["admin"])
    assert s["summary"]["directCost"] == orig["summary"]["directCost"]
    assert s["summary"]["directCost"] > 0


def test_a_given_title_is_used(api, tokens):
    tid = _tender("TND-DUP-8")
    _, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid, "title": "Danang AHUs"})
    assert r["title"] == "Danang AHUs"


def test_duplicating_twice_gives_two_separate_tenders(api, tokens):
    tid = _tender("TND-DUP-9")
    _bill(tid, 2)
    _, a = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    _, b = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    assert a["id"] != b["id"]
    ia = {i["id"] for i in _rows("est_items", a["id"])}
    ib = {i["id"] for i in _rows("est_items", b["id"])}
    assert ia and ib and not (ia & ib)


def test_the_duplicate_is_written_to_the_audit_log(api, tokens):
    tid = _tender("TND-DUP-10")
    _bill(tid, 1)
    _, r = api("POST", "/api/est/duplicate", tokens["admin"], {"estId": tid})
    hits = [a for a in db.list_collection("audit")
            if a.get("action") == "Tender duplicated" and r["id"] in str(a.get("detail") or "")]
    assert hits, "a tender was copied and nothing recorded it"
