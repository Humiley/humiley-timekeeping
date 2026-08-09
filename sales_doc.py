"""The spine every sell-side document shares — lines, links and the open balance.

Quotation, contract, payment application, credit note: they differ in what they mean and agree
completely on what they are made of. A document has a header, a customer, a status, and a list of
lines; and every line after the first document points back at the line it came from.

Two decisions live here because they are the ones that cannot be retrofitted.

FIRST — every line carries a STABLE uid, minted once, never the array index. A 300-line bill of
quantities gets reordered, inserted into and deleted from constantly. If history points at "line 7"
then inserting a heading at the top silently re-points every claim, every certificate and every
invoice line by one row. Nobody would ever see it happen.

SECOND — every line carries its OPEN BALANCE, not just its value. "How much of this contract is
still to bill" is the question the whole sell side exists to answer, and it cannot be derived after
the fact from a pile of documents that only know their own totals. Partial delivery and partial
invoicing are the normal case for a contractor, not an edge case: a ₫2.4bn contract is billed in
eight applications over a year, and the eighth one has to know what the first seven took.

The counters only ever move through `apply()`, which refuses to overshoot and says by how much. It
never clamps silently — a clamp turns "you are claiming more than the contract" into a number that
looks fine, and that is the single most expensive silent failure available on this side of the
business.

Pure — no database, no clock, no money formatting. Exercised by tests/test_sales_doc.py.
"""

# ── line kinds ───────────────────────────────────────────────────────────────────────────────────
# A bill of quantities is not a flat list of priced rows. Headings and notes carry no value and must
# never reach a total; an optional line is priced but excluded until it is taken up.
ITEM, SERVICE, HEADING, NOTE, OPTIONAL = "item", "service", "heading", "note", "optional"
VALUED = (ITEM, SERVICE)          # the only kinds that contribute to a total

# ── document status ──────────────────────────────────────────────────────────────────────────────
DRAFT = "draft"
ISSUED = "issued"
ACCEPTED = "accepted"
LOST = "lost"
EXPIRED = "expired"
SUPERSEDED = "superseded"
CANCELLED = "cancelled"
CLOSED = "closed"

# What may follow what. A status machine written down is a status machine that can be tested; the
# alternative is an `if` in a click handler that nobody can enumerate.
TRANSITIONS = {
    DRAFT: (ISSUED, CANCELLED),
    ISSUED: (ACCEPTED, LOST, EXPIRED, SUPERSEDED, CANCELLED),
    ACCEPTED: (CLOSED, SUPERSEDED),
    LOST: (),
    EXPIRED: (SUPERSEDED, LOST),
    SUPERSEDED: (),
    CANCELLED: (),
    CLOSED: (),
}

# Once a document has left the building it is evidence. Editing it changes what you can prove you
# sent, so a change after issue is a NEW REVISION, never an edit in place.
EDITABLE = (DRAFT,)
TERMINAL = (LOST, SUPERSEDED, CANCELLED, CLOSED)


def can_transition(frm, to):
    return to in TRANSITIONS.get(str(frm or DRAFT), ())


def transition(doc, to, reason=""):
    """Move a document's status, or explain precisely why it cannot move.

    A refusal names both states. "Invalid status" tells somebody nothing they can act on.
    """
    cur = str((doc or {}).get("status") or DRAFT)
    to = str(to or "")
    if cur == to:
        return {"ok": False, "why": "The document is already %s." % cur}
    if not can_transition(cur, to):
        allowed = TRANSITIONS.get(cur, ())
        return {"ok": False, "why": "A %s document cannot become %s. It can only become: %s."
                                    % (cur, to, ", ".join(allowed) or "nothing — this is final")}
    if to in (LOST, CANCELLED) and not str(reason or "").strip():
        # Why you lost is the only thing that makes a win rate diagnosable. Marking a deal Lost with
        # no reason is how a company charts its losses for years without learning anything.
        return {"ok": False, "why": "A reason is required when a document is marked %s." % to}
    return {"ok": True, "status": to, "reason": str(reason or "").strip()}


# ── lines ────────────────────────────────────────────────────────────────────────────────────────

COUNTERS = ("orderedAmt", "certifiedAmt", "billedAmt", "settledAmt", "cancelledAmt")


def new_line(uid, desc="", kind=ITEM, qty=1, unitPrice=0, discPct=0, uom="lot", src=None, **kw):
    """One line, in the shape every sell-side document uses.

    `uid` is the caller's to mint and must be stable for the life of the line — see the module
    docstring for why an array index is not good enough.
    """
    ln = {
        "uid": str(uid), "kind": kind, "desc": desc, "uom": uom,
        "qty": _num(qty), "unitPrice": _num(unitPrice), "discPct": _num(discPct),
        "src": dict(src) if src else None,
    }
    ln["amount"] = line_amount(ln)
    for c in COUNTERS:
        ln[c] = _num(kw.get(c, 0))
    ln.update({k: v for k, v in kw.items() if k not in COUNTERS})
    return ln


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if n != n else n          # NaN in a money field is worse than zero


def line_amount(ln):
    """What this line is worth. A heading or a note is worth nothing, whatever is typed on it."""
    ln = ln or {}
    if ln.get("kind") not in VALUED:
        return 0.0
    gross = _num(ln.get("qty")) * _num(ln.get("unitPrice"))
    disc = max(0.0, min(100.0, _num(ln.get("discPct"))))
    return round(gross * (1 - disc / 100.0), 2)


def open_amount(ln, counter="billedAmt"):
    """What is left to claim on this line. Never negative — a negative open balance is a bug
    upstream, and reporting it as a negative would let it net off against another line and vanish."""
    ln = ln or {}
    return max(0.0, round(line_amount(ln) - _num(ln.get(counter)) - _num(ln.get("cancelledAmt")), 2))


def totals(lines, counter="billedAmt"):
    """The document's totals, counting only the kinds that carry value."""
    val = [l for l in (lines or []) if (l or {}).get("kind") in VALUED]
    gross = round(sum(line_amount(l) for l in val), 2)
    done = round(sum(_num(l.get(counter)) for l in val), 2)
    cancelled = round(sum(_num(l.get("cancelledAmt")) for l in val), 2)
    return {"lines": len(val), "amount": gross, "applied": done, "cancelled": cancelled,
            "open": round(max(0.0, gross - done - cancelled), 2),
            "pct": round(done / gross * 100, 2) if gross else 0.0}


# ── moving the counters, which is where money is either right or silently wrong ─────────────────

TOL = 0.005      # half a cent: absorbs float noise, never a real overclaim


def apply(lines, claims, counter="billedAmt"):
    """Add `claims` ({uid: amount}) to a counter, or refuse the WHOLE document and say why.

    All or nothing on purpose. Applying the lines that fit and rejecting the rest would leave a
    payment application half-posted, with a total on the PDF that no longer matches the lines behind
    it — and somebody would sign it.

    It never clamps. A clamp turns "you are claiming ₫40m more than this line is worth" into a
    number that looks fine.
    """
    by_uid = {str(l.get("uid")): l for l in (lines or []) if (l or {}).get("uid") is not None}
    problems = []
    for uid, amt in (claims or {}).items():
        uid = str(uid)
        ln = by_uid.get(uid)
        if ln is None:
            problems.append({"uid": uid, "why": "No line with this id on the document."})
            continue
        if ln.get("kind") not in VALUED:
            problems.append({"uid": uid, "why": "A %s line carries no value and cannot be claimed."
                                                % ln.get("kind")})
            continue
        a = _num(amt)
        if a < 0:
            problems.append({"uid": uid, "why": "A negative claim is a credit note, not a claim."})
            continue
        avail = open_amount(ln, counter)
        if a - avail > TOL:
            problems.append({"uid": uid, "amount": a, "available": avail,
                             "over": round(a - avail, 2),
                             "why": "Claiming %.2f against %.2f still open — over by %.2f."
                                    % (a, avail, a - avail)})
    if problems:
        return {"ok": False, "problems": problems,
                "why": "%d line(s) cannot be claimed as asked; nothing was applied."
                       % len(problems)}
    out = []
    for l in (lines or []):
        c = dict(l)
        uid = str(c.get("uid"))
        if uid in (claims or {}):
            c[counter] = round(_num(c.get(counter)) + _num(claims[uid]), 2)
        out.append(c)
    return {"ok": True, "lines": out, "applied": round(sum(_num(v) for v in (claims or {}).values()), 2)}


def copy_to(lines, doc_kind, doc_id, uids=None, counter="billedAmt"):
    """Carry lines into the next document, each pointing back at the line it came from.

    Only what is still OPEN is carried, so a second application against the same contract starts
    from the remainder rather than the original value — the single most common way a progress claim
    goes out for money that was already invoiced.

    This is SAP's BaseType/BaseEntry/BaseLine, per LINE rather than per document, which is what makes
    a trace view possible at all.
    """
    out = []
    for l in (lines or []):
        if (l or {}).get("kind") not in VALUED:
            continue
        uid = str(l.get("uid"))
        if uids is not None and uid not in {str(u) for u in uids}:
            continue
        rest = open_amount(l, counter)
        if rest <= TOL:
            continue
        out.append(new_line(
            uid=uid, desc=l.get("desc", ""), kind=l.get("kind"), uom=l.get("uom", "lot"),
            qty=1, unitPrice=rest, discPct=0,
            src={"coll": doc_kind, "id": doc_id, "uid": uid}))
    return out


def trace(lines):
    """Where each line came from — the spine of a document trail."""
    return [{"uid": l.get("uid"), "desc": l.get("desc"), "amount": line_amount(l),
             "from": l.get("src")} for l in (lines or []) if (l or {}).get("kind") in VALUED]


def next_uid(lines, prefix="l"):
    """A uid no line on this document has had. Monotonic, so a deleted line's id is never reused —
    reuse would silently attach old history to a new line."""
    top = 0
    for l in (lines or []):
        u = str((l or {}).get("uid") or "")
        if u.startswith(prefix) and u[len(prefix):].isdigit():
            top = max(top, int(u[len(prefix):]))
    return "%s%d" % (prefix, top + 1)
