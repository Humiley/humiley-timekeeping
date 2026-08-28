"""AHU production control — the part that has to look things up.

ahu_route.py holds the process: the order of the steps and the limit each reading is judged against.
It is pure and knows nothing about this portal. This module is the other half — it reads the unit's
own records and answers the questions the pure library cannot:

  * what does THIS unit declare about itself, so a class-derived limit can be resolved?
  * which of its steps are signed, and what may therefore start now?
  * is a gate's exit criteria actually met — is every BOM line kitted, is any NCR still open, has
    the FAT report been signed?
  * what goes in the as-built dossier, and what is missing from it?

The split matters. A gate refusal has to name the thing that is missing, and the only way to name it
is to have looked. Keeping the looking here leaves ahu_route.py testable without a database.

Nothing in this module writes. It reads, judges and reports; app.py decides what to do about it.
"""
import db
import ahu_route as R

# The collections this module reads. Registered in app.py's COLLECTIONS set.
UNITS, ORDERS, STEPS = "ahu_units", "ahu_orders", "ahu_steps"
BOM, DOCS, TRACE, NCR, DISPATCH = "ahu_bom", "ahu_docs", "ahu_trace", "ahu_ncr", "ahu_dispatch"

# A step is signed when it reaches one of these. "Waived" is deliberately NOT among them: a waived
# step is a decision to skip something the standard asked for, and it must not read as done.
SIGNED_STATUSES = {"complete", "completed", "passed", "signed", "released"}
OPEN_NCR_STATUSES = {"open", "raised", "under review", "in progress", "pending", ""}


def _norm(v):
    return str(v or "").strip().lower()


def _rows(coll, field, value):
    return [r for r in db.list_collection(coll) if r.get(field) == value]


def _grouped(coll, field):
    """A whole collection read ONCE and grouped by one field."""
    out = {}
    for r in db.list_collection(coll):
        out.setdefault(r.get(field), []).append(r)
    return out


# ── What the unit declares about itself ──────────────────────────────────────────────────────────
def unit_decl(unit):
    """The properties a class-derived acceptance limit is resolved from.

    Where the unit has not declared a class of its own it inherits the Design Standard default for
    its family — that is what the unit was sold as unless the order said otherwise. `cleanroom` and
    `voltage` are never defaulted: an assumed cleanroom class would put a made-up number on a
    validation record, and an assumed voltage would set the hi-pot test voltage.
    """
    unit = unit or {}
    fam = _norm(unit.get("family")) or "modular"
    defaults = R.FAMILY_CLASS_DEFAULTS.get(fam, R.FAMILY_CLASS_DEFAULTS["modular"])
    out = {
        "classD": unit.get("classD") or defaults["D"],
        "classL": unit.get("classL") or defaults["L"],
        "classF": unit.get("classF") or defaults["F"],
        "classT": unit.get("classT") or defaults["T"],
        "classTB": unit.get("classTB") or defaults["TB"],
        "coilDesignBar": unit.get("coilDesignBar"),
        "voltage": unit.get("voltage"),
        "cleanroom": unit.get("cleanroom"),
    }
    return out


def route_opts(unit, order=None):
    unit = unit or {}
    skip = unit.get("skipSteps")
    if isinstance(skip, str):
        skip = [s.strip() for s in skip.split(",") if s.strip()]
    return {"fat": bool(unit.get("fatRequired") or (order or {}).get("fatRequired")),
            "sound_test": bool(unit.get("soundTest")),
            "skip": skip or []}


def build_for(unit, order=None):
    """This unit's route. Raises ValueError if its family is not one the Design Standards define."""
    return R.build_route(_norm(unit.get("family")) or "modular", route_opts(unit, order))


def safe_build_for(unit, order=None):
    """(steps, error) — the route, or an empty route and a sentence saying why there isn't one.

    `ahu_units` is a generic collection, so a `family` typed as "kappa" is stored without complaint
    and then cannot be turned into a route. Letting that ValueError escape took down the whole
    production board — a 500 on the landing screen for EVERY user, because one row out of hundreds
    could not be built. One unreadable unit should cost that unit's row, not everybody's screen.
    """
    try:
        return build_for(unit, order), None
    except ValueError as exc:
        return [], str(exc)


# ── Instantiating a unit's route ─────────────────────────────────────────────────────────────────
def instantiate(unit, order=None, existing=None):
    """The step rows a unit needs, as dicts ready to be written.

    Called both when a unit is created and when its specification changes. Steps already signed are
    returned untouched — a route rebuild must never quietly discard a signature, so a step that has
    left the route but carries one is kept and flagged `orphan` for somebody to look at rather than
    deleted.
    """
    existing = {r.get("code"): r for r in (existing or [])}
    want = build_for(unit, order)
    out, seen = [], set()
    for s in want:
        seen.add(s["code"])
        prior = existing.get(s["code"])
        row = {
            "unitId": unit.get("id"), "code": s["code"], "kind": s["kind"], "stage": s["stage"],
            "seq": s["seq"], "title": s["title"], "titleVn": s.get("title_vn", ""),
            "signRole": s.get("sign"), "after": ",".join(s.get("after") or []),
            "wi": s.get("wi") or s.get("doc") or "", "std": s.get("std") or "",
            "forms": ",".join(s.get("forms") or []), "tact": s.get("tact") or "",
            "activity": s.get("activity") or s.get("method") or "",
            "witnessNot": s.get("witness_not") or "", "sampling": s.get("sampling") or "",
            "optional": bool(s.get("optional")),
        }
        if prior:
            # Carry the record forward. Everything a person put there stays; only the process
            # description is refreshed from the library.
            merged = dict(prior)
            merged.update(row)
            merged["orphan"] = False
            out.append(merged)
        else:
            row["id"] = "%s-%s" % (unit.get("id"), s["code"])
            row["status"] = "Pending"
            out.append(row)
    for code, prior in existing.items():
        if code in seen:
            continue
        if has_signature(prior):
            orphan = dict(prior)
            orphan["orphan"] = True
            out.append(orphan)
    out.sort(key=lambda r: (r.get("seq") or 0))
    return out


# Two different questions, and conflating them is a real hazard.
#
#   is_passed(step)      did this step COMPLETE SUCCESSFULLY? Gates, progress and "what can start
#                        next" all ask this one. A FAILED step must answer no, or G4 would pass a
#                        unit with a failed workstation and the next station would unlock behind it.
#
#   has_signature(step)  has somebody PUT THEIR NAME to it, for any outcome? Only the route rebuild
#                        asks this — a failed hold point that later leaves the route still has to be
#                        carried forward and flagged, because it is the record you would most want
#                        to still see. /api/esign deliberately stamps signedBy on 'Failed' and
#                        'Held' too: who decided a unit failed is what an investigation needs.
def is_passed(step):
    return _norm((step or {}).get("status")) in SIGNED_STATUSES


def has_signature(step):
    step = step or {}
    return is_passed(step) or bool(str(step.get("signedBy") or "").strip())


# Kept as the old name for the pass-semantics question, which is what every existing caller meant.
is_signed = is_passed


def signed_codes(steps):
    return {s.get("code") for s in (steps or []) if is_signed(s)}


# ── Judging a step ───────────────────────────────────────────────────────────────────────────────
def spec_for(unit, code, order=None):
    """The library's definition of one step, by code."""
    return next((s for s in build_for(unit, order) if s["code"] == code), None)


def readings_of(step):
    r = (step or {}).get("readings")
    return r if isinstance(r, dict) else {}


def verdict(unit, step, order=None):
    """Judge a step's recorded readings against the standard. Returns the ahu_route verdict dict,
    or None when the step is not part of this unit's route."""
    spec = spec_for(unit, step.get("code"), order)
    if not spec:
        return None
    return R.evaluate_step(spec, readings_of(step), unit_decl(unit))


# ── The context a gate is judged in ──────────────────────────────────────────────────────────────
CTX_COLLS = (("steps", STEPS), ("bom", BOM), ("docs", DOCS), ("trace", TRACE),
             ("ncr", NCR), ("dispatch", DISPATCH))


def ctx_index():
    """The six per-unit collections plus the orders, each read ONCE and keyed by id.

    Pass the result to `load_ctx` when building context for MANY units. Without it every unit
    re-reads and re-parses all six collections in full, so a board of N units does N x (six whole
    collections) of work — quadratic, because the collections themselves grow with N. Measured on
    the shop-floor board: 0.06 s at 10 units, 1.98 s at 100, and that screen is polled.

    A snapshot, not a live view, and READ-ONLY. Build it, use it, discard it: anything written
    while it is held will not be in it, and the row dicts it hands out are SHARED between every
    context built from it — the un-indexed path re-parses the JSON and so hands out private copies.
    Every caller here only reads. Anything that wants to mutate a step must take the un-indexed
    path or copy the row first, or it will change what the other units on the board are showing.
    """
    idx = {"orders": {o.get("id"): o for o in db.list_collection(ORDERS)},
           "units": {u.get("id"): u for u in db.list_collection(UNITS)}}
    for key, coll in CTX_COLLS:
        idx[key] = _grouped(coll, "unitId")
    return idx


def load_ctx(unit_id, idx=None):
    """Everything about one unit, in one pass, so a gate check does not re-read six collections.

    `idx` is an optional `ctx_index()` snapshot. With one, this does no database work beyond the
    unit itself; without one it reads the collections directly, which is what every single-unit
    caller wants.
    """
    unit = (idx["units"].get(unit_id) if idx else db.get_collection_item(UNITS, unit_id)) or {}
    order = None
    if unit.get("orderId"):
        order = (idx["orders"].get(unit["orderId"]) if idx
                 else db.get_collection_item(ORDERS, unit["orderId"]))
    ctx = {"unit": unit, "order": order or {}}
    for key, coll in CTX_COLLS:
        ctx[key] = list(idx[key].get(unit_id) or []) if idx else _rows(coll, "unitId", unit_id)
    ctx["steps"] = sorted(ctx["steps"], key=lambda r: (r.get("seq") or 0))
    return ctx


def open_ncrs(ctx):
    return [n for n in ctx["ncr"]
            if _norm(n.get("status")) in OPEN_NCR_STATUSES and _norm(n.get("kind")) != "punch"]


def open_punch(ctx):
    return [n for n in ctx["ncr"]
            if _norm(n.get("kind")) == "punch" and _norm(n.get("status")) in OPEN_NCR_STATUSES]


def open_ecns(ctx):
    """An engineering change still open against the design this unit is built to.

    Reads the design-control register when the unit is linked to a commission, so a unit cannot be
    released to the shop floor while the drawing it is built from is being changed. A unit with no
    design link has nothing to check and reports none, rather than inventing a blocker.
    """
    pid = ctx["unit"].get("engProjectId")
    if not pid:
        return []
    done = {"approved", "rejected", "implemented", "closed", "cancelled"}
    return [c for c in db.list_collection("eng_changes")
            if c.get("projectId") == pid and _norm(c.get("status")) not in done]


def _has_doc(ctx, **match):
    for d in ctx["docs"]:
        if all(_norm(d.get(k)) == _norm(v) for k, v in match.items()):
            return True
    return False


def _doc_by_form(ctx, form):
    return next((d for d in ctx["docs"] if _norm(d.get("form")) == _norm(form)), None)


# ── Gate exit criteria ───────────────────────────────────────────────────────────────────────────
# One function per predicate named in ahu_route.STAGES[*]["requires"]. Each returns None when the
# criterion is met, or a sentence saying what is missing. The sentence is what the signer sees, so
# it names the specific thing rather than repeating the criterion's title.
def _p_contract_review_signed(ctx):
    o = ctx["order"]
    if not o:
        return "This unit is not linked to a customer order"
    if not (o.get("contractReviewSigned") or o.get("contractReviewBy")):
        return "Contract review AHU-FM-101 has not been signed on order %s" % (o.get("poNumber") or o.get("id") or "")
    return None


def _p_no_open_exceptions(ctx):
    ex = ctx["order"].get("openExceptions")
    n = len(ex) if isinstance(ex, list) else (int(ex or 0) if str(ex or "").strip().isdigit() else 0)
    return "%d commercial or technical exception(s) are still open on the order" % n if n else None


def _p_pin_registered(ctx):
    return None if str(ctx["unit"].get("pin") or "").strip() else \
        "The unit has no Production Identification Number"


def _p_schedule_baselined(ctx):
    return None if ctx["order"].get("scheduleBaselined") else \
        "The master schedule has not been baselined on the order"


def _p_ga_issued(ctx):
    return None if _has_doc(ctx, kind="GA drawing", status="Issued") else \
        "No general-arrangement drawing has been issued for this unit"


def _p_bom_released(ctx):
    if not ctx["bom"]:
        return "No bill of materials has been raised for this unit"
    return None if _norm(ctx["unit"].get("bomStatus")) == "released" else \
        "The bill of materials is not marked released"


def _p_selection_attached(ctx):
    if str(ctx["unit"].get("selectionRef") or "").strip():
        return None
    return None if _has_doc(ctx, kind="Selection report") else \
        "No AeroSelect selection report is attached to the unit"


def _p_no_open_ecn(ctx):
    n = len(open_ecns(ctx))
    return "%d engineering change(s) are still open on the linked design" % n if n else None


def _p_bom_fully_kitted(ctx):
    if not ctx["bom"]:
        return "No bill of materials has been raised for this unit"
    short = [b for b in ctx["bom"] if _num(b.get("kittedQty")) < _num(b.get("qty"))]
    if short:
        return "%d BOM line(s) not fully kitted, first: %s" % (
            len(short), short[0].get("partNo") or short[0].get("description") or "?")
    return None


def _p_iqc_closed(ctx):
    pend = [b for b in ctx["bom"]
            if _num(b.get("receivedQty")) > 0 and _norm(b.get("iqcStatus")) not in ("passed", "accepted", "n/a")]
    if pend:
        return "Incoming inspection is open on %d received line(s), first: %s" % (
            len(pend), pend[0].get("partNo") or pend[0].get("description") or "?")
    return None


def _p_no_shortage(ctx):
    short = [b for b in ctx["bom"] if _num(b.get("shortageQty")) > 0]
    return "%d line(s) have an open shortage" % len(short) if short else None


def _stage_steps(ctx, stage, kinds=None):
    return [s for s in ctx["steps"] if s.get("stage") == stage and not s.get("orphan")
            and (kinds is None or s.get("kind") in kinds)]


def _p_all_ops_signed(ctx):
    un = [s for s in _stage_steps(ctx, 5, {"op"}) if not is_signed(s)]
    return "%d workstation operation(s) unsigned, first: %s" % (len(un), un[0].get("code")) if un else None


def _p_all_ipqc_passed(ctx):
    un = [s for s in _stage_steps(ctx, 5, {"ipqc"}) if not is_signed(s)]
    return "%d hold point(s) not passed, first: %s" % (len(un), un[0].get("code")) if un else None


def _p_no_open_ncr(ctx):
    n = open_ncrs(ctx)
    return "%d non-conformance(s) still open, first: %s" % (
        len(n), n[0].get("ncrNo") or n[0].get("title") or "?") if n else None


def _p_assembly_checklist_complete(ctx):
    return None if _doc_by_form(ctx, "AHU-FM-501") else \
        "Final assembly checklist AHU-FM-501 is not attached"


def _p_all_tests_passed(ctx):
    un = [s for s in _stage_steps(ctx, 6, {"test"}) if not is_signed(s) and not s.get("optional")]
    return "%d test(s) not passed, first: %s" % (len(un), un[0].get("code")) if un else None


def _p_fat_signed_if_required(ctx):
    if not (ctx["unit"].get("fatRequired") or ctx["order"].get("fatRequired")):
        return None
    d = _doc_by_form(ctx, "AHU-FM-602")
    if not d:
        return "A FAT was sold with this unit and no FAT report AHU-FM-602 is attached"
    return None if _norm(d.get("status")) in ("issued", "signed", "approved") else \
        "The FAT report is attached but not signed"


def _p_punch_list_closed(ctx):
    p = open_punch(ctx)
    return "%d punch-list item(s) still open" % len(p) if p else None


def _p_dossier_complete(ctx):
    """Every document that must travel with the unit (SOP section 12.5) is attached.

    The FAT report is conditional — it is only required of a unit a FAT was sold with — so it is
    added to the required list rather than tested by a second branch.
    """
    required = [d for d in R.DOSSIER if d["always"] and d["form"]]
    if ctx["unit"].get("fatRequired") or ctx["order"].get("fatRequired"):
        required += [d for d in R.DOSSIER if d["k"] == "fat_report"]
    missing = [d["label"] for d in required if not _doc_by_form(ctx, d["form"])]
    return "The dossier is missing: %s" % ", ".join(missing) if missing else None


def _p_packing_recorded(ctx):
    return None if ctx["dispatch"] else "No packing record has been raised"


def _p_loading_photos(ctx):
    for d in ctx["dispatch"]:
        ph = d.get("photos")
        if (len(ph) if isinstance(ph, list) else _num(ph)) > 0:
            return None
    return "The loading photo set has not been uploaded"


def _p_customer_notified(ctx):
    return None if any(d.get("customerNotified") for d in ctx["dispatch"]) else \
        "The customer has not been notified of dispatch"


def _num(v):
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


PREDICATES = {
    "contract_review_signed": _p_contract_review_signed,
    "no_open_exceptions": _p_no_open_exceptions,
    "pin_registered": _p_pin_registered,
    "schedule_baselined": _p_schedule_baselined,
    "ga_issued": _p_ga_issued,
    "bom_released": _p_bom_released,
    "selection_attached": _p_selection_attached,
    "no_open_ecn": _p_no_open_ecn,
    "bom_fully_kitted": _p_bom_fully_kitted,
    "iqc_closed": _p_iqc_closed,
    "no_shortage": _p_no_shortage,
    "all_ops_signed": _p_all_ops_signed,
    "all_ipqc_passed": _p_all_ipqc_passed,
    "no_open_ncr": _p_no_open_ncr,
    "assembly_checklist_complete": _p_assembly_checklist_complete,
    "all_tests_passed": _p_all_tests_passed,
    "fat_signed_if_required": _p_fat_signed_if_required,
    "punch_list_closed": _p_punch_list_closed,
    "dossier_complete": _p_dossier_complete,
    "packing_recorded": _p_packing_recorded,
    "loading_photos": _p_loading_photos,
    "customer_notified": _p_customer_notified,
}


def gate_blockers(gate_code, ctx):
    """Why this gate cannot be signed yet — a list of sentences, empty when it can.

    A predicate this module does not implement is reported as a blocker naming itself, not skipped.
    Silently passing an unknown criterion is how a gate ends up checking nothing.
    """
    stage = next((s for s in R.STAGES if s.get("gate") == gate_code), None)
    if not stage:
        return ["%s is not a gate in the production process" % gate_code]
    out = []
    for key in stage["requires"]:
        fn = PREDICATES.get(key)
        if not fn:
            out.append("Criterion %r is not implemented — refusing rather than assuming it is met"
                       % key)
            continue
        try:
            why = fn(ctx)
        except Exception as exc:                       # a broken lookup must not read as "met"
            why = "%s could not be checked (%s)" % (R.GATE_REASONS.get(key, key), exc)
        if why:
            out.append(why)
    return out


# ── Progress and the live picture ────────────────────────────────────────────────────────────────
def unit_progress(ctx):
    steps, _err = safe_build_for(ctx["unit"], ctx["order"])
    return R.route_progress(steps, signed_codes(ctx["steps"]))


def unit_state(ctx):
    """A one-line summary of where a unit actually is: its current step, what is next, and whether
    anything is holding it."""
    unit, steps = ctx["unit"], ctx["steps"]
    live = [s for s in steps if not s.get("orphan")]
    done = signed_codes(live)
    spec, route_error = safe_build_for(unit, ctx["order"])
    nxt = R.next_steps(spec, done)
    running = [s for s in live if _norm(s.get("status")) in ("in progress", "started")]
    failed = [s for s in live if _norm(s.get("status")) == "failed"]
    # The stage a unit is IN is the stage of the work it is about to do — not the stage of the last
    # thing it finished. Those differ at every gate: passing G1 CLOSES stage 1, so a unit whose next
    # step is G2 is working in stage 2, and reporting it as stage 1 puts it on the board under the
    # stage it has just left. On a board captioned "the step it is on", that is simply wrong, and it
    # makes the process strip on the first page pile every unit into the stage behind it.
    #
    # A unit with nothing left to do keeps the stage of its last signed step: it finished there.
    if nxt:
        stage_no = nxt[0]["stage"]
    else:
        stage_no = 1
        for s in spec:
            if s["code"] in done:
                stage_no = s["stage"]
    return {
        "unitId": unit.get("id"), "pin": unit.get("pin"), "tag": unit.get("tag"),
        "family": unit.get("family"), "orderId": unit.get("orderId"),
        "progress": R.route_progress(spec, done),
        "stage": stage_no,
        "stageTitle": (R.STAGE_BY_NO.get(stage_no) or {}).get("title", ""),
        "running": [s.get("code") for s in running],
        "next": [s["code"] for s in nxt],
        "nextTitle": nxt[0]["title"] if nxt else "",
        "failed": [s.get("code") for s in failed],
        "openNcr": len(open_ncrs(ctx)),
        "signed": len(done), "total": len(spec),
        # Set only when the unit has no buildable route. The board shows the row and says so,
        # instead of the screen failing for everybody.
        "routeError": route_error,
    }


def board():
    """Every unit not yet dispatched, with where it is — the shop-floor board.

    A unit that cannot be summarised at all still gets a row saying so. This screen is the one
    people leave open on a wall, and it must not be the thing that breaks when a single record is
    malformed.
    """
    out = []
    idx = ctx_index()
    for unit in idx["units"].values():
        if _norm(unit.get("status")) in ("dispatched", "cancelled", "closed"):
            continue
        try:
            out.append(unit_state(load_ctx(unit.get("id"), idx)))
        except Exception as exc:                       # one bad row costs its own row, not the board
            out.append({"unitId": unit.get("id"), "pin": unit.get("pin"),
                        "tag": unit.get("tag"), "family": unit.get("family"),
                        "orderId": unit.get("orderId"), "progress": 0, "stage": 1,
                        "stageTitle": "", "running": [], "next": [], "nextTitle": "",
                        "failed": [], "openNcr": 0, "signed": 0, "total": 0,
                        "routeError": "This unit could not be read (%s)." % exc})
    out.sort(key=lambda s: (-(s.get("progress") or 0), s.get("pin") or ""))
    return out


# ── The as-built dossier ─────────────────────────────────────────────────────────────────────────
def dossier(unit_id):
    """Everything that makes up the unit's birth certificate, assembled in one structure.

    This is the answer to "show me the full record for this AHU": the order it was built against,
    the design it was built to, what went into it, who did each step and who signed it off, every
    measured value with the limit it was judged against, and what left the factory with it.
    """
    ctx = load_ctx(unit_id)
    unit, order = ctx["unit"], ctx["order"]
    if not unit:
        return None
    decl = unit_decl(unit)
    spec_by_code = {s["code"]: s for s in build_for(unit, order)}

    steps = []
    for row in ctx["steps"]:
        spec = spec_by_code.get(row.get("code"))
        v = R.evaluate_step(spec, readings_of(row), decl) if spec else None
        steps.append({
            "code": row.get("code"), "kind": row.get("kind"), "stage": row.get("stage"),
            "title": row.get("title"), "status": row.get("status"),
            "wi": row.get("wi"), "forms": row.get("forms"), "std": row.get("std"),
            "operator": row.get("operator"), "startedOn": row.get("startedOn"),
            "signedBy": row.get("signedBy"), "signedOn": row.get("signedOn"),
            "signatures": row.get("signatures") or [],
            "orphan": bool(row.get("orphan")),
            "verdict": v["status"] if v else None,
            "checks": v["checks"] if v else [],
        })

    required = [d for d in R.DOSSIER
                if d["always"] or (d["k"] == "fat_report" and (unit.get("fatRequired") or order.get("fatRequired")))]
    docs = [{"label": d["label"], "form": d["form"],
             "present": bool(_doc_by_form(ctx, d["form"])) if d["form"] else False,
             "doc": _doc_by_form(ctx, d["form"]) if d["form"] else None}
            for d in required]

    return {
        "unit": unit, "order": order, "declaration": decl,
        "family": R.FAMILIES.get(_norm(unit.get("family")) or "modular", {}),
        "progress": unit_progress(ctx), "state": unit_state(ctx),
        "steps": steps, "bom": ctx["bom"], "trace": ctx["trace"],
        "ncr": ctx["ncr"], "dispatch": ctx["dispatch"],
        "documents": docs,
        "missingDocuments": [d["label"] for d in docs if not d["present"]],
        "gates": [{"code": st["gate"], "title": st["gate_title"],
                   "blockers": gate_blockers(st["gate"], ctx)}
                  for st in R.STAGES if st.get("gate")],
    }
