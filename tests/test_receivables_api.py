"""Stage 5 — the legal invoice, the cash, and the three clocks.

The point of this group is what the portal refuses to pretend: it cannot issue a Vietnamese VAT
invoice, so it captures the provider's and flags anything typed in with no XML behind it as
UNVERIFIED, permanently. And a contractor's receivable is never one number — trade debt, retention
and advance run on three different clocks pointing in two different directions.
"""
import pytest

import db
import sales_contract as SC


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications", "sales_receipts", "crm_companies"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _certified(api, tokens, claim=200_000_000, terms_code="NET30"):
    acc = db.put_collection_item("crm_companies", {"name": "Pharma Co", "termsCode": terms_code,
                                                   "legalNameVn": "Cty", "mst": "0123456789",
                                                   "regAddress": "HCM", "owner": "Staff One"})
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co", accountId=acc["id"],
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], advancePct=30,
          retentionPct=5, warrantyMonths=12, recoveryRule=SC.REC_PRORATA, releaseRule=SC.REL_WARRANTY_END)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    c = db.get_collection_item("sales_contracts", c["id"])
    a = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
              period="2026-08", claims={c["lines"][0]["uid"]: claim})[1]["item"]
    _post(api, tokens["management"], "/api/sales/application", action="certify", id=a["id"])
    return db.get_collection_item("sales_applications", a["id"]), c


# ── the legal invoice: captured, never generated ─────────────────────────────────────────────────

def test_a_typed_invoice_number_is_recorded_as_unverified(api, tokens):
    """Without this flag, "we have an invoice number" and "we have an invoice" become the same
    sentence."""
    a, _ = _certified(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"],
                  einvSerial="C26TAA", einvNo="00001234", einvDate="2026-08-09")
    assert st == 200, r
    assert r["verified"] is False
    assert "UNVERIFIED" in r["note"]


def test_the_providers_signed_xml_is_what_makes_it_verified(api, tokens):
    a, _ = _certified(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA",
                  einvNo="00001234", einvXml="<Invoice>…signed…</Invoice>")
    assert st == 200 and r["verified"] is True
    assert "signed XML" in r["note"]


def test_both_the_ky_hieu_and_the_number_are_required(api, tokens):
    a, _ = _certified(api, tokens)
    assert _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvNo="00001234")[0] == 400
    assert _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA")[0] == 400


def test_an_invoice_cannot_be_attached_before_the_claim_is_certified(api, tokens):
    a, c = _certified(api, tokens)
    a2 = _post(api, tokens["staff"], "/api/sales/application", action="draft", contractId=c["id"],
               period="2026-09", claims={c["lines"][0]["uid"]: 1_000})[1]["item"]
    st, r = _post(api, tokens["staff"], "/api/sales/einvoice", id=a2["id"], einvSerial="X", einvNo="1")
    assert st == 400 and "CERTIFIED" in r["error"]


# ── cash ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_receipt_settles_the_claim_it_is_allocated_to(api, tokens):
    a, _ = _certified(api, tokens)
    net = a["netPayable"]
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=net,
                  allocations={a["id"]: net}, method="Bank", reference="FT2608")
    assert st == 200, r
    after = db.get_collection_item("sales_applications", a["id"])
    assert after["settledAmt"] == net and after["settledFully"] is True


def test_every_dong_has_to_land_somewhere(api, tokens):
    a, _ = _certified(api, tokens)
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=100_000_000,
                  allocations={a["id"]: 50_000_000})
    assert st == 400 and "land somewhere" in r["error"]


def test_a_short_payment_needs_a_reason(api, tokens):
    """"They paid 90%" with no reason is how a dispute becomes a write-off eighteen months later."""
    a, _ = _certified(api, tokens)
    part = round(a["netPayable"] * 0.9, 2)
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=part, allocations={a["id"]: part})
    assert st == 400 and "short payment needs a reason" in r["error"]
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=part, allocations={a["id"]: part},
                  shortReason="Disputed variation VO-3")
    assert st == 200, r


def test_you_cannot_allocate_more_than_is_outstanding(api, tokens):
    a, _ = _certified(api, tokens)
    over = a["netPayable"] + 1_000
    st, r = _post(api, tokens["staff"], "/api/sales/receipt", amount=over, allocations={a["id"]: over})
    assert st == 400 and "outstanding" in r["error"]


def test_a_receipt_must_be_allocated_at_all(api, tokens):
    assert _post(api, tokens["staff"], "/api/sales/receipt", amount=1_000)[0] == 400


def test_receipts_are_audited(api, tokens):
    a, _ = _certified(api, tokens)
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]})
    assert any(x.get("action") == "Recorded customer receipt" for x in db.list_collection("audit"))


# ── the three clocks ─────────────────────────────────────────────────────────────────────────────

def _recv(api, t):
    return api("GET", "/api/sales/receivables", t)


def test_the_three_clocks_are_reported_separately_and_never_summed(api, tokens):
    """Retention is not late — it is not due until the warranty ends. An advance is money you hold
    that is owed BACK. Adding them gives a figure wrong in three directions."""
    _certified(api, tokens)
    st, r = _recv(api, tokens["management"])
    assert st == 200, r
    assert r["trade"]["total"] > 0
    assert r["retentionHeldByCustomers"] == 10_000_000
    assert r["advanceOwedBack"] == 240_000_000
    assert "three different clocks" in r["whyNotOneNumber"]


def test_a_settled_claim_leaves_the_receivable(api, tokens):
    a, _ = _certified(api, tokens)
    _post(api, tokens["staff"], "/api/sales/receipt", amount=a["netPayable"],
          allocations={a["id"]: a["netPayable"]})
    _, r = _recv(api, tokens["management"])
    assert r["trade"]["total"] == 0


def test_an_unverified_invoice_is_surfaced_on_the_receivable(api, tokens):
    a, _ = _certified(api, tokens)
    _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA", einvNo="0007")
    _, r = _recv(api, tokens["management"])
    assert [x["einvNo"] for x in r["unverifiedInvoices"]] == ["0007"]


def test_a_customer_with_no_payment_terms_is_named_rather_than_given_a_made_up_due_date(api, tokens):
    """An invented due date makes an aging report confidently wrong."""
    _certified(api, tokens, terms_code="")
    _, r = _recv(api, tokens["management"])
    assert r["withoutPaymentTerms"]
    assert all(not row["termsKnown"] for row in r["trade"]["rows"])


def test_receivables_are_not_for_staff(api, tokens):
    assert _recv(api, tokens["staff"])[0] == 403
    assert _recv(api, None)[0] == 401


def test_a_department_manager_is_past_the_route_guard_and_still_refused(api, tokens):
    """The route's manager=True gate lets a department manager through, so the endpoint's own
    management-level check is the only thing standing between a line manager and the company's whole
    order book. Testing this with `staff` proves nothing — the route guard refuses first."""
    assert _recv(api, tokens["mgr"])[0] == 403
