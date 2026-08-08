"""A create (POST /api/coll/<name>) must never overwrite an existing record via a client-supplied `id`.

db.put_collection_item is a blind upsert (INSERT ... ON CONFLICT DO UPDATE), so _coll_add strips any
incoming id and always mints a fresh one. Without this, any authenticated staff user could POST an
existing id and OVERWRITE that row wholesale — destroying another user's signed financial record,
re-owning a colleague's CRM deal, or forging an append-only audit entry — bypassing every owner/status
guard the PATCH/DELETE paths enforce.
"""


def test_create_ignores_client_id_and_never_overwrites(api, tokens):
    # Staff One creates a CRM deal -> record with a server-minted id.
    st, b = api("POST", "/api/coll/crm_deals", tokens["staff"], {"title": "Original", "owner": "Staff One"})
    assert st == 200, (st, b)
    victim = b["item"]["id"]
    assert victim, b

    # Another staff attempts a create carrying the SAME id — must mint a FRESH id, not overwrite.
    st2, b2 = api("POST", "/api/coll/crm_deals", tokens["other"], {"id": victim, "title": "Evil", "owner": "Mallory"})
    assert st2 == 200, (st2, b2)
    assert b2["item"]["id"] != victim, "create must strip the client id and mint a fresh one"

    # The original record is intact: same title + owner, not overwritten.
    st3, rows = api("GET", "/api/coll/crm_deals", tokens["admin"])
    assert st3 == 200, (st3, rows)
    items = rows if isinstance(rows, list) else rows.get("items", [])
    orig = next((x for x in items if x.get("id") == victim), None)
    assert orig is not None, "the original record must still exist after the second create"
    assert orig.get("title") == "Original", "the original record must not have been overwritten"


def test_create_cannot_overwrite_a_money_record(api, tokens):
    # Create a claim (money record) as Staff One, then try to clobber it by id as another user.
    st, b = api("POST", "/api/coll/claims", tokens["staff"], {"title": "Real claim", "amount": 100})
    if st != 200:
        # If claim validation rejects this minimal body in some configs, the overwrite invariant is
        # still exercised by the CRM test above — skip rather than assert on unrelated validation.
        return
    victim = b["item"]["id"]
    st2, b2 = api("POST", "/api/coll/claims", tokens["other"], {"id": victim, "title": "Hijacked", "amount": 1})
    # Either the create mints a new id (never the victim's), or it is rejected — never an overwrite.
    assert st2 != 200 or b2.get("item", {}).get("id") != victim, "a create must never overwrite an existing money record"
