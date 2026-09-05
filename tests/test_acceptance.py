"""The acceptance dossier — the rules that decide whether a minute may be signed.

Checked against Nghị định 06/2021/NĐ-CP Điều 12, 21, 23, 24; Luật Xây dựng Điều 123, 124; and
PMBOK 6 §5.5 Validate Scope / §8.3 Control Quality.

The failure this file exists to prevent is the one that costs a project a month: a completion
acceptance signed while the work underneath it was never accepted, or while an open defect that
affects load-bearing capacity is sitting in the punch list. Both are legal in the sense that nothing
stops you typing them; neither survives a client's audit or the construction authority's check.
"""
import acceptance as A


# ── the catalogue is internally consistent ───────────────────────────────────────────────────────

def test_every_type_names_parties_and_prerequisites_that_exist():
    for t in A.ACCEPTANCE_TYPES:
        for p in t["parties"]:
            assert A.party(p), "%s names an unknown party %r" % (t["key"], p)
        for r in t.get("requires", []) + t.get("expects", []):
            assert A.acceptance_type(r), "%s names an unknown prerequisite %r" % (t["key"], r)
        assert t["law"], "%s cites no legal basis" % t["key"]
        assert t["pmbok"], "%s maps to no PMBOK process" % t["key"]


def test_the_prerequisite_chain_has_no_cycle():
    """A cycle would make every dossier in it permanently unsignable, with a message that reads
    like a data problem."""
    seen = {}

    def depth(key, trail):
        assert key not in trail, "prerequisite cycle: %s" % " -> ".join(trail + [key])
        if key in seen:
            return seen[key]
        t = A.acceptance_type(key) or {}
        d = 1 + max([0] + [depth(r, trail + [key]) for r in t.get("requires", [])])
        seen[key] = d
        return d

    for t in A.ACCEPTANCE_TYPES:
        depth(t["key"], [])


def test_every_type_carries_both_languages_so_a_printed_sheet_is_bilingual():
    """The minute prints a Vietnamese title above an English one. It must NOT pick a language from
    the operator's UI setting — an English session printed "BIÊN BẢN NGHIỆM THU ACCEPTANCE OF
    CONSTRUCTION WORK" on the line that has to be Vietnamese. The sheet is bilingual by
    construction, which needs both halves present on every type."""
    for t in A.ACCEPTANCE_TYPES:
        assert t["vi"].strip() and t["en"].strip(), t["key"]
        assert t["vi"] != t["en"], t["key"]
    for p in A.PARTIES:
        assert p["vi"] and p["en"] and p["role_vi"] and p["role_en"], p["key"]


def test_a_basis_row_is_prefilled_only_when_the_text_is_a_standing_statement():
    """"Theo bản vẽ thi công được phê duyệt" is what the row SAYS on every acceptance form — it is
    content. "Tiêu chuẩn áp dụng cho công tác này" is an instruction to whoever is filling it in,
    and printing it on a signed minute produces a document that appears to cite a standard and
    cites nothing."""
    rows = {b["key"]: b for b in A.default_basis()}
    assert rows["drawing"]["title"] and rows["method"]["title"]
    assert rows["spec"]["title"] == "" and rows["standard"]["title"] == "" \
        and rows["procedure"]["title"] == ""
    # …and the instruction is still available, as the field's placeholder
    for b in A.BASIS_ROWS:
        assert b["hint_vi"] and b["hint_en"], b["key"]


def test_every_standard_belongs_to_a_real_discipline():
    for s in A.STANDARDS:
        for d in s["disc"]:
            assert d in A.DISCIPLINE_CODES, "%s is filed under unknown discipline %r" % (s["code"], d)


def test_every_seeded_form_belongs_to_a_real_discipline_and_has_lines():
    codes = set()
    for f in A.FORM_LIBRARY:
        assert f["disc"] in A.DISCIPLINE_CODES, "%s: unknown discipline" % f["code"]
        assert f["code"] not in codes, "duplicate form code %s" % f["code"]
        codes.add(f["code"])
        assert f["items"], "%s has no checklist lines" % f["code"]


def test_standard_label_writes_the_edition_the_way_the_form_does():
    assert A.standard_label({"code": "TCVN 4453", "edition": "1995"}) == "TCVN 4453:1995"
    assert A.standard_label({"code": "QCVN 06", "edition": "2022/BXD"}) == "QCVN 06:2022/BXD"
    assert A.standard_label({"code": "TCVN 1651", "edition": "bộ / series"}) == "TCVN 1651 bộ / series"
    assert A.standard_label({"code": "TCVN 9999", "edition": ""}) == "TCVN 9999"


def test_standards_for_a_discipline_always_includes_the_general_ones():
    ele = A.standards_for("ELE")
    codes = [s["code"] for s in ele]
    assert "TCVN 9207" in codes           # its own
    assert "TCVN 4055" in codes           # the GEN one, appended
    # …and does not silently return the whole catalogue
    assert "TCVN 4513" not in codes       # a plumbing standard has no business on an electrical form


def test_an_unknown_discipline_returns_the_whole_catalogue_rather_than_nothing():
    """An imported register can carry a code this app has never heard of. Offering every standard is
    unhelpful; offering none makes the field unfillable, which is worse."""
    assert A.standards_for("ZZZ") == A.STANDARDS


# ── results: what the register actually receives ────────────────────────────────────────────────

def test_results_are_read_in_both_languages_and_from_a_spreadsheet():
    for v in ("Đạt", "dat", "Pass", "P", "ok", "YES"):
        assert A._res(v) == A.RESULT_PASS, v
    for v in ("Không đạt", "khong dat", "K.Đạt", "Fail", "KĐ", "no"):
        assert A._res(v) == A.RESULT_FAIL, v
    for v in ("N/A", "na", "Không áp dụng"):
        assert A._res(v) == A.RESULT_NA, v


def test_an_unreadable_result_is_pending_never_pass():
    """The one direction that must not be guessed. A cell reading "see note" or "?" closes nothing."""
    for v in ("", None, "?", "see note", "chờ", "xyz"):
        assert A._res(v) == A.RESULT_PENDING, repr(v)


def test_progress_percentage_is_of_the_applicable_lines_not_of_all_of_them():
    items = [{"result": "Đạt"}] * 4 + [{"result": "N/A"}] * 6
    p = A.checklist_progress(items)
    assert (p["total"], p["applicable"], p["pass"], p["na"]) == (10, 4, 4, 6)
    assert p["pct"] == 100          # not 40 — the six N/A lines are not work left to do


def test_a_failed_line_beats_unchecked_lines():
    """A checklist with one failure and three blanks has already established the answer. Reporting
    'not checked' there lets a failure hide behind an incomplete form."""
    assert A.dossier_result([{"result": "Fail"}, {}, {}, {}]) == A.RESULT_FAIL


def test_an_empty_checklist_is_pending_not_pass():
    assert A.dossier_result([]) == A.RESULT_PENDING
    assert A.dossier_result([{"result": "N/A"}, {"result": "N/A"}]) == A.RESULT_PENDING


def test_a_fully_passed_checklist_is_pass():
    assert A.dossier_result([{"result": "Đạt"}, {"result": "N/A"}, {"result": "Pass"}]) == A.RESULT_PASS


# ── numbering ────────────────────────────────────────────────────────────────────────────────────

def test_the_two_series_are_rendered_from_their_templates():
    assert A.render_number("{PREFIX}-ARF-{DISC}-{SEQ}", prefix="SLPXA-RIC-ME", disc="ELE", seq=1) \
        == "SLPXA-RIC-ME-ARF-ELE-001"
    assert A.render_number("{PREFIX}-{DISC}-{SEQ}", prefix="SLPXA-RIC-ME", disc="ELE", seq=12) \
        == "SLPXA-RIC-ME-ELE-012"


def test_a_template_typo_is_left_visible_rather_than_blanked():
    """`{DISK}` on the screen gets fixed. A number that silently drops the discipline does not."""
    assert "{DISK}" in A.render_number("{PREFIX}-{DISK}-{SEQ}", prefix="ABC", seq=3)


def test_a_sequence_past_999_is_not_truncated():
    assert A.render_number("{SEQ}", seq=1000) == "1000"
    assert A.render_number("{SEQ}", seq=7) == "007"


def test_next_seq_continues_from_the_highest_not_from_the_count():
    rows = [{"arfNo": "P-ARF-001"}, {"arfNo": "P-ARF-002"}, {"arfNo": "P-ARF-007"}]
    assert A.next_seq(rows, "arfNo") == 8
    assert A.next_seq([], "arfNo") == 1
    assert A.next_seq([{"arfNo": ""}, {"arfNo": "no-digits"}], "arfNo") == 1


# ── defects: Điều 24 khoản 3 ─────────────────────────────────────────────────────────────────────

def test_the_three_named_consequences_block_and_a_cosmetic_one_does_not():
    for impact in ("structural", "safety", "function"):
        assert A.blocking_defects([{"impact": impact, "status": "Open"}]), impact
    assert not A.blocking_defects([{"impact": "cosmetic", "status": "Open"}])


def test_a_closed_defect_blocks_nothing_whatever_it_touched():
    assert not A.blocking_defects([{"impact": "structural", "status": "Closed"}])


def test_two_identical_blocking_defects_are_both_counted():
    """They compare equal as dicts. Splitting the punch list with `not in` counted the second copy
    as an ordinary defect and downgraded it to a warning."""
    d = {"impact": "safety", "status": "Open", "description": "Nắp hố ga thiếu"}
    r = A.readiness({"accType": "work", "minuteFile": "x.pdf"}, [{"result": "Đạt"}], [dict(d), dict(d)],
                    accepted_types=[], signed_parties=A.required_parties("work"))
    blocking = [x for x in r if x["code"] == "defects_blocking"][0]
    assert "2" in blocking["vi"]
    assert not [x for x in r if x["code"] == "defects_open"]


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────

def _ok_work():
    """A work acceptance with nothing wrong with it."""
    return dict(dossier={"accType": "work", "minuteFile": "BBNT-001.pdf"},
                items=[{"result": "Đạt"}, {"result": "Đạt"}],
                defects=[],
                accepted_types=[],
                signed_parties=[A.PARTY_CONTRACTOR, A.PARTY_SUPERVISOR])


def test_a_complete_work_acceptance_can_be_signed():
    assert A.can_accept(**_ok_work())


def test_an_unchecked_line_blocks():
    a = _ok_work(); a["items"] = [{"result": "Đạt"}, {}]
    assert [b["code"] for b in A.blockers(**a)] == ["checklist_pending"]


def test_a_failed_line_blocks():
    a = _ok_work(); a["items"] = [{"result": "Đạt"}, {"result": "Không đạt"}]
    assert "checklist_failed" in [b["code"] for b in A.blockers(**a)]


def test_a_dossier_with_no_checklist_at_all_blocks():
    a = _ok_work(); a["items"] = []
    assert "no_checklist" in [b["code"] for b in A.blockers(**a)]


def test_a_checklist_that_is_entirely_not_applicable_blocks():
    """It proves nothing. Signing it records an inspection that examined no criterion."""
    a = _ok_work(); a["items"] = [{"result": "N/A"}, {"result": "N/A"}]
    assert "all_na" in [b["code"] for b in A.blockers(**a)]


def test_a_missing_signature_blocks_and_names_the_party():
    a = _ok_work(); a["signed_parties"] = [A.PARTY_CONTRACTOR]
    codes = [b["code"] for b in A.blockers(**a)]
    assert "sign_supervisor" in codes
    assert "sign_contractor" not in codes


def test_completion_acceptance_refuses_while_no_work_has_been_accepted():
    """Điều 24(2), and Validate Scope's 'verified deliverables' input. This is the one rule the
    whole module exists for."""
    r = A.blockers(
        dossier={"accType": "handover_part", "clearances": [], "minuteFile": "x.pdf"},
        items=[{"result": "Đạt"}], defects=[],
        accepted_types=[],
        signed_parties=A.required_parties("handover_part"))
    assert "requires_work" in [b["code"] for b in r]


def test_completion_acceptance_passes_the_chain_once_the_work_is_accepted():
    r = A.blockers(
        dossier={"accType": "handover_part", "clearances": [], "minuteFile": "x.pdf"},
        items=[{"result": "Đạt"}], defects=[],
        accepted_types=["work"],
        signed_parties=A.required_parties("handover_part"))
    assert "requires_work" not in [b["code"] for b in r]


def test_an_expected_but_not_required_predecessor_warns_and_does_not_block():
    """Điều 23 stage acceptance happens 'where the client and contractor agree'. Turning that into
    a requirement would stop projects that legitimately do not use one."""
    a = dict(dossier={"accType": "handover_part", "clearances": [], "minuteFile": "x.pdf"},
             items=[{"result": "Đạt"}], defects=[], accepted_types=["work"],
             signed_parties=A.required_parties("handover_part"))
    all_reasons = A.readiness(**a)
    stage = [x for x in all_reasons if x["code"] == "expects_stage"]
    assert stage and stage[0]["blocks"] is False


def test_a_missing_fire_clearance_blocks_a_completion_acceptance():
    d = {"accType": "handover_all", "minuteFile": "x.pdf",
         "clearances": [{"key": "fire", "applies": True, "ref": ""}]}
    codes = [b["code"] for b in A.blockers(
        dossier=d, items=[{"result": "Đạt"}], defects=[],
        accepted_types=["handover_part", "work"],
        signed_parties=A.required_parties("handover_all"))]
    assert "clearance_fire" in codes


def _all_cleared(**over):
    """Every default-on clearance evidenced; the default-off ones left off."""
    rows = [dict(c, ref="NT-%s/2026" % c["key"]) for c in A.default_clearances() if c["applies"]]
    for k, v in over.items():
        rows = [r for r in rows if r["key"] != k] + ([v] if v else [])
    return rows


def test_a_clearance_that_is_off_by_default_needs_no_explanation_for_staying_off():
    """"Only where installed" — a warehouse with no lift is not a finding."""
    d = {"accType": "handover_all", "minuteFile": "x.pdf", "clearances": _all_cleared()}
    codes = [b["code"] for b in A.blockers(
        dossier=d, items=[{"result": "Đạt"}], defects=[],
        accepted_types=["handover_part", "work"],
        signed_parties=A.required_parties("handover_all"))]
    assert not [c for c in codes if c.startswith("clearance")], codes


def test_switching_OFF_a_default_on_clearance_needs_a_recorded_reason():
    """Fire safety applies to most works. Turning it off is a decision, and a decision that says
    nothing is indistinguishable from clicking past the check."""
    off = {"key": "fire", "applies": False, "ref": "", "reason": ""}
    d = {"accType": "handover_all", "minuteFile": "x.pdf", "clearances": _all_cleared(fire=off)}
    codes = [b["code"] for b in A.blockers(
        dossier=d, items=[{"result": "Đạt"}], defects=[],
        accepted_types=["handover_part", "work"],
        signed_parties=A.required_parties("handover_all"))]
    assert "clearance_off_fire" in codes

    off["reason"] = "Hạng mục không thuộc đối tượng thẩm duyệt PCCC theo phụ lục V."
    d["clearances"] = _all_cleared(fire=off)
    codes2 = [b["code"] for b in A.blockers(
        dossier=d, items=[{"result": "Đạt"}], defects=[],
        accepted_types=["handover_part", "work"],
        signed_parties=A.required_parties("handover_all"))]
    assert not [c for c in codes2 if c.startswith("clearance")], codes2


def test_an_empty_clearances_array_does_not_satisfy_article_24_2():
    """The bypass this rule exists to close. The list of what must be evidenced comes from the
    acceptance TYPE; the record supplies the evidence. Reading the list off the record meant an
    import, a stale row, or simply a browser sending `clearances: []` cleared the whole article by
    having nothing in it to check."""
    d = {"accType": "handover_all", "minuteFile": "x.pdf", "clearances": []}
    codes = [b["code"] for b in A.blockers(
        dossier=d, items=[{"result": "Đạt"}], defects=[],
        accepted_types=["handover_part", "work"],
        signed_parties=A.required_parties("handover_all"))]
    assert "clearance_fire" in codes and "clearance_environment" in codes


def test_a_work_acceptance_is_not_asked_for_clearances_at_all():
    """Điều 24's clearances belong to completion. Asking a slab-opening inspection for a fire
    certificate would train people to tick past the check that matters."""
    a = _ok_work()
    a["dossier"] = {"accType": "work", "minuteFile": "x.pdf",
                    "clearances": A.default_clearances()}
    assert A.can_accept(**a)


def test_an_unknown_type_still_demands_the_two_signatures_article_21_always_requires():
    assert A.required_parties("something-imported") == [A.PARTY_CONTRACTOR, A.PARTY_SUPERVISOR]


def test_every_blocking_reason_is_written_in_both_languages():
    """A refusal nobody on site can read is a refusal that gets routed around."""
    reasons = A.readiness(
        dossier={"accType": "handover_all", "clearances": A.default_clearances()},
        items=[{"result": "Không đạt"}, {}],
        defects=[{"impact": "structural", "status": "Open"}, {"impact": "cosmetic", "status": "Open"}],
        accepted_types=[], signed_parties=[])
    assert len(reasons) > 6
    for r in reasons:
        assert r["vi"].strip() and r["en"].strip(), r["code"]
        assert r["vi"] != r["en"], r["code"]


# ── the snapshot ─────────────────────────────────────────────────────────────────────────────────

def test_a_dossier_takes_a_copy_of_the_form_not_a_reference_to_it():
    """Rewording a library line must not change what a dossier signed last month says."""
    f = A.form("ELE-202")
    rows = A.snapshot_items(f)
    assert len(rows) == len(f["items"])
    assert rows[0]["seq"] == 1 and rows[0]["result"] == ""
    rows[0]["textVi"] = "CHANGED"
    assert f["items"][0]["vi"] != "CHANGED"


def test_snapshot_of_a_missing_form_is_empty_rather_than_an_error():
    assert A.snapshot_items(None) == []
    assert A.snapshot_items({}) == []


# ── the payload the browser gets ────────────────────────────────────────────────────────────────

def test_the_catalogue_carries_every_list_the_screens_render_from():
    c = A.catalogue()
    for k in ("disciplines", "types", "parties", "statuses", "results", "clearances", "basis",
              "defectImpacts", "standards", "forms", "numberTokens", "defaults", "note"):
        assert c.get(k), k


def test_the_catalogue_says_out_loud_that_the_standards_list_is_not_an_authority():
    """The one claim in this module that will go stale on its own. It has to be visible on the
    screen that uses it, not only in a docstring nobody opens."""
    note = A.catalogue()["note"]
    assert "QA/QC" in note["en"] and "QA/QC" in note["vi"]
    assert "not an authority" in note["en"]


# ── who signs, and what the portal can honestly claim about it ───────────────────────────────────

def test_a_party_counts_as_signed_when_a_signatory_is_named_on_the_minute():
    """Only the contractor has a portal account. The consultant and the client sign the printed
    sheet, so what the app can check is that their block is not blank when the form is issued."""
    d = {"signContractor": "Nguyễn Văn A", "signSupervisor": "  ", "signClient": "Trần B"}
    assert set(A.signed_parties(d)) == {A.PARTY_CONTRACTOR, A.PARTY_CLIENT}


def test_every_signatory_field_names_a_real_party_and_every_party_has_a_field():
    assert set(A.SIGNATORY_FIELDS) == set(A.PARTY_KEYS)


def test_an_acceptance_with_no_scan_of_the_signed_minute_is_refused():
    """The commonest thing missing from a dossier assembled at the end of a job rather than as it
    went: a register row saying Accepted with nothing behind it."""
    a = _ok_work()
    a["dossier"] = {"accType": "work"}
    assert "no_minute" in [b["code"] for b in A.blockers(**a)]


# ══ the checklist library ════════════════════════════════════════════════════════════════════════
#
# 97 forms of content nobody will read line by line again. What a test can check is the properties
# that make it USABLE — and the one property that makes it honest.

import acceptance_forms as FL


def test_the_library_covers_every_discipline_the_app_offers():
    """A discipline in the dropdown with no forms behind it is a dead end somebody finds at the
    point of compiling a dossier."""
    have = {f["disc"] for f in FL.LIBRARY}
    assert have == set(A.DISCIPLINE_CODES), "no forms for: %s" % sorted(set(A.DISCIPLINE_CODES) - have)


def test_form_codes_are_unique_and_shaped_like_a_document_number():
    import re
    codes = [f["code"] for f in FL.LIBRARY]
    dups = sorted({c for c in codes if codes.count(c) > 1})
    assert not dups, "duplicate form codes: %s" % dups
    bad = [c for c in codes if not re.match(r"^[A-Z]{2,4}-\d{3}$", c)]
    assert not bad, "form codes that will not sort or cite cleanly: %s" % bad


def test_every_checklist_line_is_written_in_both_languages():
    """A consultant reads the Vietnamese and a client's technical adviser often reads the English.
    A line in one language only is a line one of them cannot check."""
    bad = []
    for f in FL.LIBRARY:
        for i, it in enumerate(f["items"]):
            if not it["vi"] and not it["en"]:
                continue                      # the deliberate blank line on the blank form
            if not (it["vi"].strip() and it["en"].strip()):
                bad.append("%s line %d" % (f["code"], i + 1))
    assert not bad, bad[:10]


def test_every_real_line_says_how_it_is_checked():
    """A checklist that says WHAT without saying HOW leaves the method to whoever is holding the
    pen, and two engineers then "check" the same line differently."""
    bad = []
    for f in FL.LIBRARY:
        for i, it in enumerate(f["items"]):
            if (it["vi"] or it["en"]) and not it["method"].strip():
                bad.append("%s line %d" % (f["code"], i + 1))
    assert not bad, "lines with no inspection method: %s" % bad[:10]


def test_methods_come_from_the_fixed_set_rather_than_being_typed_each_time():
    """Free-text methods make the register unsearchable — "Đo", "đo đạc" and "Measure" are three
    strings for one thing."""
    allowed = {FL.M_V, FL.M_M, FL.M_T, FL.M_D, FL.M_C, FL.M_F, FL.M_W, ""}
    bad = sorted({it["method"] for f in FL.LIBRARY for it in f["items"]} - allowed)
    assert not bad, "methods outside the fixed set: %s" % bad


def test_no_form_ships_marked_as_adopted():
    """THE honesty property of the whole library. These are drafts written against the standards,
    not transcriptions of an approved ITP; a form that shipped marked adopted would be the app
    asserting a review that never happened, on a document somebody signs."""
    assert all(f["adopted"] is False for f in FL.LIBRARY)
    assert all(f["origin"] == "shipped" for f in FL.LIBRARY)


def test_using_a_shipped_form_warns_and_never_blocks():
    """Blocking would make the library useless on day one, which is how a control gets removed
    rather than satisfied. Warning is what puts the provenance in front of the signer."""
    a = _ok_work()
    a["dossier"] = dict(a["dossier"], formCode="ELE-202")
    r = A.readiness(**a)
    w = [x for x in r if x["code"] == "form_not_adopted"]
    assert w and w[0]["blocks"] is False
    assert "ELE-202" in w[0]["vi"] and "ELE-202" in w[0]["en"]
    assert A.can_accept(**a), "an un-adopted form must not stop an acceptance"


def test_an_adopted_form_raises_nothing():
    a = _ok_work()
    a["dossier"] = dict(a["dossier"], formCode="ELE-202", formAdopted=True)
    assert not [x for x in A.readiness(**a) if x["code"] == "form_not_adopted"]


def test_the_library_counts_are_computed_not_written_down():
    c = FL.counts()
    assert sum(v["forms"] for v in c.values()) == len(FL.LIBRARY)
    assert c["ELE"]["items"] == sum(
        len([i for i in f["items"] if i["vi"] or i["en"]])
        for f in FL.LIBRARY if f["disc"] == "ELE")


# ══ the construction stages ══════════════════════════════════════════════════════════════════════

def test_stages_are_numbered_in_order_and_point_at_real_predecessors():
    nos = [s["no"] for s in A.STAGES]
    assert nos == sorted(nos) == list(range(1, len(A.STAGES) + 1)), "stage numbering is not a sequence"
    for s in A.STAGES:
        if s["after"]:
            prev = A.stage(s["after"])
            assert prev, "%s follows unknown stage %r" % (s["key"], s["after"])
            assert prev["no"] < s["no"], "%s follows a LATER stage" % s["key"]


def test_every_stage_names_real_disciplines_and_real_acceptance_types():
    for s in A.STAGES:
        for d in s["disc"]:
            assert d in A.DISCIPLINE_CODES, "%s: unknown discipline %r" % (s["key"], d)
        for t in s["types"]:
            assert A.acceptance_type(t), "%s: unknown acceptance type %r" % (s["key"], t)
        assert s["note_vi"] and s["note_en"], s["key"]


def test_every_acceptance_type_arises_in_at_least_one_stage():
    """A type belonging to no stage cannot be planned for, and would only ever be reached by
    somebody picking it out of a dropdown by accident."""
    covered = {t for s in A.STAGES for t in s["types"]}
    missing = sorted({t["key"] for t in A.ACCEPTANCE_TYPES} - covered)
    assert not missing, missing


def test_the_stages_that_get_covered_up_are_the_ones_that_actually_do():
    """The one fact about a stage the app is firm on, so it is pinned rather than left to drift."""
    covered = {s["key"] for s in A.STAGES if s["covered"]}
    assert covered == {"foundation", "structure", "mep_rough", "envelope", "external"}
    assert A.is_covered_stage("mep_rough") is True
    assert A.is_covered_stage("finishes") is False
    assert A.is_covered_stage("nonsense") is False


def test_a_concealed_stage_warns_loudly_and_still_never_blocks():
    """A concealed work acceptance is the only kind that cannot be redone — the alternative is
    opening the building up. So it is said while there is still something to look at, and said as a
    warning, because Điều 21 does not make it a condition of the signature."""
    a = _ok_work()
    a["dossier"] = dict(a["dossier"], stage="mep_rough")
    w = [x for x in A.readiness(**a) if x["code"] == "stage_covered"]
    assert w and w[0]["blocks"] is False
    assert "che khuất" in w[0]["vi"] and "covered up" in w[0]["en"]
    assert A.can_accept(**a)


def test_a_stage_out_of_sequence_warns_about_the_one_before_it():
    a = _ok_work()
    a["dossier"] = dict(a["dossier"], stage="finishes")
    codes = [x["code"] for x in A.readiness(**a)]
    assert "stage_after_envelope" in codes
    a["dossier"] = dict(a["dossier"], _stagesDone=["envelope"])
    assert "stage_after_envelope" not in [x["code"] for x in A.readiness(**a)]


def test_an_unusual_type_for_a_stage_is_questioned_not_refused():
    a = _ok_work()
    a["dossier"] = dict(a["dossier"], accType="work", stage="handover")
    w = [x for x in A.readiness(**a) if x["code"] == "stage_type_unusual"]
    assert w and w[0]["blocks"] is False


def test_stages_for_a_discipline_are_the_ones_it_appears_in():
    ele = [s["key"] for s in A.stages_for("ELE")]
    assert "mep_rough" in ele and "test_commission" in ele
    assert "finishes" not in ele, "an electrician should not scroll past architectural finishes"
    assert A.stages_for("") == A.STAGES
    assert A.stages_for("ZZZ") == A.STAGES, "an unknown discipline gets everything, not nothing"


def test_stage_warnings_are_silent_when_the_dossier_names_no_stage():
    assert A.stage_warnings({"accType": "work"}) == []
    assert A.stage_warnings({"accType": "work", "stage": "nonsense"}) == []


# ══ the detail each type now carries ═════════════════════════════════════════════════════════════

def test_every_type_says_what_evidence_travels_with_the_minute():
    """The commonest reason a dossier comes back from a consultant is a missing attachment, not a
    failed inspection. Điều 21(3) requires the minute to identify what it was judged against, so the
    form says up front what has to be with it."""
    for t in A.ACCEPTANCE_TYPES:
        assert t["evidence_vi"] and t["evidence_en"], t["key"]
        assert len(t["evidence_vi"]) == len(t["evidence_en"]), t["key"]
        assert t["attends_vi"] and t["attends_en"], t["key"]


def test_the_notice_period_is_labelled_as_convention_rather_than_law():
    """It is not in Điều 21 or Điều 24. Presenting a convention as a legal requirement is the same
    error as citing a withdrawn standard edition."""
    import io
    src = io.open(A.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert src.count("convention, not law") >= len(
        [t for t in A.ACCEPTANCE_TYPES if t.get("notice_days")])
    for t in A.ACCEPTANCE_TYPES:
        assert isinstance(t["notice_days"], int) and t["notice_days"] > 0, t["key"]


def test_the_types_that_happen_in_every_stage_do_not_claim_one():
    """Materials arrive and work happens at every stage of a build. A default naming one stage would
    be wrong most of the time, and a wrong default is worse than a blank somebody has to fill."""
    assert A.acceptance_type("material")["stage"] == ""
    assert A.acceptance_type("work")["stage"] == ""
    assert A.acceptance_type("handover_deed")["stage"] == "handover"


def test_the_warranty_type_closes_the_last_obligation():
    t = A.acceptance_type("warranty_end")
    assert t and "Điều 28" in t["law"]
    assert t["requires"] == ["handover_deed"]
    assert A.stage("warranty")["types"] == ["warranty_end"]


# ══ coverage — what is left to accept ════════════════════════════════════════════════════════════
#
# The failure this whole section guards against is a confident wrong number. A coverage screen is
# read by somebody deciding whether a package is finished, and a percentage computed from a fuzzy
# name match is worse than no screen at all: it is wrong in the direction of "everything is fine".

def _itp(i, no, title="Lắp đặt thang máng cáp", disc="ELE", due=""):
    return {"id": i, "itpNo": no, "title": title, "discipline": disc, "plannedFinish": due}


def _dos(i, **kw):
    d = {"id": i, "refNo": "REF-" + i, "status": "Draft", "title": "Lắp đặt thang máng cáp",
         "discipline": "ELE"}
    d.update(kw)
    return d


def test_coverage_counts_only_what_was_explicitly_linked():
    """A dossier covers an ITP when somebody SAID it does. Matching by name would silently pair the
    tray acceptance on level 2 with the ITP for level 5, report 80%, and be discovered when the
    consultant asks for the missing minutes."""
    c = A.coverage(itps=[_itp("t1", "ITP-001"), _itp("t2", "ITP-002")],
                   dossiers=[_dos("d1", status="Accepted", itpId="t1"),
                             _dos("d2", status="Accepted")])          # same title, NOT linked
    assert c["itp"]["accepted"] == 1, "a look-alike title must not count as coverage"
    assert c["itp"]["none"] == 1
    assert c["unlinkedDossiers"] == 1


def test_the_unlinked_count_is_returned_beside_every_figure():
    """It is the figure's own error bar, not a footnote."""
    c = A.coverage(itps=[_itp("t1", "ITP-001")],
                   dossiers=[_dos("d%d" % i) for i in range(9)] + [_dos("x", itpId="t1")])
    assert c["unlinkedDossiers"] == 9
    assert c["trust"]["linkedPct"] == 10
    assert c["trust"]["level"] == "low"
    assert "10%" in c["trust"]["en"] and "10%" in c["trust"]["vi"]


def test_trust_says_coverage_is_UNDERSTATED_not_overstated():
    """The direction matters. Unlinked dossiers are excluded from the numerator, so real coverage is
    HIGHER than shown — telling somebody it might be lower would send them looking for work that is
    already done."""
    c = A.coverage(itps=[_itp("t1", "ITP-001")], dossiers=[_dos("d1"), _dos("d2", itpId="t1")])
    assert "higher than the figure shown" in c["trust"]["en"]
    assert "cao hơn con số hiển thị" in c["trust"]["vi"]


def test_trust_reports_full_confidence_only_when_everything_is_linked():
    c = A.coverage(itps=[_itp("t1", "ITP-001")], dossiers=[_dos("d1", itpId="t1")])
    assert c["trust"]["level"] == "full" and c["trust"]["linkedPct"] == 100


def test_an_empty_register_says_so_rather_than_reporting_zero_per_cent():
    """0% coverage and "nothing has been planned yet" look identical as a number and mean opposite
    things — one is a project behind schedule, the other is a project that has not started."""
    assert A.coverage()["trust"]["level"] == "none"
    assert A.coverage(itps=[_itp("t1", "ITP-001")])["trust"]["level"] == "empty"


def test_the_four_states_an_itp_can_be_in():
    itps = [_itp("t1", "ITP-001"), _itp("t2", "ITP-002"), _itp("t3", "ITP-003"), _itp("t4", "ITP-004")]
    c = A.coverage(
        itps=itps,
        dossiers=[_dos("d1", status="Accepted", itpId="t1"), _dos("d2", status="Draft", itpId="t2")],
        plans=[{"id": "p1", "itpId": "t3"}])
    st = {r["no"]: r["state"] for r in c["itp"]["rows"]}
    assert st["ITP-001"] == A.COV_ACCEPTED
    assert st["ITP-002"] == A.COV_OPEN, "a dossier exists but nobody has signed it"
    assert st["ITP-003"] == A.COV_CALLED, "an inspection was called, no dossier compiled"
    assert st["ITP-004"] == A.COV_NONE


def test_lateness_is_only_judged_when_the_caller_says_what_day_it_is():
    """A missing date is not a reason to call something on time, and not a reason to call it late.
    The module has no clock, so it does not guess one."""
    itps = [_itp("t1", "ITP-001", due="2026-01-01")]
    assert A.coverage(itps=itps)["itp"]["overdue"] == 0
    assert A.coverage(itps=itps, today="2026-09-05")["itp"]["overdue"] == 1


def test_an_accepted_itp_is_never_overdue_however_late_it_was():
    """It is done. Reporting it as outstanding puts work on a list that nobody can take off."""
    c = A.coverage(itps=[_itp("t1", "ITP-001", due="2026-01-01")],
                   dossiers=[_dos("d1", status="Accepted", itpId="t1")], today="2026-09-05")
    assert c["itp"]["overdue"] == 0


def test_an_itp_with_no_planned_date_is_not_silently_called_late():
    c = A.coverage(itps=[_itp("t1", "ITP-001")], today="2026-09-05")
    assert c["itp"]["overdue"] == 0 and c["itp"]["rows"][0]["state"] == A.COV_NONE


def test_wbs_packages_are_measured_the_same_way():
    c = A.coverage(deliverables=[{"id": "w1", "wbs": "1.2", "name": "Hệ thống điện tầng 1"},
                                 {"id": "w2", "wbs": "1.3", "name": "Cấp thoát nước"}],
                   dossiers=[_dos("d1", status="Accepted", deliverableId="w1")])
    assert c["wbs"]["total"] == 2 and c["wbs"]["accepted"] == 1 and c["wbs"]["pct"] == 50


def test_a_dossier_can_cover_an_itp_and_a_wbs_package_at_once():
    """It usually does — the ITP says how it is inspected, the WBS says what it is part of — and it
    must not be counted as unlinked because it was reached from the other side."""
    c = A.coverage(itps=[_itp("t1", "ITP-001")],
                   deliverables=[{"id": "w1", "wbs": "1.2", "name": "Điện"}],
                   dossiers=[_dos("d1", status="Accepted", itpId="t1", deliverableId="w1")])
    assert c["itp"]["accepted"] == 1 and c["wbs"]["accepted"] == 1
    assert c["unlinkedDossiers"] == 0


def test_stage_coverage_lists_every_stage_even_the_empty_ones():
    """A stage missing from the list reads as a stage with no work in it. An empty row reads as a
    stage nothing has been accepted in yet, which is the true statement."""
    c = A.coverage(dossiers=[_dos("d1", status="Accepted", stage="mep_rough"),
                             _dos("d2", stage="mep_rough")])
    assert len(c["stages"]) == len(A.STAGES)
    row = next(s for s in c["stages"] if s["key"] == "mep_rough")
    assert row["dossiers"] == 2 and row["accepted"] == 1
    assert next(s for s in c["stages"] if s["key"] == "handover")["dossiers"] == 0


def test_a_dossier_on_an_unknown_stage_is_counted_rather_than_dropped():
    """An import, or a stage somebody renamed. A row that vanishes from a coverage screen is the
    worst kind of missing."""
    c = A.coverage(dossiers=[_dos("d1", stage="phase-4b"), _dos("d2", stage="")])
    assert c["stageUnknown"] == 1
    assert c["stageNotStated"] == 1


# ── suggestions: offered, never applied ─────────────────────────────────────────────────────────

def test_a_dossier_quoting_the_itp_number_is_suggested_for_it():
    s = A.suggest_links(itps=[_itp("t1", "ITP-047")],
                        dossiers=[_dos("d1", refNo="SLPXA-ELE-009",
                                       jobDescription="Theo ITP-047, lắp đặt thang máng")])
    assert len(s) == 1 and s[0]["itpId"] == "t1" and s[0]["why"] == "number"


def test_a_title_match_is_suggested_only_when_exactly_one_itp_could_be_meant():
    """Two floors of the same tray run carry identical titles. Suggesting one of them at random is
    how a wrong link gets confirmed by somebody clicking through."""
    one = A.suggest_links(itps=[_itp("t1", "ITP-001")], dossiers=[_dos("d1")])
    assert len(one) == 1 and one[0]["why"] == "title"
    two = A.suggest_links(itps=[_itp("t1", "ITP-001"), _itp("t2", "ITP-002")],
                          dossiers=[_dos("d1")])
    assert two == [], "an ambiguous title must produce no suggestion at all"


def test_the_title_match_is_accent_insensitive_and_discipline_scoped():
    s = A.suggest_links(itps=[_itp("t1", "ITP-001", title="LẮP ĐẶT THANG MÁNG CÁP")],
                        dossiers=[_dos("d1", title="lắp đặt thang máng cáp")])
    assert len(s) == 1
    none = A.suggest_links(itps=[_itp("t1", "ITP-001", disc="HVAC")], dossiers=[_dos("d1")])
    assert none == [], "an electrical dossier must not be offered an HVAC plan"


def test_a_one_or_two_character_itp_number_never_matches_by_number():
    """A register numbered 1, 2, 3 would otherwise match "1" inside every reference and date on the
    dossier — the single most likely way this feature produces nonsense at scale."""
    s = A.suggest_links(itps=[_itp("t1", "1", title="Khác hẳn", disc="ELE")],
                        dossiers=[_dos("d1", refNo="SLPXA-ELE-001", title="Không liên quan")])
    assert s == []


def test_a_dossier_that_is_already_linked_is_never_suggested_again():
    s = A.suggest_links(itps=[_itp("t1", "ITP-047")],
                        dossiers=[_dos("d1", itpId="t1", jobDescription="ITP-047")])
    assert s == []


def test_a_suggestion_says_when_the_itp_already_has_a_dossier_on_it():
    """Legitimate — an ITP re-inspected after a failure has two — but the person confirming should
    see it rather than discover it."""
    s = A.suggest_links(itps=[_itp("t1", "ITP-047")],
                        dossiers=[_dos("d0", itpId="t1"),
                                  _dos("d1", jobDescription="ITP-047")])
    assert len(s) == 1 and s[0]["alreadyLinkedElsewhere"] is True


def test_suggestions_are_bounded():
    itps = [_itp("t%d" % i, "ITP-%03d" % i, title="Công tác %d" % i) for i in range(200)]
    dos = [_dos("d%d" % i, jobDescription="theo ITP-%03d" % i) for i in range(200)]
    assert len(A.suggest_links(itps=itps, dossiers=dos)) == 60
    assert len(A.suggest_links(itps=itps, dossiers=dos, limit=5)) == 5


# ══ the completion dossier index — Phụ lục VIb ═══════════════════════════════════════════════════
#
# The failure this section exists to prevent is subtle and expensive: an index that renders "the
# register contains 47 of these" and "somebody ticked a box" identically. Both belong in the
# dossier; only one is something the portal can produce on demand, and a handover meeting works
# through this sheet line by line.

import acceptance_index as X


def test_the_four_parts_of_the_list_are_all_present_and_every_row_belongs_to_one():
    assert [p["key"] for p in X.PARTS] == ["I", "II", "III", "IV"]
    for it in X.ITEMS:
        assert X.part(it["part"]), "%s is in unknown part %r" % (it["no"], it["part"])
        assert X.holder(it["holder"]), "%s names unknown holder %r" % (it["no"], it["holder"])


def test_item_numbers_are_unique_and_ordered_within_their_part():
    nos = [i["no"] for i in X.ITEMS]
    assert len(nos) == len(set(nos)), "duplicate item numbers"
    for p in X.PARTS:
        seq = [int(i["no"].split(".")[1]) for i in X.ITEMS if i["part"] == p["key"]]
        assert seq == sorted(seq) == list(range(1, len(seq) + 1)), \
            "part %s is not numbered 1..n in order: %s" % (p["key"], seq)


def test_every_row_is_written_in_both_languages():
    """A handover meeting reads the Vietnamese; a foreign client's adviser reads the English. A row
    in one language is a row one of them cannot check off."""
    for it in X.ITEMS:
        assert it["vi"].strip() and it["en"].strip(), it["no"]
        assert it["vi"] != it["en"], it["no"]


def test_a_register_backed_row_names_a_register_this_module_can_actually_count():
    """A `reg` key nothing understands silently counts zero, and a zero renders exactly like a
    genuinely empty register — the row would read "missing" forever with nothing to fix."""
    ctx = {"accepted": [{"accType": t["key"]} for t in A.ACCEPTANCE_TYPES],
           "itps": [{}], "openDefects": [{}], "clearances": [{"key": c["key"]} for c in A.CLEARANCES]}
    for it in X.ITEMS:
        if it["source"] != X.SRC_REGISTER:
            assert not it["reg"], "%s is declared but names a register" % it["no"]
            continue
        assert it["reg"], "%s is register-backed but names no register" % it["no"]
        assert X._count(it["reg"], ctx) > 0, \
            "%s names %r, which counts zero even when every register is full" % (it["no"], it["reg"])


def test_every_acceptance_type_reaches_the_index_somewhere():
    """A type of minute the completion dossier never asks for is a type nobody would file."""
    regs = " ".join(i["reg"] for i in X.ITEMS if i["reg"].startswith("acc:"))
    for t in A.ACCEPTANCE_TYPES:
        if t["key"] == "warranty_end":
            continue          # closes the warranty, after the dossier is handed over
        assert t["key"] in regs, "%s appears in no index row" % t["key"]


def test_counted_and_declared_are_reported_separately():
    """THE property. A tick meaning "the register contains this" and a tick meaning "somebody said
    so" are not the same evidence and must never be added into one number."""
    r = X.build_index(accepted=[{"accType": "work"}],
                      items_state=[{"no": "I.1", "declared": True, "declaredBy": "Trần Văn B",
                                    "ref": "QĐ 123/QĐ-UBND"}])
    s = r["summary"]
    assert s["counted"] == 1 and s["declared"] == 1
    assert s["held"] == 2
    assert "counted directly" in r["verdict"]["en"] or "counted" in r["verdict"]["en"]


def test_a_declaration_with_no_name_against_it_is_not_a_declaration():
    """A reference typed into a box is a note. Counting it would be the app inventing an
    attestation nobody made."""
    r = X.build_index(items_state=[{"no": "I.1", "declared": True, "ref": "QĐ 123"}])
    row = next(x for x in r["rows"] if x["no"] == "I.1")
    assert row["state"] == X.ST_MISSING
    assert r["summary"]["declared"] == 0


def test_a_register_row_is_held_only_when_the_register_actually_has_something():
    r = X.build_index(accepted=[])
    row = next(x for x in r["rows"] if x["no"] == "III.7")
    assert row["state"] == X.ST_MISSING and row["count"] == 0
    r2 = X.build_index(accepted=[{"accType": "work"}, {"accType": "work"}])
    row2 = next(x for x in r2["rows"] if x["no"] == "III.7")
    assert row2["state"] == X.ST_HELD and row2["count"] == 2


def test_a_register_row_cannot_be_satisfied_by_declaring_it():
    """The whole point of a counted row. If somebody could tick "yes we have the work acceptance
    minutes" the index would report a dossier the register cannot produce."""
    r = X.build_index(accepted=[], items_state=[
        {"no": "III.7", "declared": True, "declaredBy": "Ai Đó", "ref": "ở đâu đó"}])
    row = next(x for x in r["rows"] if x["no"] == "III.7")
    assert row["state"] == X.ST_MISSING


def test_an_optional_row_with_nothing_behind_it_is_not_chased():
    """Điều 23 stage acceptance and the Điều 24(3) punch-list annex only exist on some projects.
    Reporting them as gaps would put work on a list that cannot be cleared."""
    r = X.build_index()
    for no in ("III.8", "III.11", "III.13"):
        assert next(x for x in r["rows"] if x["no"] == no)["state"] == X.ST_OPTIONAL
    assert "III.8" not in r["verdict"]["missing"]


def test_a_row_can_be_marked_not_applicable_and_stops_being_a_gap():
    r = X.build_index(items_state=[{"no": "I.3", "applies": False,
                                    "naReason": "Công trình không thuộc đối tượng cấp phép."}])
    row = next(x for x in r["rows"] if x["no"] == "I.3")
    assert row["state"] == X.ST_NA and row["naReason"]
    assert r["summary"]["na"] == 1


def test_marking_a_REQUIRED_row_not_applicable_removes_it_from_the_required_count():
    """Otherwise the denominator lies: a project legitimately without a construction permit would
    read as permanently incomplete."""
    base = X.build_index()["summary"]["required"]
    off = X.build_index(items_state=[{"no": "I.1", "applies": False, "naReason": "x"}])
    assert off["summary"]["required"] == base - 1


def test_the_verdict_names_the_missing_rows_rather_than_only_counting_them():
    """"22 items missing" sends somebody back to the table. Naming them is the difference between a
    number and a next action."""
    r = X.build_index()
    assert r["verdict"]["level"] == "incomplete"
    assert "I.1" in r["verdict"]["vi"] and "I.1" in r["verdict"]["en"]
    assert r["verdict"]["missing"], "the caller gets the list, not just the sentence"


def test_a_complete_index_still_says_how_much_of_it_is_only_somebody_s_word():
    """The dangerous moment: everything ticked, about to be printed and signed."""
    state = [{"no": i["no"], "declared": True, "declaredBy": "Nguyễn Văn A", "ref": "REF"}
             for i in X.ITEMS if i["source"] == X.SRC_DECLARED]
    r = X.build_index(
        items_state=state,
        accepted=[{"accType": t} for t in ("material", "work", "commission", "stage",
                                           "handover_part", "handover_all", "handover_deed")],
        itps=[{}], open_defects=[{}], clearances=[{"key": "fire"}, {"key": "authority_check"}])
    assert r["verdict"]["level"] == "complete"
    assert r["summary"]["missing"] == 0
    assert r["summary"]["declared"] > r["summary"]["counted"], \
        "most of a completion dossier is documents the portal never held — say so"
    assert "attestation" in r["verdict"]["en"]
    assert "xác nhận" in r["verdict"]["vi"]


def test_the_as_built_row_refuses_to_count_marked_up_acceptance_drawings():
    """They are different documents. An index that counted inspection mark-ups as as-builts would
    report a deliverable the project has not produced — and III.2 is one of the first things a
    client's handover team asks for."""
    row = next(i for i in X.ITEMS if i["no"] == "III.2")
    assert row["source"] == X.SRC_DECLARED and not row["reg"]
    assert "not the marked-up drawings" in row["note_en"]


def test_rows_come_back_in_phu_luc_order():
    """It is a table of contents. Sorting it any other way makes it a different document."""
    r = X.build_index()
    assert [x["no"] for x in r["rows"]] == [i["no"] for i in X.ITEMS]


def test_an_unknown_register_key_counts_zero_rather_than_raising():
    """A row added with a typo must not take the whole index down — it should read as missing, which
    is visible, rather than as a 500."""
    assert X._count("acc:nonsense", {"accepted": [{"accType": "work"}]}) == 0
    assert X._count("", {}) == 0
    assert X._count("something-else", {}) == 0
