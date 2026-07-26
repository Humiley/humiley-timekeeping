"""Multi-invoice-per-email capture: an email (or a single ZIP) can carry several DISTINCT invoices.

Pins that (a) a ZIP with N invoice XMLs yields N invoices, (b) the SAME invoice delivered as both XML
and PDF collapses to ONE row (no double-count) — even when the PDF parse misses the seller-MST, and
(c) two DIFFERENT invoices stay as two rows with their totals preserved. This is the fix for
"still not getting all file invoices and total value" (was: only the first attachment parsed).
"""
import io
import zipfile
import app


def _xml(serial, invno, mst, before, vat, after):
    return (
        "<HDon><DLHDon><TTChung>"
        "<KHHDon>" + serial + "</KHHDon><SHDon>" + invno + "</SHDon><NLap>2026-06-15</NLap>"
        "</TTChung><NDHDon>"
        "<NBan><Ten>Cong ty " + invno + "</Ten><MST>" + mst + "</MST></NBan>"
        "<NMua><MST>0318835868</MST></NMua>"
        "<TToan><TgTCThue>" + before + "</TgTCThue><TgTThue>" + vat + "</TgTThue>"
        "<TgTTTBSo>" + after + "</TgTTTBSo></TToan>"
        "</NDHDon></DLHDon></HDon>"
    ).encode("utf-8")


def test_zip_yields_every_invoice():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.xml", _xml("1C26TAA", "111", "0311111111", "1000000", "100000", "1100000"))
        z.writestr("b.xml", _xml("1C26TAA", "222", "0311111111", "2000000", "200000", "2200000"))
        z.writestr("c.xml", _xml("1C26TBB", "333", "0322222222", "3000000", "300000", "3300000"))
    invs = app._einv_all_from_zip(buf.getvalue())
    assert len(invs) == 3, "a ZIP of 3 invoices must yield 3 (was: 1)"
    assert {i["invNo"] for i in invs} == {"111", "222", "333"}
    assert sum(i["after"] for i in invs) == 6600000   # all totals captured
    # legacy first-only helper is unchanged (still used elsewhere)
    assert app._einv_from_zip(buf.getvalue())["invNo"] == "111"


def test_same_invoice_xml_and_pdf_collapse_no_double_count():
    xml_inv = {"invNo": "500", "serial": "1C26TAA", "taxCode": "0311111111", "before": 1000000, "vat": 100000, "after": 1100000, "method": "xml"}
    pdf_inv = {"invNo": "500", "serial": "C26TAA", "taxCode": "", "after": 1100000, "method": "pdf"}  # PDF: diff serial, no MST
    out = app._invtrack_dedupe_invoices([(xml_inv, {"id": "fx", "name": "hd.xml"}), (pdf_inv, {"id": "fp", "name": "hd.pdf"})])
    assert len(out) == 1, "same invoice as XML+PDF must be ONE row, not two"
    assert out[0]["after"] == 1100000                 # counted once
    assert {f["id"] for f in out[0]["_files"]} == {"fx", "fp"}, "both files kept on the one row"


def test_two_distinct_invoices_stay_two_rows():
    a = {"invNo": "600", "serial": "1C26TAA", "taxCode": "0311111111", "after": 1100000}
    b = {"invNo": "601", "serial": "1C26TAA", "taxCode": "0311111111", "after": 2200000}
    out = app._invtrack_dedupe_invoices([(a, {"id": "f1"}), (b, {"id": "f2"})])
    assert len(out) == 2
    assert sum(i["after"] for i in out) == 3300000    # both totals


def test_distinct_invoices_survive_collapse():
    # rows from ONE email share the same tra-cuu code/desc; the collapse must NOT fold different invoice-nos
    rows = [
        {"msgId": "m1", "invNo": "700", "taxCode": "0311111111", "dateISO": "2026-06-15", "desc": "Hoa don thang 6", "after": 1100000, "lookup": "  https://x?code=ABC123"},
        {"msgId": "m1::701|0311111111", "invNo": "701", "taxCode": "0311111111", "dateISO": "2026-06-15", "desc": "Hoa don thang 6", "after": 2200000, "lookup": "  https://x?code=ABC123"},
    ]
    collapsed = app._invtrack_collapse(rows)
    assert len(collapsed) == 2, "two different invoice-nos must not collapse even sharing a lookup code/desc"
    assert sum(r["after"] for r in collapsed) == 3300000


def test_multi_invoice_sync_e2e_idempotent(monkeypatch, base_url):
    """Full app-only sync path (Graph mocked): a single email with a 2-invoice ZIP → 2 register rows with
       both totals; a second sync does NOT duplicate them (msgId + content dedup + _multiScanned bound)."""
    import base64
    import db
    app.INVTRACK["mailbox"] = "hd@humiley.com"
    monkeypatch.setattr(app, "_invtrack_app_ready", lambda: True)
    monkeypatch.setattr(app, "_graph_app_token", lambda: "tok")
    monkeypatch.setattr(app, "_invtrack_store_file", lambda raw, name, ct: {"id": "zf", "name": name or "x.zip", "kind": "zip"})
    monkeypatch.setattr(app, "_invtrack_sp_upload", lambda *a, **k: None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.xml", _xml("1C26TAA", "8111", "0388111111", "1000000", "100000", "1100000"))
        z.writestr("b.xml", _xml("1C26TAA", "8222", "0388111111", "2000000", "200000", "2200000"))
    zipb = buf.getvalue()
    msg = {"id": "AAMkMULTI", "internetMessageId": "<multi@x>", "subject": "Hoa don ZIP",
           "from": {"emailAddress": {"address": "seller@ncc.vn", "name": "NCC"}},
           "receivedDateTime": "2026-06-15T09:00:00Z", "hasAttachments": True, "body": {"content": ""}, "bodyPreview": ""}
    att = {"value": [{"name": "invoices.zip", "contentType": "application/zip", "contentBytes": base64.b64encode(zipb).decode()}]}
    monkeypatch.setattr(app, "_graph_get", lambda url, tok: (att if "/attachments" in url else {"value": [msg]}))

    def rows():
        return [i for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)
                for i in d["items"] if i.get("invNo") in ("8111", "8222")]

    r1 = app._invtrack_sync("manual")
    assert r1.get("ok"), r1
    assert len(rows()) == 2, "both invoices in the one ZIP became rows"
    assert sum(i.get("after") or 0 for i in rows()) == 3300000, "both totals captured"

    app._invtrack_sync("manual")   # re-sync
    assert len(rows()) == 2, "re-sync must not duplicate the multi-invoice rows"
    assert sum(i.get("after") or 0 for i in rows()) == 3300000


def _xml_full(invno, mst, with_items=True):
    items = ""
    if with_items:
        items = (
            "<DSHHDVu>"
            "<HHDVu><STT>1</STT><THHDVu>May quat</THHDVu><DVTinh>Cai</DVTinh><SLuong>2</SLuong>"
            "<DGia>1000000</DGia><TSuat>10%</TSuat><ThTien>2000000</ThTien></HHDVu>"
            "<HHDVu><STT>2</STT><THHDVu>Lap dat</THHDVu><DVTinh>Lan</DVTinh><SLuong>1</SLuong>"
            "<DGia>500000</DGia><TSuat>10%</TSuat><ThTien>500000</ThTien></HHDVu>"
            "</DSHHDVu>")
    return (
        "<HDon><DLHDon><TTChung>"
        "<KHHDon>1C26TAA</KHHDon><SHDon>" + invno + "</SHDon><NLap>2026-06-15</NLap>"
        "<DVTTe>VND</DVTTe><HTTToan>Chuyen khoan</HTTToan></TTChung><NDHDon>"
        "<NBan><Ten>Cong ty " + invno + "</Ten><MST>" + mst + "</MST><DChi>12 Le Loi, Q1, HCM</DChi></NBan>"
        "<NMua><Ten>Humiley Co</Ten><MST>0318835868</MST><DChi>KCN Long Duc, Dong Nai</DChi></NMua>"
        + items +
        "<TToan><TgTCThue>2500000</TgTCThue><TgTThue>250000</TgTThue><TgTTTBSo>2750000</TgTTTBSo></TToan>"
        "</NDHDon></DLHDon></HDon>"
    ).encode("utf-8")


def test_xml_captures_all_invoice_detail():
    r = app._einv_parse_xml(_xml_full("900", "0311111111"))
    assert r["buyerName"] == "Humiley Co" and r["buyerMST"] == "0318835868"
    assert r["sellerAddr"].startswith("12 Le Loi") and r["buyerAddr"].startswith("KCN Long Duc")
    assert r["currency"] == "VND" and r["payMethod"] == "Chuyen khoan" and r["vatRate"] == "10%"
    assert len(r["items"]) == 2
    assert r["items"][0]["name"] == "May quat" and r["items"][0]["amount"] == 2000000
    assert r["items"][0]["unit"] == "Cai" and r["items"][0]["qty"] == 2 and r["items"][0]["price"] == 1000000
    assert sum(it["amount"] for it in r["items"]) == 2500000   # matches TgTCThue


def test_row_carries_enriched_fields():
    ex = app._einv_parse_xml(_xml_full("901", "0311111111"))
    msg = {"id": "AAA", "internetMessageId": "<x@y>", "subject": "Hoa don",
           "from": {"emailAddress": {"address": "seller@ncc.vn", "name": "NCC"}},
           "receivedDateTime": "2026-06-15T09:00:00Z", "hasAttachments": True, "body": {"content": ""}}
    row = app._invtrack_item(msg, ex)
    assert row["buyerName"] == "Humiley Co" and row["buyerMST"] == "0318835868"
    assert row["currency"] == "VND" and row["payMethod"] == "Chuyen khoan" and row["vatRate"] == "10%"
    assert row["sellerAddr"] and row["buyerAddr"]
    assert len(row["items"]) == 2 and row["items"][1]["name"] == "Lap dat"


def test_dedupe_preserves_line_items_from_xml_when_pdf_has_none():
    xml_ex = app._einv_parse_xml(_xml_full("902", "0311111111", with_items=True))
    pdf_ex = {"invNo": "902", "serial": "C26TAA", "taxCode": "", "after": 2750000, "items": [], "method": "pdf"}
    out = app._invtrack_dedupe_invoices([(pdf_ex, {"id": "fp"}), (xml_ex, {"id": "fx"})])
    assert len(out) == 1, "same invoice XML+PDF collapse to one"
    assert len(out[0]["items"]) == 2, "line items from the XML survive the merge with the item-less PDF"
    assert out[0]["buyerName"] == "Humiley Co"


def test_pdf_line_item_parser_and_totals():
    # Bkav-style PDF text: item #1's unit wraps ('Suất/phầ' + 'n'); the total row lists all three sums.
    text = ("STT Ten hang hoa Don vi tinh So luong Don gia Tien chua thue Thue suat Tien thue Thanh tien\n"
            "1 Banh Bao xa xiu Suat/pha\n"
            "n 1 79.000 79.000 8% 6.320 85.320\n"
            "2 Nuoc Dasani 510ml Chai 1 29.000 29.000 8% 2.320 31.320\n"
            "Tong cong 108.000 8.640 116.640\n")
    items = app._einv_pdf_items(text)
    assert len(items) == 2, "both line items parsed (incl. the wrapped-unit first row)"
    assert items[0]["name"] == "Banh Bao xa xiu" and items[0]["unit"] == "Suat/phan"
    assert items[0]["amount"] == 85320 and items[0]["qty"] == 1 and items[0]["price"] == 79000
    assert items[1]["name"] == "Nuoc Dasani 510ml" and items[1]["unit"] == "Chai"
    assert sum(i["amount"] for i in items) == 116640   # == the total row's grand total


def test_body_fields_extracts_ehoadon_serial_invno_mtc():
    body = ("Kính gửi Quý khách. Ký hiệu: C26MME  Số hóa đơn: 00010039  "
            "Mã tra cứu: MVHSMPB954D  <a href='https://tchd.ehoadon.vn/TCHD?MTC=MVHSMPB954D'>Tra cứu</a>")
    bf = app._invtrack_body_fields(body)
    assert bf["serial"] == "C26MME"
    assert bf["code"] == "MVHSMPB954D"
    assert bf["invNo"] == "10039"


def test_ehoadon_fetch_guards_bad_input():
    # missing any of serial / invoice-no / code -> no network call, returns (None, None)
    assert app._invtrack_fetch_ehoadon("", "10039", "MVHSMPB954D") == (None, None)
    assert app._invtrack_fetch_ehoadon("C26MME", "", "MVHSMPB954D") == (None, None)
    assert app._invtrack_fetch_ehoadon("C26MME", "10039", "") == (None, None)


def test_xml_number_parser_handles_decimal_and_display():
    n = app._einv_xml_num
    assert n("2736000.000000") == 2736000       # MISA fixed 6-decimal (dot = decimal point)
    assert n("23.790000") == 23.79
    assert round(n("115006.310000"), 2) == 115006.31
    assert n("3009600") == 3009600
    assert n("2.736.000") == 2736000             # rare: dots as thousands in XML -> fallback
    assert n("1.234.567,89") == 1234567.89       # VN display 1.234.567,89
    assert n("") == 0.0


def test_misa_and_dispatch_guards():
    assert app._invtrack_fetch_misa("abc") == (None, None)      # code too short -> no network call
    assert app._invtrack_fetch_by_url("https://example.com/x", code="ABCDEF") == (None, None)  # unknown host


def test_attach_file_fills_row_and_attaches(base_url):
    import base64
    import db
    for d in list(db.list_collection("invtrack")):        # prod keeps ONE dataset doc; isolate from other tests
        if d.get("id"):
            db.delete_collection_item("invtrack", d["id"])
    db.put_collection_item("invtrack", {"kind": "invtrack-dataset", "meta": {}, "items": [
        {"msgId": "<att@x>", "desc": "Hoa don VNPT", "type": "Hoá đơn mua vào (NCC)", "after": 0}]})
    xml = _xml_full("7001", "0311111111")   # user 'downloaded' this from a CAPTCHA portal and uploads it
    r = app._invtrack_attach_file({"msgId": "<att@x>", "name": "hoadon.xml",
                                   "contentB64": base64.b64encode(xml).decode()})
    assert r["ok"] and r["parsed"], r
    rows = [i for d in db.list_collection("invtrack") if isinstance(d.get("items"), list)
            for i in d["items"] if i.get("msgId") == "<att@x>"]
    assert rows and rows[0]["invNo"] == "7001" and rows[0]["buyerName"] == "Humiley Co"
    assert len(rows[0].get("items") or []) == 2 and (rows[0].get("files") or [])
    assert rows[0]["after"] == 2750000 and not rows[0].get("needsLookup")


def test_attach_file_rejects_junk(base_url):
    import base64
    import db
    db.put_collection_item("invtrack", {"kind": "invtrack-dataset", "meta": {}, "items": [{"msgId": "<j@x>"}]})
    r = app._invtrack_attach_file({"msgId": "<j@x>", "name": "note.txt",
                                   "contentB64": base64.b64encode(b"just some text").decode()})
    assert not r["ok"]
