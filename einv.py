"""Vietnamese e-invoice (TT78) parsing — XML / ZIP / PDF-text extractors, pulled out of app.py.
   A pure leaf module: depends only on stdlib + tkutil (one-way import; app.py -> einv -> tkutil).
   The impure orchestrator _einv_from_pdf (which calls invtrack helpers) stays in app.py and imports these."""
import xml.etree.ElementTree as ET
import re
import zipfile
import io
from tkutil import _einv_num, _einv_xml_num, _vn_fold


_EINV_MAX_BYTES = 4 * 1024 * 1024          # hard cap on any single untrusted attachment we parse


_PDF_ITEM_RE = re.compile(
    r"^(\d{1,3})\s+(.+?)\s+(\d[\d.,]*)\s+([\d.,]{3,})\s+([\d.,]{3,})\s+(\d{1,2})\s*%\s+([\d.,]{1,})\s+([\d.,]{3,})$")


_PDF_UNIT_RE = re.compile(r"(Su[ấa]t/ph[ầa]n|C[ốo]c/ly|Chai|C[áa]i|B[ộo]|L[ầa]n|Kg|Lon|H[ộo]p|Th[ùu]ng|Ph[ầa]n|T[úu]i|G[óo]i|M[ée]t|B[ìi]nh|Su[ấa]t|Chi[ếe]c|Đôi|Bao|Can)\s*$")


def _einv_safe_xml(xml_bytes):
    """Reject untrusted XML that could be an entity-expansion (billion-laughs) bomb before parsing."""
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8", "ignore")
    if not xml_bytes or len(xml_bytes) > _EINV_MAX_BYTES:
        return None
    low = xml_bytes.lower()   # scan the FULL (already <=4MB-capped) content — a padded prolog comment must not hide a DOCTYPE
    flat = low.replace(b"\x00", b"")   # defeat UTF-16/UTF-32 XML: expat auto-detects them, but the DOCTYPE bytes are null-interleaved
    if b"<!doctype" in low or b"<!entity" in low or b"<!doctype" in flat or b"<!entity" in flat:   # TT78 e-invoices never carry a DTD/entities
        return None
    return xml_bytes


def _zip_read_bounded(z, zi, limit):
    """Read a ZIP member with a HARD decompressed-size cap — NEVER trust zi.file_size (attacker-controlled
       central-directory metadata). Bounds the decompression itself, so a bomb member can't blow up memory.
       Returns the bytes, or None if the member exceeds the cap or fails to read."""
    try:
        with z.open(zi) as fh:
            data = fh.read(limit + 1)
        return None if len(data) > limit else data
    except Exception:
        return None


def _einv_parse_xml(xml_bytes):
    """Vietnamese TT78 e-invoice XML -> structured dict, or None. Namespace-agnostic + bomb-guarded."""
    xml_bytes = _einv_safe_xml(xml_bytes)
    if xml_bytes is None:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None

    def _local(tag):
        return tag.rsplit("}", 1)[-1]

    def first(name):
        for el in root.iter():
            if _local(el.tag) == name:
                return (el.text or "").strip()
        return ""

    def under(parent, child):
        for p in root.iter():
            if _local(p.tag) == parent:
                for c in p.iter():
                    if _local(c.tag) == child:
                        return (c.text or "").strip()
        return ""

    serial = first("KHHDon")
    inv_no = first("SHDon")
    date_raw = first("NLap")
    seller = under("NBan", "Ten")
    seller_mst = under("NBan", "MST")
    buyer_mst = under("NMua", "MST")
    lookup = ""
    for tt in root.iter():
        if _local(tt.tag) != "TTin":
            continue
        lab = val = ""
        for ch in tt:
            if _local(ch.tag) == "TTruong":
                lab = ch.text or ""
            elif _local(ch.tag) == "DLieu":
                val = ch.text or ""
        if "tra cuu" in _vn_fold(lab):
            lookup = (val or "").strip() or lookup
    if not (serial or inv_no or seller):
        return None
    iso = date_raw[:10] if (len(date_raw) >= 10 and date_raw[4:5] == "-") else ""
    # Richer party + document detail (so the tracking row carries EVERYTHING on the invoice).
    buyer_name = under("NMua", "Ten")
    seller_addr = under("NBan", "DChi")
    buyer_addr = under("NMua", "DChi")
    currency = first("DVTTe")
    pay_method = first("HTTToan") or first("HTThuc")     # payment-method label varies by issuer
    # Line items: every <HHDVu> under the goods/services list — the heart of "all information".
    items = []
    for el in root.iter():
        if _local(el.tag) != "HHDVu":
            continue
        cell = {}
        for c in el:
            cell[_local(c.tag)] = (c.text or "").strip()
        name = cell.get("THHDVu") or cell.get("TChat") or ""
        if not name and not cell.get("ThTien"):          # a pure discount/placeholder line
            continue
        items.append({"no": cell.get("STT") or cell.get("STHang") or str(len(items) + 1),
                      "name": name, "unit": cell.get("DVTinh", ""),
                      "qty": _einv_xml_num(cell.get("SLuong", "")), "price": _einv_xml_num(cell.get("DGia", "")),
                      "amount": _einv_xml_num(cell.get("ThTien", "")), "taxRate": cell.get("TSuat", "")})
        if len(items) >= 200:
            break
    vat_rate = ""
    for it in items:
        if it.get("taxRate"):
            vat_rate = it["taxRate"]
            break
    if not vat_rate:
        vat_rate = first("TSuat")
    return {"serial": serial, "invNo": inv_no, "dateISO": iso, "dateRaw": date_raw,
            "supplier": seller, "taxCode": seller_mst, "buyerMST": buyer_mst,
            "buyerName": buyer_name, "sellerAddr": seller_addr, "buyerAddr": buyer_addr,
            "currency": currency, "payMethod": pay_method, "vatRate": vat_rate, "items": items,
            "before": _einv_xml_num(first("TgTCThue")), "vat": _einv_xml_num(first("TgTThue")),
            "after": _einv_xml_num(first("TgTTTBSo")), "lookupCode": lookup,
            "docType": first("THDon"), "method": "xml"}


def _einv_from_zip(zip_bytes):
    """Unpack a ZIP e-invoice + parse the XML inside. Guards against zip decompression bombs."""
    if not zip_bytes or len(zip_bytes) > 8 * 1024 * 1024:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception:
        return None
    checked = 0
    for zi in z.infolist():
        if not zi.filename.lower().endswith(".xml"):
            continue
        checked += 1
        if checked > 20:
            break
        raw = _zip_read_bounded(z, zi, _EINV_MAX_BYTES)   # bounded read — do NOT trust zi.file_size (bomb defence)
        if raw is None:
            continue
        try:
            r = _einv_parse_xml(raw)
        except Exception:
            r = None
        if r:
            r["method"] = "zip-xml"
            return r
    return None


def _einv_all_from_zip(zip_bytes):
    """Parse EVERY e-invoice XML inside a ZIP — a single ZIP can bundle many invoices. Zip-bomb guarded."""
    out = []
    if not zip_bytes or len(zip_bytes) > 8 * 1024 * 1024:
        return out
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception:
        return out
    checked = 0
    total = 0
    for zi in z.infolist():
        if not zi.filename.lower().endswith(".xml"):
            continue
        checked += 1
        if checked > 40:
            break
        raw = _zip_read_bounded(z, zi, _EINV_MAX_BYTES)     # bounded read — do NOT trust zi.file_size (bomb defence)
        if raw is None:
            continue
        total += len(raw)
        if total > 24 * 1024 * 1024:                        # cap total decompressed bytes across the whole archive
            break
        try:
            r = _einv_parse_xml(raw)
        except Exception:
            r = None
        if r:
            r["method"] = "zip-xml"
            out.append(r)
    return out


def _inv_ident(ex):
    """Canonical identity of a parsed invoice = invoice-no (+ seller-MST when present). Used to key each
       distinct invoice's row; the invoice number is unique per seller, so the XML and PDF of the SAME
       invoice share it even if the PDF's serial is formatted differently or its MST wasn't extracted."""
    if not ex:
        return None
    n = str(ex.get("invNo") or "").strip()
    if not n:
        return None
    t = str(ex.get("taxCode") or "").split("-")[0].strip()
    return (n, t)


def _inv_ident_str(ex):
    """A short string form of the identity — gives each invoice from the same email a DISTINCT stable row key."""
    ident = _inv_ident(ex)
    if ident:
        return "|".join(x for x in ident if x)
    return (str(ex.get("serial") or "") + "|" + str(int(float(ex.get("after") or 0)))) or "x"


def _einv_parse_text(text):
    """Best-effort structured fields from OCR/PDF text (Vietnamese invoice labels)."""
    if not text:
        return None
    def grab(rx):
        m = re.search(rx, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""
    def numv(rx):
        return _einv_num(grab(rx))
    inv_no = grab(r"(?:Số HĐ|Số hóa đơn|Invoice No\.?)\s*[:.]?\s*([0-9]{1,10})")
    after = numv(r"(?:Tổng tiền thanh toán|Total payment|Tổng thanh toán)\s*[:.]?\s*([0-9.,]{4,})")
    if not inv_no and not after:
        return None
    return {"invNo": inv_no, "serial": grab(r"(?:Ký hiệu|Serial)\s*[:.]?\s*([0-9A-Z]{5,8})"),
            "taxCode": grab(r"(?:Mã số thuế|MST)\s*[:.]?\s*([0-9]{10}(?:-[0-9]{3})?)"),
            "vat": numv(r"(?:Tiền thuế GTGT|Thuế GTGT)\s*[:.]?\s*([0-9.,]{3,})"),
            "before": numv(r"(?:Cộng tiền hàng|Tiền hàng)\s*[:.]?\s*([0-9.,]{4,})"),
            "after": after, "method": "ocr"}


def _pdf_engine_ok():
    """True if the server can read PDF text (pypdf installed) — used to diagnose 'amounts not filling'."""
    try:
        import pypdf  # noqa: F401
        return True
    except Exception:
        return False


def _einv_pdf_items(text):
    """Best-effort line items from a Bkav-style e-invoice PDF text layer. Each row ends with the regular
       numeric tail <qty> <unitPrice> <amountBeforeTax> <rate>% <taxAmount> <lineTotal>; the name+unit
       precede it (the unit often wraps to the next line, so we un-wrap first). Same shape as XML items."""
    if not text:
        return []
    joined = re.sub(r"([^\W\d_])[ \t]*\n[ \t]*(?=[^\W\d_])", r"\1", text, flags=re.UNICODE)   # heal a mid-word wrap ('phầ'+'n')
    out = []
    for ln in joined.split("\n"):                    # match PER LINE so a stray number can't span rows
        ln = re.sub(r"\s{2,}", " ", ln.strip())
        m = _PDF_ITEM_RE.match(ln)
        if not m:
            continue
        qty = _einv_num(m.group(3))
        total = _einv_num(m.group(8))
        if not (qty and total):
            continue
        name = (m.group(2) or "").strip()
        unit = ""
        um = _PDF_UNIT_RE.search(name)
        if um:
            unit = um.group(1)
            name = name[:um.start()].strip()
        if not name or len(name) > 160:
            continue
        out.append({"no": m.group(1), "name": name, "unit": unit,
                    "qty": qty, "price": _einv_num(m.group(4)), "amount": total, "taxRate": m.group(6) + "%"})
        if len(out) >= 200:
            break
    return out
