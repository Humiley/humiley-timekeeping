"""The AeroSelect selection handoff — reading a selection into production without retyping it.

A unit is sold on numbers AeroSelect computed: the airflow, the external static pressure, the casing
classes, the coil design pressure, the supply voltage. Production then needs exactly those numbers,
because they are what the factory builds and tests against. Until now somebody retyped them, and a
retyped figure is a figure that can be wrong in a way nobody notices until a test is judged against
the wrong limit.

This module reads an **AeroSelect selection document** — a self-contained JSON export — and maps it
onto a production unit. It is pure: no database, no request, no clock, so every rule is exercised by
tests/test_ahu_selection.py.

The document shape is specified in docs/AEROSELECT-HANDOFF.md and is grounded in AeroSelect's own
types (`AHUUnit`, `AHUResults`, `ComplianceReport`, `EN1886Result`) rather than invented here.

── The one thing worth understanding ────────────────────────────────────────────────────────────

AeroSelect deliberately does NOT compute the EN 1886 **leakage (L)** and **filter bypass (F)**
classes. Its own type marks both "test-only (declared by the manufacturer), undefined until tested",
because those classes are awarded by testing a built unit and never by running software.

So the handoff carries them as **declared targets**, not as results — and this factory is what turns
a target into a fact:

    AeroSelect declares  L2  ──▶  imported as the target for this unit
                                   ──▶  test T3 measures the built casing at −400 Pa
                                        ──▶  judged against 0.44 l/(s·m²), the L2 threshold
                                             ──▶  the as-built record states what was measured

The same for F and test T4. D, T and TB *are* computed by AeroSelect and come across as computed
values. `classes_measured_by_test()` says which is which, so nothing on screen or in the dossier can
present a target as though it were a measurement.

── Trust ────────────────────────────────────────────────────────────────────────────────────────

Two independent things, deliberately not conflated:

* **Integrity** — a content hash over the payload. Answers "did this document change since it was
  written?" Always checked; a document whose hash does not match its content is refused outright.
* **Authenticity** — an optional HMAC signature over that hash, keyed by a secret shared with
  AeroSelect. Answers "did AeroSelect write it?" Checked only when a secret is configured.

With no secret configured, a document is accepted and reported as `unverified`, and the import is
recorded that way on the unit — the same honesty AeroSelect's own API applies to its API keys. What
this module will not do is call an unverified document verified, or silently skip a hash that fails.
"""
import hashlib
import hmac
import json

# The document shape this module understands. Bumped only when a change would make an older
# document read incorrectly — a new optional field does not need a new version.
#
# 2 — the hash and signature now cover the document's IDENTITY as well as its payload. In version 1
# they covered `payload` alone, and `selectionRef`, `engine`, `engineVersion` and `generatedOn` sit
# in the envelope: all four are written onto the unit, and selectionRef is also the document number
# of the Selection report filed as gate G2's evidence. So a version-1 document could carry a
# perfectly valid signature and still claim to be a selection AeroSelect never wrote — the
# signature said "these numbers are ours" while the document said "and they belong to selection X".
# That is a worse failure than no signature at all, because it prints "Signature verified" over it.
SPEC_VERSION = 2

# The envelope fields that are part of what is being attested. Anything here is read onto the unit
# or into its evidence, so it has to be inside the hash.
SIGNED_ENVELOPE_FIELDS = ("document", "specVersion", "selectionRef", "engine", "engineVersion",
                          "generatedOn")

# Bound the payload. A selection document is a few kilobytes of numbers; anything vastly larger is
# either a mistake or an attempt to make the parser work hard.
MAX_BYTES = 512 * 1024

# EN 1886 classes AeroSelect computes, versus the ones only a test can establish. See the module
# docstring: this distinction is the point of the integration, not an implementation detail.
CLASSES_COMPUTED = ("D", "T", "TB")
CLASSES_BY_TEST = {"L": "T3", "F": "T4"}

VALID = {
    "D": ("D1", "D2", "D3"),
    "L": ("L1", "L2", "L3"),
    "F": ("F8", "F9"),
    "T": ("T1", "T2", "T3", "T4", "T5"),
    "TB": ("TB1", "TB2", "TB3", "TB4", "TB5"),
}

# AeroSelect's `unit_type` / family wording mapped onto the four production families the Design
# Standards define. Anything unrecognised is left for a human rather than guessed into a route.
#
# Keys are in the NORMALISED form _fold() produces — lower case with spaces, hyphens and underscores
# removed — so "Built-Up", "built_up" and "BUILT UP" all arrive here as "builtup". Writing the keys
# in their unnormalised form is why "built-up" silently failed to match: the lookup had already
# stripped the hyphen the key still carried.
FAMILY_ALIASES = {
    "modular": "modular", "builtup": "modular", "cau": "modular", "ahu": "modular",
    "packaged": "packaged", "compact": "packaged", "pau": "packaged",
    "hygienic": "hygienic", "cleanroom": "hygienic", "pharma": "hygienic",
    "outdoor": "outdoor", "rooftop": "outdoor", "weatherproof": "outdoor",
}


def _fold(v):
    """The one normalisation FAMILY_ALIASES keys are written in."""
    return str(v or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")


class SelectionError(ValueError):
    """The document cannot be trusted or cannot be understood. The message is shown to a person."""


def attested(env, payload):
    """What the hash and the signature are actually taken over.

    The payload AND the envelope fields that identify it. Anything a reader will act on has to be
    in here, or a signature attests to less than the document appears to claim.
    """
    return {"envelope": {k: (env or {}).get(k) for k in SIGNED_ENVELOPE_FIELDS},
            "payload": payload}


def canonical(obj):
    """The exact bytes a hash and a signature are taken over.

    Sorted keys, no insignificant whitespace, UTF-8. Both sides must agree on this or every
    document fails its hash for no reason — so it is stated once, here, and the spec quotes it.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def content_hash(env, payload):
    return "sha256:" + hashlib.sha256(canonical(attested(env, payload))).hexdigest()


def sign(env, payload, secret):
    """The signature AeroSelect writes: HMAC-SHA256 over the canonical attested bytes."""
    return "hmac-sha256:" + hmac.new(secret.encode("utf-8"), canonical(attested(env, payload)),
                                     hashlib.sha256).hexdigest()


def _num(v):
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        f = float(v)
        return f if -1e12 < f < 1e12 else None
    except (TypeError, ValueError):
        return None


def _cls(kind, v):
    """Normalise a class code, or None. 'iso 7' style values are handled by _cleanroom."""
    s = str(v or "").strip().upper().replace(" ", "").replace("-", "")
    return s if s in VALID.get(kind, ()) else None


def _cleanroom(v):
    s = str(v or "").strip().upper().replace(" ", "").replace("-", "").replace("CLASS", "")
    return s if s in ("ISO5", "ISO6", "ISO7", "ISO8") else None


def parse(raw, secret=None):
    """Read a selection document. Returns a dict describing it, or raises SelectionError.

    `raw` may be bytes, str or an already-decoded dict. `secret` is the shared secret, when one is
    configured; without it the document is accepted and reported unverified.
    """
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_BYTES:
            raise SelectionError("That file is too large to be a selection document.")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SelectionError("That file is not UTF-8 text — is it the PDF rather than the "
                                 "selection export?")
    if isinstance(raw, str):
        if len(raw) > MAX_BYTES:
            raise SelectionError("That file is too large to be a selection document.")
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise SelectionError("That is not a selection document — it is not valid JSON (%s)."
                                 % exc)
    if not isinstance(raw, dict):
        raise SelectionError("A selection document is a JSON object.")

    env = raw.get("aeroselect")
    if not isinstance(env, dict):
        raise SelectionError("This file has no `aeroselect` header, so it is not a selection "
                             "document. Export it from AeroSelect with 'Export for production'.")
    if str(env.get("document") or "").strip().lower() != "selection":
        raise SelectionError("This is an AeroSelect file, but not a selection export (it says %r)."
                             % (env.get("document"),))
    try:
        ver = int(env.get("specVersion") or 0)
    except (TypeError, ValueError):
        ver = 0
    if ver != SPEC_VERSION:
        raise SelectionError(
            "This selection document is spec version %s; this portal reads version %d. Update "
            "whichever side is behind rather than importing across versions."
            % (env.get("specVersion"), SPEC_VERSION))

    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise SelectionError("The document has no `payload`.")

    # ── Integrity, always. A document whose hash does not match its own content is refused: it has
    # been edited since AeroSelect wrote it, and the edit may be the numbers the unit is built to.
    stated = str(env.get("contentHash") or "").strip()
    actual = content_hash(env, payload)
    if not stated:
        raise SelectionError("The document carries no content hash, so nothing can be said about "
                             "whether it still matches what AeroSelect wrote.")
    if not hmac.compare_digest(stated, actual):
        raise SelectionError("This document has been altered since AeroSelect produced it — its "
                             "content hash does not match its contents. Re-export it rather than "
                             "importing this copy.")

    # ── Authenticity, when a secret is configured.
    sig = str(env.get("signature") or "").strip()
    if secret:
        if not sig:
            raise SelectionError("This portal requires signed selection documents and this one is "
                                 "unsigned. Re-export it from an AeroSelect that shares the "
                                 "signing secret.")
        if not hmac.compare_digest(sig, sign(env, payload, secret)):
            raise SelectionError("The signature on this document does not verify against the "
                                 "shared secret. It was not produced by the AeroSelect this "
                                 "portal is paired with.")
        verified = True
    else:
        verified = False

    unit = payload.get("unit") if isinstance(payload.get("unit"), dict) else {}
    if not unit:
        raise SelectionError("The document has no `payload.unit`.")

    # A class code that is PRESENT but unreadable is refused, and is not the same thing as one that
    # is absent. `_cls` returns None for both, and `to_unit_fields` skips a None — so "D4" used to
    # be dropped, `differences()` reported nothing, and a unit already holding D2 kept D2 while the
    # document declared otherwise. It was then built and tested against the D2 limit with no warning
    # anywhere. That is precisely the failure this module opens by describing: a figure wrong in a
    # way nobody notices until a test is judged against the wrong limit.
    _cls_in = payload.get("classes") if isinstance(payload.get("classes"), dict) else {}
    _bad = []
    for _k in ("D", "L", "F", "T", "TB"):
        _v = _cls_in.get(_k)
        if _v not in (None, "") and _cls(_k, _v) is None:
            _bad.append("%s = %r (expected one of %s)" % (_k, _v, ", ".join(VALID[_k])))
    _cr = unit.get("cleanroom")
    if _cr not in (None, "") and _cleanroom(_cr) is None:
        _bad.append("cleanroom = %r (expected ISO5, ISO6, ISO7 or ISO8)" % (_cr,))
    if _bad:
        raise SelectionError(
            "This selection declares a class this portal cannot read, and a class it cannot read is "
            "a test limit it cannot apply: %s. Correct the export rather than importing it — "
            "dropping the value silently would leave the unit tested against whatever it held "
            "before." % "; ".join(_bad))

    out = {
        "specVersion": ver,
        "verified": verified,
        "signed": bool(sig),
        "contentHash": actual,
        "engine": str(env.get("engine") or "").strip() or None,
        "engineVersion": str(env.get("engineVersion") or "").strip() or None,
        "generatedOn": str(env.get("generatedOn") or "").strip() or None,
        "selectionRef": str(env.get("selectionRef") or "").strip() or None,
        "project": payload.get("project") if isinstance(payload.get("project"), dict) else {},
        "unit": unit,
        "classes": payload.get("classes") if isinstance(payload.get("classes"), dict) else {},
        "performance": (payload.get("performance")
                        if isinstance(payload.get("performance"), dict) else {}),
        "sections": payload.get("sections") if isinstance(payload.get("sections"), list) else [],
    }
    if not out["selectionRef"]:
        raise SelectionError("The document has no selection reference, so the unit could not say "
                             "which selection it was built to.")
    return out


def family_of(doc):
    """The production family this selection maps to, or None if it cannot be told.

    Never guessed. A unit whose family cannot be determined gets no route, which is the correct
    outcome — the route decides which workstations and which tests apply.
    """
    for key in (doc.get("unit", {}).get("family"), doc.get("unit", {}).get("unitType")):
        s = _fold(key)
        if s in FAMILY_ALIASES:
            return FAMILY_ALIASES[s]
    return None


def classes_measured_by_test(doc):
    """Which declared classes are targets a test still has to prove, as {class: test code}.

    Present so nothing downstream can show a target as though it were a measurement.
    """
    cls = doc.get("classes") or {}
    return {k: t for k, t in CLASSES_BY_TEST.items() if _cls(k, cls.get(k))}


def to_unit_fields(doc):
    """The portal `ahu_units` fields this selection determines.

    Only fields the document actually carries are returned — a missing value is left alone rather
    than written as blank, so importing a partial selection cannot erase something already known.
    """
    unit = doc.get("unit") or {}
    cls = doc.get("classes") or {}
    perf = doc.get("performance") or {}
    out = {}

    def put(k, v):
        if v is not None and v != "":
            out[k] = v

    put("selectionRef", doc.get("selectionRef"))
    put("tag", str(unit.get("tag") or "").strip() or None)
    put("model", str(unit.get("model") or "").strip() or None)
    put("family", family_of(doc))
    put("airflow", _num(unit.get("airflow_m3h")))
    put("esp", _num(unit.get("esp_pa")))
    put("voltage", _num(unit.get("voltage_v")))
    put("coilDesignBar", _num(unit.get("coilDesignBar")))
    put("cleanroom", _cleanroom(unit.get("cleanroom")))
    for k in ("D", "L", "F", "T", "TB"):
        put("class" + k, _cls(k, cls.get(k)))
    # Provenance. Everything above came from a document rather than from somebody typing, and the
    # unit should be able to say so a year later.
    put("selectionEngine", doc.get("engine"))
    put("selectionEngineVersion", doc.get("engineVersion"))
    put("selectionGeneratedOn", doc.get("generatedOn"))
    put("selectionHash", doc.get("contentHash"))
    out["selectionVerified"] = bool(doc.get("verified"))
    put("selectionSfpInt", _num((perf.get("erp") or {}).get("sfpIntWm3s")
                                if isinstance(perf.get("erp"), dict) else None))
    put("selectionErp", str((perf.get("erp") or {}).get("verdict") or "").strip().upper() or None
        if isinstance(perf.get("erp"), dict) else None)
    put("selectionEurovent", str(perf.get("euroventClass") or "").strip() or None)
    return out


def differences(doc, unit):
    """What this document would change on a unit that already has a selection.

    Returns a list of (field, from, to). Used to refuse a silent respecification: re-importing a
    different selection onto a unit already released for production is an engineering change, and
    somebody has to see exactly what moved.
    """
    unit = unit or {}
    out = []
    for k, v in to_unit_fields(doc).items():
        # The hash and the generated date identify the document rather than describe the unit, so
        # they are not "what moved". `selectionVerified` IS reported: re-importing the same document
        # on a portal that has lost its shared secret downgrades a verified unit to unverified, and
        # that is a change somebody confirming should be able to see.
        if k in ("selectionHash", "selectionGeneratedOn", "selectionEngineVersion"):
            continue
        cur = unit.get(k)
        if cur in (None, "") and v in (None, ""):
            continue
        # Compare numbers as numbers. Stringly comparison made 12000 and 12000.0 look like a change,
        # which put a field that had not moved next to the ones that had, in the one message
        # somebody reads when deciding whether to supersede a unit already being built.
        a, b = _num(cur), _num(v)
        if a is not None and b is not None:
            if a != b:
                out.append((k, cur, v))
            continue
        if str(cur or "").strip().lower() != str(v or "").strip().lower():
            out.append((k, cur, v))
    return out


def is_same_selection(doc, unit):
    """Whether the unit is already built to exactly this selection."""
    return bool(unit) and str(unit.get("selectionHash") or "") == str(doc.get("contentHash") or "")


def summary(doc):
    """A short human description, for a confirmation prompt and the audit trail."""
    unit = doc.get("unit") or {}
    bits = [doc.get("selectionRef") or "selection",
            str(unit.get("tag") or "").strip(),
            str(unit.get("model") or "").strip()]
    fam = family_of(doc)
    if fam:
        bits.append(fam)
    a = _num(unit.get("airflow_m3h"))
    if a:
        bits.append("%g m3/h" % a)
    e = _num(unit.get("esp_pa"))
    if e:
        bits.append("%g Pa" % e)
    return " · ".join(b for b in bits if b)
