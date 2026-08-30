"""Who may see the commercial position of a job, and who may only work on it.

The QS registers are deliberately NOT one access level. That split is the easiest decision in the
module to get wrong in the convenient direction — "it is all project data, put it at staff" hands
every site account the job's margin; "it is all money, put it at manager" stops a site engineer
opening the bill they are measuring against, which is the whole job.

  pm_qs_boq       staff    the CONTRACT bill. The client signed those rates and has their own copy,
  pm_qs_measure   staff    and a site engineer who cannot open it cannot measure against it.
  pm_qs_daywork   staff    Our own cost and margin live in est_* and pm_qs_cvr, not here.

  pm_qs_variations   manager   what we are claiming, and
  pm_qs_materials    manager   what we are making. These match pm_costs.
  pm_qs_valuations   manager
  pm_qs_cvr          manager

Project scoping still applies to the staff-readable three through _pm_visible_projects, so "staff"
means the site team of THAT job, not every account in the company.

Asserted against app.py's own tables rather than against a running server: the dev database has a
single admin employee, so a live check would have nothing below manager to sign in as — and a check
with nothing to examine is worse than no check.
"""
import re

import app
import qsurvey


H = app.Handler
QS = ("pm_qs_boq", "pm_qs_measure", "pm_qs_daywork", "pm_qs_variations",
      "pm_qs_materials", "pm_qs_valuations", "pm_qs_cvr")

SITE_LEVEL = {"pm_qs_boq", "pm_qs_measure", "pm_qs_daywork"}
COMMERCIAL_LEVEL = {"pm_qs_variations", "pm_qs_materials", "pm_qs_valuations", "pm_qs_cvr"}


def _src():
    with open(app.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
        return fh.read()


def test_every_qs_register_is_a_known_collection():
    """A collection missing from COLLECTIONS is refused by /api/coll with "Unknown collection" —
    the register renders empty and reads as "nothing ever happened here"."""
    missing = sorted(c for c in QS if c not in H.COLLECTIONS)
    assert not missing, "not in COLLECTIONS: %s" % ", ".join(missing)


def test_the_site_registers_are_readable_by_the_site():
    """The bill, the measurement and the daywork sheets are the site team's working documents. Put
    at manager, a site engineer could not open the bill they are measuring against."""
    for c in sorted(SITE_LEVEL):
        assert H.READ_MIN.get(c) == "staff", (
            "%s is at %r — a site engineer cannot measure against a bill they cannot read."
            % (c, H.READ_MIN.get(c)))


def test_the_commercial_registers_match_pm_costs():
    """What we are claiming and what we are making. These are the same class of fact as pm_costs and
    must not drift away from it — if pm_costs is ever raised, this test says these have to move
    with it rather than silently becoming the loosest thing on the project."""
    for c in sorted(COMMERCIAL_LEVEL):
        assert H.READ_MIN.get(c) == H.READ_MIN["pm_costs"], (
            "%s is at %r but pm_costs is at %r" % (c, H.READ_MIN.get(c), H.READ_MIN["pm_costs"]))


def test_every_qs_register_states_a_level():
    """Absent from READ_MIN is not "unclassified", it is DEFAULT-ALLOW: /api/coll serves an unlisted
    collection to every account holding the owning app. That is the exact shape of a leak this
    codebase has already had once."""
    missing = sorted(c for c in QS if c not in H.READ_MIN)
    assert not missing, (
        "these QS registers are not in READ_MIN, so they are served to every account with the "
        "Projects app: %s" % ", ".join(missing))


def test_the_summary_endpoint_is_gated_at_manager():
    """/api/qs/summary carries the valuation, the exposure and the margin in one payload. The
    per-collection levels above would not protect it — it reads the registers server-side."""
    src = _src()
    i = src.index("def _qs_may_read")
    body = src[i:src.index("def _qs_rows")]
    assert '_lvl_rank("manager")' in body, "_qs_may_read no longer checks the level"
    assert "_pm_visible_projects" in body, "_qs_may_read no longer checks project visibility"
    assert '_app_blocked(u, "pm")' in body, "_qs_may_read no longer honours the Projects app switch"


def test_every_qs_endpoint_runs_the_same_gate():
    """Four endpoints, one gate. A new one that forgets it is a hole the collection levels cannot
    close, because these read the registers on the server's behalf."""
    src = _src()
    for fn in ("_qs_summary_ep", "_qs_valuation_ep", "_qs_variation_ep", "_qs_cvr_ep",
               "_qs_boq_ep"):
        i = src.index("def %s(" % fn)
        head = src[i:i + 900]
        assert "_qs_may_read" in head, "%s does not call _qs_may_read" % fn


def test_a_valuation_cannot_be_moved_through_the_generic_route():
    """A valuation snapshots itself when it is submitted (qsurvey rule 5). Moved through /api/coll
    it would change status with no snapshot, and every later read would recompute a claim that had
    already gone to the client."""
    assert "pm_qs_valuations" in H.ISSUED_ONLY
    assert H.ISSUED_ONLY["pm_qs_valuations"][1] == "/api/qs/valuation"


def test_a_variation_can_be_created_but_its_lifecycle_cannot_be_posted():
    """The register was briefly unreachable: ISSUED_ONLY refused creation and the endpoint only
    moves an EXISTING variation, so there was no way to make one. What must not be posted is the
    lifecycle — the four fields that decide whether the money enters a valuation."""
    assert "pm_qs_variations" not in H.ISSUED_ONLY, (
        "listing pm_qs_variations here makes the register impossible to create in — "
        "/api/qs/variation only moves an existing one")
    src = _src()
    add = src[src.index('if name in ("pm_qs_variations",):'):]
    add = add[:add.index('if name.startswith("eng_"):')]
    for k in ("status", "agreedValue", "agreedOn", "basis"):
        assert '"%s"' % k in add, "_coll_add does not strip %r from a new variation" % k
    assert "qsurvey.V_IDENTIFIED" in add, "a new variation does not start at the first status"

    upd = src[src.index('if name == "pm_qs_variations":'):]
    upd = upd[:upd.index('if name.startswith("eng_"):')]
    for k in ("status", "agreedValue", "agreedOn", "basis"):
        assert '"%s"' % k in upd, (
            "_coll_update does not preserve %r, so a whole-document PATCH from the edit form could "
            "move an agreed variation back to whatever the browser was holding" % k)


def test_the_form_does_not_offer_a_field_the_server_drops():
    """A field the server silently strips is worse than no field: it reads as saved. The variation
    form must not carry the four the write path removes."""
    with open("templates/index.html", encoding="utf-8") as fh:
        html = fh.read()
    i = html.index("pm_qs_variations: { title: 'Variation'")
    form = html[i:html.index("pm_qs_daywork: { title:", i)]
    for k in ("agreedValue", "agreedOn", "basis"):
        assert ("k: '%s'" % k) not in form, (
            "the variation form offers %r, which /api/coll strips — it would read as saved and "
            "would not be" % k)
    assert "k: 'status'" not in form


def test_the_frontend_lifecycle_mirrors_the_engine():
    """The buttons offer the next legal step. The SERVER is the authority and re-checks every
    transition, but a button that offers an impossible move and then shows a 409 wastes an
    afternoon — and a MISSING one hides a step that is legal."""
    with open("templates/index.html", encoding="utf-8") as fh:
        html = fh.read()
    block = html[html.index("const _QS_VFLOW = {"):]
    block = block[:block.index("};") + 2]
    ui = {}
    for m in re.finditer(r"(\w+): \[([^\]]*)\]", block):
        ui[m.group(1)] = [x.strip().strip("'") for x in m.group(2).split(",") if x.strip()]
    assert ui, "could not read _QS_VFLOW out of index.html"
    engine = {k: list(v) for k, v in qsurvey.VARIATION_FLOW.items()}
    assert ui == engine, (
        "the variation lifecycle on screen disagrees with qsurvey.VARIATION_FLOW.\n"
        "  screen: %s\n  engine: %s" % (ui, engine))
