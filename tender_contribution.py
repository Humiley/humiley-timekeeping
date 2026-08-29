"""Which lines of a quotation actually carry the profit.

`tender.pnl` says what the whole tender makes: revenue, COGS, gross profit, opex, EBIT, net. Every
one of those is a total, and a total cannot answer the question an estimator is asked in a
negotiation — *which* line is the margin in?

It matters in three ways a total hides.

CONCENTRATION.  If two lines out of forty carry 80% of the profit, the bid is fragile: a client who
negotiates exactly those two takes the whole margin with them, and the other thirty-eight were
never worth defending. A tender whose profit is spread evenly is a completely different commercial
position from one that is not, and the totals look identical.

LINES SOLD BELOW COST.  A discount applied pro rata, a mispriced import, a rate that moved — any of
them can leave a line whose revenue is less than what it costs to deliver. It is invisible in a
gross profit that is still positive, and it is the first thing anybody would want to know.

WHERE AN ESTIMATE ERROR HURTS.  The line carrying most of the margin is the line whose cost estimate
matters most. Getting a 2% quantity wrong on the biggest profit line costs more than getting a 20%
error on a line that makes nothing.

Nothing here re-prices anything. It reads the lines `tender.quotation` already produced and
rearranges them, so the numbers on this screen and the numbers on the P&L cannot disagree.
"""


def _num(v):
    try:
        return float(str(v).replace(",", "").replace(" ", "").replace("₫", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def contribution(quote, top_share=80.0):
    """Profit by line, biggest contributor first.

    `top_share` — the share of total profit used to answer "how few lines carry most of it".
    """
    lines = list((quote or {}).get("lines") or [])
    rows = []
    for l in lines:
        # netAfterDiscount is what the customer actually pays for this line; `net` is before the
        # discount was apportioned. Using `net` would report a profit the tender is not making.
        revenue = _num(l.get("netAfterDiscount", l.get("net")))
        cost = _num(l.get("cogs"))
        profit = revenue - cost
        rows.append({
            "itemCode": str(l.get("itemCode") or "").strip(),
            "desc": str(l.get("desc") or "").strip(),
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            # The margin ON THIS LINE. None rather than 0 when the line is free: a zero here reads
            # as "sold at cost", which is a different and much less alarming thing.
            "marginPct": (profit / revenue * 100.0) if revenue else None,
            "belowCost": profit < 0,
        })

    total_profit = sum(r["profit"] for r in rows)
    total_revenue = sum(r["revenue"] for r in rows)

    # SHARE OF PROFIT IS ONLY MEANINGFUL WHEN THERE IS A PROFIT.
    #
    # On a tender that loses money the total is negative, and "this line is 140% of the profit" is
    # not a sentence anybody can act on — worse, a loss-making line would show a NEGATIVE share and
    # read as though it helped. So the shares are withheld and `shareMeaningful` says why.
    meaningful = total_profit > 0
    for r in rows:
        r["sharePct"] = (r["profit"] / total_profit * 100.0) if meaningful else None

    rows.sort(key=lambda r: (-r["profit"], r["itemCode"], r["desc"]))

    # How few lines carry `top_share` of the profit. Counted from the biggest down, over the
    # PROFITABLE lines only — including a loss-making line in a cumulative total makes the count
    # smaller and the bid look more concentrated than it is.
    carriers, running = 0, 0.0
    if meaningful:
        for r in rows:
            if r["profit"] <= 0:
                break
            carriers += 1
            running += r["profit"]
            if running / total_profit * 100.0 >= top_share:
                break

    below = [r for r in rows if r["belowCost"]]
    return {
        "rows": rows,
        "lineCount": len(rows),
        "totalRevenue": total_revenue,
        "totalCost": sum(r["cost"] for r in rows),
        "totalProfit": total_profit,
        "marginPct": (total_profit / total_revenue * 100.0) if total_revenue else None,
        "shareMeaningful": meaningful,
        "topShare": top_share,
        "carriers": carriers,
        # Stated as a fraction of the whole bill, because "3 lines carry 80%" means something very
        # different on a 4-line quotation and on a 90-line one.
        "carriersOf": len(rows),
        "concentrated": bool(meaningful and rows and carriers and
                             (carriers / float(len(rows))) <= 0.25),
        "belowCost": below,
        "belowCostCount": len(below),
    }
