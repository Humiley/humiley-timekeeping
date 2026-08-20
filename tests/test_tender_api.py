"""The tender endpoint: which engine runs, who may see a margin, and what reaches the customer.

The arithmetic is tested in `test_tender`. What matters here is the boundary — a tender states what
a job costs and what margin is being taken, which is the most commercially sensitive record the
company holds — and the one thing that must never be wrong: the customer's copy of the document
carries no cost and no mark-up.
"""
import db


def _trading(tid="TND-TR"):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": "EST-2026-100", "quoteNo": "QT-2026-100", "title": "Pump package",
        "costingType": "trading", "status": "Draft",
        "client": "ABC Manufacturing Co., Ltd.", "clientTaxCode": "0123456789",
        "clientAddress": "Lot A1, VSIP II-A, Binh Duong", "clientAttn": "Mr. Nguyen Van A",
        "issueDate": "2026-08-20", "validUntil": "2026-09-19"})
    db.put_collection_item("est_landed", {
        "id": tid + "-i1", "estId": tid, "itemCode": "IMP-001", "hsCode": "8413.70",
        "desc": "Industrial Centrifugal Pump 50HP", "unit": "PCS", "qty": 2, "exwUnit": 8500,
        "currency": "USD", "origin": "Germany", "supplier": "KSB GmbH",
        "coForm": "Form EUR.1 (EVFTA)", "ftaDutyPct": 0, "mfnDutyPct": 20})
    db.put_collection_item("est_local", {
        "id": tid + "-l1", "estId": tid, "itemCode": "LOC-001", "desc": "Steel frame",
        "unit": "SET", "qty": 1, "unitPrice": 95000000, "vatPct": 8,
        "transPct": 5, "handlingPct": 1})
    return tid


def _epc(tid="TND-EPC"):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": "EST-2026-200", "quoteNo": "QT-2026-200",
        "title": "EU-GMP manufactory", "costingType": "epc", "status": "Draft",
        "client": "Client Pharma", "clientTaxCode": "9999", "issueDate": "2026-08-20",
        "validUntil": "2026-10-20"})
    for i, (centre, qty, cost) in enumerate([("CIV", 1000, 100), ("CLR", 500, 200),
                                             ("OSD", 2, 150000), ("SVP", 1, 90000)]):
        db.put_collection_item("est_bom", {
            "id": "%s-b%d" % (tid, i), "estId": tid, "costCentre": centre,
            "code": "X-%03d" % i, "descEn": "Item %d" % i, "unit": "set",
            "qty": qty, "unitCostUsd": cost})
    return tid


# ── the boundary ─────────────────────────────────────────────────────────────────────────────────

def test_staff_cannot_read_a_tender_summary(api, tokens):
    tid = _trading("TND-ACL")
    st, r = api("GET", "/api/tender/summary?id=" + tid, tokens["staff"])
    assert st == 403
    assert "manager" in (r.get("error") or "").lower()


def test_staff_cannot_reach_the_costing_lines_through_the_collection_route_either(api, tokens):
    _trading("TND-ACL2")
    for coll in ("est_landed", "est_local", "est_bom", "est_quote"):
        st, _ = api("GET", "/api/coll/" + coll, tokens["staff"])
        assert st == 403, coll


def test_a_missing_tender_is_a_404(api, tokens):
    st, _ = api("GET", "/api/tender/summary?id=ghost", tokens["admin"])
    assert st == 404


# ── which engine runs ────────────────────────────────────────────────────────────────────────────

def test_a_trading_tender_is_priced_by_the_customs_chain(api, tokens):
    tid = _trading()
    st, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert st == 200
    assert r["costingType"] == "trading"
    assert "master" in r and "rollup" not in r
    assert len(r["master"]["rows"]) == 2
    imp = [x for x in r["master"]["rows"] if x["source"] == "import"][0]
    # 2 x 8500 EXW, 6.8% of legs -> CIF, EVFTA certificate so 0% duty not the 20% MFN.
    assert imp["cifFx"] == 18156
    assert imp["dutyRate"] == 0 and "FTA" in imp["dutyBasis"]
    assert imp["vatRecoverable"] > 0
    assert imp["landed"] < imp["cif"] + imp["vatRecoverable"]     # VAT is not in the cost


def test_an_epc_tender_is_priced_by_cost_centre(api, tokens):
    tid = _epc()
    st, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert st == 200
    assert r["costingType"] == "epc"
    assert "rollup" in r and "master" not in r
    assert [c["costCentre"] for c in r["rollup"]["centres"]] == ["CIV", "CLR", "OSD", "SVP"]
    assert r["quote"]["lineCount"] == 4


def test_the_costing_type_comes_from_the_tender_not_from_the_caller(api, tokens):
    """Two people reading the same tender must not be able to read it two ways."""
    tid = _trading("TND-TYPE")
    st, r = api("GET", "/api/tender/summary?id=" + tid + "&costingType=epc", tokens["admin"])
    assert r["costingType"] == "trading"


# ── the configurator ─────────────────────────────────────────────────────────────────────────────

def test_switching_a_production_line_off_removes_it_from_the_quotation(api, tokens):
    tid = _epc("TND-CFG")
    _, before = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    e = next(x for x in db.list_collection("est_projects") if x["id"] == tid)
    e["bomConfig"] = {"OSD": {"include": False}}
    db.put_collection_item("est_projects", e)
    _, after = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert "OSD" not in [c["costCentre"] for c in after["rollup"]["centres"]]
    assert after["rollup"]["excludedCentres"] == ["OSD"]
    assert after["quote"]["net"] < before["quote"]["net"]
    # And absent from the customer's document, not present as a zero.
    assert "OSD" not in [l["itemCode"] for l in after["document"]["lines"]]


def test_capacity_scale_reprices_a_line_without_touching_its_unit_price(api, tokens):
    tid = _epc("TND-SCALE")
    e = next(x for x in db.list_collection("est_projects") if x["id"] == tid)
    e["bomConfig"] = {"OSD": {"scale": 0.5}}
    db.put_collection_item("est_projects", e)
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    osd = [l for l in r["rollup"]["lines"] if l["costCentre"] == "OSD"][0]
    assert osd["qty"] == 1 and osd["unitCostUsd"] == 150000


# ── assumptions ──────────────────────────────────────────────────────────────────────────────────

def test_the_assumption_sheet_comes_back_with_its_groups_so_the_ui_need_not_restate_them(api, tokens):
    tid = _trading("TND-ASSUMP")
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    groups = {s["group"] for s in r["assumptionSpec"]}
    assert {"FX", "EXW to CIF", "Local charges", "Tax", "Pricing", "Opex"} <= groups
    assert r["assumptions"]["fxUsd"] == 25500


def test_changing_the_fx_rate_reprices_every_imported_line(api, tokens):
    tid = _trading("TND-FX")
    _, before = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    e = next(x for x in db.list_collection("est_projects") if x["id"] == tid)
    e["assump"] = {"fxUsd": 27000}
    db.put_collection_item("est_projects", e)
    _, after = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert after["master"]["importTotal"] > before["master"]["importTotal"]
    assert after["master"]["localTotal"] == before["master"]["localTotal"]   # local is already dong


# ── the quotation, the P&L, and the gate ─────────────────────────────────────────────────────────

def test_the_quotation_prices_the_cost_master_and_the_pnl_runs_off_it(api, tokens):
    tid = _trading("TND-QT")
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    q, p = r["quote"], r["pnl"]
    assert q["gross"] == q["net"] + q["vat"]
    assert p["revenue"] == q["net"]
    assert p["netProfit"] == p["ebit"] + p["cit"]
    assert 0 < q["grossMarginPct"] < 100


def test_the_customers_document_carries_no_cost_and_no_markup(api, tokens):
    """The single most expensive thing that can leave this endpoint."""
    tid = _trading("TND-DOC")
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    doc = r["document"]
    assert doc["lines"]
    for line in doc["lines"]:
        assert "unitCost" not in line and "cogs" not in line and "markupPct" not in line
    assert doc["totals"]["net"] == r["quote"]["net"]
    assert doc["client"]["taxCode"] == "0123456789"
    assert len(doc["terms"]) >= 9
    assert [s["role"] for s in doc["signatures"]] == ["Prepared by", "Approved by", "Customer acceptance"]


def test_a_tender_missing_its_validity_date_cannot_be_issued_and_says_which_field(api, tokens):
    tid = _trading("TND-GATE")
    e = next(x for x in db.list_collection("est_projects") if x["id"] == tid)
    e["validUntil"] = ""
    db.put_collection_item("est_projects", e)
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert r["issue"]["canIssue"] is False
    assert "Valid until" in r["issue"]["missing"]


def test_a_thin_margin_warns_but_does_not_block(api, tokens):
    tid = _trading("TND-THIN")
    e = next(x for x in db.list_collection("est_projects") if x["id"] == tid)
    e["assump"] = {"markupPct": 2}
    db.put_collection_item("est_projects", e)
    _, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert r["issue"]["canIssue"] is True
    assert any("margin" in w.lower() for w in r["issue"]["warnings"])


def test_a_line_can_be_excluded_or_repriced_from_the_quotation_without_touching_the_costing(api, tokens):
    tid = _trading("TND-OV")
    _, before = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    db.put_collection_item("est_quote", {"id": tid + "-o1", "estId": tid,
                                         "srcId": tid + "-l1", "exclude": True})
    _, after = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert after["quote"]["lineCount"] == before["quote"]["lineCount"] - 1
    # The costing still holds both lines — only the customer's quotation dropped one.
    assert len(after["master"]["rows"]) == len(before["master"]["rows"])
