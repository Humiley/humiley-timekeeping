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

print("payments in the register: %d\n" % len(rows))
for k in sorted(buckets): print("  %-46s %d" % (k, buckets[k]))
if risky:
    print("\nAT RISK — re-attach the bills on these by hand:")
    print("  %-16s %-12s %-28s %s" % ("REQ NO", "STATUS", "PAYEE", "DATE"))
    for r in sorted(risky, key=lambda x: x[3], reverse=True):
        print("  %-16s %-12s %-28s %s" % (r[0], r[1][:12], str(r[2])[:28], r[3]))
else:
    print("\nNothing at risk — every payment with a combined file also kept its individual uploads.")
