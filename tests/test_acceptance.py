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
    f = A.form("HML-EL-205")
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
