"""The invoice register is the legal tax-invoice record. Duplicate prevention used to be app-logic only
(the backend mailbox sync de-duped, but the client's manual save wrote an arbitrary items array), so a
buggy or hostile client could book the same legal invoice twice. The server now rejects duplicates at the
write boundary — on both create and update — keyed the same way the frontend keys them.
"""
import db


def _doc(items):
    return {"kind": "invtrack-dataset", "meta": {}, "items": items}


def test_duplicate_invoice_number_is_rejected_on_create(api, tokens):
    st, r = api("POST", "/api/coll/invtrack", tokens["editor"],
                _doc([{"invNo": "INV-001", "serial": "AA/26E"}, {"invNo": "INV-001", "serial": "AA/26E"}]))
    assert st == 400 and "duplicate" in str(r).lower(), (st, r)


def test_duplicate_message_id_is_rejected(api, tokens):
    st, r = api("POST", "/api/coll/invtrack", tokens["editor"],
                _doc([{"msgId": "<m1@humiley>", "invNo": "A"}, {"msgId": "<m1@humiley>", "invNo": "B"}]))
    assert st == 400 and "duplicate" in str(r).lower(), (st, r)


def test_distinct_invoices_are_accepted_and_stored(api, tokens):
    st, b = api("POST", "/api/coll/invtrack", tokens["editor"],
                _doc([{"invNo": "INV-100", "serial": "AA/26E"}, {"invNo": "INV-101", "serial": "AA/26E"},
                      {"invNo": "INV-100", "serial": "BB/26E"}]))   # same number, DIFFERENT serial = distinct
    assert st == 200, b
    assert len(db.get_collection_item("invtrack", b["item"]["id"])["items"]) == 3


def test_duplicate_is_rejected_on_update_too(api, tokens):
    st, b = api("POST", "/api/coll/invtrack", tokens["editor"], _doc([{"invNo": "INV-200", "serial": "AA"}]))
    assert st == 200, b
    iid = b["item"]["id"]
    st2, r2 = api("PATCH", "/api/coll/invtrack/" + iid, tokens["editor"],
                  _doc([{"invNo": "INV-200", "serial": "AA"}, {"invNo": "INV-200", "serial": "AA"}]))
    assert st2 == 400 and "duplicate" in str(r2).lower(), (st2, r2)
    # the stored register is untouched by the rejected write
    assert len(db.get_collection_item("invtrack", iid)["items"]) == 1


def test_rows_without_an_identity_do_not_block_the_save(api, tokens):
    # partially-captured rows (no invNo yet, no msgId) must not be treated as duplicates of each other
    st, b = api("POST", "/api/coll/invtrack", tokens["editor"],
                _doc([{"note": "still extracting"}, {"note": "still extracting"}, {"invNo": "INV-300"}]))
    assert st == 200, b
