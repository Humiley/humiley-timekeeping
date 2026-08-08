"""Pure, leaf-level utilities extracted from app.py — stdlib-only, with NO app/db dependency, so the
   import is strictly one-way (app.py -> tkutil, never back). This is the first, behavior-preserving
   step of modularising the monolith; correctness is guarded by the existing test suite. Add only
   functions here that depend on nothing in app.py (else you create a circular import)."""
import re
import unicodedata
from datetime import datetime, timedelta


def _money_vnd(v):
    try:
        return "{:,.0f} ₫".format(float(str(v).replace(",", "").replace(" ", "").replace("₫", "")))
    except Exception:
        return str(v or "")


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")   # `datetime` is the class (from datetime import datetime)


def _vn_fold(s):
    """Fold Vietnamese diacritics for classification (đ->d, drop accents) so 'HĐĐT'/'Hóa đơn' all match."""
    return "".join(ch for ch in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(ch) != "Mn").replace("đ", "d")


def _iso_minus(iso, minutes):
    """Subtract minutes from an ISO instant (for a safe overlap window). Best-effort; returns input on failure."""
    try:
        return (datetime.strptime((iso or "").split(".")[0].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return iso


def _einv_num(x):
    """Parse a money value tolerant of VN/EN grouping+decimal conventions. TT78 XML uses plain integers."""
    s = re.sub(r"[^0-9,.\-]", "", str(x if x is not None else "")).strip()
    if not s:
        return 0.0
    neg = s.startswith("-")
    s = s.lstrip("-")
    last = max(s.rfind(","), s.rfind("."))
    frac = len(s) - last - 1
    if last != -1 and 1 <= frac <= 2:              # last separator with 1-2 trailing digits = decimal
        s = s[:last].replace(",", "").replace(".", "") + "." + s[last + 1:]
    else:                                          # all separators are thousands-grouping
        s = s.replace(",", "").replace(".", "")
    try:
        v = float(s or 0)
    except ValueError:
        return 0.0
    return -v if neg else v


def _einv_xml_num(x):
    """Parse a numeric value from e-invoice XML, where dot is the DECIMAL point (xs:decimal — issuers
       like MISA use fixed 6 places, e.g. '2736000.000000' / '23.790000'). The display-format parser
       _einv_num would wrongly read those dots as thousands separators. Falls back to dot-as-thousands
       when a plain float() fails (a rare issuer that writes '2.736.000' in the XML)."""
    s = re.sub(r"[^0-9,.\-]", "", str(x if x is not None else "")).strip()
    if not s:
        return 0.0
    neg = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:                      # both -> VN display 1.234.567,89 (dot thousands, comma decimal)
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                                 # comma as the decimal mark
        s = s.replace(",", ".")
    try:
        v = float(s)                               # only dots (or none) -> standard xs:decimal
    except ValueError:
        try:
            v = float(s.replace(".", ""))          # multiple dots were thousands grouping
        except ValueError:
            return 0.0
    return -v if neg else v


def _appr_state_of(status):
    s = str(status or "").strip().lower()
    if s in ("reviewed", "pending approval"):
        return "review"
    if s == "approved":
        return "approved"
    if s == "paid":
        return "paid"
    if s == "rejected":
        return "rejected"
    return "submit"


def _appr_epoch(v):
    """Best-effort epoch (UTC) from an ISO timestamp or a 'YYYY-MM-DD' date string. None if unparseable."""
    if not v:
        return None
    s = str(v).strip()
    for parse in (lambda x: datetime.strptime(x.replace("T", " ").replace("Z", "").split(".")[0][:19], "%Y-%m-%d %H:%M:%S"),
                  lambda x: datetime.strptime(x[:10], "%Y-%m-%d")):
        try:
            return (parse(s) - datetime(1970, 1, 1)).total_seconds()
        except Exception:
            pass
    return None


def _claim_items(c):
    """Port of the frontend _claimItems: a claim's line items, or one synthetic legacy line."""
    its = c.get("items") if isinstance(c, dict) else None
    if isinstance(its, list) and its:
        return its
    return [{"status": (c.get("status") if isinstance(c, dict) else None) or "Submitted"}]


def _claim_rollup(c):
    """Port of the frontend _claimRollup — MUST match it so the My Space 'pending' count agrees with
    what the user sees. Aggregates per-line item statuses into one claim status."""
    its = _claim_items(c)
    if not its:
        return (c.get("status") if isinstance(c, dict) else None) or "Submitted"
    ss = [(it.get("status") or "Submitted") for it in its]
    if any(s == "Submitted" for s in ss):
        return "Partially approved" if any(s in ("Approved", "Rejected", "Reviewed") for s in ss) else "Submitted"
    if all(s == "Reviewed" for s in ss):
        return "Reviewed"
    if all(s == "Approved" for s in ss):
        return "Approved"
    if all(s == "Rejected" for s in ss):
        return "Rejected"
    if any(s == "Reviewed" for s in ss):
        return "Reviewed"
    return "Partially approved"
