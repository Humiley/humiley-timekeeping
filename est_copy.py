"""Duplicating a tender.

Almost no quotation is written from nothing. It is last year's job for the same customer, or the
same scope at a different site, or revision C after the client moved the goalposts — and until now
the only way to produce one was to open the old tender on a second screen and retype the bill.
A forty-line bill retyped is a forty-line bill with a typo in it.

Two things make this harder than copying a row.

THE BUILD-UPS POINT AT THE BILL LINES.  est_resources carries `itemId`, naming the est_items row it
prices. Copy both without re-pointing and the new tender's build-ups still name the ORIGINAL
tender's lines: the copy shows a bill with no rates under it, the original shows each rate twice,
and nothing anywhere says the word "error". The remap below is the whole reason this module exists
rather than a loop at the call site.

A COPY MUST NOT BE BORN FROZEN.  `adoptedProjectId` is what makes a tender the untouchable budget of
a live project. Inherited by a copy, the copy is read-only from the moment it exists and the
estimator is told to "raise a revised estimate instead" — of a tender they just created. Everything
in CLEARED is a fact about the ORIGINAL's passage through the world, not about the job being priced.

What is deliberately KEPT is the pricing: the customer, the costing model, the bill, the build-ups,
the mark-ups, the scope and the exclusions. That is the work worth copying.
"""

DRAFT = "Draft"

#: Collections that belong to a tender and are copied with it, all keyed by `estId`.
#: est_resources is here, but its `itemId` is re-pointed afterwards — see `duplicate`.
CHILDREN = ("est_items", "est_resources", "est_landed", "est_local",
            "est_bom", "est_wbs", "est_quote", "est_risks")

#: Deliberately NOT copied.
#:   est_revs   the revision history is the ORIGINAL's audit trail. Copied onto a new tender it
#:              would assert that this document went through approvals it has never seen.
#:   est_rates  the rate library is company-wide, not a possession of one tender.
NOT_COPIED = ("est_revs", "est_rates")

#: Dropped from the copy. Each is a fact about the original's life, not about the priced job.
CLEARED = (
    "estNo", "quoteNo",                          # numbers are issued to a document, never inherited
    "issueDate", "validUntil", "dateIssued",     # when the ORIGINAL was priced and sent
    "dueDate",                                   # the original's submission deadline, long past
    "amountInWords",                             # a printed statement of a specific figure
    "approvedBy",                                # nobody has approved a tender that did not exist
    "adoptedProjectId", "adoptedAt", "adoptedBy",  # the freeze — see the module docstring
    "pmProjectId",                               # a copy does not price an already-running project
    "signedBy", "signedAt", "issuedBy", "issuedAt",  # issue e-signature, if one was taken
)


def _blank(v):
    return v is None or str(v).strip() == ""


def copy_title(src, title=None):
    """A name the estimator can find again. 'Copy of' is a placeholder, not a decision — it reads
    as unfinished on a list precisely so somebody renames it."""
    if not _blank(title):
        return str(title).strip()
    base = str(src.get("title") or "").strip()
    return ("Copy of " + base).strip() if base else "Copy"


def duplicate(src, rows, new_id, mkid, title=None, today=""):
    """Plan a duplicate. Pure: works out every new row, writes nothing.

    `src`    the est_projects row being copied
    `rows`   {collection: [all rows in it]} — filtered by estId here
    `mkid`   () -> a fresh id, called once per copied row
    returns  (head, {collection: [new rows]}, report)
    """
    src_id = src.get("id")
    if _blank(src_id):
        raise ValueError("The tender being copied has no id.")

    head = dict(src)
    for k in CLEARED:
        head.pop(k, None)
    head["id"] = new_id
    head["status"] = DRAFT
    head["title"] = copy_title(src, title)
    # Provenance, so a bill that turns out to be wrong can be traced to the tender it came from —
    # and so the same mistake can be found in every other copy of it.
    head["copiedFrom"] = src_id
    head["copiedFromNo"] = str(src.get("estNo") or src.get("quoteNo") or "")
    head["copiedAt"] = today

    out, idmap = {}, {}
    for coll in CHILDREN:
        made = []
        for r in rows.get(coll) or []:
            if r.get("estId") != src_id:
                continue
            n = dict(r)
            n["id"] = mkid()
            n["estId"] = new_id
            if coll == "est_items":
                idmap[r.get("id")] = n["id"]
            made.append(n)
        out[coll] = made

    # Re-point the build-ups — in its OWN pass, after every item has an id, so this does not depend
    # on the order CHILDREN happens to be written in.
    #
    # A resource whose item was deleted is an orphan: it prices nothing, and `_est_rows` already
    # buckets it under a key no item matches, so it has never reached a total. It is DROPPED rather
    # than carried over, because the alternative — leaving `itemId` pointing into the original
    # tender — is the one outcome that looks fine and is not.
    kept, orphans = [], 0
    for n in out.get("est_resources", []):
        old = n.get("itemId")
        if old in idmap:
            n["itemId"] = idmap[old]
            kept.append(n)
        elif _blank(old):
            kept.append(n)          # never attached to a line in the first place; harmless
        else:
            orphans += 1
    out["est_resources"] = kept

    report = {
        "lines": len(out.get("est_items", [])),
        "resources": len(kept),
        "orphansDropped": orphans,
        "copied": {c: len(out.get(c) or []) for c in CHILDREN},
        "notCopied": list(NOT_COPIED),
    }
    return head, out, report
