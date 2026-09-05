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


# ── marked-up drawings ──────────────────────────────────────────────────────────────────────────

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _drawing(pid, did, **kw):
    r = {"projectId": pid, "dossierId": did, "seq": 1, "name": "SD-101.png",
         "image": PNG, "w": 2200, "h": 1558, "caption": "", "paper": "A4L",
         "shapes": [{"k": "box", "x": 10, "y": 10, "w": 100, "h": 80, "color": "#E11D48", "sw": 7}]}
    r.update(kw)
    return db.put_collection_item("pm_acc_drawings", r)


def test_the_dossier_view_returns_drawings_without_their_rasters(base_url, proj):
    """This endpoint is re-read after every checklist click. A dozen A3 sheets re-sent each time is
    the most expensive thing this module could do, and the screen only needs the shapes to draw a
    thumbnail count — the bytes come from the image endpoint when a sheet is actually opened."""
    d = _dossier(proj["id"])
    _line(proj["id"], d["id"])
    _drawing(proj["id"], d["id"])
    _, _, out = _H()._acc_dossier_ep(PM, {"id": [d["id"]]})
    assert len(out["drawings"]) == 1
    dr = out["drawings"][0]
    assert dr["image"] == "" and dr["hasImage"] is True and dr["imageBytes"] > 0
    assert len(dr["shapes"]) == 1, "the mark-up itself must still come back — it is tiny"


def test_a_register_read_strips_the_raster_too(base_url, proj):
    """The same cost by the other route. `image` is not a generic key — only this collection uses
    it — so the shared stripper has to be told about it or a list read ships every sheet."""
    d = _dossier(proj["id"])
    _drawing(proj["id"], d["id"])
    lean = app.Handler._strip_file_bytes({"id": "x", "image": PNG, "shapes": []})
    assert lean["image"] == "" and lean["hasImage"] is True and lean["imageBytes"] == len(PNG)


def test_a_row_with_no_image_is_returned_untouched(base_url):
    """The stripper must not invent hasImage on every record in the portal."""
    row = {"id": "x", "name": "n"}
    assert app.Handler._strip_file_bytes(row) is row


def test_a_drawing_on_a_signed_minute_cannot_be_marked_up_or_removed(base_url, proj):
    """A mark-up is what the minute POINTS AT. Being able to move an arrow onto a different grid
    line after the minute is signed is the same as being able to change what it says."""
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    dr = _drawing(proj["id"], d["id"])
    kind, _, msg = _update(PM, "pm_acc_drawings", dr["id"],
                           dict(dr, shapes=[{"k": "arr", "x1": 0, "y1": 0, "x2": 9, "y2": 9}]))
    assert kind == "err" and "shapes" in msg
    kind2, status2, _ = _delete(PM, "pm_acc_drawings", dr["id"])
    assert kind2 == "err" and status2 == 403


def test_a_drawing_on_an_unsigned_dossier_is_freely_marked_up(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_REVIEWED)
    dr = _drawing(proj["id"], d["id"])
    kind, _, msg = _update(PM, "pm_acc_drawings", dr["id"], dict(dr, shapes=[], caption="Tầng 1"))
    assert kind != "err", msg
    assert db.get_collection_item("pm_acc_drawings", dr["id"])["caption"] == "Tầng 1"


def test_nothing_new_can_be_added_to_a_signed_minute(base_url, proj):
    """The hole the update and delete guards left. Both froze a signed dossier's children; CREATE
    was reachable by the one verb neither covered, so a drawing, a checklist line or an outstanding
    item could still be added to a minute somebody had already put their name to."""
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    for coll, row in (("pm_acc_drawings", {"name": "late.png", "image": PNG}),
                      ("pm_acc_items", {"textVi": "Mục thêm sau", "result": "Đạt"}),
                      ("pm_acc_defects", {"description": "Tồn tại thêm sau", "impact": "cosmetic"})):
        body = dict(row, projectId=proj["id"], dossierId=d["id"])
        kind, status, msg = _H()._coll_add(PM, coll, body)
        assert kind == "err" and status == 409, (coll, kind, status, msg)
        assert "has been signed" in msg


def test_and_still_can_be_added_to_one_that_is_not(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_SUBMITTED)
    kind, _, out = _H()._coll_add(PM, "pm_acc_items", {
        "projectId": proj["id"], "dossierId": d["id"], "textVi": "Mục mới", "result": ""})
    assert kind == "json", out


def test_the_image_endpoint_serves_real_bytes_over_http(base_url, proj, tokens):
    """Over the socket, not through the stubbed handler. This endpoint writes a body itself rather
    than going through _json, so a fake handler with no socket proves nothing about it — and the
    headers are the point: an uploaded file served from the portal's own origin has to arrive
    sandboxed and non-sniffable, like every other file this app hands back."""
    import urllib.request
    import urllib.error

    d = _dossier(proj["id"])
    dr = _drawing(proj["id"], d["id"])
    req = urllib.request.Request(
        base_url + "/api/pm/acceptance/drawing?id=" + dr["id"],
        headers={"Authorization": "Bearer " + tokens["admin"]})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read()
        assert r.status == 200
        assert r.headers.get("Content-Type") == "image/png"
        assert body[:8] == b"\x89PNG\r\n\x1a\n", "that is not a PNG"
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert "sandbox" in (r.headers.get("Content-Security-Policy") or "")

    blank = _drawing(proj["id"], d["id"], image="", seq=2)
    try:
        urllib.request.urlopen(urllib.request.Request(
            base_url + "/api/pm/acceptance/drawing?id=" + blank["id"],
            headers={"Authorization": "Bearer " + tokens["admin"]}), timeout=10)
        assert False, "a row with no image must not return 200"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_the_image_endpoint_will_not_serve_a_project_you_are_not_on(base_url, proj, tokens):
    """Scoping is not re-implemented in that endpoint — it goes through _coll_one, which runs the
    LIST and picks the row out of it. A second answer to the same question is how two gates come to
    disagree; this asserts the one that is there actually bites."""
    import urllib.request
    import urllib.error

    d = _dossier(proj["id"])
    dr = _drawing(proj["id"], d["id"])
    try:
        urllib.request.urlopen(urllib.request.Request(
            base_url + "/api/pm/acceptance/drawing?id=" + dr["id"]), timeout=10)
        assert False, "an unauthenticated caller was served a project drawing"
    except urllib.error.HTTPError as e:
        assert e.code in (401, 403)


# ── composing a dossier ─────────────────────────────────────────────────────────────────────────

def test_composing_copies_the_checklist_rather_than_pointing_at_it(base_url, proj):
    """A dossier that referenced the library would change its own wording every time the library was
    edited, and a minute signed in March would quietly start saying what the form says in
    September."""
    kind, _, out = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "formCode": "ELE-202",
        "refNo": "ZZ-ELE-900"})
    assert kind == "json", out
    did = out["dossier"]["id"]
    rows = [r for r in db.list_collection("pm_acc_items") if r.get("dossierId") == did]
    assert len(rows) == len(A.form("ELE-202")["items"]) > 5
    assert all(r["result"] == "" for r in rows), "a copied checklist starts unanswered"
    assert out["dossier"]["formCode"] == "ELE-202"


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
        "projectId": proj["id"], "code": "ELE-202", "disc": "ELE",
        "vi": "Bản của dự án", "en": "The project's own",
        "items": [{"vi": "Một mục duy nhất", "en": "One single line"}]})
    _, _, out = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "formCode": "ELE-202"})
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


# ── coverage at the boundary ────────────────────────────────────────────────────────────────────

def _itp_row(pid, no, **kw):
    r = {"projectId": pid, "itpNo": no, "title": "Lắp đặt thang máng cáp", "discipline": "ELE"}
    r.update(kw)
    return db.put_collection_item("pm_quality_itp", r)


def test_coverage_is_computed_on_the_server_from_the_projects_own_rows(base_url, proj):
    """This figure ends up in a progress report. Two implementations of it — one here, one in the
    browser — would eventually disagree with nobody able to say which was right, which is the same
    argument that put the readiness verdict on this side."""
    t = _itp_row(proj["id"], "ITP-001")
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED, itpId=t["id"])
    kind, _, out = _H()._acc_coverage_ep(PM, {"projectId": [proj["id"]]})
    assert kind == "json"
    c = out["coverage"]
    assert c["itp"]["total"] == 1 and c["itp"]["accepted"] == 1
    assert c["trust"]["level"] == "full"


def test_coverage_does_not_leak_another_projects_registers(base_url, proj):
    other = db.put_collection_item("pm_projects", {"name": "ZZ Other", "manager": "Nobody"})
    try:
        _itp_row(other["id"], "OTHER-001")
        _itp_row(proj["id"], "ITP-001")
        _, _, out = _H()._acc_coverage_ep(BOSS, {"projectId": [proj["id"]]})
        nos = [r["no"] for r in out["coverage"]["itp"]["rows"]]
        assert nos == ["ITP-001"]
    finally:
        for r in list(db.list_collection("pm_quality_itp")):
            if r.get("projectId") == other["id"]:
                db.delete_collection_item("pm_quality_itp", r["id"])
        db.delete_collection_item("pm_projects", other["id"])


def test_coverage_refuses_a_project_you_are_not_on(base_url, proj):
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    kind, status, _ = _H()._acc_coverage_ep(stranger, {"projectId": [proj["id"]]})
    assert kind == "err" and status == 403


def test_linking_a_dossier_to_an_itp_and_back_off_again(base_url, proj):
    t = _itp_row(proj["id"], "ITP-001")
    d = _dossier(proj["id"])
    kind, _, out = _H()._acc_link_ep(PM, {"dossierId": d["id"], "itpId": t["id"]})
    assert kind == "json", out
    assert db.get_collection_item("pm_acc", d["id"])["itpId"] == t["id"]
    _H()._acc_link_ep(PM, {"dossierId": d["id"], "itpId": ""})
    assert db.get_collection_item("pm_acc", d["id"])["itpId"] == ""


def test_a_link_can_never_point_at_another_projects_itp(base_url, proj):
    """The one way a coverage figure could be corrupted from outside the project it belongs to."""
    other = db.put_collection_item("pm_projects", {"name": "ZZ Other 2", "manager": "Nobody"})
    try:
        foreign = _itp_row(other["id"], "OTHER-001")
        d = _dossier(proj["id"])
        kind, status, msg = _H()._acc_link_ep(PM, {"dossierId": d["id"], "itpId": foreign["id"]})
        assert kind == "err" and status == 400 and "different project" in msg
        assert not db.get_collection_item("pm_acc", d["id"]).get("itpId")
    finally:
        for r in list(db.list_collection("pm_quality_itp")):
            if r.get("projectId") == other["id"]:
                db.delete_collection_item("pm_quality_itp", r["id"])
        db.delete_collection_item("pm_projects", other["id"])


def test_a_signed_minutes_LINKS_can_still_be_corrected(base_url, proj):
    """What the minute says about the inspection is frozen. Which ITP it answers is bookkeeping, and
    a dossier filed against the wrong plan is something somebody should be able to put right rather
    than work around."""
    t = _itp_row(proj["id"], "ITP-001")
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    kind, _, _ = _H()._acc_link_ep(PM, {"dossierId": d["id"], "itpId": t["id"]})
    assert kind == "json"
    assert db.get_collection_item("pm_acc", d["id"])["itpId"] == t["id"]
    # …and the freeze on what it SAYS is untouched by that
    ln = _line(proj["id"], d["id"], result="Không đạt")
    kind2, _, _ = _update(PM, "pm_acc_items", ln["id"], dict(ln, result="Đạt"))
    assert kind2 == "err"


def test_linking_refuses_a_project_you_are_not_on(base_url, proj):
    t = _itp_row(proj["id"], "ITP-001")
    d = _dossier(proj["id"])
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    kind, status, _ = _H()._acc_link_ep(stranger, {"dossierId": d["id"], "itpId": t["id"]})
    assert kind == "err" and status == 403


def test_composing_can_link_at_birth(base_url, proj):
    """The cheapest moment to link is while the person is looking at the ITP anyway."""
    t = _itp_row(proj["id"], "ITP-001")
    kind, _, out = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "itpId": t["id"], "stage": "mep_rough"})
    assert kind == "json", out
    assert out["dossier"]["itpId"] == t["id"]
    assert out["dossier"]["stage"] == "mep_rough"


def test_composing_refuses_a_stage_this_app_does_not_know(base_url, proj):
    kind, status, msg = _H()._acc_compose_ep(PM, {
        "projectId": proj["id"], "accType": "work", "stage": "phase-4b"})
    assert kind == "err" and status == 400 and "stage" in msg


# ── the completion dossier index at the boundary ────────────────────────────────────────────────

import acceptance_index as X


def _idx_row(pid, no):
    return next((r for r in db.list_collection("pm_acc_index")
                 if r.get("projectId") == pid and str(r.get("no")).upper() == no), None)


def test_the_index_counts_the_registers_and_reports_the_split(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED, accType="work")
    kind, _, out = _H()._acc_index_ep(PM, {"projectId": [proj["id"]]})
    assert kind == "json"
    ix = out["index"]
    row = next(r for r in ix["rows"] if r["no"] == "III.7")
    assert row["state"] == X.ST_HELD and row["count"] == 1
    assert ix["summary"]["counted"] >= 1 and ix["summary"]["declared"] == 0


def test_a_declaration_takes_its_name_and_date_from_the_session_not_the_body(base_url, proj):
    """The whole reason this is not a generic PATCH. A body-supplied signer would let an index row
    carry an attestation nobody gave — on the sheet a handover meeting signs off from."""
    kind, _, out = _H()._acc_index_declare_ep(PM, {
        "projectId": proj["id"], "no": "I.1", "declared": True, "ref": "QĐ 123/QĐ-UBND",
        "declaredBy": "Somebody Else", "declaredById": "U-FAKE", "declaredOn": "1999-01-01"})
    assert kind == "json", out
    row = _idx_row(proj["id"], "I.1")
    assert row["declaredBy"] == PM["name"] and row["declaredById"] == PM["id"]
    assert row["declaredOn"] != "1999-01-01"


def test_withdrawing_a_declaration_clears_the_name_with_it(base_url, proj):
    """A name left behind on a withdrawn declaration reads as an attestation that still stands."""
    _H()._acc_index_declare_ep(PM, {"projectId": proj["id"], "no": "I.1", "declared": True})
    _H()._acc_index_declare_ep(PM, {"projectId": proj["id"], "no": "I.1", "declared": False})
    row = _idx_row(proj["id"], "I.1")
    assert row["declared"] is False and row["declaredBy"] == "" and row["declaredOn"] == ""


def test_a_counted_row_cannot_be_satisfied_by_declaring_it(base_url, proj):
    """Refused at the endpoint as well as in the module. Otherwise the index would report a dossier
    the register cannot produce, which is the one claim this whole screen exists to prevent."""
    kind, status, msg = _H()._acc_index_declare_ep(PM, {
        "projectId": proj["id"], "no": "III.7", "declared": True})
    assert kind == "err" and status == 409
    assert "counted from the register" in msg


def test_striking_an_item_off_needs_a_reason(base_url, proj):
    kind, status, msg = _H()._acc_index_declare_ep(PM, {
        "projectId": proj["id"], "no": "I.3", "applies": False, "naReason": ""})
    assert kind == "err" and status == 400 and "why" in msg
    kind2, _, _ = _H()._acc_index_declare_ep(PM, {
        "projectId": proj["id"], "no": "I.3", "applies": False,
        "naReason": "Công trình không thuộc đối tượng phải cấp phép xây dựng."})
    assert kind2 == "json"
    assert _idx_row(proj["id"], "I.3")["applies"] is False


def test_an_unknown_item_number_is_refused(base_url, proj):
    kind, status, _ = _H()._acc_index_declare_ep(PM, {
        "projectId": proj["id"], "no": "IX.99", "declared": True})
    assert kind == "err" and status == 400


def test_the_index_refuses_a_project_you_are_not_on(base_url, proj):
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    kind, status, _ = _H()._acc_index_ep(stranger, {"projectId": [proj["id"]]})
    assert kind == "err" and status == 403
    kind2, status2, _ = _H()._acc_index_declare_ep(stranger, {
        "projectId": proj["id"], "no": "I.1", "declared": True})
    assert kind2 == "err" and status2 == 403


def test_a_clearance_with_no_document_number_does_not_tick_its_own_row(base_url, proj):
    """An applicable clearance with nothing behind it is exactly the gap this index exists to
    surface. Counting it would hide the thing being looked for."""
    _dossier(proj["id"], status=A.STATUS_ACCEPTED, accType="handover_all",
             clearances=[{"key": "fire", "applies": True, "ref": ""}])
    _, _, out = _H()._acc_index_ep(PM, {"projectId": [proj["id"]]})
    assert next(r for r in out["index"]["rows"] if r["no"] == "III.12")["count"] == 0
    _dossier(proj["id"], refNo="ZZ-ELE-777", status=A.STATUS_ACCEPTED, accType="handover_all",
             clearances=[{"key": "fire", "applies": True, "ref": "Số 123/NT-PCCC"}])
    _, _, out2 = _H()._acc_index_ep(PM, {"projectId": [proj["id"]]})
    assert next(r for r in out2["index"]["rows"] if r["no"] == "III.12")["count"] == 1


def test_the_punch_list_row_counts_across_the_whole_project(base_url, proj):
    """Điều 24(3)'s annex is ONE list bound into the completion dossier, however many minutes
    contributed to it."""
    a = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    b = _dossier(proj["id"], refNo="ZZ-ELE-778", status=A.STATUS_ACCEPTED)
    for did in (a["id"], b["id"]):
        db.put_collection_item("pm_acc_defects", {
            "projectId": proj["id"], "dossierId": did, "description": "x",
            "impact": "cosmetic", "status": "Open"})
    _, _, out = _H()._acc_index_ep(PM, {"projectId": [proj["id"]]})
    assert next(r for r in out["index"]["rows"] if r["no"] == "III.11")["count"] == 2


def test_a_closed_defect_leaves_the_annex(base_url, proj):
    d = _dossier(proj["id"], status=A.STATUS_ACCEPTED)
    db.put_collection_item("pm_acc_defects", {
        "projectId": proj["id"], "dossierId": d["id"], "description": "x",
        "impact": "cosmetic", "status": "Closed"})
    _, _, out = _H()._acc_index_ep(PM, {"projectId": [proj["id"]]})
    assert next(r for r in out["index"]["rows"] if r["no"] == "III.11")["count"] == 0


def test_the_index_does_not_count_another_projects_records(base_url, proj):
    other = db.put_collection_item("pm_projects", {"name": "ZZ Other 3", "manager": "Nobody"})
    try:
        db.put_collection_item("pm_acc", {"projectId": other["id"], "accType": "work",
                                          "status": A.STATUS_ACCEPTED})
        _, _, out = _H()._acc_index_ep(BOSS, {"projectId": [proj["id"]]})
        assert next(r for r in out["index"]["rows"] if r["no"] == "III.7")["count"] == 0
    finally:
        for r in list(db.list_collection("pm_acc")):
            if r.get("projectId") == other["id"]:
                db.delete_collection_item("pm_acc", r["id"])
        db.delete_collection_item("pm_projects", other["id"])


# ── the invitation at the boundary ──────────────────────────────────────────────────────────────
#
# This is the only thing in the module that leaves the building. Everything below is about the two
# ways an outward-facing action lies: by sending when it should not, and by reporting success when
# nothing arrived.

CONTACTS = {"contractor": "site@humiley.com",
            "supervisor": "Trần Văn B <b@ricons.example>",
            "client": [{"name": "Phạm C", "email": "c@slp.example"}]}


@pytest.fixture
def mail(monkeypatch):
    """Capture every send instead of making one. No test in this file may put a message on the
    wire — the addresses above are .example domains for the same reason."""
    box = {"sent": [], "ok": True, "err": ""}

    def fake(sender, to, subject, html, cc=None):
        box["sent"].append({"sender": sender, "to": list(to or []), "cc": list(cc or []),
                            "subject": subject, "html": html})
        return (box["ok"], box["err"])

    monkeypatch.setattr(app, "_graph_send_now", fake)
    return box


def _plan(pid, **kw):
    r = {"projectId": pid, "arfNo": "ZZ-ARF-ELE-001", "title": "Lắp đặt thang máng cáp",
         "titleEn": "Cable tray installation", "acceptDate": "2026-09-24", "timeFrom": "9h00",
         "timeTo": "9h30", "location": "Tầng 1 - Xưởng A3", "discipline": "ELE",
         "formCode": "ELE-202"}
    r.update(kw)
    return db.put_collection_item("pm_acc_plans", r)


def _contacts(pid, c=None):
    db.put_collection_item("pm_settings", {"id": pid, "projectId": pid,
                                           "accContacts": CONTACTS if c is None else c})


def test_the_preview_shows_what_would_go_out_and_sends_nothing(base_url, proj, mail):
    """Nobody should have to press a button that emails a customer in order to find out what the
    customer will read."""
    p = _plan(proj["id"]); _contacts(proj["id"])
    kind, _, out = _H()._acc_notice_preview_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    assert kind == "json"
    assert mail["sent"] == [], "the preview sent a message"
    assert out["plan"]["to"] == ["b@ricons.example"]
    # Exactly the contractor's address, not "one of two things I could not be bothered to check".
    assert out["plan"]["cc"] == ["site@humiley.com"]
    assert "Thư mời nghiệm thu" in out["subject"] and "Inspection invitation" in out["subject"]
    assert "ZZ-ARF-ELE-001" in out["subject"]


def test_the_invitation_is_bilingual_and_cites_the_article(base_url, proj, mail):
    p = _plan(proj["id"]); _contacts(proj["id"])
    _, _, out = _H()._acc_notice_preview_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    h = out["html"]
    assert "Thư mời nghiệm thu" in h and "Invitation to an acceptance inspection" in h
    assert "Điều 21" in h, "the invitation says what it is being called under"
    assert "Tầng 1 - Xưởng A3" in h and "9h00" in h
    assert "signed in person on site" in h, "the consultant is told the minute is signed there"


def test_sending_records_who_what_and_when(base_url, proj, mail):
    p = _plan(proj["id"]); _contacts(proj["id"])
    kind, _, out = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    assert kind == "json", out
    assert len(mail["sent"]) == 1
    assert mail["sent"][0]["to"] == ["b@ricons.example"]
    row = db.get_collection_item("pm_acc_plans", p["id"])
    assert row["noticeSentBy"] == PM["name"] and row["noticeSentAt"]
    assert len(row["noticeLog"]) == 1 and row["noticeLog"][0]["ok"] is True


def test_a_failed_send_is_reported_as_a_failure_and_never_as_sent(base_url, proj, mail):
    """The whole reason this uses the BLOCKING sender. "I invited the consultant" is a claim a
    project relies on weeks later, in front of somebody disputing it."""
    p = _plan(proj["id"]); _contacts(proj["id"])
    mail["ok"] = False; mail["err"] = "Mail.Send is not consented"
    kind, status, msg = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    assert kind == "err" and status == 502
    assert "Mail.Send" in msg
    row = db.get_collection_item("pm_acc_plans", p["id"])
    assert not row.get("noticeSentAt"), "a failed send must not stamp the row as sent"
    assert row["noticeLog"][-1]["ok"] is False and row["noticeLog"][-1]["error"]


def test_every_attempt_is_logged_including_the_failures(base_url, proj, mail):
    """A log keeping only the last send cannot answer "when did you first invite us", which is the
    only question it will ever be asked — and one that dropped failures would show a clean history
    of a message nobody received."""
    p = _plan(proj["id"]); _contacts(proj["id"])
    mail["ok"] = False
    _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    mail["ok"] = True
    _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    log = db.get_collection_item("pm_acc_plans", p["id"])["noticeLog"]
    assert [x["ok"] for x in log] == [False, True]


def test_no_recipient_refuses_rather_than_sending_to_nobody(base_url, proj, mail):
    """An invitation with an empty recipient list is silence that looks like success. The project
    finds out when the consultant does not turn up."""
    p = _plan(proj["id"]); _contacts(proj["id"], {"contractor": "site@humiley.com"})
    kind, status, msg = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    assert kind == "err" and status == 409
    assert "No email address recorded" in msg
    assert mail["sent"] == []
    assert not db.get_collection_item("pm_acc_plans", p["id"]).get("noticeLog")


def test_a_missing_particular_refuses_and_names_every_one(base_url, proj, mail):
    p = _plan(proj["id"], acceptDate="", location=""); _contacts(proj["id"])
    kind, status, msg = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": p["id"]})
    assert kind == "err" and status == 409
    assert "acceptance date" in msg and "location" in msg
    assert mail["sent"] == []


def test_an_invitation_can_be_sent_from_a_dossier_too(base_url, proj, mail):
    """A project invites from whichever register it happens to be looking at."""
    _contacts(proj["id"])
    d = _dossier(proj["id"], acceptDate="2026-09-24", timeFrom="9h00",
                 location="Tầng 1", title="Lắp đặt thang máng cáp")
    kind, _, _ = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "dossierId": d["id"]})
    assert kind == "json"
    assert db.get_collection_item("pm_acc", d["id"])["noticeSentAt"]


def test_a_completion_invitation_needs_the_client_recorded(base_url, proj, mail):
    _contacts(proj["id"], {"contractor": "site@humiley.com", "supervisor": "b@ricons.example"})
    d = _dossier(proj["id"], accType="handover_part", acceptDate="2026-09-24", timeFrom="9h00",
                 location="Xưởng A3", title="Nghiệm thu hoàn thành")
    kind, status, msg = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "dossierId": d["id"]})
    assert kind == "err" and status == 409 and "client" in msg
    assert mail["sent"] == []


def test_neither_endpoint_serves_a_project_you_are_not_on(base_url, proj, mail):
    p = _plan(proj["id"]); _contacts(proj["id"])
    stranger = {"id": "U-NOBODY", "name": "Ai Đó", "role": "staff", "level": "viewer"}
    for fn in (_H()._acc_notice_preview_ep, _H()._acc_notice_send_ep):
        kind, status, _ = fn(stranger, {"projectId": proj["id"], "planId": p["id"]})
        assert kind == "err" and status == 403
    assert mail["sent"] == []


def test_an_unknown_inspection_is_a_404_not_an_empty_invitation(base_url, proj, mail):
    kind, status, _ = _H()._acc_notice_send_ep(PM, {"projectId": proj["id"], "planId": "nope"})
    assert kind == "err" and status == 404
    assert mail["sent"] == []


def test_the_sender_is_one_the_health_panel_watches(base_url):
    """A mailbox the app sends from and the panel does not know about breaks silently — and this is
    the one message a CUSTOMER reads, so its failure is noticed outside the company first."""
    assert app._acc_sender() in [r["address"] for r in app._mail_senders()]
