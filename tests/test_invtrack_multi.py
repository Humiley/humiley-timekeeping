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
