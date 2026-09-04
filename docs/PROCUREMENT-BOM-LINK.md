# Procurement ↔ AHU bill of materials

**Status: specified, not built.** The portal half is in place. The Procurement half is not, and it
cannot be built from this repository — see [What is blocking it](#what-is-blocking-it).

---

## The problem

`ahu_bom` records, per line: required quantity, kitted quantity, received quantity, shortage, and
incoming-inspection status. Every one of those is typed by hand.

Procurement — a separate application, embedded in this portal — already holds the same facts as
purchase-order lines and goods receipts. So a BOM line and a PO line are one fact recorded twice, by
two people, in two systems, and nothing reconciles them.

Gate G3 (Material Ready) refuses on those typed numbers. That is the part that matters. A gate is
only as truthful as what it reads, and today G3 will pass a unit whose materials exist entirely as
numbers somebody entered — and refuse one whose material is physically on the floor but whose
kitting figure was never updated. Both failures are silent and both are routine.

## What the portal already does

- `ahu_bom` lines carry a `poRef` field: the purchase order or goods receipt the material came
  from. Editable on the BOM line form.
- The Materials tab counts kitted lines with no `poRef` and says so, as a **statement, not a gate
  criterion**.

That last distinction is deliberate and should survive this document. Kitting from existing stock is
normal, and its incoming inspection happened on a different record, possibly months earlier.
Refusing G3 for a missing receipt reference would block legitimate work on a rule the company has
never written down. Encoding an acceptance criterion nobody asked for is the specific mistake this
module exists to avoid.

## What is blocking it

The Procurement application is a **separate git repository**, `.gitignore`d from this one, with its
own database (Prisma) and its own deployment. It is not present in this checkout. Building the link
requires:

1. **An endpoint on the Procurement side.** It does not exist, and its schema cannot be read from
   here, so the contract below is a *request*, not a description of something already available.
2. **A decision from the company** about what a BOM line's authoritative source is: a purchase-order
   line, a goods receipt, or a stock issue. These are three different records and the answer decides
   what "linked" means. This is an operations question, not a technical one.

Neither can be settled from inside this repository.

## The contract being asked for

One read-only endpoint on the Procurement app, authenticated with the existing portal↔Procurement
shared secret (the same one `/api/procurement/sso` already uses — no new credential).

```
GET /api/portal/materials?ref=<poNumber|projectRef>
Authorization: Bearer <portal-minted token>
```

```jsonc
{
  "ref": "PO-2026-0417",
  "lines": [
    {
      "partNo": "FRM-40x40-AL",         // matches ahu_bom.partNo
      "description": "Aluminium profile 40x40",
      "orderedQty": 120,
      "receivedQty": 120,               // goods actually receipted
      "receiptRefs": ["GRN-2026-0881"], // what the portal writes into poRef
      "inspection": "Passed",           // maps to ahu_bom.iqcStatus
      "outstandingQty": 0,
      "expectedOn": "2026-08-30"        // null when there is no committed date
    }
  ],
  "generatedOn": "2026-08-21T09:15:00Z"
}
```

### Rules the portal side will apply

These are stated here so the Procurement implementation is not guessing.

- **`receivedQty` is what was receipted, not what was ordered or invoiced.** If Procurement cannot
  distinguish those, it must say so in the response rather than send the closest number — a received
  quantity that is really an ordered quantity would make G3 pass a unit whose material has not
  arrived, which is worse than the hand-typed figure it replaced.
- **A part number Procurement does not recognise is reported, never dropped.** The portal will show
  it as unmatched. A silently shortened list reads as "everything is accounted for".
- **The portal never writes to Procurement.** One direction only. Two systems that can both edit the
  same quantity will disagree, and there is no rule here for who wins.
- **The import is a suggestion until somebody accepts it**, in the same shape as the AeroSelect
  selection handoff (`docs/AEROSELECT-HANDOFF.md`): the portal shows what would change and a person
  confirms. A background sync that silently rewrote kitting figures would move a gate criterion
  without anybody deciding to.
- **No date is invented.** A line with no committed delivery date comes back `null` and is shown as
  unknown, not as today.

### What G3 would then read

`_p_no_shortage` and `_p_bom_fully_kitted` in `ahu.py` would continue to read `ahu_bom` — the link
fills those fields rather than replacing the predicates. That keeps one place where a gate criterion
is defined, which is the property worth protecting: today the gate logic is testable without any
network, and it should stay that way.

## Until then

The hand-entered figures remain authoritative and G3 keeps refusing on them. The `poRef` field and
the unsourced-line count are the groundwork: they give the portal somewhere to put the answer, and
they make the size of the gap visible instead of assumed.
