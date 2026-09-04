"""Recording acceptance, releasing retention, and the register that finds what nobody is chasing."""
import pytest

import app
import db
import sales_contract as SC


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "crm_companies"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()



@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    """Certifying, applying a variation and applying a credit note are all e-signatures now, so
    every test in this file drives /api/esign. The M365 re-auth is skipped here — the Part 11
    identity component has its own tests; these are about what the signature DOES."""
    monkeypatch.setattr(app, "DEMO_MODE", True)

def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _live_contract(api, tokens, release=SC.REL_WARRANTY_END, claim=400_000_000):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], advancePct=0,
          retentionPct=5, warrantyMonths=12, recoveryRule=SC.REC_PRORATA, releaseRule=release)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    c = db.get_collection_item("sales_contracts", c["id"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-07", claims={c["lines"][0]["uid"]: claim})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    return db.get_collection_item("sales_contracts", c["id"])



def _certify(api, token, aid, monkey=None):
    """Certifying is an e-signature now — the same act PMC's interim payment certificate has
    required for months. Tests drive it through /api/esign."""
    return api("POST", "/api/esign", token,
               {"coll": "sales_applications", "id": aid, "meaning": "Certified payment application",
                "setStatus": "certified"})

# ── acceptance starts the clock ─────────────────────────────────────────────────────────────────

def test_recording_acceptance_dates_the_release(api, tokens):
    c = _live_contract(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"],
                  acceptedOn="2026-01-15")
    assert st == 200, r
    assert r["item"]["acceptedOn"] == "2026-01-15"
    assert r["retention"]["tranches"][0]["dueOn"] == "2027-01-15"


def test_without_acceptance_the_retention_cannot_be_dated(api, tokens):
    c = _live_contract(api, tokens)
    _, r = api("GET", "/api/sales/retention", tokens["management"])
    assert [x["contractNo"] for x in r["undateable"]] == [c["contractNo"]]
    assert r["contracts"] == []


def test_an_acceptance_date_in_the_future_is_refused(api, tokens):
    """A warranty cannot start before the works were accepted."""
    c = _live_contract(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"],
                  acceptedOn="2099-01-01")
    assert st == 400 and "future" in r["error"]


def test_a_garbled_date_is_refused_rather_than_stored(api, tokens):
    c = _live_contract(api, tokens)
    assert _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"],
                 acceptedOn="15/01/2026")[0] == 400


def test_a_draft_contract_has_nothing_to_accept(api, tokens):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="J",
              lines=[{"desc": "W", "qty": 1, "unitPrice": 100}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    assert _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"],
                 acceptedOn="2026-01-15")[0] == 400


def test_acceptance_is_audited(api, tokens):
    c = _live_contract(api, tokens)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    assert any(x.get("action") == "Recorded works acceptance" for x in db.list_collection("audit"))


# ── releasing it ────────────────────────────────────────────────────────────────────────────────

def test_retention_due_can_be_released(api, tokens):
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="release_retention",
                  id=c["id"], amount=10_000_000)
    assert st == 200, r
    assert r["item"]["retentionReleased"] == 10_000_000
    assert r["retention"]["outstanding"] == 10_000_000


def test_releasing_more_than_is_due_needs_a_reason(api, tokens):
    """Early is allowed — customers do pay retention back ahead of the warranty — but "released" and
    "was owed" are different facts, and only one of them chases a customer."""
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="release_retention",
                  id=c["id"], amount=20_000_000)
    assert st == 400 and "early" in r["error"]
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="release_retention",
                  id=c["id"], amount=20_000_000, earlyReason="Bank guarantee swapped in")
    assert st == 200, r
    assert r["item"]["retentionReleases"][0]["early"] is True


def test_you_cannot_release_more_than_is_held(api, tokens):
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="release_retention",
                  id=c["id"], amount=99_000_000, earlyReason="x")
    assert st == 400 and "still held" in r["error"]


def test_retention_cannot_be_released_before_the_clock_can_even_be_read(api, tokens):
    """No acceptance date means no due date. Releasing against that would record money coming back
    on a schedule nobody has agreed."""
    c = _live_contract(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/contract", action="release_retention",
                  id=c["id"], amount=1_000_000)
    assert st == 400 and "acceptance" in r["error"].lower()


def test_a_release_records_who_and_when(api, tokens):
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    _post(api, tokens["staff"], "/api/sales/contract", action="release_retention", id=c["id"],
          amount=5_000_000, releasedOn="2026-02-01")
    h = db.get_collection_item("sales_contracts", c["id"])["retentionReleases"][0]
    assert h["by"] and h["on"] == "2026-02-01"
    assert any(x.get("action") == "Released retention" for x in db.list_collection("audit"))


# ── the register ────────────────────────────────────────────────────────────────────────────────

def test_the_register_shows_what_is_due_back_now(api, tokens):
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    st, r = api("GET", "/api/sales/retention", tokens["management"])
    assert st == 200, r
    assert r["totalHeld"] == 20_000_000 and r["dueNow"] == 10_000_000
    assert "₫" in r["statement"]


def test_a_contract_with_nothing_held_is_not_listed(api, tokens):
    c = _live_contract(api, tokens, release=SC.REL_HALF_AT_COMPLETION)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    _post(api, tokens["staff"], "/api/sales/contract", action="release_retention", id=c["id"],
          amount=20_000_000, earlyReason="settled in full")
    _, r = api("GET", "/api/sales/retention", tokens["management"])
    assert r["contracts"] == [] and r["undateable"] == [] and r["totalHeld"] == 0


def test_a_draft_contracts_opening_balance_is_not_a_receivable_yet(api, tokens):
    """`opening` lets you load an in-flight contract's balances, and until it is activated those
    figures are still editable. Reporting an editable number as money a customer owes back would
    put a retention chase behind a value somebody is still typing."""
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="J",
              lines=[{"desc": "W", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], retentionPct=5,
          warrantyMonths=12, releaseRule=SC.REL_WARRANTY_END)
    _post(api, tokens["staff"], "/api/sales/contract", action="opening", id=c["id"],
          certifiedToDate=400_000_000, retentionHeld=20_000_000)
    _, r = api("GET", "/api/sales/retention", tokens["management"])
    assert r["totalHeld"] == 0 and r["contracts"] == [] and r["undateable"] == []


def test_a_staff_user_sees_only_their_own_contracts_retention(api, tokens):
    """It carries the contract value and the customer. Reads here are default-allow, so the scoping
    has to be done in the endpoint."""
    _live_contract(api, tokens)
    st, r = api("GET", "/api/sales/retention", tokens["other"])
    assert st == 200, r
    assert r["contracts"] == [] and r["undateable"] == []


def test_it_needs_a_session(api, tokens):
    assert api("GET", "/api/sales/retention", None)[0] == 401
