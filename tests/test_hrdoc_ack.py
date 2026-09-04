"""Signing for a company document.

HR publishes a policy once; everybody it applies to reads it and signs. The signature is the whole
point — in six months the question is never "was it announced", it is "show me what they signed and
which version it was". So the record has to say who, when, and against which VERSION, and none of
those may come from the browser: a client that could choose them could sign a policy in a colleague's
name, or backdate a signature to before the incident it is meant to cover.
"""
import app
import db


def _doc(api, tokens, **kw):
    # A published document carries a file. One without is a title nobody can read, and signing for
    # it is refused — see test_a_document_with_no_file_cannot_be_signed.
    body = {"title": "Employee Handbook", "code": "HML-HR-001", "version": "1.0",
            "category": "Handbook", "audience": "All",
            "file": "data:application/pdf;base64,JVBERi0xLjQK", "fileName": "handbook.pdf"}
    body.update(kw)
    st, b = api("POST", "/api/coll/hrdocs", tokens["admin"], body)
    assert st == 200, b
    return b["item"]


def _sign(api, token, doc_id, **extra):
    body = {"docId": doc_id, "signature": "data:image/png;base64,AAA"}
    body.update(extra)
    return api("POST", "/api/coll/hrdoc_acks", token, body)


def test_an_employee_can_sign_for_a_document(api, tokens):
    d = _doc(api, tokens)
    st, b = _sign(api, tokens["staff"], d["id"])
    assert st == 200, b
    a = b["item"]
    assert a["empId"] == "HML-STF" and a["name"] == "Staff One"
    assert a["docTitle"] == "Employee Handbook" and a["docVersion"] == "1.0"


def test_you_cannot_sign_in_somebody_else_s_name(api, tokens):
    """The one that matters. A signature is worthless if the signer is a field the client fills in."""
    d = _doc(api, tokens, code="HML-HR-002")
    st, b = _sign(api, tokens["staff"], d["id"], empId="HML-ADM", name="Admin User")
    assert b["item"]["empId"] == "HML-STF", "a client signed as somebody else"
    assert b["item"]["name"] == "Staff One"


def test_a_signature_cannot_be_backdated(api, tokens):
    """Backdating would let somebody claim they had read a safety policy before an accident."""
    d = _doc(api, tokens, code="HML-HR-003")
    st, b = _sign(api, tokens["staff"], d["id"], ts="2020-01-01T00:00:00.000Z")
    assert not b["item"]["ts"].startswith("2020")


def test_the_version_signed_for_comes_from_the_published_record(api, tokens):
    """Otherwise a client could sign against v1 while reading v2 — or against a title it invented."""
    d = _doc(api, tokens, code="HML-HR-004", version="3.2", title="Code of Conduct")
    st, b = _sign(api, tokens["staff"], d["id"], docVersion="1.0", docTitle="Something harmless")
    assert b["item"]["docVersion"] == "3.2"
    assert b["item"]["docTitle"] == "Code of Conduct"


def test_you_cannot_sign_for_a_document_that_does_not_exist(api, tokens):
    st, b = _sign(api, tokens["staff"], "made-up-id")
    assert st == 404, (st, b)


def test_the_client_cannot_claim_where_the_signature_was_filed(api, tokens):
    """webUrl is the server's statement that the PDF reached SharePoint. A client that could set it
       would let an unfiled acknowledgement look filed."""
    d = _doc(api, tokens, code="HML-HR-005")
    st, b = _sign(api, tokens["staff"], d["id"], webUrl="https://example.invalid/not-really")
    assert not b["item"].get("webUrl")


def test_staff_see_only_their_own_acknowledgements(api, tokens):
    d = _doc(api, tokens, code="HML-HR-006")
    _sign(api, tokens["staff"], d["id"])
    _sign(api, tokens["other"], d["id"])
    st, b = api("GET", "/api/coll/hrdoc_acks", tokens["staff"])
    assert all(a["empId"] == "HML-STF" for a in b.get("items", []))


def test_everybody_can_read_the_published_documents(api, tokens):
    """A policy nobody can fetch is a policy nobody can sign."""
    _doc(api, tokens, code="HML-HR-007", title="HSE rules")
    st, b = api("GET", "/api/coll/hrdocs", tokens["staff"])
    assert st == 200
    assert "HSE rules" in [d.get("title") for d in b.get("items", [])]


def test_staff_cannot_publish_a_document(api, tokens):
    """Publishing decides what the whole company must sign — that is not a self-service action."""
    st, b = api("POST", "/api/coll/hrdocs", tokens["staff"],
                {"title": "My own policy", "audience": "All"})
    assert st == 403, (st, b)


def test_only_an_admin_can_create_the_employee_folders(api, tokens):
    st, b = api("POST", "/api/hr/employee-folders", tokens["mgr"], {})
    assert st == 403, (st, b)


def test_filing_somebody_else_s_acknowledgement_is_refused(api, tokens):
    d = _doc(api, tokens, code="HML-HR-008")
    ack = _sign(api, tokens["staff"], d["id"])[1]["item"]
    st, b = api("POST", "/api/hr/onboarding/file", tokens["other"],
                {"ackId": ack["id"], "data": "data:application/pdf;base64,JVBERi0="})
    assert st == 403, (st, b)


# ── due dates, reminders and the compliance view ──────────────────────────────────────────────────
#
# Without a deadline "outstanding" never becomes actionable, and somebody has to chase by hand — which
# is how this decays in every company that tries it. The deadline is counted from the LATER of
# publication and the person's start date, so a policy published in March does not show a June joiner
# as instantly delinquent.

def test_a_document_with_no_deadline_has_no_due_date(api, tokens):
    d = _doc(api, tokens, code="DUE-0")
    assert app._hrdoc_due(d, {"joinDate": "2026-01-01"}) == ""


def test_the_deadline_runs_from_publication(api, tokens):
    d = _doc(api, tokens, code="DUE-1", dueDays=7, effectiveFrom="2026-03-01")
    assert app._hrdoc_due(d, {"joinDate": "2020-01-01"}) == "2026-03-08"


def test_a_later_joiner_gets_the_deadline_from_their_start_date(api, tokens):
    """THE reason this is not just publication + N. Otherwise every new hire is born overdue."""
    d = _doc(api, tokens, code="DUE-2", dueDays=7, effectiveFrom="2026-03-01")
    assert app._hrdoc_due(d, {"joinDate": "2026-06-10"}) == "2026-06-17"


def test_an_unsigned_document_is_outstanding_and_a_signed_one_is_not(api, tokens):
    d = _doc(api, tokens, code="OUT-1", audience="Selected", empIds="HML-STF")
    pend = [p for p in app._hrdoc_outstanding() if p["doc"]["id"] == d["id"]]
    assert [p["emp"]["id"] for p in pend] == ["HML-STF"]
    _sign(api, tokens["staff"], d["id"])
    assert not [p for p in app._hrdoc_outstanding() if p["doc"]["id"] == d["id"]]


def test_a_new_version_makes_it_outstanding_again(api, tokens):
    """Re-issuing a policy must ask everyone again — the old signature covered the old text."""
    d = _doc(api, tokens, code="VER-1", version="1.0", audience="Selected", empIds="HML-STF")
    _sign(api, tokens["staff"], d["id"])
    assert not [p for p in app._hrdoc_outstanding() if p["doc"]["id"] == d["id"]]
    d["version"] = "2.0"
    api("PATCH", "/api/coll/hrdocs/" + d["id"], tokens["admin"], d)
    assert [p for p in app._hrdoc_outstanding() if p["doc"]["id"] == d["id"]]


def test_an_inactive_employee_is_not_chased(api, tokens):
    """A leaver on the outstanding list is noise that makes the whole report ignorable."""
    d = _doc(api, tokens, code="OUT-2", audience="All")
    live = {p["emp"]["id"] for p in app._hrdoc_outstanding() if p["doc"]["id"] == d["id"]}
    for e in db.list_employees():
        if str(e.get("status") or "Active").lower() == "inactive":
            assert e["id"] not in live


def test_the_compliance_view_is_manager_only(api, tokens):
    """It is a list of who is behind — management information, not self-service."""
    st, b = api("GET", "/api/hr/compliance", tokens["staff"])
    assert st == 403, (st, b)


def test_the_compliance_view_covers_everybody_not_just_the_caller(api, tokens):
    """Staff reads of the acknowledgements are scoped to their own, correctly — which is exactly why
       this has to be computed on the server."""
    d = _doc(api, tokens, code="MTX-1", audience="All")
    st, b = api("GET", "/api/hr/compliance", tokens["mgr"])
    assert st == 200, b
    who = {r["empId"] for r in b["rows"] if r["docId"] == d["id"]}
    assert {"HML-STF", "HML-OTH"} <= who


def test_the_compliance_view_reports_a_rate_per_document(api, tokens):
    """One person behind is a person. Most of a department behind is a failed rollout."""
    d = _doc(api, tokens, code="MTX-2", audience="Selected", empIds="HML-STF,HML-OTH")
    _sign(api, tokens["staff"], d["id"])
    b = api("GET", "/api/hr/compliance", tokens["mgr"])[1]
    stat = [x for x in b["docs"] if x["id"] == d["id"]][0]
    assert stat["required"] == 2 and stat["signed"] == 1 and stat["pct"] == 50


def test_reminders_are_manager_only(api, tokens):
    st, b = api("POST", "/api/hr/remind", tokens["staff"], {})
    assert st == 403, (st, b)


# ── migrating the old tick-box policies ───────────────────────────────────────────────────────────
#
# Two places that both mean "acknowledged" is the problem. But the old records ARE records, so they
# are carried across rather than deleted — and carried across honestly. A tick-box that arrives
# wearing a signature image would be a forgery, and an auditor who finds one is worse off than one
# who reads "acknowledged by tick-box on this date".

def test_the_migration_publishes_the_old_policies(api, tokens):
    st, b = api("POST", "/api/hr/policy-migrate", tokens["admin"], {})
    assert st == 200, b
    codes = {d.get("code") for d in db.list_collection("hrdocs")}
    assert {"HML-HR-001", "HML-HR-002", "HML-IT-001", "HML-LE-001", "HML-HSE-001", "HML-CB-001"} <= codes


def test_an_old_tick_box_is_carried_over_without_inventing_a_signature(api, tokens):
    """THE line that matters. It becomes a record marked as what it was."""
    db.put_collection_item("acks", {"empId": "HML-MGT", "doc": "IT Acceptable Use Policy", "ts": "2026-03-12"})
    api("POST", "/api/hr/policy-migrate", tokens["admin"], {})
    doc = [d for d in db.list_collection("hrdocs") if d.get("code") == "HML-IT-001"][0]
    got = [a for a in db.list_collection("hrdoc_acks")
           if a.get("docId") == doc["id"] and a.get("empId") == "HML-MGT"]
    assert got, "the existing acknowledgement was lost"
    a = got[0]
    assert a["method"] == "legacy-tickbox"
    assert not a.get("signature"), "a signature image was invented for a tick-box"
    assert a["ts"] == "2026-03-12", "the original date was not preserved"
    assert "tick-box" in a["meaning"]


def test_a_real_signature_is_never_replaced_by_a_legacy_record(api, tokens):
    """If somebody has already signed properly, importing the old tick-box list must not downgrade
       their signature to "acknowledged by tick-box"."""
    d = _doc(api, tokens, code="HML-LE-001", title="Confidentiality, IP & Data", version="1.0")
    _sign(api, tokens["other"], d["id"])
    db.put_collection_item("acks", {"empId": "HML-OTH", "doc": "Confidentiality, IP & Data", "ts": "2020-01-01"})
    api("POST", "/api/hr/policy-migrate", tokens["admin"], {})
    got = [a for a in db.list_collection("hrdoc_acks")
           if a.get("docId") == d["id"] and a.get("empId") == "HML-OTH"]
    assert len(got) == 1, "the migration added a duplicate acknowledgement"
    assert got[0].get("method") != "legacy-tickbox", "a real signature was downgraded"
    assert got[0].get("signature"), "the signature image was lost"


def test_the_migration_can_be_run_twice_without_duplicating(api, tokens):
    db.put_collection_item("acks", {"empId": "HML-OTH", "doc": "HSE / Site Safety", "ts": "2026-04-01"})
    api("POST", "/api/hr/policy-migrate", tokens["admin"], {})
    before = len(db.list_collection("hrdoc_acks")), len(db.list_collection("hrdocs"))
    st, b = api("POST", "/api/hr/policy-migrate", tokens["admin"], {})
    assert (b["documents"], b["acknowledgements"]) == (0, 0)
    assert (len(db.list_collection("hrdoc_acks")), len(db.list_collection("hrdocs"))) == before


def test_only_an_admin_can_migrate(api, tokens):
    st, b = api("POST", "/api/hr/policy-migrate", tokens["mgr"], {})
    assert st == 403, (st, b)


def test_the_hardcoded_policy_library_is_gone_from_the_frontend():
    """Two places that mean "acknowledged", only one of which produces a signature, is the thing this
       whole change exists to remove."""
    import os
    idx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "index.html")
    with open(idx, encoding="utf-8") as fh:
        src = fh.read()
    assert "_POLICY_LIB" not in src, "the hardcoded policy list is still there"
    assert "function tkConfirmPolicy" not in src, "the tick-box acknowledgement flow is still there"


def test_the_onboarding_module_is_actually_wired_up():
    """The Onboarding tab is a tab, a dispatch line and a My Tools card that all call functions
       defined somewhere else in a 22,000-line file. A previous edit removed the definitions while
       leaving every reference in place: the file parsed, every backend test passed, and the tab was
       dead. Nothing catches that except checking the definitions exist."""
    import os
    idx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "index.html")
    with open(idx, encoding="utf-8") as fh:
        src = fh.read()
    for fn in ("tkRenderMyOnboarding", "tkOnbSign", "tkOnbSignSave", "tkOnbOpen",
               "_onbForMe", "_onbAck", "_onbAckPdf", "_onbFileAck", "tkRenderCompliance",
               "tkCompExport", "tkCompRemind", "tkPolicyMigrate",
               "tkRenderDocRegister", "tkDocArchive", "tkDocReissue", "_hrDocHasFile",
               "_hrDocSigned"):
        assert ("function " + fn) in src, "%s is referenced but no longer defined" % fn
    # And the wiring that reaches them.
    assert "'myonboarding'" in src and "myonboarding-root" in src
    assert "id=\"hr-compliance\"" in src, "the compliance view has no host element"
    assert "id=\"hr-docreg\"" in src, "the published-documents register has no host element"


def test_a_published_document_can_be_opened_for_editing():
    """The register's whole reason to exist: before it, `hrdocs` was the one compliance-critical
    collection with no edit affordance anywhere, so a document published without its PDF stayed that
    way for good. tkQuickAdd's second argument is what puts the form in edit mode."""
    import os
    import re
    idx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "index.html")
    with open(idx, encoding="utf-8") as fh:
        src = fh.read()
    assert "tkQuickAdd(\\'hrdocs\\',\\'" in src, "no edit-mode call site for hrdocs"
    # And saving has to repaint the REGISTER, or a successful save looks like a failed one. This
    # assertion used to name the tab ('recruitment', then 'onboarding') — pinning the mechanism
    # rather than the intent, so it went green while pointing at a view the register had moved off.
    # The register now mounts on both Onboarding and Compliance, so what must hold is that whatever
    # `reload` names has a handler, and that the handler repaints the register itself.
    m = re.search(r"coll: 'hrdocs', reload: '([a-z_]+)'", src)
    assert m, "the hrdocs quick-add spec names no reload target"
    target = m.group(1)
    handler = re.search(r"^\s*" + target + r": \(\) => (\w+)\(", src, re.M)
    assert handler, "reload target '%s' has no entry in _HR_RELOAD" % target
    assert handler.group(1) in ("tkRenderCompliance", "tkRenderDocRegister"), (
        "saving a document repaints %s(), which does not redraw the register" % handler.group(1))
