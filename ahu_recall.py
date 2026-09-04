"""Which units got this component — the question traceability exists to answer.

`ahu_trace` records a serial number, a batch and a make against a unit, so the portal could always
answer *"what is inside PIN-2026-0417-01?"*. It could not answer the reverse. And the reverse is the
only one that matters when it matters: a fan supplier reports a bearing fault in batch B-2026-14, or
a coil maker recalls a production run, and somebody has to say — today, not next week — which units
received it and where those units now are.

Without this the defensible answer is "all of them", which is why recalls get expensive.

Pure: rows in, matches out. No database, no clock.

── Why matching is deliberately broad, and why that is the safe direction ───────────────────────

A serial is typed by a person at a workstation. It arrives with stray spaces, in either case,
sometimes with the maker's prefix and sometimes without. So the match is case-insensitive and
substring-based, and it looks across serial, batch, make and component.

That will occasionally return a unit that does not really have the part. That is the right way to be
wrong here: a recall list with one extra unit costs an inspection, and a recall list with one
missing unit ships a fault to a customer. The rows carry WHICH field matched so a person can discard
the false ones quickly — a list you cannot audit is one that gets ignored wholesale.
"""

FIELDS = ("serial", "batch", "maker", "component", "section")


def _s(v):
    return str(v or "").strip()


def search(trace_rows, query, units_by_id=None, fields=FIELDS):
    """Every trace row matching `query`, with the unit it belongs to and the field that matched.

    Returns [] for an empty query rather than everything. A blank search box that silently selects
    the entire register is how somebody recalls a factory.
    """
    q = _s(query).lower()
    if not q:
        return []
    out = []
    for row in (trace_rows or []):
        hits = [f for f in fields if q in _s(row.get(f)).lower()]
        if not hits:
            continue
        unit = (units_by_id or {}).get(_s(row.get("unitId"))) or {}
        out.append({
            "traceId": row.get("id"),
            "unitId": row.get("unitId"),
            "pin": unit.get("pin") or row.get("unitId"),
            "tag": unit.get("tag"),
            "status": unit.get("status"),
            "component": row.get("component"),
            "maker": row.get("maker"),
            "serial": row.get("serial"),
            "batch": row.get("batch"),
            "section": row.get("section"),
            "recordedOn": row.get("recordedOn"),
            "matchedOn": hits,
        })
    out.sort(key=lambda r: (str(r.get("pin") or ""), str(r.get("component") or "")))
    return out


def group_by_unit(matches, orders_by_unit=None):
    """The same matches collapsed to one row per unit — the list somebody actually acts on.

    Carries the order and customer where they are known, because the first question after "which
    units" is always "and who has them".
    """
    by = {}
    for m in matches:
        uid = m.get("unitId")
        g = by.setdefault(uid, {"unitId": uid, "pin": m.get("pin"), "tag": m.get("tag"),
                                "status": m.get("status"), "components": [], "count": 0})
        g["count"] += 1
        label = " ".join(x for x in (m.get("component"), m.get("serial") or m.get("batch")) if x)
        if label and label not in g["components"]:
            g["components"].append(label)
        o = (orders_by_unit or {}).get(uid) or {}
        if o:
            g["poNumber"] = o.get("poNumber")
            g["customer"] = o.get("customer")
            g["deliveryDate"] = o.get("deliveryDate")
    return sorted(by.values(), key=lambda g: str(g.get("pin") or ""))


# ── Has it left the building? ───────────────────────────────────────────────────────────────────
# The single most useful thing to know about a recalled unit, because it decides who has to be
# told. Derived from the dispatch record rather than from the unit's status field: a unit is gone
# when something says it was dispatched, and a status somebody forgot to update is not that.

def dispatch_state(unit_id, dispatch_rows):
    d = next((x for x in (dispatch_rows or []) if _s(x.get("unitId")) == _s(unit_id)), None)
    if not d:
        return {"shipped": False, "where": "Still in the factory, on this record."}
    when = _s(d.get("dispatchedOn")) or _s(d.get("date"))
    if not when:
        return {"shipped": False,
                "where": ("A dispatch record exists but carries no date, so whether this unit has "
                          "left cannot be read from it.")}
    return {"shipped": True, "dispatchedOn": when,
            "where": "Dispatched on %s%s." % (when, (" to " + _s(d.get("consignee")))
                                              if d.get("consignee") else "")}


def summarise(matches, dispatch_rows):
    """How many matched units have shipped, and how many have not. The rest is a phone call."""
    shipped, held = [], []
    seen = set()
    for m in matches:
        uid = m.get("unitId")
        if uid in seen:
            continue
        seen.add(uid)
        (shipped if dispatch_state(uid, dispatch_rows)["shipped"] else held).append(m.get("pin"))
    return {"units": len(seen), "shipped": sorted(x for x in shipped if x),
            "inFactory": sorted(x for x in held if x)}
