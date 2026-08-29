"""Re-pricing a tender against today's rate library.

`estimating.stale_rates` already says WHICH library rates have moved since a tender copied them, and
saying so was the right half to build first: a snapshot that silently re-priced itself would mean
a tender's cost changed while nobody was looking at it.

But that left the other half missing. An estimator looking at eleven drifted rates on a forty-line
bill had exactly one way to act: open each build-up and retype the number. So in practice nobody
did, and the drift panel became a list of things that are wrong with a tender rather than something
you can fix.

Three rules decide what this touches.

ONLY WHAT CAME FROM THE LIBRARY.  A resource with no `rateId` was priced by hand — a supplier quote,
a phone call, a number somebody negotiated. Overwriting that with a library average would destroy
the most reliable figure on the bill, and it is the one nobody could reconstruct.

NEVER A TENDER THAT IS SOMEBODY'S BUDGET.  `adoptedProjectId` means a live project is measured
against these numbers. Re-pricing it would move the baseline under a running job.

PREVIEW AND APPLY COMPUTE THE SAME THING.  `plan()` returns the new resource rows; the caller prices
BOTH the current and the planned set through `estimating` and shows the difference. Applying writes
the very rows the preview was costed from. A preview produced by different code from the change is
a preview that can lie, and this one decides whether somebody re-prices a bid.
"""


def _vnd(v):
    try:
        s = str(v).replace(",", "").replace(" ", "").replace("₫", "").strip()
        return round(float(s or 0))
    except (TypeError, ValueError):
        return 0


def plan(res_by_item, library, today=""):
    """Work out the re-price. Pure: returns new rows, writes nothing.

    `res_by_item`  {itemId: [resource rows]} — the shape `estimating` uses
    `library`      the est_rates rows
    returns        (new_res_by_item, changes, counts)
    """
    by_id = {r.get("id"): r for r in (library or []) if r.get("id")}
    out, changes = {}, []
    counts = {"changed": 0, "handPriced": 0, "unchanged": 0, "goneFromLibrary": 0}

    for item_id, rows in (res_by_item or {}).items():
        made = []
        for r in rows or []:
            rate_id = r.get("rateId")
            if not rate_id:
                counts["handPriced"] += 1        # a negotiated number — never overwritten
                made.append(r)
                continue
            lib = by_id.get(rate_id)
            if not lib:
                # The library row was deleted or renumbered. The tender keeps the number it was
                # priced at: substituting anything else would be inventing a rate.
                counts["goneFromLibrary"] += 1
                made.append(r)
                continue
            was, now = _vnd(r.get("unitCost")), _vnd(lib.get("unitCost"))
            if was == now:
                counts["unchanged"] += 1
                made.append(r)
                continue
            n = dict(r)
            n["unitCost"] = now
            # The snapshot fields move with the rate. Without them the drift check would go on
            # comparing against the price this row USED to carry.
            n["ratePricedOn"] = lib.get("effectiveFrom") or ""
            n["rateSource"] = lib.get("source") or ""
            n["repricedFrom"] = was
            n["repricedOn"] = today
            counts["changed"] += 1
            made.append(n)
            changes.append({
                "resourceId": r.get("id"),
                "itemId": item_id,
                "rateId": rate_id,
                "code": str(lib.get("code") or "").strip(),
                "desc": str(lib.get("desc") or r.get("desc") or "").strip(),
                "was": was,
                "now": now,
                "deltaPct": round((now - was) / was * 100.0, 1) if was else None,
            })
        out[item_id] = made

    # Dearest move first — the rate that matters most is the one that moved furthest, and an
    # estimator scanning eleven rows should not have to hunt for it.
    changes.sort(key=lambda c: (-abs(c["now"] - c["was"]), c["code"]))
    return out, changes, counts


def changed_rows(new_res_by_item, changes):
    """The rows THIS run rewrote, flat — what the caller has to save.

    Selected by the `changes` list `plan` returned, so there is exactly one notion of "changed" and
    the preview, the count and the write all use it.

    It deliberately does NOT scan for the `repricedFrom` marker. That marker is written to the
    database and stays there, so on any later re-price it would match every row an EARLIER run had
    touched — reporting a tender as freshly re-priced when nothing had moved, and re-saving rows
    that did not change.
    """
    want = {c.get("resourceId") for c in (changes or [])}
    out = []
    for rows in (new_res_by_item or {}).values():
        for r in rows or []:
            if r.get("id") in want:
                out.append(r)
    return out
