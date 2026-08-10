"""The customer's PO, and the deposit as a balance that moves when cash moves.

Two things a contractor's order-to-cash has that a distributor's does not, and that this portal
could not express before:

  · the customer accepts by issuing a PO, not by signing the quotation back. Their accounts payable
    rejects an invoice that does not quote its number, and the PO is usually where the deposit is
    actually agreed. It can also legitimately differ from the contract.
  · the deposit arrives on signing, weeks before any progress claim exists. Requiring an allocation
    to a certified application made the single largest payment on most contracts impossible to
    record — it was going in as "somebody will remember".
"""
import pytest

import db
import sales_contract as SC


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_receipts"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _live(api, tokens, value=1_000_000_000, activate=True, **terms):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": value}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    t = dict({"advancePct": 30, "retentionPct": 5, "warrantyMonths": 12,
              "recoveryRule": SC.REC_PRORATA, "releaseRule": SC.REL_WARRANTY_END}, **terms)
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], **t)
    if activate:
        _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    return db.get_collection_item("sales_contracts", c["id"])


def _dep(api, t, cid, amount, **kw):
    return _post(api, t, "/api/sales/receipt", kind="advance", contractId=cid, amount=amount, **kw)


# ── the customer's purchase order ───────────────────────────────────────────────────────────────

def test_the_po_number_is_recorded_against_the_contract(api, tokens):
    c = _live(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"],
                  poNo="4500123456", poDate="2026-06-01", poValue=1_000_000_000)
    assert st == 200, r
    assert r["item"]["poNo"] == "4500123456"
    assert r["differsFromContract"] is False


def test_a_po_for_a_different_amount_is_recorded_and_flagged_not_blocked(api, tokens):
    """Reduced scope, a negotiated round-down, a variation issued as a second PO — all real. The
    useful thing is to see the difference, not to be stopped by it or to have it quietly overwrite
    the contract."""
    c = _live(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"],
                  poNo="PO-9", poValue=900_000_000)
    assert st == 200, r
    assert r["differsFromContract"] is True and r["difference"] == -100_000_000
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_000_000_000, \
        "the PO must not silently rewrite the contract"


def test_a_po_with_no_number_is_refused(api, tokens):
    c = _live(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"],
                  poValue=900_000_000)
    assert st == 400 and "has to appear on the invoice" in r["error"]


def test_a_garbled_po_date_is_refused(api, tokens):
    c = _live(api, tokens)
    assert _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"],
                 poNo="PO-1", poDate="01/06/2026")[0] == 400


def test_the_claim_carries_the_po_number_onto_itself(api, tokens):
    """The invoice raised from the claim has to quote it, and looking it up later is how a claim
    ends up invoiced against a PO that was changed in the meantime."""
    c = _live(api, tokens)
    _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"], poNo="4500123456")
    c = db.get_collection_item("sales_contracts", c["id"])
    _, r = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
                 period="2026-08", claims={c["lines"][0]["uid"]: 100_000_000})
    assert r["item"]["poNo"] == "4500123456"


def test_recording_the_po_is_audited(api, tokens):
    c = _live(api, tokens)
    _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"], poNo="PO-1")
    assert any(x.get("action") == "Recorded customer PO" for x in db.list_collection("audit"))


def test_you_cannot_put_a_po_on_somebody_elses_contract(api, tokens):
    c = _live(api, tokens)
    assert _post(api, tokens["other"], "/api/sales/contract", action="po", id=c["id"],
                 poNo="PO-1")[0] == 403


# ── the deposit arriving ────────────────────────────────────────────────────────────────────────

def test_a_deposit_can_be_recorded_before_any_claim_exists(api, tokens):
    """The shape the receipt path could not express at all."""
    c = _live(api, tokens)
    st, r = _dep(api, tokens["staff"], c["id"], 300_000_000, reference="FT-DEP", method="Bank")
    assert st == 200, r
    assert r["advanceReceived"] == 300_000_000 and r["stillToArrive"] == 0
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["advanceOutstanding"] == 300_000_000


def test_a_staged_deposit_arrives_in_tranches(api, tokens):
    c = _live(api, tokens, advancePct=0, advanceSchedule=[
        {"basis": SC.ADV_PCT, "value": 20, "trigger": "On signing"},
        {"basis": SC.ADV_PCT, "value": 10, "trigger": "On delivery to site"}])
    st, r = _dep(api, tokens["staff"], c["id"], 200_000_000, tranche="On signing")
    assert st == 200, r
    assert r["stillToArrive"] == 100_000_000
    _, r2 = _dep(api, tokens["staff"], c["id"], 100_000_000, tranche="On delivery to site")
    assert r2["stillToArrive"] == 0


def test_a_deposit_stated_as_an_amount_works_the_same(api, tokens):
    c = _live(api, tokens, value=986_000_000, advancePct=0,
              advanceSchedule=[{"basis": SC.ADV_FIXED, "value": 200_000_000}])
    st, r = _dep(api, tokens["staff"], c["id"], 200_000_000)
    assert st == 200 and r["agreed"] == 200_000_000


def test_more_than_was_agreed_needs_a_reason(api, tokens):
    """Customers do round up, and a PO can be varied after the contract was typed. Silently
    accepting it leaves a deposit balance nobody can reconcile to any document."""
    c = _live(api, tokens)
    st, r = _dep(api, tokens["staff"], c["id"], 400_000_000)
    assert st == 400 and "say why" in r["error"]
    st, r = _dep(api, tokens["staff"], c["id"], 400_000_000, overReason="PO varied to 40% on 5 Aug")
    assert st == 200, r


def test_a_second_deposit_counts_what_already_arrived(api, tokens):
    c = _live(api, tokens)
    _dep(api, tokens["staff"], c["id"], 250_000_000)
    st, r = _dep(api, tokens["staff"], c["id"], 100_000_000)
    assert st == 400 and "already arrived" in r["error"]


def test_a_contract_with_no_deposit_refuses_one(api, tokens):
    """Cash on a contract with no deposit term is somebody about to mis-key a progress payment."""
    c = _live(api, tokens, advancePct=0)
    st, r = _dep(api, tokens["staff"], c["id"], 1_000_000)
    assert st == 400 and "does not have a deposit" in r["error"]


def test_a_deposit_cannot_be_taken_on_a_draft_contract(api, tokens):
    c = _live(api, tokens, activate=False)
    assert _dep(api, tokens["staff"], c["id"], 1_000_000)[0] == 400


def test_a_negative_deposit_is_refused(api, tokens):
    c = _live(api, tokens)
    assert _dep(api, tokens["staff"], c["id"], -1)[0] == 400


def test_you_cannot_bank_cash_on_somebody_elses_contract(api, tokens):
    c = _live(api, tokens)
    assert _dep(api, tokens["other"], c["id"], 1_000_000)[0] == 403


def test_a_deposit_is_audited(api, tokens):
    c = _live(api, tokens)
    _dep(api, tokens["staff"], c["id"], 300_000_000)
    assert any(x.get("action") == "Recorded deposit received" for x in db.list_collection("audit"))


def test_a_receipt_with_neither_an_allocation_nor_a_contract_says_both_ways_out(api, tokens):
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=1_000)
    assert st == 400 and "deposit against a contract" in r["error"]


def test_a_deposit_shows_on_the_trail_as_its_own_step(api, tokens):
    c = _live(api, tokens)
    _dep(api, tokens["staff"], c["id"], 300_000_000, reference="FT-DEP")
    _, r = api("GET", "/api/sales/trace?id=" + c["id"], tokens["staff"])
    dep = [s for s in r["steps"] if s["kind"] == "deposit"]
    assert dep and dep[0]["ref"] == "FT-DEP" and dep[0]["amount"] == 300_000_000
    assert "deposit-not-received" not in [g["what"] for g in r["gaps"]]


def test_a_deposit_that_never_arrived_is_a_gap_with_the_amount(api, tokens):
    c = _live(api, tokens)
    _, r = api("GET", "/api/sales/trace?id=" + c["id"], tokens["staff"])
    g = [x for x in r["gaps"] if x["what"] == "deposit-not-received"]
    assert g and g[0]["amount"] == 300_000_000


def test_an_impossible_deposit_is_refused_when_it_is_TYPED_not_a_month_later(api, tokens):
    """A schedule the claim engine will refuse is a contract that can never be billed. Finding that
    out at the first progress claim is the expensive way to find it out."""
    c = _live(api, tokens, activate=False)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"],
                  advanceSchedule=[{"basis": SC.ADV_FIXED, "value": 5_000_000_000}])
    assert st == 400 and "larger than the job" in r["error"]


def test_a_valid_schedule_comes_back_priced(api, tokens):
    """So the person typing "20% + ₫50,000,000" sees what that is in đồng before they sign it."""
    c = _live(api, tokens, activate=False)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"],
                  advanceSchedule=[{"basis": SC.ADV_PCT, "value": 20},
                                   {"basis": SC.ADV_FIXED, "value": 50_000_000}])
    assert st == 200, r
    assert r["advanceSchedule"]["total"] == 250_000_000
    assert [x["amount"] for x in r["advanceSchedule"]["tranches"]] == [200_000_000, 50_000_000]


# ── the contract and the project it is delivered by ─────────────────────────────────────────────

def test_linking_a_contract_to_a_project_writes_BOTH_directions(api, tokens):
    """A link you can only follow one way is a link somebody has to remember exists."""
    c = _live(api, tokens)
    pr = db.put_collection_item("pm_projects", {"name": "Block B fitout"})
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c["id"],
                  projectId=pr["id"])
    assert st == 200, r
    assert r["item"]["projectId"] == pr["id"] and r["item"]["projectName"] == "Block B fitout"
    back = db.get_collection_item("pm_projects", pr["id"])
    assert back["contractId"] == c["id"] and back["contractValue"] == 1_000_000_000


def test_one_project_cannot_deliver_two_contracts(api, tokens):
    """Two contracts on one project is how the value a PM plans against stops matching the value
    claims are measured against — the exact drift the link exists to prevent."""
    c1 = _live(api, tokens)
    c2 = _live(api, tokens)
    pr = db.put_collection_item("pm_projects", {"name": "Block B fitout"})
    assert _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c1["id"],
                 projectId=pr["id"])[0] == 200
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c2["id"],
                  projectId=pr["id"])
    assert st == 400 and "already linked" in r["error"]


def test_unlinking_clears_both_sides(api, tokens):
    c = _live(api, tokens)
    pr = db.put_collection_item("pm_projects", {"name": "Block B fitout"})
    _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c["id"],
          projectId=pr["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c["id"],
                  projectId="")
    assert st == 200 and r["item"]["projectId"] == ""
    assert db.get_collection_item("pm_projects", pr["id"])["contractId"] == ""


def test_an_unknown_project_is_refused(api, tokens):
    c = _live(api, tokens)
    assert _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c["id"],
                 projectId="pm-nope")[0] == 404


def test_linking_is_audited(api, tokens):
    c = _live(api, tokens)
    pr = db.put_collection_item("pm_projects", {"name": "P"})
    _post(api, tokens["staff"], "/api/sales/contract", action="link_project", id=c["id"],
          projectId=pr["id"])
    assert any(x.get("action") == "Linked contract to project" for x in db.list_collection("audit"))


def test_an_unlinked_contract_is_a_gap_on_the_trail(api, tokens):
    c = _live(api, tokens)
    _, r = api("GET", "/api/sales/trace?id=" + c["id"], tokens["staff"])
    assert "no-project" in [g["what"] for g in r["gaps"]]
