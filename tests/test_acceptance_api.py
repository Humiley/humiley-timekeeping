# -*- coding: utf-8 -*-
"""The acceptance dossier at the boundary: who may sign it, and what stops being editable.

acceptance.py proves the RULES. This proves the app actually applies them — which is the half that
has failed before in this codebase, twice, in exactly the same shape: a module full of correct logic
that no route ever consults, and a register that looks governed and is not.

Three things are pinned here:

  * the Điều 24(2) chain is read from the SERVER'S register, not from whatever the browser claims
    has been accepted;
  * segregation of duties on the compile → check step, read from the stored signature's
    server-applied `setStatus`, not from the client's free-text `meaning`;
  * a signed minute freezes. Not the collection — the RECORD, once accepted, and only the parts
    that say what was inspected.
"""
import app
import db
import pytest

import acceptance as A


class _H(app.Handler):
    """The guards under test, without a socket."""
    def __init__(self):
        # _coll_update reads the optional `If-Match` precondition off the request headers. Empty is
        # the "caller sent none" case, which is the one every test here is about.
        self.headers = {}

    def _json(self, obj, status=200):
        return ("json", status, obj)

    def _err(self, msg, status=400):
        return ("err", status, msg)

    def _utc_now(self):
        return "2026-09-05T02:00:00Z"


PM = {"id": "U-PM", "name": "Tran Van Minh", "role": "staff", "level": "viewer"}
QA = {"id": "U-QA", "name": "Le Thi Hoa", "role": "staff", "level": "viewer"}
BOSS = {"id": "U-BOSS", "name": "Do Van Hung", "role": "manager", "level": "manager"}


@pytest.fixture
def proj():
    p = db.put_collection_item("pm_projects", {"name": "ZZ Acceptance", "manager": PM["name"]})
    db.put_collection_item("pm_resources", {"projectId": p["id"], "empId": QA["id"], "name": QA["name"]})
    yield p
    for coll in ("pm_acc", "pm_acc_items", "pm_acc_defects", "pm_acc_plans", "pm_acc_forms",
                 "pm_resources"):
        for r in list(db.list_collection(coll)):
            if r.get("projectId") == p["id"]:
                try:
                    db.delete_collection_item(coll, r["id"])
                except Exception:
                    pass
    try:
        db.delete_collection_item("pm_projects", p["id"])
    except Exception:
        pass


def _dossier(pid, **kw):
    r = {"projectId": pid, "accType": "work", "discipline": "ELE",
         "refNo": "ZZ-ELE-001", "status": A.STATUS_DRAFT,
         "signContractor": "Nguyễn Văn A", "signSupervisor": "Trần Văn B",
         "minuteFile": "data:application/pdf;base64,AAAA"}
    r.update(kw)
    return db.put_collection_item("pm_acc", r)


def _line(pid, did, result="Đạt", seq=1):
    return db.put_collection_item("pm_acc_items", {
        "projectId": pid, "dossierId": did, "seq": seq,
        "textVi": "Vị trí đúng bản vẽ", "textEn": "Position as drawing", "result": result})


def _cleared():
    """Every statutory clearance evidenced — so a test about the CHAIN is not also a test about
    Điều 24(2)'s paperwork."""
    return [dict(c, ref="NT-%s/2026" % c["key"].upper()) for c in A.default_clearances()
            if c["applies"]]


def _sign(user, dos, status):
    """The check /api/esign runs before it appends a signature."""
    return _H()._acc_appr_check(user, dos.get("status"), status, dos.get("signatures") or [], dos)


# ── the compile → check → accept chain ───────────────────────────────────────────────────────────

def test_a_qa_engineer_may_compile_and_submit_without_manager_access(base_url, proj):
    """The whole authority argument. The person who compiles an acceptance dossier is the project's
    QA/QC engineer — an ordinary staff account. Gating this on `manager` would mean either the wrong
    person signs every minute, or every site engineer is handed manager access."""
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"])
    assert _sign(QA, d, "Submitted") is None


def test_the_person_who_compiled_it_cannot_also_check_it(base_url, proj):
    d = _dossier(proj["id"], signatures=[
        {"userId": QA["id"], "name": QA["name"], "setStatus": "Submitted",
         "meaning": "dossier compiled"}])
    why = _sign(QA, d, "Reviewed")
    assert why and "cannot also check" in why


def test_segregation_reads_the_server_applied_status_not_the_signers_own_words(base_url, proj):
    """`meaning` is client text. A signer who worded theirs to omit "compiled" would otherwise
    check their own work — the same hole the payrun preparer/finaliser split closes."""
    d = _dossier(proj["id"], signatures=[
        {"userId": QA["id"], "name": QA["name"], "setStatus": "Submitted",
         "meaning": "reviewed and found in order"}])
    assert _sign(QA, d, "Reviewed"), "the meaning text must not be what decides this"


def test_not_even_a_director_may_check_their_own_dossier(base_url, proj):
    """No manager exemption, deliberately. Everywhere else in _appr_check a manager steps over a
    gate because the gate stops accidents; this one stops a person marking their own homework, and
    a director doing it is the case the control most needs to cover. It also matches the two
    unconditional splits already in that method — "You cannot review your own request" and the
    payrun preparer/finaliser rule."""
    d = _dossier(proj["id"], signatures=[
        {"userId": BOSS["id"], "setStatus": "Submitted", "meaning": "dossier compiled"}])
    _line(proj["id"], d["id"])
    assert _sign(BOSS, d, "Reviewed"), "a manager checked a dossier they compiled themselves"
    admin = {"id": "U-ADM2", "name": "Admin", "role": "manager", "level": "admin"}
    d2 = _dossier(proj["id"], refNo="ZZ-ELE-050", signatures=[
        {"userId": admin["id"], "setStatus": "Submitted", "meaning": "dossier compiled"}])
    assert _sign(admin, d2, "Reviewed"), "an admin checked a dossier they compiled themselves"


def test_somebody_else_may_check_it(base_url, proj):
    d = _dossier(proj["id"], signatures=[
        {"userId": QA["id"], "setStatus": "Submitted", "meaning": "dossier compiled"}])
    _line(proj["id"], d["id"])
    assert _sign(PM, d, "Reviewed") is None


def test_recording_a_failed_inspection_is_never_refused(base_url, proj):
    """The one refusal that would make people stop using the register. A rejection has to be
    recordable with nothing in place — that IS the record of why there was a second visit."""
    d = _dossier(proj["id"], minuteFile="", signContractor="", signSupervisor="")
    assert _sign(QA, d, "Rejected") is None


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────

def test_a_complete_work_acceptance_can_be_accepted(base_url, proj):
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"])
    assert _sign(PM, d, "Accepted") is None


def test_an_unchecked_checklist_line_refuses_the_acceptance(base_url, proj):
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"], result="Đạt", seq=1)
    _line(proj["id"], d["id"], result="", seq=2)
    why = _sign(PM, d, "Accepted")
    assert why and "no result yet" in why


def test_an_open_structural_defect_refuses_the_acceptance(base_url, proj):
    """Điều 24(3): a punch list may remain, provided nothing on it affects load-bearing capacity,
    safety in use or the function of the works."""
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"])
    db.put_collection_item("pm_acc_defects", {
        "projectId": proj["id"], "dossierId": d["id"], "no": 1,
        "description": "Nứt dầm D3", "impact": "structural", "status": "Open"})
    why = _sign(PM, d, "Accepted")
    assert why and "load-bearing" in why


def test_a_cosmetic_defect_does_not(base_url, proj):
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"])
    db.put_collection_item("pm_acc_defects", {
        "projectId": proj["id"], "dossierId": d["id"], "no": 1,
        "description": "Xước sơn", "impact": "cosmetic", "status": "Open"})
    assert _sign(PM, d, "Accepted") is None


def test_completion_acceptance_refuses_until_a_work_acceptance_exists_on_this_project(base_url, proj):
    """The rule the whole module exists for, and the one place it must not be takeable on trust from
    the browser: the chain is read from the register."""
    d = _dossier(proj["id"], accType="handover_part", signClient="Phạm C",
                 clearances=_cleared())
    _line(proj["id"], d["id"])
    why = _sign(PM, d, "Accepted")
    assert why and "no acceptance of construction work" in why.lower()

    # …and passes once one is genuinely on record
    w = _dossier(proj["id"], refNo="ZZ-ELE-002", status=A.STATUS_ACCEPTED)
    _line(proj["id"], w["id"])
    assert _sign(PM, d, "Accepted") is None


def test_a_dossier_that_is_only_marked_accepted_in_the_browser_does_not_satisfy_the_chain(base_url, proj):
    """A DRAFT work acceptance is not an accepted one, however the screen labels it."""
    _dossier(proj["id"], refNo="ZZ-ELE-003", status=A.STATUS_DRAFT)
    d = _dossier(proj["id"], accType="handover_part", signClient="Phạm C",
                 clearances=_cleared())
    _line(proj["id"], d["id"])
    assert _sign(PM, d, "Accepted"), "a draft predecessor must not unlock a completion acceptance"


def test_every_reason_comes_back_at_once_not_one_at_a_time(base_url, proj):
    """Being sent back four times, once per missing item, is how a control stops being used."""
    d = _dossier(proj["id"], accType="handover_all", signContractor="", minuteFile="",
                 clearances=A.default_clearances())
    why = _sign(PM, d, "Accepted")
    assert why.count("•") >= 4, why


# ── a signed minute is evidence ─────────────────────────────────────────────────────────────────

def _update(user, coll, iid, body):
    return _H()._coll_update(user, coll, iid, body)


def _delete(user, coll, iid):
    return _H()._coll_delete(user, coll, iid)


def test_a_draft_dossier_is_ordinary_working_data(base_url, proj):
    """Narrow on purpose. A dossier set up wrong deletes freely — refusing those would train people
    around the guard on the ones that matter."""
    d = _dossier(proj["id"])
    kind, _, msg = _delete(PM, "pm_acc", d["id"])
    assert kind != "err", msg
    assert db.get_collection_item("pm_acc", d["id"]) is None


def test_an_accepted_minute_cannot_be_deleted_even_by_an_admin(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    for who in (PM, BOSS, {"id": "U-ADM", "name": "Admin", "role": "manager", "level": "admin"}):
        kind, status, msg = _delete(who, "pm_acc", d["id"])
        assert kind == "err" and status == 403, (who["level"], msg)
        assert "Điều 26" in msg
    assert db.get_collection_item("pm_acc", d["id"])


def test_a_failed_checklist_line_cannot_be_edited_to_pass_after_the_minute_is_signed(base_url, proj):
    """The change that would turn a conditional acceptance into a clean one, silently."""
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    ln = _line(proj["id"], d["id"], result="Không đạt")
    kind, status, msg = _update(PM, "pm_acc_items", ln["id"], dict(ln, result="Đạt"))
    assert kind == "err", "a signed minute's checklist was rewritten"
    assert "result" in msg
    assert db.get_collection_item("pm_acc_items", ln["id"])["result"] == "Không đạt"


def test_a_checklist_line_on_an_unsigned_dossier_is_freely_editable(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_REVIEWED)
    ln = _line(proj["id"], d["id"], result="")
    kind, _, msg = _update(PM, "pm_acc_items", ln["id"], dict(ln, result="Đạt"))
    assert kind != "err", msg


def test_a_punch_list_item_can_still_be_CLOSED_after_the_minute_is_signed(base_url, proj):
    """Điều 24(3)'s whole point: the minute is signed WITH outstanding items and a date to fix them.
    A freeze that stopped the closing would make conditional acceptance unusable."""
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    df = db.put_collection_item("pm_acc_defects", {
        "projectId": proj["id"], "dossierId": d["id"], "no": 1,
        "description": "Xước sơn", "impact": "cosmetic", "status": "Open"})
    kind, _, msg = _update(PM, "pm_acc_defects", df["id"],
                           dict(df, status="Closed", closedOn="2026-09-10"))
    assert kind != "err", msg
    assert db.get_collection_item("pm_acc_defects", df["id"])["status"] == "Closed"


def test_but_what_the_defect_SAYS_cannot_be_rewritten(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    df = db.put_collection_item("pm_acc_defects", {
        "projectId": proj["id"], "dossierId": d["id"], "no": 1,
        "description": "Nứt dầm D3", "impact": "structural", "status": "Open"})
    kind, _, msg = _update(PM, "pm_acc_defects", df["id"], dict(df, impact="cosmetic"))
    assert kind == "err" and "impact" in msg


def test_the_scan_of_the_signed_sheet_may_still_be_attached_afterwards(base_url, proj):
    """Paperwork arrives late. What may be written afterwards is the evidence, never the finding."""
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    kind, _, msg = _update(PM, "pm_acc", d["id"],
                           dict(d, minuteFile="data:application/pdf;base64,BBBB",
                                minuteName="BBNT-001-signed.pdf"))
    assert kind != "err", msg


# ── composing a dossier ─────────────────────────────────────────────────────────────────────────

def test_composing_copies_the_checklist_rather_than_pointing_at_it(base_url, proj):
    """A dossier that referenced the library would change its own wording every time the library was
    edited, and a minute signed in March would quietly start saying what the form says in
    September."""
    kind, _, out = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "formCode": "HML-EL-205",
        "refNo": "ZZ-ELE-900"})
    assert kind == "json", out
    did = out["dossier"]["id"]
    rows = [r for r in db.list_collection("pm_acc_items") if r.get("dossierId") == did]
    assert len(rows) == len(A.form("HML-EL-205")["items"]) > 5
    assert all(r["result"] == "" for r in rows), "a copied checklist starts unanswered"
    assert out["dossier"]["formCode"] == "HML-EL-205"


def test_a_work_acceptance_is_not_born_carrying_completion_clearances(base_url, proj):
    """Five empty clearance rows on a slab-opening inspection teach people to tick past them, and
    the ticking-past is what the check exists to prevent."""
    _, _, out = _H()._acc_compose_ep(PM, {"projectId": proj["id"], "accType": "work"})
    assert out["dossier"]["clearances"] == []
    _, _, out2 = _H()._acc_compose_ep(PM, {"projectId": proj["id"], "accType": "handover_all"})
    assert len(out2["dossier"]["clearances"]) == len(A.CLEARANCES)


def test_composing_refuses_an_unknown_form_rather_than_making_an_empty_one(base_url, proj):
    kind, status, msg = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "formCode": "NOPE-999"})
    assert kind == "err" and status == 404


def test_a_projects_own_form_library_wins_over_the_seeded_one(base_url, proj):
    """The seeded library is a starting point. A contractor's real PP-EL-205 is written against
    their own ITP and must override it."""
    db.put_collection_item("pm_acc_forms", {
        "projectId": proj["id"], "code": "HML-EL-205", "disc": "ELE",
        "vi": "Bản của dự án", "en": "The project's own",
        "items": [{"vi": "Một mục duy nhất", "en": "One single line"}]})
    _, _, out = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "formCode": "HML-EL-205"})
    assert out["items"] == 1
    assert out["dossier"]["formTitleEn"] == "The project's own"


def test_composing_refuses_a_project_you_are_not_on(base_url, proj):
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    kind, status, msg = _H()._acc_compose_ep(stranger, {"projectId": proj["id"], "accType": "work"})
    assert kind == "err" and status == 403


# ── the assembled dossier the print view reads ──────────────────────────────────────────────────

def test_the_dossier_endpoint_computes_the_same_verdict_the_signature_gate_uses(base_url, proj):
    """Two implementations of one gate would eventually disagree, and the one people believe is the
    green one on the screen."""
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"], result="")
    kind, _, out = _H()._acc_dossier_ep(PM, {"id": [d["id"]]})
    assert kind == "json"
    assert out["canAccept"] is False
    assert _sign(PM, d, "Accepted") is not None

    db.put_collection_item("pm_acc_items", dict(out["items"][0], result="Đạt"))
    _, _, out2 = _H()._acc_dossier_ep(PM, {"id": [d["id"]]})
    assert out2["canAccept"] is True
    assert _sign(PM, d, "Accepted") is None


def test_the_dossier_endpoint_refuses_a_project_you_are_not_on(base_url, proj):
    d = _dossier(proj["id"])
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    kind, status, _ = _H()._acc_dossier_ep(stranger, {"id": [d["id"]]})
    assert kind == "err" and status == 403


def test_checklist_lines_come_back_in_form_order_however_the_seq_was_typed(base_url, proj):
    """Imported registers carry "1", 1, "01", "1." and blank in the same column."""
    d = _dossier(proj["id"])
    for s in ("3", 1, "02", ""):
        db.put_collection_item("pm_acc_items", {
            "projectId": proj["id"], "dossierId": d["id"], "seq": s, "result": "Đạt",
            "textVi": "x" + str(s)})
    _, _, out = _H()._acc_dossier_ep(PM, {"id": [d["id"]]})
    assert [r["textVi"] for r in out["items"]] == ["x1", "x02", "x3", "x"]


def test_the_catalogue_endpoint_serves_the_law_rather_than_the_browser_holding_a_copy(base_url):
    kind, _, out = _H()._acc_catalogue_ep(PM)
    assert kind == "json"
    keys = {t["key"] for t in out["catalogue"]["types"]}
    assert {"work", "stage", "handover_part", "handover_all"} <= keys
