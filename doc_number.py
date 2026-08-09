"""Document numbers — the one thing every controlled document in this portal needs and none had.

A payment request, a quotation, a sales order, a delivery note, an invoice: each is a document that
leaves the building with a number on it, and a customer or an auditor refers to it by that number.
Two documents may never share one, and a number that has been printed may never be re-issued.

Neither held here before.

  · Payment requests numbered themselves IN THE BROWSER — `_payNextNo` took the highest `PR-YYYY-nnn`
    it could see and added one. `payments` is a SELF_OWNED collection, so a staff member's browser
    holds only their OWN requests: everybody's first request is PR-YYYY-001. Not a race that needs
    bad luck — a collision by construction, and nothing on the server checked.

  · The quotation reference was a HASH of the deal id: 'HML-QT-' + year + (1000 + h % 9000). Two
    consequences, both bad for a document a pharma client keeps on file. Re-quoting the same deal
    reproduces the same number, so a revised price silently reuses the reference of the old one and
    there is no v1/v2. And 9000 slots hashed means two unrelated deals can land on one number.

This module holds the format and the rules; db.next_doc_no does the atomic allocation. Splitting
them that way is deliberate: the shape of a number is a business decision that wants tests, and the
uniqueness of a number is a database property that wants a lock. Neither can enforce the other.

The format is PREFIX-YYYY-NNNN, zero-padded to at least the series width and never truncated — the
1000th document of a 3-wide series is 1000, not 000. Numbers reset each calendar year, which is what
Vietnamese practice and every ERP this is measured against do.

Pure — no database, no clock. Exercised by tests/test_doc_number.py.
"""
import re

# The document series. `coll` is the collection whose creates get this prefix; None means the series
# exists but nothing writes it automatically yet (the sell-side cycle fills these in).
SERIES = {
    "PR": {"name": "Payment request", "nameVn": "Đề nghị thanh toán", "coll": "payments", "width": 3},
    "QT": {"name": "Sales quotation", "nameVn": "Báo giá", "coll": None, "width": 4},
    "SO": {"name": "Sales order", "nameVn": "Đơn hàng bán", "coll": None, "width": 4},
    "DO": {"name": "Delivery note", "nameVn": "Phiếu giao hàng", "coll": None, "width": 4},
    "IN": {"name": "A/R invoice", "nameVn": "Hóa đơn bán hàng", "coll": None, "width": 4},
    "CN": {"name": "A/R credit memo", "nameVn": "Giấy báo có", "coll": None, "width": 4},
    "RC": {"name": "Incoming payment", "nameVn": "Phiếu thu", "coll": None, "width": 4},
}

# collection -> prefix, derived so the two can never disagree.
BY_COLL = {v["coll"]: k for k, v in SERIES.items() if v.get("coll")}

_RE = re.compile(r"^\s*([A-Z]{2,4})-(\d{4})-(\d+)\s*$")


def series_for(collection):
    """The prefix a collection's documents carry, or None if it is not a numbered document."""
    return BY_COLL.get(collection)


def width_of(prefix):
    return int((SERIES.get(prefix) or {}).get("width") or 3)


def format_no(prefix, year, n, width=None):
    """PR-2026-001. Padded to the series width, never truncated past it.

    Truncating would be the worst failure available: PR-2026-001 for both the 1st and the 1001st
    document is a collision that looks like a formatting choice.
    """
    w = int(width if width is not None else width_of(prefix))
    return "%s-%04d-%s" % (prefix, int(year), str(int(n)).zfill(max(1, w)))


def parse_no(s):
    """('PR', 2026, 1) from 'PR-2026-001', or None if it is not one of our numbers.

    Deliberately strict. A loose parser that accepted anything vaguely numeric would let a foreign
    reference seed the counter and skip the sequence forward by thousands.
    """
    m = _RE.match(str(s or ""))
    if not m:
        return None
    return {"prefix": m.group(1), "year": int(m.group(2)), "n": int(m.group(3))}


def highest(values, prefix, year):
    """The largest number already issued in this series and year, across whatever exists.

    This is how a live database is adopted without re-issuing a number somebody already holds: the
    counter starts above the highest number the data can show, not at 1.
    """
    top = 0
    for v in (values or ()):
        p = parse_no(v)
        if p and p["prefix"] == prefix and p["year"] == int(year):
            top = max(top, p["n"])
    return top


def numbers_in(items, field="reqNo"):
    """Pull the document numbers out of a collection's rows."""
    out = []
    for it in (items or ()):
        if isinstance(it, dict):
            v = it.get(field)
            if v:
                out.append(str(v))
    return out


def duplicates(values):
    """Numbers issued more than once. For the health check — a register that cannot see its own
    collisions is how they survive for years."""
    seen, dupes = {}, []
    for v in (values or ()):
        k = str(v or "").strip().upper()
        if not k:
            continue
        seen[k] = seen.get(k, 0) + 1
    for k, c in seen.items():
        if c > 1:
            dupes.append({"number": k, "count": c})
    return sorted(dupes, key=lambda d: (-d["count"], d["number"]))
