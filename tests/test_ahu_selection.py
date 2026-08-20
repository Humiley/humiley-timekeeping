"""The AeroSelect selection handoff — reading a selection in without retyping it.

Two things these tests exist to pin down.

The first is trust. A selection document decides the airflow a unit is built to and the limit its
casing is tested against, so "probably fine" is not good enough: a document whose content hash does
not match its contents is refused, and a document that is merely unsigned is accepted but reported
UNVERIFIED — never quietly upgraded to verified.

The second is the L/F distinction. AeroSelect does not compute the EN 1886 leakage and filter-bypass
classes, because those are awarded by testing a built unit. They cross the wire as declared targets
that tests T3 and T4 still have to prove, and nothing here may present one as a measurement.
"""
import json

import pytest

import ahu_selection as S

SECRET = "shared-with-aeroselect-0123456789"


def payload(**over):
    p = {
        "project": {"number": "P-2026-014", "name": "Cleanroom Block B",
                    "client": "Vinh Phuc Pharma JSC"},
        "unit": {
            "tag": "AHU-B-01", "model": "AeroSmart AS-24", "family": "hygienic",
            "airflow_m3h": 12000, "esp_pa": 450, "voltage_v": 400,
            "coilDesignBar": 16, "cleanroom": "ISO 7",
        },
        "classes": {"D": "D1", "L": "L1", "F": "F9", "T": "T1", "TB": "TB1"},
        "performance": {"erp": {"verdict": "PASS", "sfpIntWm3s": 810.0},
                        "euroventClass": "A+"},
        "sections": [{"type": "filter_hepa"}, {"type": "cooling_coil_chw"}],
    }
    p.update(over)
    return p


def doc(secret=None, spec=S.SPEC_VERSION, ref="AS-2026-0410", **over):
    p = payload(**over)
    env = {
        "document": "selection", "specVersion": spec, "selectionRef": ref,
        "engine": "AeroSelect", "engineVersion": "2.0.0",
        "generatedOn": "2026-08-20T09:14:00Z",
    }
    env["contentHash"] = S.content_hash(env, p)
    if secret:
        env["signature"] = S.sign(env, p, secret)
    return {"aeroselect": env, "payload": p}


# ── integrity ────────────────────────────────────────────────────────────────────────────────────

def test_a_well_formed_document_parses():
    d = S.parse(doc())
    assert d["selectionRef"] == "AS-2026-0410"
    assert d["unit"]["tag"] == "AHU-B-01"


def test_it_reads_bytes_and_text_as_well_as_a_dict():
    raw = doc()
    assert S.parse(json.dumps(raw))["selectionRef"] == "AS-2026-0410"
    assert S.parse(json.dumps(raw).encode())["selectionRef"] == "AS-2026-0410"


def test_a_document_edited_after_export_is_refused():
    """The dangerous case: somebody opens the JSON and changes the airflow."""
    raw = doc()
    raw["payload"]["unit"]["airflow_m3h"] = 20000
    with pytest.raises(S.SelectionError) as e:
        S.parse(raw)
    assert "altered" in str(e.value)


def test_a_document_with_no_hash_is_refused():
    raw = doc()
    del raw["aeroselect"]["contentHash"]
    with pytest.raises(S.SelectionError) as e:
        S.parse(raw)
    assert "content hash" in str(e.value)


def test_the_hash_is_independent_of_key_order():
    """Both sides must agree on the canonical bytes or every document fails for no reason."""
    e = {"document": "selection", "specVersion": S.SPEC_VERSION, "selectionRef": "R"}
    a = {"b": 2, "a": 1, "c": {"y": 1, "x": 2}}
    b = {"a": 1, "c": {"x": 2, "y": 1}, "b": 2}
    assert S.content_hash(e, a) == S.content_hash(e, b)


def test_a_non_json_file_is_refused_with_a_useful_message():
    with pytest.raises(S.SelectionError) as e:
        S.parse(b"%PDF-1.7 not json at all")
    assert "not valid JSON" in str(e.value) or "not UTF-8" in str(e.value)


def test_an_oversized_file_is_refused_before_parsing():
    with pytest.raises(S.SelectionError) as e:
        S.parse(b"{" + b" " * (S.MAX_BYTES + 10))
    assert "too large" in str(e.value)


def test_a_file_that_is_not_a_selection_export_says_so():
    with pytest.raises(S.SelectionError) as e:
        S.parse({"aeroselect": {"document": "datasheet"}, "payload": {}})
    assert "not a selection export" in str(e.value)


def test_a_file_with_no_aeroselect_header_says_what_to_do():
    with pytest.raises(S.SelectionError) as e:
        S.parse({"unit": {"tag": "AHU-1"}})
    assert "Export it from AeroSelect" in str(e.value)


def test_a_future_spec_version_is_refused_rather_than_guessed():
    with pytest.raises(S.SelectionError) as e:
        S.parse(doc(spec=S.SPEC_VERSION + 1))
    assert "spec version" in str(e.value)


def test_the_signature_covers_the_documents_identity_not_only_its_numbers():
    """The failure this spec version exists to close. `selectionRef`, `engine`, `engineVersion` and
    `generatedOn` live in the envelope and are all written onto the unit — selectionRef is also the
    document number of the Selection report filed as gate G2's evidence. When the hash covered only
    the payload, a document could carry a perfectly valid signature and still claim to be a
    selection AeroSelect never wrote, with "Signature verified" printed over it."""
    for field, value in [("selectionRef", "TOTALLY-DIFFERENT-REF"),
                         ("engine", "NotAeroSelect"),
                         ("engineVersion", "9.9.9"),
                         ("generatedOn", "2001-01-01T00:00:00Z")]:
        raw = doc(secret=SECRET)
        raw["aeroselect"][field] = value
        with pytest.raises(S.SelectionError) as e:
            S.parse(raw, secret=SECRET)
        assert "altered" in str(e.value), field


def test_tampering_with_the_identity_breaks_the_hash_even_with_no_secret():
    """It is the HASH that carries this, so it holds on an unpaired portal too."""
    raw = doc()
    raw["aeroselect"]["selectionRef"] = "SOMEBODY-ELSES-REF"
    with pytest.raises(S.SelectionError) as e:
        S.parse(raw)
    assert "altered" in str(e.value)


def test_a_document_with_no_selection_reference_is_refused():
    with pytest.raises(S.SelectionError) as e:
        S.parse(doc(ref=""))
    assert "selection reference" in str(e.value)


# ── authenticity ─────────────────────────────────────────────────────────────────────────────────

def test_with_no_secret_configured_a_document_is_accepted_but_unverified():
    """Honest about its own state, rather than calling an unchecked document verified."""
    d = S.parse(doc())
    assert d["verified"] is False
    assert d["signed"] is False


def test_a_correctly_signed_document_verifies():
    d = S.parse(doc(secret=SECRET), secret=SECRET)
    assert d["verified"] is True and d["signed"] is True


def test_a_document_signed_with_the_wrong_secret_is_refused():
    d = doc(secret="some-other-secret")
    with pytest.raises(S.SelectionError) as e:
        S.parse(d, secret=SECRET)
    assert "does not verify" in str(e.value)


def test_an_unsigned_document_is_refused_when_a_secret_is_configured():
    with pytest.raises(S.SelectionError) as e:
        S.parse(doc(), secret=SECRET)
    assert "unsigned" in str(e.value)


def test_a_signature_does_not_survive_an_edit():
    raw = doc(secret=SECRET)
    raw["payload"]["classes"]["L"] = "L3"
    raw["aeroselect"]["contentHash"] = S.content_hash(raw["aeroselect"], raw["payload"])  # forge it
    with pytest.raises(S.SelectionError) as e:
        S.parse(raw, secret=SECRET)
    assert "does not verify" in str(e.value)


# ── what it means for the unit ───────────────────────────────────────────────────────────────────

def test_the_selection_determines_the_units_figures():
    f = S.to_unit_fields(S.parse(doc()))
    assert f["airflow"] == 12000 and f["esp"] == 450
    assert f["voltage"] == 400 and f["coilDesignBar"] == 16
    assert f["cleanroom"] == "ISO7"
    assert f["model"] == "AeroSmart AS-24"
    assert f["family"] == "hygienic"


def test_the_classes_come_across():
    f = S.to_unit_fields(S.parse(doc()))
    assert (f["classD"], f["classL"], f["classF"], f["classT"], f["classTB"]) == \
        ("D1", "L1", "F9", "T1", "TB1")


def test_leakage_and_bypass_are_reported_as_targets_a_test_must_prove():
    """AeroSelect does not compute L or F — they are declared, and T3/T4 are what establish them."""
    assert S.classes_measured_by_test(S.parse(doc())) == {"L": "T3", "F": "T4"}


def test_a_selection_that_declares_no_leakage_target_has_nothing_for_t3_to_prove():
    d = S.parse(doc(classes={"D": "D2", "T": "T2", "TB": "TB2"}))
    assert S.classes_measured_by_test(d) == {}
    assert "classL" not in S.to_unit_fields(d)


def test_provenance_travels_with_the_figures():
    f = S.to_unit_fields(S.parse(doc()))
    assert f["selectionEngine"] == "AeroSelect"
    assert f["selectionEngineVersion"] == "2.0.0"
    assert f["selectionHash"].startswith("sha256:")
    assert f["selectionVerified"] is False


def test_verified_provenance_is_recorded_when_it_was_verified():
    f = S.to_unit_fields(S.parse(doc(secret=SECRET), secret=SECRET))
    assert f["selectionVerified"] is True


def test_a_missing_value_is_left_alone_rather_than_written_blank():
    """Importing a partial selection must not erase something already known about the unit."""
    u = dict(payload()["unit"])
    u.pop("coilDesignBar")
    u.pop("cleanroom")
    f = S.to_unit_fields(S.parse(doc(unit=u)))
    assert "coilDesignBar" not in f and "cleanroom" not in f


def test_a_class_this_portal_cannot_read_is_refused_not_dropped():
    """The nastiest shape in the module. A dropped class leaves whatever the unit held before, so a
    document declaring D4 would leave a D2 unit tested against the D2 limit, silently."""
    with pytest.raises(S.SelectionError) as e:
        S.parse(doc(classes={"D": "D9", "L": "L2"}))
    assert "cannot read" in str(e.value) and "D9" in str(e.value)


def test_an_unreadable_cleanroom_class_is_refused_too():
    assert S.to_unit_fields(S.parse(doc()))["cleanroom"] == "ISO7"
    u = dict(payload()["unit"], cleanroom="Class 100")
    with pytest.raises(S.SelectionError) as e:
        S.parse(doc(unit=u))
    assert "cleanroom" in str(e.value)


def test_an_absent_class_is_still_simply_absent():
    """Refusing an unreadable value must not turn a missing one into an error."""
    d = S.parse(doc(classes={"D": "D2"}))
    f = S.to_unit_fields(d)
    assert f["classD"] == "D2" and "classL" not in f


def test_text_where_a_number_belongs_is_dropped_not_read_as_zero():
    u = dict(payload()["unit"], airflow_m3h="n/a", voltage_v="")
    f = S.to_unit_fields(S.parse(doc(unit=u)))
    assert "airflow" not in f and "voltage" not in f


# ── family ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expect", [
    ("hygienic", "hygienic"), ("Cleanroom", "hygienic"), ("Rooftop", "outdoor"),
    ("built-up", "modular"), ("CAU", "modular"), ("Compact", "packaged"),
])
def test_the_family_maps_onto_the_four_design_standards(given, expect):
    u = dict(payload()["unit"], family=given)
    assert S.family_of(S.parse(doc(unit=u))) == expect


def test_an_unrecognised_family_is_left_for_a_person_rather_than_guessed():
    """The family decides which workstations and which tests apply — guessing it builds the wrong
    unit to the wrong route."""
    u = dict(payload()["unit"], family="something new", unitType="")
    d = S.parse(doc(unit=u))
    assert S.family_of(d) is None
    assert "family" not in S.to_unit_fields(d)


# ── re-importing ─────────────────────────────────────────────────────────────────────────────────

def test_the_same_selection_is_recognised_as_the_same():
    d = S.parse(doc())
    unit = S.to_unit_fields(d)
    assert S.is_same_selection(d, unit) is True


def test_a_changed_selection_lists_exactly_what_moved():
    first = S.parse(doc())
    unit = S.to_unit_fields(first)
    u = dict(payload()["unit"], airflow_m3h=14000)
    second = S.parse(doc(unit=u, classes={"D": "D1", "L": "L2", "F": "F9", "T": "T1", "TB": "TB1"}))
    assert S.is_same_selection(second, unit) is False
    moved = dict((f, (a, b)) for f, a, b in S.differences(second, unit))
    assert moved["airflow"] == (12000, 14000)
    assert moved["classL"] == ("L1", "L2")
    assert "esp" not in moved


def test_a_number_that_did_not_move_is_not_reported_as_a_change():
    """12000 and 12000.0 are the same airflow. Stringly comparison put a field that had not moved
    next to the ones that had, in the one message somebody reads before superseding a unit already
    being built."""
    d = S.parse(doc())
    moved = [f for f, _a, _b in S.differences(d, {"airflow": 12000, "esp": 450})]
    assert "airflow" not in moved and "esp" not in moved


def test_losing_the_shared_secret_shows_up_as_a_change():
    """Re-importing the same document on a portal that can no longer verify it downgrades the unit
    to unverified — honest, but somebody confirming should be able to see it happen."""
    verified = S.to_unit_fields(S.parse(doc(secret=SECRET), secret=SECRET))
    assert verified["selectionVerified"] is True
    unverified = S.parse(doc(secret=SECRET))          # same document, no secret this side
    moved = dict((f, (a, b)) for f, a, b in S.differences(unverified, verified))
    assert moved["selectionVerified"] == (True, False)


def test_a_unit_with_no_selection_yet_shows_everything_as_a_change():
    assert S.differences(S.parse(doc()), {}) != []


def test_the_summary_reads_like_something_a_person_would_confirm():
    s = S.summary(S.parse(doc()))
    assert "AS-2026-0410" in s and "AHU-B-01" in s and "hygienic" in s


# ── the example the spec hands to AeroSelect ─────────────────────────────────────────────────────

@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "UNDETERMINED", "NOT_ASSESSED"])
def test_the_erp_verdict_is_carried_verbatim_including_the_undetermined_states(verdict):
    """AeroSelect's ErP verdict is TRI-STATE, not PASS/FAIL.

    Its resolver withholds a verdict when a required input was never declared, and exports
    UNDETERMINED rather than the PASS its legacy `erp.label` field would have claimed. The portal
    must carry that through untouched: coercing an unknown verdict to PASS would put a compliance
    claim on a unit whose compliance nobody established, and coercing it to FAIL would condemn one
    for the same absence of evidence.

    So this field is PROVENANCE, not a validated enum — whatever AeroSelect concluded, recorded as
    it concluded it. Pinned because the exporting side asked whether we accept these values, and a
    promise in a message is not an answer a year from now.
    """
    p = {"unit": {"tag": "AHU-1", "family": "modular"},
         "performance": {"erp": {"verdict": verdict, "sfpIntWm3s": 810}}}
    env = {"document": "selection", "specVersion": S.SPEC_VERSION, "selectionRef": "AS-1",
           "engine": "AeroSelect", "engineVersion": "2.0.0",
           "generatedOn": "2026-01-01T00:00:00Z"}
    env["contentHash"] = S.content_hash(env, p)
    f = S.to_unit_fields(S.parse({"aeroselect": env, "payload": p}))
    assert f["selectionErp"] == verdict


def test_a_selection_that_omits_the_unmodelled_fields_still_imports():
    """AeroSelect genuinely does not model supply voltage, coil design pressure or cleanroom class,
    and declines to invent them. Omission must therefore be ordinary, not an error — and must not
    blank a value the unit already holds. What the portal does instead is refuse to JUDGE the tests
    that depend on them, which is the honest outcome."""
    p = {"unit": {"tag": "AHU-1", "family": "modular"},
         "classes": {"D": "D2", "L": "L2"}}
    env = {"document": "selection", "specVersion": S.SPEC_VERSION, "selectionRef": "AS-2",
           "engine": "AeroSelect", "engineVersion": "2.0.0",
           "generatedOn": "2026-01-01T00:00:00Z"}
    env["contentHash"] = S.content_hash(env, p)
    f = S.to_unit_fields(S.parse({"aeroselect": env, "payload": p}))
    for absent in ("voltage", "coilDesignBar", "cleanroom"):
        assert absent not in f, "%s must be left alone, not written blank" % absent
    assert f["classL"] == "L2"


def test_the_worked_example_carries_no_whole_number_float():
    """A whole-number float makes the example unreproducible by the side it is FOR.

    Python renders 810.0 with the trailing .0; JavaScript has no int/float distinction and writes
    810. The example shipped with `sfpIntWm3s: 810.0`, so the AeroSelect exporter's first run
    against it would have failed with no bug behind it — and the obvious fix would have been to bend
    their canonicaliser until it matched, breaking the live path that works.

    tests/handoff_example_cross_language.js proves the hashes agree; this states the underlying rule
    on the Python side, where the file is generated.
    """
    import json
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "docs", "examples",
                           "aeroselect-selection-example.json"), encoding="utf-8") as fh:
        doc = json.load(fh)

    offenders = []

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, "%s.%s" % (path, k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, "%s[%d]" % (path, i))
        elif isinstance(v, float) and v.is_integer():
            offenders.append("%s = %r" % (path, v))

    walk(doc["payload"], "payload")
    walk(doc["aeroselect"], "aeroselect")
    assert not offenders, (
        "unreproducible from JavaScript — write these as integers: " + ", ".join(offenders))


def test_the_worked_example_in_the_spec_actually_imports():
    """docs/examples/aeroselect-selection-example.json is what the AeroSelect side will assert its
    exporter against. A spec whose own example fails the check it documents is worse than none, so
    the example is generated (tools/make_selection_example.py) and pinned here."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "docs", "examples", "aeroselect-selection-example.json")
    with open(path, encoding="utf-8") as fh:
        d = S.parse(fh.read())
    assert d["selectionRef"] == "AS-2026-0410"
    assert d["verified"] is False           # unsigned on purpose — imports on any portal
    assert S.classes_measured_by_test(d) == {"L": "T3", "F": "T4"}
    f = S.to_unit_fields(d)
    assert f["family"] == "hygienic" and f["airflow"] == 12000 and f["classL"] == "L1"
