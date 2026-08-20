# The AeroSelect selection handoff

How a selection computed in **AeroSelect** reaches **AHU Production** without anybody retyping it.

This document is the contract between the two applications. The portal side is implemented
(`ahu_selection.py`, `POST /api/ahu/unit/<id>/selection`); the AeroSelect side is an export that
writes the document described here.

---

## Why it exists

A unit is sold on numbers AeroSelect computed — the airflow, the external static pressure, the
casing classes, the coil design pressure, the supply voltage. Production then needs *exactly* those
numbers, because they are what the factory builds to and what the test bench judges against.

Until now somebody retyped them. A retyped figure is a figure that can be wrong in a way nobody
notices, and the specific way it goes wrong here is nasty: the portal resolves test acceptance
limits from the unit's declared classes, so a mistyped `L2` instead of `L1` means the casing is
leak-tested against **0.44 l/(s·m²) rather than 0.15** — three times the leakage — and passes.

## The shape of it

One JSON file. Two top-level keys: `aeroselect` (the envelope) and `payload` (the data).

```json
{
  "aeroselect": {
    "document":      "selection",
    "specVersion":   2,
    "selectionRef":  "AS-2026-0410",
    "engine":        "AeroSelect",
    "engineVersion": "2.0.0",
    "generatedOn":   "2026-08-20T09:14:00Z",
    "contentHash":   "sha256:9f2c…",
    "signature":     "hmac-sha256:41ab…"
  },
  "payload": {
    "project": { "number": "P-2026-014", "name": "Cleanroom Block B",
                 "client": "Vinh Phuc Pharma JSC" },
    "unit": {
      "tag": "AHU-B-01", "model": "AeroSmart AS-24", "family": "hygienic",
      "airflow_m3h": 12000, "esp_pa": 450,
      "voltage_v": 400, "coilDesignBar": 16, "cleanroom": "ISO 7"
    },
    "classes":     { "D": "D1", "L": "L1", "F": "F9", "T": "T1", "TB": "TB1" },
    "performance": { "erp": { "verdict": "PASS", "sfpIntWm3s": 810.0 },
                     "euroventClass": "A+" },
    "sections":    [ { "type": "filter_hepa" }, { "type": "cooling_coil_chw" } ]
  }
}
```

### Envelope

| Field | Required | Notes |
|---|---|---|
| `document` | yes | Literally `"selection"`. Anything else is refused by name. |
| `specVersion` | yes | `2`. A mismatch is refused rather than guessed across. |
| `selectionRef` | yes | Your stable identifier for this selection. Becomes the unit's `selectionRef` and the document number of the selection report. Refused if blank — a unit has to be able to say which selection it was built to. |
| `engine`, `engineVersion` | recommended | Recorded as provenance and shown on the unit. `engineVersion` is your `ENGINE_VERSION` / `API_VERSION`. |
| `generatedOn` | recommended | ISO 8601 UTC. |
| `contentHash` | **yes** | See below. |
| `signature` | when paired | See below. |

### Payload

Everything is optional except `unit`. **A field you omit is left alone on the portal side, not
written blank** — importing a partial selection can never erase something already known.

**A class code the portal cannot read is refused, not dropped.** `classes.D = "D4"` or
`unit.cleanroom = "Class 100"` fails the import and names the offending value. This is deliberate:
dropping it silently would leave the unit tested against whatever class it held before, while the
document declared something else — a figure wrong in exactly the way nobody notices until a test is
judged against the wrong limit. An **absent** class is still simply absent.

`unit.family` maps to the four families the Design Standards define. Accepted spellings, case- and
separator-insensitive: `modular` / `built-up` / `CAU` / `AHU`; `packaged` / `compact` / `PAU`;
`hygienic` / `cleanroom` / `pharma`; `outdoor` / `rooftop` / `weatherproof`. Anything else is **not
guessed** — the family decides which workstations and which tests apply, and the import is refused
unless the unit already has one.

---

## The part worth reading twice: L and F are not results

AeroSelect's own `EN1886Result` says it, and it is right:

```ts
leakage_class?: string       // test-only (declared by the manufacturer), undefined until tested
filter_bypass_class?: string // test-only (declared), undefined until tested
```

EN 1886 awards leakage and filter-bypass classes by **testing a built unit**, never by running
software. So in this handoff:

| Class | What it is | What the factory does |
|---|---|---|
| **D** strength | computed by AeroSelect | carried as a computed value |
| **T** transmittance | computed by AeroSelect | carried as a computed value |
| **TB** bridging | computed by AeroSelect | carried as a computed value |
| **L** leakage | **declared target** | test **T3** measures the casing at −400 Pa and judges it against the L threshold |
| **F** filter bypass | **declared target** | test **T4** scans downstream and judges it against the F threshold |

Send `L` and `F` as **the class the unit is sold as** — the target. The portal stores them as the
acceptance limits T3 and T4 are judged against, labels them on screen as targets a test still has to
prove, and only calls them proved once the test is signed. Nothing in the portal presents a target
as a measurement.

This is the loop closing properly: AeroSelect states what the unit is sold as, and the factory is
what makes it true.

---

## Integrity and authenticity

Two independent things, deliberately not conflated.

### `contentHash` — always checked

SHA-256 over the **canonical bytes** of the *attested object* — the payload **and** the envelope
fields that identify it:

```json
{ "envelope": { "document": …, "specVersion": …, "selectionRef": …,
                "engine": …, "engineVersion": …, "generatedOn": … },
  "payload":  { … } }
```

**This is the change in spec version 2, and it is the reason to bump.** In version 1 the hash
covered `payload` alone — but `selectionRef`, `engine`, `engineVersion` and `generatedOn` live in
the envelope, are all written onto the production unit, and `selectionRef` becomes the document
number of the Selection report filed as gate G2's evidence. So a version-1 document could carry a
perfectly valid signature and still claim to be a selection AeroSelect never wrote, with
"Signature verified" printed over it. `contentHash` and `signature` are excluded, for the obvious
reason.

Canonical bytes, of that object:

* `JSON.stringify` with **sorted keys**, no insignificant whitespace, UTF-8.
* Written as `"sha256:" + hex`.

Both sides must agree on the canonical form or every document fails its hash for no reason. The
portal's implementation is `ahu_selection.canonical()`:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

In TypeScript, the equivalent needs a **recursive** key sort — `JSON.stringify(obj, Object.keys(obj).sort())`
does not sort nested objects:

```ts
const canonical = (v: unknown): unknown =>
  Array.isArray(v) ? v.map(canonical)
  : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v as object).sort()
        .map(k => [k, canonical((v as Record<string, unknown>)[k])]))
    : v
const attested = {
  envelope: {
    document: env.document, specVersion: env.specVersion, selectionRef: env.selectionRef,
    engine: env.engine, engineVersion: env.engineVersion, generatedOn: env.generatedOn,
  },
  payload,
}
const bytes = new TextEncoder().encode(JSON.stringify(canonical(attested)))
```

A document whose hash does not match its contents is **refused outright**. That is the case where
somebody opened the JSON and changed the airflow.

#### Two rules that are invisible until they bite

**The hash is over the PARSED VALUES, not the file's bytes.** A JSON number is a number: `810` and
`810.0` are the same value to one side and different text to the other. Python's `json.dumps`
preserves a float's trailing `.0`; JavaScript has no int/float distinction and cannot emit it at
all:

```
python3 -c "import json;print(json.dumps(810.0))"   ->  810.0
node    -e "console.log(JSON.stringify(810.0))"     ->  810
```

So **never put a whole-number float in a payload.** Write `810`, not `810.0`. The shipped example
originally carried `810.0`, which made it unreproducible from JavaScript — the exact file offered as
the thing to assert against. `tools/make_selection_example.py` now refuses to write one, and
`tests/handoff_example_cross_language.js` runs the recipe below over the committed example in Node
and fails CI if the hashes disagree.

**Sort object KEYS recursively; never sort ARRAY elements.** `payload.sections` is ordered — it is
the module chain in airflow order. A canonicaliser that sorted array contents would silently reorder
a unit's sections and still hash "successfully", which is worse than failing. Python's
`json.dumps(sort_keys=True)` never touches list order, so this is a hazard for the TypeScript side
only — and this is where a TypeScript implementer will look.

### `signature` — checked when the two are paired

HMAC-SHA256 over those same canonical bytes — the attested object, envelope included — keyed by a
shared secret, written as `"hmac-sha256:" + hex`.

The portal reads its secret from `TK_AEROSELECT_SECRET`, and its behaviour is honest about its own
state — the same honesty your `/v1` API applies to `API_KEYS`:

| Portal secret | Document | Result |
|---|---|---|
| not set | unsigned | accepted, recorded and displayed as **unverified** |
| not set | signed | accepted, recorded as unverified (it cannot check) |
| set | signed, valid | accepted, **verified** |
| set | signed, invalid | refused |
| set | unsigned | refused |

What the portal will not do is call an unverified document verified, or skip a failed hash.

### Turning signing on — the order matters

A configured secret means signatures are **required**. Setting it before AeroSelect signs refuses
every import, so:

1. **AeroSelect ships the exporter** and signs with the shared value.
2. **Set the same value on both sides.** On the portal: `TK_AEROSELECT_SECRET` in `.env` on the VPS,
   then `docker compose up -d portal`. On the AeroSelect side, wherever its export reads it from.
3. **Re-import one selection** and confirm the unit shows *Signature verified* rather than
   *Signature not verified*.

Generate the value with `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` — or any
CSPRNG. It is a credential: it belongs in the environment on both hosts and in your password
manager, never in either repository.

Rotating it is safe and uneventful. Documents already imported keep the `selectionVerified` flag
they were imported under; re-importing one signed with the old secret is refused, which is the
correct behaviour and is why the flag records the state at import time rather than being recomputed.

---

## What the portal does with it

1. Validates the envelope, the hash, and the signature if paired.
2. Stamps the unit: `family`, `model`, `tag`, `airflow`, `esp`, `voltage`, `coilDesignBar`,
   `cleanroom`, `classD/L/F/T/TB`, plus provenance (`selectionRef`, engine, version, generated date,
   content hash, verified flag, who imported it and when).
3. Files an **ahu_docs** row of kind `Selection report` — which is what gate **G2** requires, so the
   import satisfies the gate rather than leaving somebody to attach a second copy by hand.
4. Writes an audit entry recording the summary, the hash and the verification state.

### Re-importing

* Re-importing the **same** selection (same content hash) is idempotent.
* A **different** selection, before the unit passes G2: applied normally. Nothing is built yet, so
  re-selecting is ordinary engineering work.
* A **different** selection **after** the unit has passed G2: **refused with 409**, listing exactly
  which fields would move. The design has changed under a unit somebody is already building — that
  is an engineering change, and a person has to decide it. Re-import with `supersede: true` (manager
  only) once the change is raised.

---

## What AeroSelect needs to build

One export — "Export for production" — on a saved AHU, producing the file above.

Suggested placement: alongside the existing report exports in `apps/web/src/lib/reports/`, since it
draws on exactly the values those already read (`AHUUnit`, `AHUResults.compliance.en1886`,
`compliance.erp`, `compliance.eurovent_energy`).

A worked example that the portal accepts today is committed at
`docs/examples/aeroselect-selection-example.json` — a useful fixture to assert your exporter's
output against, and the canonical-bytes rule is the thing most likely to trip on the first attempt.

Two requests from this side:

1. **Send `L` and `F` as the sold targets** even though the engine does not compute them. Without
   them the factory has no acceptance limit for T3 and T4, and the portal will report those tests as
   *undeterminable* rather than inventing one.
2. **Keep `selectionRef` stable** across revisions of the same selection, and change the content when
   the selection changes — the portal uses the hash, not the ref, to tell "same selection" from
   "different selection", and the ref to tell a person which one it was.

Questions to the portal side; the shape is not fixed in stone, and `specVersion` exists so it can
move.
