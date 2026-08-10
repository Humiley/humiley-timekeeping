"""One order, end to end — and the gaps that are only visible when you line the documents up.

This is the question a pharma or electronics customer's auditor actually asks: show me this order,
and show me it hangs together. Until this endpoint the answer lived in five screens and somebody's
memory.

The gaps are the useful half. Each one is a real thing somebody has to go and do, and each is
invisible on the screen that would otherwise show it — a certified claim looks finished on the
billing list, and only the trail shows that no invoice was ever raised against it.
"""
import pytest

import app
import db
import sales_contract as SC


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_receipts",
                  "crm_companies"):
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


def _quote(api, tokens, value=1_000_000_000):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Cleanroom AHU",
              accountName="Pharma Co", lines=[{"desc": "Works", "qty": 1, "unitPrice": value}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    return q


def _full_chain(api, tokens, claim=400_000_000):
    q = _quote(api, tokens)
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], advancePct=0,
          retentionPct=5, warrantyMonths=12, recoveryRule=SC.REC_PRORATA, releaseRule=SC.REL_WARRANTY_END)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    c = db.get_collection_item("sales_contracts", c["id"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-07", claims={c["lines"][0]["uid"]: claim})[1]["item"]
    _certify(api, tokens["management"], a["id"])
    return q, c, db.get_collection_item("sales_applications", a["id"])


def _trace(api, t, doc_id):
    return api("GET", "/api/sales/trace?id=" + doc_id, t)


def _kinds(r):
    return [s["kind"] for s in r["steps"]]



def _certify(api, token, aid, monkey=None):
    """Certifying is an e-signature now — the same act PMC's interim payment certificate has
    required for months. Tests drive it through /api/esign."""
    return api("POST", "/api/esign", token,
               {"coll": "sales_applications", "id": aid, "meaning": "Certified payment application",
                "setStatus": "certified"})

# ── the trail ────────────────────────────────────────────────────────────────────────────────────

def test_the_whole_chain_is_walked_from_the_quotation(api, tokens):
    q, c, a = _full_chain(api, tokens)
    _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA", einvNo="0001",
          einvXml="<Invoice/>")
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]}, reference="FT01")
    _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"],
          poNo="4500123456", poDate="2026-06-01", poValue=1_000_000_000)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"],
          acceptedOn="2026-07-31")
    st, r = _trace(api, tokens["staff"], q["id"])
    assert st == 200, r
    assert _kinds(r) == ["quotation", "po", "contract", "acceptance", "claim", "invoice", "receipt"]
    assert r["gaps"] == [], r["gaps"]


def test_an_order_billed_and_paid_in_full_still_has_an_open_item_until_acceptance_is_recorded(api, tokens):
    """The trail is the only place this shows. On every other screen the order looks finished:
    invoiced, paid, nothing outstanding — while 5% of it sits with the customer on a clock nobody
    has started."""
    q, c, a = _full_chain(api, tokens)
    _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA", einvNo="0003",
          einvXml="<Invoice/>")
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]})
    _post(api, tokens["staff"], "/api/sales/contract", action="po", id=c["id"], poNo="PO-1")
    r = _trace(api, tokens["staff"], c["id"])[1]
    assert [g["what"] for g in r["gaps"]] == ["retention-no-acceptance"]


def test_any_document_in_the_chain_finds_the_same_trail(api, tokens):
    """An auditor holds one number — a claim, an invoice, a receipt — not the quotation."""
    q, c, a = _full_chain(api, tokens)
    from_quote = _trace(api, tokens["staff"], q["id"])[1]
    for doc_id in (c["id"], a["id"]):
        assert _kinds(_trace(api, tokens["staff"], doc_id)[1]) == _kinds(from_quote)


def test_a_receipt_id_also_resolves_the_order(api, tokens):
    q, c, a = _full_chain(api, tokens)
    rec = _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
                allocations={a["id"]: a["netPayable"]})[1]["item"]
    assert _kinds(_trace(api, tokens["staff"], rec["id"])[1])[0] == "quotation"


def test_superseded_revisions_stay_in_the_trail(api, tokens):
    """What the customer was actually sent, and what replaced it — not just the version that won."""
    q = _quote(api, tokens)
    r2 = _post(api, tokens["staff"], "/api/sales/quote", action="revise", id=q["id"],
               lines=[{"desc": "Works", "qty": 1, "unitPrice": 900_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=r2["id"])
    st, r = _trace(api, tokens["staff"], r2["id"])
    assert [s["kind"] for s in r["steps"]] == ["quotation", "quotation"]
    assert [s["rev"] for s in r["steps"]] == [1, 2], "oldest first — the trail reads forwards"


def test_the_acceptance_date_appears_as_its_own_step(api, tokens):
    q, c, a = _full_chain(api, tokens)
    _post(api, tokens["staff"], "/api/sales/contract", action="accept", id=c["id"], acceptedOn="2026-01-15")
    r = _trace(api, tokens["staff"], c["id"])[1]
    acc = [s for s in r["steps"] if s["kind"] == "acceptance"]
    assert acc and acc[0]["on"] == "2026-01-15"


# ── the gaps ─────────────────────────────────────────────────────────────────────────────────────

def test_an_accepted_quotation_with_no_contract_is_a_gap(api, tokens):
    """Nothing is tracking what is owed on it — the most expensive silence on the sell side."""
    q = _quote(api, tokens)
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    r = _trace(api, tokens["staff"], q["id"])[1]
    assert [g["what"] for g in r["gaps"]] == ["accepted-no-contract"]


def test_work_certified_and_never_invoiced_is_a_gap(api, tokens):
    q, c, a = _full_chain(api, tokens)
    r = _trace(api, tokens["staff"], c["id"])[1]
    assert "certified-not-invoiced" in [g["what"] for g in r["gaps"]]


def test_an_invoice_number_with_no_signed_xml_is_a_gap(api, tokens):
    q, c, a = _full_chain(api, tokens)
    _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA", einvNo="0002")
    r = _trace(api, tokens["staff"], c["id"])[1]
    g = [x for x in r["gaps"] if x["what"] == "invoice-unverified"]
    assert g and g[0]["ref"] == "0002"


def test_an_unpaid_claim_is_a_gap_that_states_the_amount(api, tokens):
    q, c, a = _full_chain(api, tokens)
    r = _trace(api, tokens["staff"], c["id"])[1]
    g = [x for x in r["gaps"] if x["what"] == "unpaid"]
    assert g and "₫" in g[0]["why"]
    assert g[0]["amount"] == a["netPayable"], \
        "the amount travels as a number so the screen can write it in its own currency format"


def test_a_paid_claim_is_not_reported_as_unpaid(api, tokens):
    q, c, a = _full_chain(api, tokens)
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]})
    r = _trace(api, tokens["staff"], c["id"])[1]
    assert "unpaid" not in [g["what"] for g in r["gaps"]]


def test_retention_that_cannot_be_dated_names_the_actual_missing_thing(api, tokens):
    """"Cannot be dated" is two different problems with two different fixes — record the acceptance
    date, or record the release rule — so they are two codes, not one."""
    q, c, a = _full_chain(api, tokens)
    r = _trace(api, tokens["staff"], c["id"])[1]
    g = [x for x in r["gaps"] if x["what"].startswith("retention-")]
    assert [x["what"] for x in g] == ["retention-no-acceptance"]
    assert g[0]["amount"] > 0, "the screen writes the amount in its own currency format"


def test_a_short_payment_carries_its_reason_into_the_trail(api, tokens):
    q, c, a = _full_chain(api, tokens)
    part = round(a["netPayable"] * 0.9, 2)
    _post(api, tokens["staff"], "/api/sales/receipt", amount=part, allocations={a["id"]: part},
          shortReason="Disputed VO-3")
    r = _trace(api, tokens["staff"], c["id"])[1]
    rec = [s for s in r["steps"] if s["kind"] == "receipt"][0]
    assert rec["status"] == "short" and rec["note"] == "Disputed VO-3"


def test_another_orders_cash_never_appears_on_this_trail(api, tokens):
    """A trail that shows somebody else's payment is worse than no trail — it is the one document
    an auditor would take at face value."""
    _, c1, a1 = _full_chain(api, tokens)
    _, c2, a2 = _full_chain(api, tokens, claim=300_000_000)
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a2["netPayable"],
          allocations={a2["id"]: a2["netPayable"]}, reference="OTHER-ORDER")
    r = _trace(api, tokens["staff"], c1["id"])[1]
    assert [s for s in r["steps"] if s["kind"] == "receipt"] == []
    r2 = _trace(api, tokens["staff"], c2["id"])[1]
    assert [s["ref"] for s in r2["steps"] if s["kind"] == "receipt"] == ["OTHER-ORDER"]


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

def test_you_cannot_trace_somebody_elses_order(api, tokens):
    q, c, a = _full_chain(api, tokens)
    assert _trace(api, tokens["other"], c["id"])[0] == 403


def test_management_can(api, tokens):
    q, c, a = _full_chain(api, tokens)
    assert _trace(api, tokens["management"], c["id"])[0] == 200


def test_an_unknown_id_is_a_404_not_an_empty_trail(api, tokens):
    """An empty trail reads as "this order has no documents", which is a different and much more
    alarming thing than "that is not one of our ids"."""
    st, r = _trace(api, tokens["staff"], "sal-nope")
    assert st == 404 and "Nothing on the sell side" in r["error"]


def test_it_asks_which_document(api, tokens):
    assert api("GET", "/api/sales/trace", tokens["staff"])[0] == 400


def test_it_needs_a_session(api, tokens):
    assert _trace(api, None, "x")[0] == 401
