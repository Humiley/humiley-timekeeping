"""The variation over the wire — and the reason applying it is a signature, not a save.

Raising the value every later claim is measured against is the single most consequential act on a
sell-side contract. PMC's own variation order has required an e-signature for months; this brings
the sell side to the same standard, through the same /api/esign path, with the same
somebody-other-than-the-author rule.
"""
import pytest

import app
import db
import sales_contract as SC
import sales_doc as S
import sales_variation as V


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_variations"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO','VO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _live(api, tokens, value=1_000_000_000):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": value}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], retentionPct=5,
          warrantyMonths=12, releaseRule=SC.REL_WARRANTY_END, recoveryRule=SC.REC_PRORATA)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    return db.get_collection_item("sales_contracts", c["id"])


def _var(api, tokens, c, **kw):
    b = dict({"action": "draft", "contractId": c["id"], "title": "Extra AHU to Block C",
              "lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]}, **kw)
    return _post(api, tokens["staff"], "/api/sales/variation", **b)


@pytest.fixture
def signing(monkeypatch):
    """Skip the M365 re-auth so a test can drive the e-signature — the same shim the bank-slip
    tests use. The Part 11 identity component is exercised by its own tests; what these are about
    is what the signature DOES."""
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _sign(api, token, vid, status=V.APPLIED, meaning="Applied variation"):
    return api("POST", "/api/esign", token,
               {"coll": "sales_variations", "id": vid, "meaning": meaning, "setStatus": status})


# ── raising one ──────────────────────────────────────────────────────────────────────────────────

def test_a_draft_shows_what_it_would_do_before_anybody_signs(api, tokens):
    c = _live(api, tokens)
    st, r = _var(api, tokens, c)
    assert st == 200, r
    assert r["effect"]["newValue"] == 1_080_000_000
    assert "₫80,000,000 added to the contract" in r["effect"]["statement"]


def test_issuing_takes_a_VO_number(api, tokens):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    assert st == 200, r
    assert r["item"]["variationNo"].startswith("VO-")
    assert r["item"]["status"] == V.ISSUED


def test_a_variation_needs_a_title(api, tokens):
    c = _live(api, tokens)
    v = _var(api, tokens, c, title="")[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    assert st == 400 and "title" in r["error"]


def test_an_issued_variation_cannot_be_edited(api, tokens):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    st, r = _var(api, tokens, c, id=v["id"])
    assert st == 400 and "cannot be edited" in r["error"]


def test_a_variation_that_changes_nothing_is_refused_at_draft(api, tokens):
    c = _live(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/variation", action="draft",
                  contractId=c["id"], title="Nothing")
    assert st == 400 and "changes nothing" in r["error"]


def test_a_variation_belongs_to_an_active_contract(api, tokens):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="J",
              lines=[{"desc": "W", "qty": 1, "unitPrice": 100}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    assert _var(api, tokens, c)[0] == 400


# ── applying it is a SIGNATURE ───────────────────────────────────────────────────────────────────

def test_applying_is_not_an_action_on_this_endpoint(api, tokens):
    """The whole point. If it were an action, the value ceiling would move on an unsigned POST."""
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/variation", action="apply", id=v["id"])
    assert st == 400 and "e-signature, not an action" in r["error"]


def test_a_signed_variation_raises_the_contract_and_appends_its_lines(api, tokens, signing):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    st, r = _sign(api, tokens["management"], v["id"])
    assert st == 200, r
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["value"] == 1_080_000_000
    assert len(after["lines"]) == 2
    assert after["lines"][1]["src"]["doc"] == "variation"


def test_the_signature_is_on_the_variation(api, tokens, signing):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    _sign(api, tokens["management"], v["id"])
    after = db.get_collection_item("sales_variations", v["id"])
    assert after["status"] == V.APPLIED and after["signatures"]
    assert after["appliedBy"]


def test_the_raised_ceiling_is_what_the_claim_engine_now_measures_against(api, tokens, signing):
    """The refusal that named the variation in the first place. Before: certifying ₫1.05bn against
    a ₫1bn contract is refused. After a signed ₫80m variation, it is fine."""
    c = _live(api, tokens)
    uid = c["lines"][0]["uid"]
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="2026-08", claims={uid: 1_050_000_000})
    assert st == 400
    assert "over by ₫50,000,000" in r["error"], r     # the LINE guard fires first, and in đồng

    v = _var(api, tokens, c, lines=[{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    _sign(api, tokens["management"], v["id"])
    c2 = db.get_collection_item("sales_contracts", c["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/application", action="draft",
                  contractId=c["id"], period="2026-08",
                  claims={uid: 1_000_000_000, c2["lines"][1]["uid"]: 50_000_000})
    assert st == 200, r
    assert r["preview"]["certifiedThis"] == 1_050_000_000


def test_a_draft_variation_cannot_be_signed_into_effect(api, tokens, signing):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    st, r = _sign(api, tokens["management"], v["id"])
    assert st == 400 and "issued variation" in r["error"]
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_000_000_000


def test_applying_it_twice_does_not_raise_the_contract_twice(api, tokens, signing):
    """A retry or a double click on a signature must not add ₫160,000,000."""
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    assert _sign(api, tokens["management"], v["id"])[0] == 200
    second = _sign(api, tokens["management"], v["id"])
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_080_000_000, second


def test_it_is_applied_by_somebody_other_than_the_person_who_raised_it(api, tokens, signing):
    """Same rule the payment application already enforces: the sell-side equivalent of approving
    your own expense."""
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    st, r = _sign(api, tokens["staff"], v["id"])
    assert st == 403


def test_applying_is_a_management_act(api, tokens, signing):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    st, r = _sign(api, tokens["mgr"], v["id"])
    assert st == 403 and "management" in r["error"]


# ── the outcomes that are not "applied" ─────────────────────────────────────────────────────────

def test_a_rejection_needs_a_reason(api, tokens):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    assert _post(api, tokens["staff"], "/api/sales/variation", action="reject", id=v["id"])[0] == 400
    st, r = _post(api, tokens["staff"], "/api/sales/variation", action="reject", id=v["id"],
                  reason="Client de-scoped it")
    assert st == 200 and r["item"]["status"] == V.REJECTED


def test_a_rejected_variation_never_touched_the_contract(api, tokens, signing):
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])
    _post(api, tokens["staff"], "/api/sales/variation", action="reject", id=v["id"], reason="no")
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_000_000_000
    assert _sign(api, tokens["management"], v["id"])[0] == 400


# ── the generic route stays shut ────────────────────────────────────────────────────────────────

def test_the_collection_route_cannot_create_or_rewrite_one(api, tokens):
    c = _live(api, tokens)
    st, r = api("POST", "/api/coll/sales_variations", tokens["management"], {"title": "Backdoor"})
    assert st == 400 and "/api/sales/variation" in r["error"]
    v = _var(api, tokens, c)[1]["item"]
    cur = db.get_collection_item("sales_variations", v["id"])
    st, r = api("PATCH", "/api/coll/sales_variations/" + v["id"], tokens["management"],
                dict(cur, valueDelta=999_000_000))
    assert st == 400 and "/api/sales/variation" in r["error"]


def test_a_staff_user_sees_only_their_own(api, tokens):
    c = _live(api, tokens)
    _var(api, tokens, c)
    st, r = api("GET", "/api/coll/sales_variations", tokens["other"])
    assert st == 200, r
    assert (r["items"] if isinstance(r, dict) and "items" in r else r) == []


# ── the three the first mutation pass walked straight through ───────────────────────────────────

def test_management_cannot_apply_a_variation_IT_raised(api, tokens, signing):
    """Testing this with `staff` proves nothing: the management-level check refuses them first, so
    the author rule was never reached. It only bites when the author IS management."""
    c = _live(api, tokens)
    v = _post(api, tokens["management"], "/api/sales/variation", action="draft",
              contractId=c["id"], title="Self-raised",
              lines=[{"desc": "Extra", "qty": 1, "unitPrice": 10_000_000}])[1]["item"]
    _post(api, tokens["management"], "/api/sales/variation", action="issue", id=v["id"])
    st, r = _sign(api, tokens["management"], v["id"])
    assert st == 403 and "other than the person who raised it" in r["error"]
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_000_000_000


def test_a_variation_that_became_invalid_between_issue_and_signature_is_refused(api, tokens, signing):
    """It is issued while the contract has nothing certified, and signed after ₫900,000,000 has
    been. The reduction is now impossible, and the signature must not apply it anyway."""
    c = _live(api, tokens)
    v = _post(api, tokens["staff"], "/api/sales/variation", action="draft", contractId=c["id"],
              title="De-scope the rest", valueDelta=-800_000_000)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])

    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-08", claims={c["lines"][0]["uid"]: 900_000_000})[1]["item"]
    _post(api, tokens["management"], "/api/sales/application", action="certify", id=a["id"])

    st, r = _sign(api, tokens["management"], v["id"])
    assert st == 400 and "already certified" in r["error"]
    after = db.get_collection_item("sales_contracts", c["id"])
    assert after["value"] == 1_000_000_000, "the contract must be untouched"
    assert db.get_collection_item("sales_variations", v["id"])["status"] == V.ISSUED


def test_a_contract_that_moved_under_the_signature_is_retried_not_overwritten(api, tokens, signing,
                                                                              monkeypatch):
    """Applying is compare-and-swap. A plain write would lose whatever a concurrent claim had just
    deducted — deterministic here rather than racing threads and hoping they overlap."""
    import db as _db
    c = _live(api, tokens)
    v = _var(api, tokens, c)[1]["item"]
    _post(api, tokens["staff"], "/api/sales/variation", action="issue", id=v["id"])

    real, calls = _db.put_collection_item_if_rev, {"n": 0}

    def flaky(coll, item, rev):
        calls["n"] += 1
        if coll == "sales_contracts" and calls["n"] == 1:
            return None                     # somebody else wrote first
        return real(coll, item, rev)

    monkeypatch.setattr(_db, "put_collection_item_if_rev", flaky)
    st, r = _sign(api, tokens["management"], v["id"])
    assert st == 200, r
    assert calls["n"] >= 2, "it must have re-read and retried, not given up or written blindly"
    assert db.get_collection_item("sales_contracts", c["id"])["value"] == 1_080_000_000
