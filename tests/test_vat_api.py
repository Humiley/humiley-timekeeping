"""Filling the VAT treatment in, and the tax line it puts on every claim.

The bug this closes is subtler than a missing screen. `vat_ready()` named two tax questions and
offered nowhere to answer them — and the "company settings" dict it was handed could never have
contained them, because that helper only ever returned the company's LEGAL IDENTITY fields. So the
two questions were unanswerable at company level no matter what anybody typed, and the check that
named them could only ever fail. A setting nothing can set is the same bug as an endpoint nothing
can call.
"""
import pytest

import db
import sales_contract as SC
import vat


@pytest.fixture(autouse=True)
def _clean():
    def wipe():
        conn = db.get_conn()
        for c in ("sales_quotes", "sales_contracts", "sales_applications"):
            conn.execute("DELETE FROM collections WHERE coll = ?", (c,))
        conn.execute("DELETE FROM doc_counters WHERE series IN ('QT','SO')")
        for k in ("vatRate", "vatBase") + vat.TAX_POINT_KEYS:
            conn.execute("DELETE FROM settings WHERE key = ?", ("portal_vat_" + k,))
        conn.commit(); conn.close()
    wipe(); yield; wipe()


def _post(api, t, path, **b):
    return api("POST", path, t, b)


def _live(api, tokens, **terms):
    q = _post(api, tokens["staff"], "/api/sales/quote", action="draft", title="Job",
              accountName="Pharma Co",
              lines=[{"desc": "Works", "qty": 1, "unitPrice": 1_000_000_000}])[1]["item"]
    _post(api, tokens["staff"], "/api/sales/quote", action="issue", id=q["id"])
    _post(api, tokens["staff"], "/api/sales/quote", action="accept", id=q["id"])
    c = _post(api, tokens["staff"], "/api/sales/contract", action="from_quote", quoteId=q["id"])[1]["item"]
    t = dict({"advancePct": 30, "retentionPct": 5, "warrantyMonths": 12,
              "recoveryRule": SC.REC_PRORATA, "releaseRule": SC.REL_WARRANTY_END}, **terms)
    _post(api, tokens["staff"], "/api/sales/contract", action="terms", id=c["id"], **t)
    _post(api, tokens["staff"], "/api/sales/contract", action="activate", id=c["id"])
    _post(api, tokens["staff"], "/api/sales/receipt", kind="advance", contractId=c["id"],
          amount=300_000_000)
    return db.get_collection_item("sales_contracts", c["id"])


def _claim(api, tokens, c, amount=200_000_000, **kw):
    return _post(api, tokens["staff"], "/api/sales/application", action="draft",
                 contractId=c["id"], period="2026-08",
                 claims={c["lines"][0]["uid"]: amount}, **kw)


# ── the settings can actually be set ────────────────────────────────────────────────────────────

def test_the_company_starts_with_nothing_recorded_and_says_what_is_missing(api, tokens):
    st, r = api("GET", "/api/sales/vat-settings", tokens["management"])
    assert st == 200, r
    assert r["complete"] is False
    assert {m["key"] for m in r["missing"]} == {"vatRate", "vatBase",
                                               "retentionTaxPoint", "advanceTaxPoint"}


def test_the_four_answers_can_be_recorded_and_come_back(api, tokens):
    st, r = _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
                  vatBase=vat.BASE_CERTIFIED, retentionTaxPoint="at_acceptance",
                  advanceTaxPoint="on_receipt")
    assert st == 200, r
    assert r["complete"] is True
    _, again = api("GET", "/api/sales/vat-settings", tokens["management"])
    assert again["rate"] == "10" and again["retentionTaxPoint"] == "at_acceptance"


def test_the_answers_reach_the_helper_that_asks_the_questions(api, tokens):
    """The actual bug: _company_settings only ever returned the company's legal-identity fields, so
    vat_ready() was handed a dict that could not contain the answers it asked for."""
    _post(api, tokens["management"], "/api/sales/vat-settings", retentionTaxPoint="at_release",
          advanceTaxPoint="on_certification")
    c = _live(api, tokens)
    _, r = _claim(api, tokens, c)
    assert r["vat"]["ready"] is True, r["vat"]


def test_a_rate_that_is_not_a_rate_is_refused(api, tokens):
    st, r = _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=12)
    assert st == 400 and "not one of the VAT rates" in r["error"]


def test_a_base_that_is_neither_is_refused(api, tokens):
    st, r = _post(api, tokens["management"], "/api/sales/vat-settings", vatBase="whatever")
    assert st == 400 and "neither" in r["error"]


def test_a_tax_point_answer_that_was_not_offered_is_refused(api, tokens):
    assert _post(api, tokens["management"], "/api/sales/vat-settings",
                 retentionTaxPoint="whenever")[0] == 400


def test_recording_the_treatment_is_audited(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=8)
    assert any(x.get("action") == "Recorded company VAT treatment"
               for x in db.list_collection("audit"))


def test_it_is_a_management_act(api, tokens):
    assert api("GET", "/api/sales/vat-settings", tokens["staff"])[0] == 403
    assert _post(api, tokens["staff"], "/api/sales/vat-settings", vatRate=8)[0] == 403


def test_a_department_manager_is_past_the_route_guard_and_still_refused(api, tokens):
    """Testing this with `staff` proves nothing — the route's manager gate refuses them first."""
    assert api("GET", "/api/sales/vat-settings", tokens["mgr"])[0] == 403


# ── the tax line on the claim ───────────────────────────────────────────────────────────────────

def test_a_claim_is_ex_vat_until_somebody_records_a_rate(api, tokens):
    c = _live(api, tokens)
    _, r = _claim(api, tokens, c)
    assert r["item"]["vatSet"] is False
    assert r["item"]["vatAmount"] == 0
    assert r["item"]["grossPayable"] == r["item"]["netPayable"], "no tax line, still worth its net"


def test_the_company_default_puts_a_tax_line_on_every_claim(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens)
    _, r = _claim(api, tokens, c)
    assert r["item"]["vatSet"] is True
    assert r["item"]["vatAmount"] == 20_000_000            # 10% of the ₫200m certified
    assert r["item"]["grossPayable"] == 150_000_000        # net ₫130m + tax
    assert r["item"]["vatFrom"] == "company"


def test_the_base_choice_changes_the_tax_by_the_recovery_and_the_retention(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10, vatBase=vat.BASE_NET)
    c = _live(api, tokens)
    _, r = _claim(api, tokens, c)
    assert r["item"]["vatAmount"] == 13_000_000, "10% of the net, not of the certified value"


def test_a_contract_can_override_the_company(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens, vatRate=8)
    _, r = _claim(api, tokens, c)
    assert r["item"]["vatAmount"] == 16_000_000 and r["item"]["vatFrom"] == "contract"


def test_a_single_claim_can_override_the_contract(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens, vatRate=8)
    _, r = _claim(api, tokens, c, vatRate=0)
    assert r["item"]["vatAmount"] == 0 and r["item"]["vatFrom"] == "claim"
    assert r["item"]["vatSet"] is True, "0% is an answer, not a blank"


def test_not_a_vat_supply_is_recorded_as_a_choice(api, tokens):
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens)
    _, r = _claim(api, tokens, c, vatRate="na")
    assert r["item"]["vatSet"] is True and r["item"]["vatRateUsed"] == "na"
    assert r["item"]["vatAmount"] == 0


def test_a_zero_percent_company_default_is_recorded_not_blanked(api, tokens):
    """`x or ""` blanks a 0, and 0% is a real answer — an export-processing-zone customer. Blanked,
    it falls through to whatever else is set and taxes an export."""
    st, r = _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=0,
                  vatBase=vat.BASE_CERTIFIED, retentionTaxPoint="at_release",
                  advanceTaxPoint="on_receipt")
    assert st == 200 and r["complete"] is True
    _, again = api("GET", "/api/sales/vat-settings", tokens["management"])
    assert str(again["rate"]) == "0"
    c = _live(api, tokens)
    _, cl = _claim(api, tokens, c)
    assert cl["item"]["vatSet"] is True and cl["item"]["vatAmount"] == 0


def test_a_nonsense_rate_on_a_claim_is_refused(api, tokens):
    c = _live(api, tokens)
    assert _claim(api, tokens, c, vatRate=12)[0] == 400
    assert _claim(api, tokens, c, vatBase="sideways")[0] == 400


def test_certifying_recomputes_the_tax_against_what_was_actually_certified(api, tokens):
    """The draft's figures are a preview. What is certified is what is taxed."""
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens)
    a = _claim(api, tokens, c)[1]["item"]
    st, r = _post(api, tokens["management"], "/api/sales/application", action="certify", id=a["id"])
    assert st == 200, r
    assert r["item"]["vatAmount"] == 20_000_000 and r["item"]["grossPayable"] == 150_000_000


def test_the_portal_still_cannot_issue_the_invoice(api, tokens):
    """Recording a VAT figure and issuing a hoá đơn GTGT are different acts, and only one of them
    is this portal's to perform."""
    _post(api, tokens["management"], "/api/sales/vat-settings", vatRate=10,
          vatBase=vat.BASE_CERTIFIED)
    c = _live(api, tokens)
    a = _claim(api, tokens, c)[1]["item"]
    _post(api, tokens["management"], "/api/sales/application", action="certify", id=a["id"])
    st, r = _post(api, tokens["staff"], "/api/sales/einvoice", id=a["id"], einvSerial="C26TAA",
                  einvNo="0001")
    assert st == 200 and r["verified"] is False, "a typed number is still UNVERIFIED"
