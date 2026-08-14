#!/usr/bin/env python3
"""How many payments could be short a document in their consolidated dossier?

READ-ONLY. Opens the portal DB, looks at every payment, and reports the ones whose
attachments cannot be rebuilt — i.e. a combined file was stored but the individual
uploads were not, so anything the merge silently dropped is simply gone.

    python3 paid_docs_audit.py [/data/timekeeping.db]
"""
import json, os, sqlite3, sys

db = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TK_DB_PATH", "/data/timekeeping.db")
con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
rows = [json.loads(d) for (d,) in con.execute("SELECT data FROM collections WHERE coll='payments'")]
con.close()

def parts(p):
    """What the record actually holds, per document the dossier is meant to consolidate."""
    lst = p.get("attachments")
    return {
        "bill": bool(p.get("attachment")),
        "bill_copies": len(lst) if isinstance(lst, list) else 0,
        "slip": bool(p.get("bankSlip")),          # attached at Mark-paid, rides the Paid e-signature
        "merged_flag": p.get("attachmentsMerged"),
    }


def cls(p):
    att, lst = p.get("attachment"), p.get("attachments")
    if not att:                       return "no attachment at all"
    if isinstance(lst, list) and lst: return "OK — every file recoverable"
    # A combined file named "<reqNo>.pdf" with no per-file list is the risky shape: if the merge
    # dropped anything, there is nothing left to rebuild it from.
    if att and (p.get("attachmentName") or "") == (p.get("reqNo") or "") + ".pdf":
        return "AT RISK — combined only, no per-file copies"
    return "single file, nothing merged (fine)"

buckets = {}
risky = []
for p in rows:
    k = cls(p); buckets[k] = buckets.get(k, 0) + 1
    if k.startswith("AT RISK"):
        risky.append((p.get("reqNo") or p.get("id"), p.get("status") or "", p.get("payee") or "", (p.get("ts") or "")[:10]))

paid = [p for p in rows if str(p.get("status") or "").lower() == "paid"]
print("payments in the register: %d  (paid: %d)\n" % (len(rows), len(paid)))
no_slip = [p for p in paid if not p.get("bankSlip")]
print("PAID but NO bank slip stored: %d" % len(no_slip))
for p in no_slip[:40]:
    print("   %-16s %s" % (p.get("reqNo") or p.get("id"), (p.get("payee") or "")[:34]))
print()
print("per-document breakdown of every PAID payment:")
print("  %-16s %-6s %-7s %-6s %s" % ("REQ NO", "BILL", "COPIES", "SLIP", "MERGED?"))
for p in sorted(paid, key=lambda x: str(x.get("reqNo") or "")):
    d = parts(p)
    print("  %-16s %-6s %-7s %-6s %s" % (p.get("reqNo") or p.get("id"),
          "yes" if d["bill"] else "NO", d["bill_copies"], "yes" if d["slip"] else "NO", d["merged_flag"]))
print()
for k in sorted(buckets): print("  %-46s %d" % (k, buckets[k]))
if risky:
    print("\nAT RISK — re-attach the bills on these by hand:")
    print("  %-16s %-12s %-28s %s" % ("REQ NO", "STATUS", "PAYEE", "DATE"))
    for r in sorted(risky, key=lambda x: x[3], reverse=True):
        print("  %-16s %-12s %-28s %s" % (r[0], r[1][:12], str(r[2])[:28], r[3]))
else:
    print("\nNothing at risk — every payment with a combined file also kept its individual uploads.")
