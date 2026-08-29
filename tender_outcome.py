"""Why a tender was won or lost, and what the record then says about how we price.

The module could already tell you a win rate: won ÷ decided, by count. That number is nearly
useless on its own, for three reasons this module exists to fix.

BY COUNT IS NOT BY VALUE.  Nine small jobs won and one large one lost is 90% by count and can be
20% by value. A contractor plans capacity, cash and factory loading against the second number. Both
are reported here, always together, because either one alone invites the wrong decision.

CANCELLED IS NOT LOST.  If the client shelved the project, nobody beat us. Counting it against the
estimating team measures the weather. `Cancelled` is excluded from both the numerator and the
denominator — and the count of excluded tenders is reported, so the exclusion is visible rather
than quietly shrinking the sample.

A LOSS WITH NO REASON TEACHES NOTHING.  "Lost" on its own cannot answer the only question worth
asking — are we losing on price, on lead time, or on terms? Each has a different fix, and two of
them are free. So a tender may not be marked won or lost without one, and where the winning price
is known the gap is measured rather than guessed.

Nothing here estimates a price gap that was not entered. A competitor's price is either something
somebody was told or something nobody knows, and a module that splits the difference produces a
confident average built from invented numbers.
"""

WON = "Won"
LOST = "Lost"
CANCELLED = "Cancelled"

#: The states that represent an outcome the estimating team owns.
DECIDED = (WON, LOST)

#: Why it went the way it did. A fixed list because free text cannot be counted, and the whole
#: point is to be able to say "we lost four of the last six on lead time".
REASONS = (
    "Price",
    "Technical compliance",
    "Delivery / lead time",
    "Payment terms",
    "Warranty / guarantees",
    "Relationship / incumbent supplier",
    "Local content / origin",
    "Client cancelled or deferred",
    "No bid submitted",
    "Other",
)


def _num(v):
    try:
        s = str(v).replace(",", "").replace(" ", "").replace("₫", "").strip()
        return float(s or 0)
    except (TypeError, ValueError):
        return 0.0


def _blank(v):
    return v is None or str(v).strip() == ""


def decision_check(t):
    """May this tender be marked with the outcome it carries? Returns a list of what is missing.

    Empty list means yes. This is the same shape as `tender.issue_check`: facts about what is
    missing, not sentences about it.
    """
    status = str(t.get("status") or "").strip()
    if status not in DECIDED:
        return []
    missing = []
    reason = str(t.get("outcomeReason") or "").strip()
    if not reason:
        missing.append("Why this tender was %s" % status.lower())
    elif reason not in REASONS:
        missing.append("An outcome reason from the list (got %r)" % reason)
    if _blank(t.get("decidedOn")):
        missing.append("The date the customer decided")
    return missing


def price_gap(t):
    """How far our price was from the one that won, as a share of the winning price.

    None when the winning price is not known — which is most of the time, and saying so is the
    point. A gap invented for the tenders where nobody asked would dominate the average.
    """
    theirs = _num(t.get("winningPrice"))
    ours = _num(t.get("quotedPrice"))
    if theirs <= 0 or ours <= 0:
        return None
    return (ours - theirs) / theirs * 100.0


def _value(t):
    """What this tender was worth to us. The price quoted, not the cost."""
    return _num(t.get("quotedPrice"))


def hit_rate(tenders):
    """Won against decided — by count and by value, with the exclusions stated."""
    won = [t for t in tenders if str(t.get("status") or "").strip() == WON]
    lost = [t for t in tenders if str(t.get("status") or "").strip() == LOST]
    cancelled = [t for t in tenders if str(t.get("status") or "").strip() == CANCELLED]
    decided = won + lost

    won_value = sum(_value(t) for t in won)
    decided_value = sum(_value(t) for t in decided)

    # A tender with no price on it cannot contribute to a by-value rate. Counting it as zero would
    # drag the rate toward nothing and look like a pricing problem instead of a data-entry one.
    unpriced = [t for t in decided if _value(t) <= 0]

    return {
        "won": len(won),
        "lost": len(lost),
        "decided": len(decided),
        "byCount": (len(won) / len(decided) * 100.0) if decided else None,
        "wonValue": won_value,
        "decidedValue": decided_value,
        "byValue": (won_value / decided_value * 100.0) if decided_value else None,
        # Stated, never silently dropped — a denominator that shrank without saying so is how a
        # hit rate comes to describe a sample nobody chose.
        "cancelledExcluded": len(cancelled),
        "unpricedExcludedFromValue": len(unpriced),
    }


def _tally(tenders, key_of):
    """Group decided tenders and rate each group the same way the whole set is rated."""
    groups = {}
    for t in tenders:
        status = str(t.get("status") or "").strip()
        if status not in DECIDED:
            continue
        k = key_of(t)
        if _blank(k):
            k = "(not recorded)"
        groups.setdefault(str(k), []).append(t)
    out = []
    for k, rows in groups.items():
        r = hit_rate(rows)
        out.append({"key": k, "won": r["won"], "lost": r["lost"], "decided": r["decided"],
                    "byCount": r["byCount"], "value": r["decidedValue"],
                    "wonValue": r["wonValue"], "byValue": r["byValue"]})
    # Biggest sample first, then by value — a 100% rate off one tender should not head the table.
    out.sort(key=lambda x: (-x["decided"], -x["value"], x["key"]))
    return out


def by_reason(tenders):
    """Only the LOSSES are grouped by reason. A win reason is worth recording and is a different
    question; mixing them produces a table where 'Price' means two opposite things."""
    lost = [t for t in tenders if str(t.get("status") or "").strip() == LOST]
    groups = {}
    for t in lost:
        k = str(t.get("outcomeReason") or "").strip() or "(not recorded)"
        groups.setdefault(k, []).append(t)
    out = [{"reason": k, "count": len(v), "value": sum(_value(x) for x in v)}
           for k, v in groups.items()]
    out.sort(key=lambda x: (-x["count"], -x["value"], x["reason"]))
    return out


def by_customer(tenders):
    return _tally(tenders, lambda t: t.get("client"))


def by_costing_type(tenders):
    return _tally(tenders, lambda t: t.get("costingType"))


def gaps(tenders):
    """The price gap on the losses where somebody found out what won.

    `known` is reported beside the average precisely so nobody reads a mean of three as the shape
    of the market.
    """
    vals = []
    for t in tenders:
        if str(t.get("status") or "").strip() != LOST:
            continue
        g = price_gap(t)
        if g is not None:
            vals.append(g)
    lost = len([t for t in tenders if str(t.get("status") or "").strip() == LOST])
    return {
        "known": len(vals),
        "lost": lost,
        "avgPct": (sum(vals) / len(vals)) if vals else None,
        "worstPct": max(vals) if vals else None,
    }


def summary(tenders):
    """Everything the outcome screen draws, computed once, here."""
    return {
        "hit": hit_rate(tenders),
        "lossReasons": by_reason(tenders),
        "byCustomer": by_customer(tenders),
        "byCostingType": by_costing_type(tenders),
        "priceGap": gaps(tenders),
        "reasons": list(REASONS),
    }
