"""The quotation number — the reference a customer and an auditor both use to name a document.

It used to be `'HML-QT-' + year + (1000 + hash(dealId) % 9000)`. Two failures in one expression:
re-quoting a deal reproduced the same number, so a revised price went out under the reference of the
price it replaced; and 9,000 slots hashed means two unrelated deals collide at around 112 quotes.
"""
import db
import doc_number as dn

DEAL = {"title": "Cleanroom AHU", "company": "Pharma Co", "stage": "Proposal", "value": 0,
        "owner": "Staff One"}   # owned by the staff fixture, since numbering writes to the deal


def _deal(api, token, **kw):
    st, r = api("POST", "/api/coll/crm_deals", token, dict(DEAL, **kw))
    assert st == 200, r
    return r["item"]["id"]


def _num(api, token, did):
    return api("POST", "/api/sales/quote-number", token, {"dealId": did})


def test_a_deal_gets_a_real_sequential_number(api, tokens):
    st, r = _num(api, tokens["staff"], _deal(api, tokens["staff"]))
    assert st == 200, r
    p = dn.parse_no(r["no"])
    assert p and p["prefix"] == "QT", r
    assert r["issued"] is True


def test_two_deals_never_share_a_number(api, tokens):
    """The hash collided outright. This is the whole point of moving it to the server."""
    a = _num(api, tokens["staff"], _deal(api, tokens["staff"]))[1]["no"]
    b = _num(api, tokens["staff"], _deal(api, tokens["staff"]))[1]["no"]
    assert a != b


def test_asking_twice_returns_the_same_number_and_burns_none(api, tokens):
    """Idempotent by design. A double-clicked Save must not take a second number and leave a hole —
    a missing number in a document register is a question somebody has to answer."""
    did = _deal(api, tokens["staff"])
    first = _num(api, tokens["staff"], did)[1]
    again = _num(api, tokens["staff"], did)[1]
    assert again["no"] == first["no"]
    assert first["issued"] is True and again["issued"] is False


def test_the_number_is_stored_on_the_deal_so_a_re_download_cannot_change_it(api, tokens):
    did = _deal(api, tokens["staff"])
    no = _num(api, tokens["staff"], did)[1]["no"]
    assert db.get_collection_item("crm_deals", did)["quoteNo"] == no


def test_an_unknown_deal_is_refused_rather_than_silently_numbered(api, tokens):
    assert _num(api, tokens["staff"], "no-such-deal")[0] == 404


def test_a_missing_deal_id_is_refused(api, tokens):
    assert api("POST", "/api/sales/quote-number", tokens["staff"], {})[0] == 400


def test_it_needs_a_session(api, tokens):
    assert _num(api, None, "anything")[0] == 401


def test_an_existing_number_in_the_data_is_never_re_issued(api, tokens):
    """Adopting the live database: quotations already sent under QT-<year>-0500 must not come round
    again, whatever numbered them before."""
    year = dn.parse_no(_num(api, tokens["staff"], _deal(api, tokens["staff"]))[1]["no"])["year"]
    conn = db.get_conn()
    conn.execute("DELETE FROM doc_counters WHERE series = 'QT'")
    conn.commit(); conn.close()
    db.put_collection_item("crm_deals", {"id": "qt-seed", "title": "Old quote",
                                         "quoteNo": dn.format_no("QT", year, 500)})
    nxt = _num(api, tokens["staff"], _deal(api, tokens["staff"]))[1]["no"]
    assert dn.parse_no(nxt)["n"] > 500, "got %s" % nxt


def test_the_number_call_returns_the_new_revision(api, tokens):
    """Writing the number bumps the deal's _rev. Without handing the caller the new one, its very
    next PATCH is refused as a conflict with its own change — which is exactly what happened, and
    what the optimistic-concurrency guard caught."""
    did = _deal(api, tokens["staff"])
    before = db.get_collection_item("crm_deals", did).get("_rev")
    r = _num(api, tokens["staff"], did)[1]
    assert r.get("rev"), r
    assert r["rev"] != before, "the revision must have moved"
    assert r["rev"] == db.get_collection_item("crm_deals", did).get("_rev")


def test_a_patch_using_the_returned_revision_is_accepted(api, tokens):
    """The end-to-end shape the quotation builder uses: take a number, then save the quotation."""
    did = _deal(api, tokens["staff"])
    r = _num(api, tokens["staff"], did)[1]
    item = db.get_collection_item("crm_deals", did)
    item["_rev"] = r["rev"]
    item["value"] = 123456
    st, body = api("PATCH", "/api/coll/crm_deals/" + did, tokens["staff"], item)
    assert st == 200, body


def test_you_cannot_number_somebody_elses_deal(api, tokens):
    """Numbering WRITES to the deal, so it needs what editing needs. Otherwise it is a way to modify
    a colleague's record — and burn a document number against it — through a side door."""
    did = _deal(api, tokens["staff"])
    assert _num(api, tokens["other"], did)[0] == 403


def test_management_can_number_any_deal(api, tokens):
    did = _deal(api, tokens["staff"])
    assert _num(api, tokens["management"], did)[0] == 200
