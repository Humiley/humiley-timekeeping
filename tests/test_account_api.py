"""The account master over the real store — the review screen and the merge.

account.py proves the rules. These prove the parts only the server can: that a merge really moves
the children and really keeps the tombstone, that it is audited, that it is refused to anybody who
should not be fusing two customers' contracts, and that the review is scoped away from staff.
"""
import pytest

import db


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        # NOT "audit": it is a tamper-evident hash chain, and deleting rows from it leaves a
        # sequence gap that /api/admin/audit/verify correctly reports as tampering — breaking every
        # later test in the run. The chain is supposed to notice; a test fixture must not trip it.
        for c in ("crm_companies", "crm_deals", "crm_contacts", "crm_leads", "pm_projects"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _acc(**kw):
    return db.put_collection_item("crm_companies", dict({"name": "ABC Corp"}, **kw))


def _review(api, token):
    return api("GET", "/api/sales/accounts/review", token)


def _merge(api, token, pid, did, confirm=False):
    return api("POST", "/api/sales/accounts/merge", token,
               {"primaryId": pid, "duplicateId": did, "confirm": confirm})


# ── who may look, who may merge ──────────────────────────────────────────────────────────────────

def test_the_review_is_not_for_staff(api, tokens):
    """It lists every customer's tax identity and credit limit."""
    assert _review(api, tokens["staff"])[0] == 403


def test_management_can_see_the_review(api, tokens):
    code, r = _review(api, tokens["management"])
    assert code == 200, r
    assert "statement" in r


def test_a_staff_user_cannot_merge_customers(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    assert _merge(api, tokens["staff"], a["id"], b["id"], confirm=True)[0] == 403


def test_it_needs_a_session(api, tokens):
    assert _review(api, None)[0] == 401


# ── what the review finds ────────────────────────────────────────────────────────────────────────

def test_two_spellings_of_one_customer_are_reported_as_duplicates(api, tokens):
    _acc(name="ABC Corp"); _acc(name="ABC Corp.")
    _, r = _review(api, tokens["management"])
    assert r["duplicates"], r["statement"]
    assert r["duplicates"][0]["reason"] == "name"


def test_a_customer_with_no_tax_code_is_reported_as_not_billable(api, tokens):
    _acc(name="No MST Co")
    _, r = _review(api, tokens["management"])
    names = {x["name"] for x in r["notBillable"]}
    assert "No MST Co" in names
    assert any("Tax code" in m for x in r["notBillable"] for m in x["missing"])


def test_a_complete_customer_is_not_reported_as_not_billable(api, tokens):
    _acc(name="Complete Co", legalNameVn="Công ty TNHH Complete", mst="0123456789",
         regAddress="12 Nguyễn Huệ, HCM")
    _, r = _review(api, tokens["management"])
    assert "Complete Co" not in {x["name"] for x in r["notBillable"]}


def test_a_lapsed_qualification_is_reported(api, tokens):
    _acc(name="Lapsed Co", prequal={"iso9001": {"expires": "2020-01-01"}})
    _, r = _review(api, tokens["management"])
    assert any(x["name"] == "Lapsed Co" and x["expired"] for x in r["qualifications"])


def test_records_nobody_owns_are_counted(api, tokens):
    """They exist, they are in nobody's pipeline, and only management can see they are there."""
    _acc(name="Orphan Co")
    db.put_collection_item("crm_deals", {"title": "Orphan deal", "company": "Orphan Co"})
    _, r = _review(api, tokens["management"])
    assert r["unassigned"]["crm_deals"] >= 1
    assert r["unassigned"]["crm_companies"] >= 1


def test_the_unverified_check_digit_travels_with_the_answer(api, tokens):
    _, r = _review(api, tokens["management"])
    assert "MST check digit" in {u["topic"] for u in r["unverified"]}


# ── merging ──────────────────────────────────────────────────────────────────────────────────────

def test_a_merge_previews_before_it_moves_anything(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    db.put_collection_item("crm_deals", {"title": "D", "company": "ABC Corp."})
    code, r = _merge(api, tokens["management"], a["id"], b["id"], confirm=False)
    assert code == 200 and r["preview"] is True
    assert r["plan"]["movedTotal"] == 1
    assert db.get_collection_item("crm_companies", b["id"]).get("mergedInto") is None, "nothing moved yet"


def test_a_confirmed_merge_repoints_the_children_by_name_and_by_id(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "ABC Corp."})
    p = db.put_collection_item("pm_projects", {"name": "P", "account": "ABC Corp."})
    code, r = _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    assert code == 200 and r["merged"] is True and r["moved"] == 2, r
    assert db.get_collection_item("crm_deals", d["id"])["company"] == "ABC Corp"
    assert db.get_collection_item("crm_deals", d["id"])["accountId"] == a["id"]
    assert db.get_collection_item("pm_projects", p["id"])["accountId"] == a["id"]


def test_the_duplicate_becomes_a_tombstone_and_is_never_deleted(api, tokens):
    """A link, a report or a printed document naming the old account must still resolve."""
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    dead = db.get_collection_item("crm_companies", b["id"])
    assert dead is not None, "the record must still exist"
    assert dead["mergedInto"] == a["id"]
    assert dead.get("mergedBy") and dead.get("mergedAt")


def test_the_survivor_inherits_the_details_it_was_missing(api, tokens):
    a = _acc(name="ABC Corp")
    b = _acc(name="ABC Corp.", mst="0123456789", regAddress="12 Nguyễn Huệ")
    _, r = _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    assert "mst" in r["filled"]
    assert db.get_collection_item("crm_companies", a["id"])["mst"] == "0123456789"


def test_two_different_legal_entities_are_refused(api, tokens):
    """THE dangerous case: merging on a name match would fuse two customers' contracts."""
    a = _acc(name="ABC", mst="0123456789")
    b = _acc(name="ABC", mst="9876543210")
    code, r = _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    assert code == 400 and "different legal entities" in r["error"]
    assert db.get_collection_item("crm_companies", b["id"]).get("mergedInto") is None


def test_a_merge_is_written_to_the_audit_chain(api, tokens):
    """Moving every deal and project attached to a customer is not a change that should be
    reconstructible only from memory."""
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    # `any`, not rows[0]: the audit collection is shared and append-only across the whole run.
    rows = [x for x in db.list_collection("audit") if x.get("action") == "Merged customer account"]
    assert any("ABC Corp." in (x.get("detail") or "") for x in rows), rows


def test_merging_an_unknown_account_is_refused(api, tokens):
    a = _acc(name="ABC Corp")
    assert _merge(api, tokens["management"], a["id"], "nope", confirm=True)[0] == 404


def test_an_account_cannot_be_merged_into_itself(api, tokens):
    a = _acc(name="ABC Corp")
    assert _merge(api, tokens["management"], a["id"], a["id"], confirm=True)[0] == 400


def test_a_tombstone_is_left_out_of_the_duplicate_report(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    _, r = _review(api, tokens["management"])
    assert r["duplicates"] == [], "the merge is done; it must stop being offered"
    assert r["tombstones"] == 1


# ── the line manager, who passes the role gate and must still be stopped ─────────────────────────
# `mgr` has role=manager (so the route's manager=True guard lets them through) but level=manager,
# below management. Without the level check INSIDE the endpoint, a department manager would see
# every customer's credit limit and tax identity, and could fuse two customers' contracts.

def test_a_line_manager_cannot_see_every_customers_credit_details(api, tokens):
    assert _review(api, tokens["mgr"])[0] == 403


def test_a_line_manager_cannot_merge_customers(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    assert _merge(api, tokens["mgr"], a["id"], b["id"], confirm=True)[0] == 403
    assert db.get_collection_item("crm_companies", b["id"]).get("mergedInto") is None


# ── the backfill ─────────────────────────────────────────────────────────────────────────────────

def _backfill(api, token, confirm=False):
    return api("POST", "/api/sales/accounts/backfill", token, {"confirm": confirm})


def test_the_backfill_previews_before_it_writes(api, tokens):
    a = _acc(name="ABC Corp")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "ABC Corp"})
    code, r = _backfill(api, tokens["management"])
    assert code == 200 and r["preview"] is True
    assert [x["id"] for x in r["link"]] == [d["id"]]
    assert db.get_collection_item("crm_deals", d["id"]).get("accountId") is None


def test_a_confirmed_backfill_links_the_records(api, tokens):
    a = _acc(name="ABC Corp")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "ABC Corp"})
    p = db.put_collection_item("pm_projects", {"name": "P", "account": "ABC Corp"})
    _, r = _backfill(api, tokens["management"], confirm=True)
    assert r["linked"] == 2, r
    assert db.get_collection_item("crm_deals", d["id"])["accountId"] == a["id"]
    assert db.get_collection_item("pm_projects", p["id"])["accountId"] == a["id"]


def test_the_customer_name_is_left_alone(api, tokens):
    """accountId is added ALONGSIDE the name, so nothing that reads the name breaks mid-migration."""
    _acc(name="ABC Corp")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "ABC Corp"})
    _backfill(api, tokens["management"], confirm=True)
    assert db.get_collection_item("crm_deals", d["id"])["company"] == "ABC Corp"


def test_an_unresolvable_name_is_reported_and_never_guessed(api, tokens):
    """Replacing free text with a confident WRONG id would bake today's typos into the joins where
    nobody would ever see them again."""
    _acc(name="ABC Corp")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "Somebody Else Ltd"})
    _, r = _backfill(api, tokens["management"], confirm=True)
    assert any(x["id"] == d["id"] and x["reason"] == "unmatched" for x in r["exceptions"])
    assert db.get_collection_item("crm_deals", d["id"]).get("accountId") is None


def test_two_accounts_with_the_same_name_stop_the_backfill_choosing(api, tokens):
    _acc(name="Same Co"); _acc(name="Same Co")
    d = db.put_collection_item("crm_deals", {"title": "D", "company": "Same Co"})
    _, r = _backfill(api, tokens["management"], confirm=True)
    assert any(x["id"] == d["id"] and x["reason"] == "ambiguous" for x in r["exceptions"])
    assert db.get_collection_item("crm_deals", d["id"]).get("accountId") is None


def test_a_record_pointing_at_a_merged_account_lands_on_the_survivor(api, tokens):
    a, b = _acc(name="ABC Corp"), _acc(name="ABC Corp.")
    _merge(api, tokens["management"], a["id"], b["id"], confirm=True)
    d = db.put_collection_item("crm_deals", {"title": "Late", "company": "ABC Corp."})
    _backfill(api, tokens["management"], confirm=True)
    assert db.get_collection_item("crm_deals", d["id"])["accountId"] == a["id"]


def test_the_backfill_is_not_for_staff(api, tokens):
    assert _backfill(api, tokens["staff"], confirm=True)[0] == 403
    assert _backfill(api, tokens["mgr"], confirm=True)[0] == 403
