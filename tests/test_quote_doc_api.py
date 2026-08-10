"""The quotation as a document — Stage 2.

It used to be a scratchpad on the deal: crmQBSave overwrote deal.lines, so re-quoting destroyed what
the customer had been sent and nothing recorded which version they accepted. These lock in the three
properties that make it a record instead: it cannot be edited after it leaves the building, it keeps
one number across every revision, and it cannot be closed as Lost without saying why.
"""
import pytest

import db
import sales_doc as S


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "crm_companies"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.commit(); conn.close()
        conn = db.get_conn()
        conn.execute("DELETE FROM doc_counters WHERE series = 'QT'")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


LINES = [{"desc": "Cleanroom AHU", "qty": 2, "unitPrice": 100_000_000},
         {"desc": "SECTION B", "kind": "heading"},
         {"desc": "Installation", "qty": 1, "unitPrice": 85_000_000, "discPct": 10}]


def _q(api, token, **body):
    return api("POST", "/api/sales/quote", token, body)


def _draft(api, token, lines=None, **kw):
    st, r = _q(api, token, action="draft", title="AHU supply", accountName="Pharma Co",
               lines=lines if lines is not None else LINES, **kw)
    assert st == 200, r
    return r["item"]


# ── drafting ─────────────────────────────────────────────────────────────────────────────────────

def test_a_draft_totals_only_the_lines_that_carry_value(api, tokens):
    st, r = _q(api, tokens["staff"], action="draft", title="AHU", lines=LINES)
    assert st == 200, r
    assert r["totals"]["lines"] == 2, "the heading is not a priced line"
    assert r["totals"]["amount"] == 200_000_000 + 76_500_000


def test_every_line_gets_a_stable_id_the_server_minted(api, tokens):
    """The browser never picks a uid: history points at these, and a client that could choose one
    could attach a new line to a claim somebody already certified."""
    q = _draft(api, tokens["staff"])
    uids = [l["uid"] for l in q["lines"]]
    assert len(set(uids)) == len(uids) and all(uids)


def test_a_draft_can_be_edited_in_place(api, tokens):
    q = _draft(api, tokens["staff"])
    st, r = _q(api, tokens["staff"], action="draft", id=q["id"],
               lines=[{"desc": "Changed", "qty": 1, "unitPrice": 5}])
    assert st == 200 and r["totals"]["amount"] == 5


def test_it_needs_a_session(api, tokens):
    assert _q(api, None, action="draft")[0] == 401


# ── issuing ──────────────────────────────────────────────────────────────────────────────────────

def test_issuing_takes_a_document_number_and_starts_the_validity_clock(api, tokens):
    q = _draft(api, tokens["staff"])
    st, r = _q(api, tokens["staff"], action="issue", id=q["id"])
    assert st == 200, r
    assert r["item"]["quoteNo"].startswith("QT-")
    assert r["item"]["status"] == S.ISSUED and r["item"]["rev"] == 1
    assert r["item"]["validUntil"]


def test_an_issued_quotation_cannot_be_edited_in_place(api, tokens):
    """It is evidence now. Editing it changes what you can prove you sent."""
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    st, r = _q(api, tokens["staff"], action="draft", id=q["id"], lines=[{"desc": "Sneaky", "qty": 1, "unitPrice": 1}])
    assert st == 400 and "REVISION" in r["error"]


def test_an_empty_quotation_cannot_be_issued(api, tokens):
    q = _draft(api, tokens["staff"], lines=[{"desc": "SECTION ONLY", "kind": "heading"}])
    st, r = _q(api, tokens["staff"], action="issue", id=q["id"])
    assert st == 400 and "no priced line" in r["error"]


def test_the_generic_collection_route_cannot_create_one__staff(api, tokens):
    """Two layers, and both matter. sales_quotes is not in STAFF_WRITE, so the role gate stops a
    staff user before anything else does."""
    assert api("POST", "/api/coll/sales_quotes", tokens["staff"], {"title": "Backdoor"})[0] == 403


def test_the_generic_collection_route_cannot_create_one__management(api, tokens):
    """Past the role gate, ISSUED_ONLY refuses and names the endpoint that should have been used.
    A PATCH through /api/coll is a whole-document replace — a one-key write would delete a 300-line
    bill of quantities and every open balance on it."""
    st, r = api("POST", "/api/coll/sales_quotes", tokens["management"], {"title": "Backdoor"})
    assert st == 400, (st, r)
    assert "/api/sales/quote" in r["error"]


def test_the_generic_route_cannot_rewrite_an_issued_one_either(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    cur = db.get_collection_item("sales_quotes", q["id"])
    st, r = api("PATCH", "/api/coll/sales_quotes/" + q["id"], tokens["management"],
                dict(cur, lines=[]))
    assert st == 400 and "/api/sales/quote" in r["error"]
    assert db.get_collection_item("sales_quotes", q["id"])["lines"], "the BOQ must survive"


# ── revising: one number, many revisions ─────────────────────────────────────────────────────────

def test_a_revision_keeps_the_number_and_supersedes_the_old_one(api, tokens):
    q = _draft(api, tokens["staff"])
    issued = _q(api, tokens["staff"], action="issue", id=q["id"])[1]["item"]
    st, r = _q(api, tokens["staff"], action="revise", id=q["id"],
               lines=[{"desc": "Cleanroom AHU", "qty": 2, "unitPrice": 80_000_000}])
    assert st == 200, r
    assert r["item"]["quoteNo"] == issued["quoteNo"], "the customer refers to one reference"
    assert r["item"]["status"] == S.DRAFT and r["item"]["supersedes"] == q["id"]
    assert db.get_collection_item("sales_quotes", q["id"])["status"] == S.SUPERSEDED


def test_the_superseded_revision_survives_intact(api, tokens):
    """What the customer already holds must stay provable."""
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    _q(api, tokens["staff"], action="revise", id=q["id"],
       lines=[{"desc": "Cheaper", "qty": 1, "unitPrice": 1}])
    old = db.get_collection_item("sales_quotes", q["id"])
    assert S.totals(old["lines"])["amount"] == 200_000_000 + 76_500_000


def test_revision_two_increments_the_revision_number(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    r2 = _q(api, tokens["staff"], action="revise", id=q["id"])[1]["item"]
    i2 = _q(api, tokens["staff"], action="issue", id=r2["id"])[1]["item"]
    assert i2["rev"] == 2 and i2["quoteNo"] == db.get_collection_item("sales_quotes", q["id"])["quoteNo"]


# ── the outcome ──────────────────────────────────────────────────────────────────────────────────

def test_accepting_records_who_and_when(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    st, r = _q(api, tokens["staff"], action="accept", id=q["id"])
    assert st == 200 and r["item"]["status"] == S.ACCEPTED
    assert r["item"]["outcomeAt"] and r["item"]["outcomeBy"]


def test_losing_without_a_reason_is_refused(api, tokens):
    """Win rate is charted already and is undiagnosable without this — a company can lose for years
    without learning whether it loses on price, lead time or scope."""
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    assert _q(api, tokens["staff"], action="lose", id=q["id"])[0] == 400


def test_losing_with_a_reason_records_it_and_the_competitor(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    st, r = _q(api, tokens["staff"], action="lose", id=q["id"], reason="price", competitor="Rival JSC")
    assert st == 200 and r["item"]["lostReason"] == "price" and r["item"]["competitor"] == "Rival JSC"


def test_a_lost_quotation_is_final(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    _q(api, tokens["staff"], action="lose", id=q["id"], reason="price")
    st, r = _q(api, tokens["staff"], action="accept", id=q["id"])
    assert st == 400 and "final" in r["error"]


def test_a_draft_cannot_be_accepted_without_being_issued(api, tokens):
    q = _draft(api, tokens["staff"])
    st, r = _q(api, tokens["staff"], action="accept", id=q["id"])
    assert st == 400 and "issued" in r["error"]


# ── who may touch it ─────────────────────────────────────────────────────────────────────────────

def test_you_cannot_change_somebody_elses_quotation(api, tokens):
    q = _draft(api, tokens["staff"])
    assert _q(api, tokens["other"], action="issue", id=q["id"])[0] == 403


def test_management_can(api, tokens):
    q = _draft(api, tokens["staff"])
    assert _q(api, tokens["management"], action="issue", id=q["id"])[0] == 200


def test_a_staff_user_sees_only_their_own_quotations(api, tokens):
    """A quotation carries the contract value, the per-line price and the margin a discount was
    approved against. Reads here are default-allow, so this had to be registered explicitly."""
    _draft(api, tokens["staff"])
    _draft(api, tokens["other"])
    st, r = api("GET", "/api/coll/sales_quotes", tokens["staff"])
    assert st == 200, r
    assert all(x.get("owner") == "Staff One" for x in (r.get("items") or r))


def test_an_unknown_action_is_named_rather_than_ignored(api, tokens):
    q = _draft(api, tokens["staff"])
    st, r = _q(api, tokens["staff"], action="frobnicate", id=q["id"])
    assert st == 400 and "draft, issue, revise" in r["error"]


def test_issuing_is_audited(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    assert any(x.get("action") == "Issued quotation" for x in db.list_collection("audit"))


def test_a_uid_the_client_invents_is_discarded(api, tokens):
    """History points at these. A browser free to choose one could attach a brand-new line to a
    claim or a certificate that was signed against a different line entirely."""
    q = _draft(api, tokens["staff"], lines=[{"uid": "attacker-1", "desc": "X", "qty": 1, "unitPrice": 10}])
    assert q["lines"][0]["uid"] != "attacker-1"


def test_a_uid_the_document_already_has_survives_an_edit(api, tokens):
    """Otherwise every save re-identifies every line and history detaches from it.

    The lines are REORDERED on the way back in, which is what a user dragging a BOQ row actually
    does — and it is the only version of this test that can fail. Saving them in their original
    order lets a server that re-mints from scratch produce the same ids by coincidence."""
    q = _draft(api, tokens["staff"])
    original = [l["uid"] for l in q["lines"]]
    reversed_lines = list(reversed(q["lines"]))
    st, r = _q(api, tokens["staff"], action="draft", id=q["id"], lines=reversed_lines)
    assert st == 200, r
    assert [l["uid"] for l in r["item"]["lines"]] == list(reversed(original)), \
        "each line kept its own id through the reorder"


def test_a_quotation_cannot_be_issued_twice(api, tokens):
    """The second issue would re-stamp the date and the validity a customer is already holding."""
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    st, r = _q(api, tokens["staff"], action="issue", id=q["id"])
    assert st == 400 and "already issued" in r["error"]


def test_a_lost_quotation_cannot_be_issued_again(api, tokens):
    q = _draft(api, tokens["staff"])
    _q(api, tokens["staff"], action="issue", id=q["id"])
    _q(api, tokens["staff"], action="lose", id=q["id"], reason="price")
    assert _q(api, tokens["staff"], action="issue", id=q["id"])[0] == 400


def test_the_deal_side_numbering_endpoint_is_gone(api, tokens):
    """/api/sales/quote-number numbered a quotation held on the DEAL, for the builder that has been
    retired. tests/test_quote_number_api.py went with it. The number is minted here, at ISSUE — the
    point at which it starts meaning something — and an endpoint whose only caller has gone is not
    "unused", it is a second way to do the thing, waiting to disagree with this one."""
    assert api("POST", "/api/sales/quote-number", tokens["staff"], {"dealId": "x"})[0] == 404
