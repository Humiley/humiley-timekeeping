"""The variation (phụ lục) — the document the claim engine has been telling people to raise.

Two refusals in this codebase name it and, until now, neither had anywhere to send you:

    sales_contract.application: "Raise a variation first, or certify less."
    the contract terms endpoint:  "Raise a variation instead."

A contract that grows is not an exception on a fit-out job, it is most of them: an extra AHU, a
re-routed duct, a client-instructed change to the cleanroom classification. With no variation, the
only ways past the value ceiling were to certify less than was actually done, or to quietly edit the
contract — and the second one destroys the thing a contract is for, which is being able to say what
was agreed and when.

WHAT A VARIATION IS HERE
  · a delta on the contract value, and/or new priced lines appended to the bill of quantities
  · a document with its own number, its own status, and a signature — never an in-place edit
  · applied EXACTLY ONCE, and never re-applied by a retry or a double click

WHAT IT REFUSES
  · shrinking a contract below what has already been certified. That work is signed off; a
    variation cannot un-sign it. The instrument for taking value back off a certified claim is a
    credit note, and this says so by name rather than clamping to zero.
  · a variation that changes nothing — no value delta and no lines. An empty document in a contract
    file is worse than no document: somebody has to work out later whether it meant anything.
  · removing or repricing an EXISTING line. Lines already carry certified balances; editing one
    would move money that has been claimed against it. New scope arrives as new lines.

Pure — no database, no clock. Exercised by tests/test_sales_variation.py.
"""

import sales_doc

DRAFT = sales_doc.DRAFT
ISSUED = sales_doc.ISSUED
APPLIED = "applied"
REJECTED = "rejected"
CANCELLED = sales_doc.CANCELLED

# A variation is signed by the customer or it is a proposal. The shape mirrors the quotation's:
# draft while it is being written, issued once it has gone out, then one terminal outcome.
TRANSITIONS = {
    DRAFT: (ISSUED, CANCELLED),
    ISSUED: (APPLIED, REJECTED, CANCELLED),
    APPLIED: (),
    REJECTED: (),
    CANCELLED: (),
}

STATUS_LABELS = {
    DRAFT: ("Draft", "Nháp"),
    ISSUED: ("Issued", "Đã phát hành"),
    APPLIED: ("Applied", "Đã áp dụng"),
    REJECTED: ("Rejected", "Bị từ chối"),
    CANCELLED: ("Cancelled", "Đã hủy"),
}


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if n != n else n


def r2(v):
    return round(_num(v), 2)


def _vnd(n):
    return "₫{:,.0f}".format(round(_num(n)))


def lines_value(lines):
    """What the new lines on this variation are worth. Headings and notes are worth nothing.

    A line arrives here as raw typed input, so it may not carry a `kind` yet — and line_amount
    values only the kinds it recognises, so an un-kinded line would price at zero. new_line() treats
    a missing kind as an item; this has to agree with it, or the preview a person approves would
    read ₫0 and the applied lines would be worth ₫80,000,000.
    """
    return r2(sum(sales_doc.line_amount(dict(l, kind=(l or {}).get("kind") or sales_doc.ITEM))
                  for l in (lines or []) if l))


def effect(contract, variation):
    """What applying this variation would do to the contract — computed, never guessed.

    The value delta may be stated directly (`valueDelta`), or left to follow from the lines, or
    both: a variation that adds ₫80,000,000 of new work and also re-negotiates ₫20,000,000 off the
    original scope is one document, and both movements belong on it.
    """
    c, v = contract or {}, variation or {}
    old_value = r2(c.get("value"))
    certified = r2(c.get("certifiedToDate"))
    new_lines = [l for l in (v.get("lines") or []) if l]
    from_lines = lines_value(new_lines)
    stated = v.get("valueDelta")
    delta = r2(stated) if str(stated or "").strip() != "" else from_lines
    new_value = r2(old_value + delta)

    out = {
        "ok": True, "oldValue": old_value, "delta": delta, "newValue": new_value,
        "linesAdded": len(new_lines), "linesValue": from_lines, "certifiedToDate": certified,
    }
    if not new_lines and abs(delta) < 0.005:
        out.update({"ok": False,
                    "why": "This variation changes nothing — no value and no lines. An empty "
                           "document in a contract file is worse than no document."})
        return out
    # This also covers "a contract cannot be worth less than nothing": certifiedToDate is never
    # negative, so anything that would take the value below zero is already below what is certified
    # and refused here. A separate negative-value guard would be unreachable code that reads like a
    # safety net — the worst kind, because it is the one nobody tests and everybody trusts.
    if new_value - certified < -0.005:
        out.update({"ok": False,
                    "why": "That would take the contract to %s, below the %s already certified. "
                           "Work that has been signed off cannot be un-signed by a variation — "
                           "raise a credit note against the claim instead."
                           % (_vnd(new_value), _vnd(certified))})
        return out
    out["statement"] = ("%s %s the contract: %s → %s%s."
                        % (_vnd(abs(delta)),
                           "added to" if delta >= 0 else "taken off",
                           _vnd(old_value), _vnd(new_value),
                           "" if not new_lines else
                           ", with %d new line(s) worth %s" % (len(new_lines), _vnd(from_lines))))
    return out


def apply_to(contract, variation, mint_uid):
    """The contract as it stands AFTER this variation, and the lines to write.

    `mint_uid(i)` supplies a stable id for each new line — the caller's job, because a line uid must
    survive being reordered and a document that mints its own would collide across variations.

    Returns the NEW contract dict rather than mutating: the caller writes it under compare-and-swap,
    and a half-applied variation is the one failure mode that would be invisible afterwards.
    """
    e = effect(contract, variation)
    if not e["ok"]:
        return e
    c = dict(contract or {})
    existing = list(c.get("lines") or [])
    known = {str(l.get("uid")) for l in existing}
    added = []
    for i, raw in enumerate([l for l in (variation.get("lines") or []) if l]):
        uid = str(mint_uid(i))
        if uid in known:
            return {"ok": False, "why": "Line id %s already exists on this contract." % uid}
        known.add(uid)
        added.append(sales_doc.new_line(
            uid, desc=raw.get("desc", ""), kind=raw.get("kind", sales_doc.ITEM),
            qty=raw.get("qty", 1), unitPrice=raw.get("unitPrice", 0),
            discPct=raw.get("discPct", 0), uom=raw.get("uom", "lot"),
            # Every line points back at the document that introduced it. Without this a bill of
            # quantities becomes a flat list nobody can explain a year later.
            src={"doc": "variation", "id": variation.get("id"), "no": variation.get("variationNo")}))
    c["lines"] = existing + added
    c["value"] = e["newValue"]
    e.update({"contract": c, "addedLines": added})
    return e


def register(contract, variations):
    """Every variation on a contract and what the original became — the audit answer to "why is
    this contract worth more than the quotation?"."""
    applied = [v for v in (variations or []) if v.get("status") == APPLIED]
    delta = r2(sum(_num(v.get("delta")) for v in applied))
    original = r2(_num((contract or {}).get("value")) - delta)
    return {
        "originalValue": original, "variedBy": delta,
        "currentValue": r2((contract or {}).get("value")),
        "applied": len(applied), "open": len([v for v in (variations or [])
                                              if v.get("status") in (DRAFT, ISSUED)]),
        "statement": ("No variations — the contract is what was quoted." if not applied else
                      "%d variation(s) took the contract from %s to %s."
                      % (len(applied), _vnd(original), _vnd((contract or {}).get("value")))),
    }


UNRESOLVED = (
    {"topic": "Whether a variation needs the customer's signature to be applied",
     "question": "Vietnamese practice varies: some clients instruct verbally on site and paper "
                 "follows weeks later, which is exactly how disputed variations arise.",
     "why_it_matters": "An applied variation raises the value every later claim is measured against.",
     "action": "Applying is an e-signed act, and the signature is recorded on the document. Whether "
               "to wait for the customer's own signature is the company's call, not this code's."},
)
