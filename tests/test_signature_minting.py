"""A signature that changes no status is a SUBMISSION — it is only ever your own, and only on a
request nobody has decided yet.

The hole this closes. /api/esign waives its ownership gate entirely for anyone whose `role` is
"manager", because a manager legitimately signs other people's records in order to approve them. And
_appr_check used to open with:

    if not t:
        return None   # requester's own submit signing (no status change)

— no owner check, no status check. The comment describes the intent perfectly and the code enforced
none of it. Meanwhile the frontend's _accessMap gives `role: 'manager'` to EVERY access level from
Contributor upward, so "manager" is not a small group; it is everybody except plain staff.

The result, on the live system: any non-staff user could append their own e-signature, carrying any
`meaning` string they liked, to ANY claim, travel, payment or leave record — including other people's,
and including records already Approved or Paid.

What it could NOT do is worth stating precisely, because it bounds the damage: the signer's name,
email and userId are taken from the authenticated session, so nobody could sign as somebody else; and
with no `setStatus` no status moved and no money moved. What it COULD do is write arbitrary entries
into the Part 11 signature manifestation — the block that renders on the record detail and on the
archived PDF that goes to a client — and a matching row into the audit log. For a platform whose whole
claim is that its signed records are trustworthy, that is the part that matters.
"""
import app
import db

PDF = "data:application/pdf;base64,QQ=="


def _payment(api, tokens, who="staff", ref="PR-MINT"):
    st, b = api("POST", "/api/coll/payments", tokens[who],
                {"reqNo": ref, "payee": "Vendor", "amount": 1000, "attachment": PDF})
    assert st == 200, b
    return b["item"]["id"]


def _row(pid):
    return next(x for x in db.list_collection("payments") if x.get("id") == pid)


def _sign(api, token, pid, meaning="Submitted", status=None, coll="payments"):
    body = {"coll": coll, "id": pid, "meaning": meaning}
    if status:
        body["setStatus"] = status
    return api("POST", "/api/esign", token, body)


# ── the hole ──────────────────────────────────────────────────────────────────────────────────────

def test_a_manager_cannot_append_a_signature_to_someone_elses_request(api, tokens, monkeypatch):
    """THE load-bearing test. 'mgr' did not raise this payment and is changing no status."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _payment(api, tokens, "staff", "PR-MINT-1")
    before = len(_row(pid).get("signatures") or [])
    st, b = _sign(api, tokens["mgr"], pid, "I was definitely involved in this")
    assert st == 403, (st, b)
    assert "your own" in (b.get("error") or "").lower(), b
    assert len(_row(pid).get("signatures") or []) == before, "a signature was minted anyway"


def test_no_level_above_staff_can_do_it_either(api, tokens, monkeypatch):
    """_accessMap maps manager, management, editor AND admin all to role='manager', so the gate the
       hole rode through was open to every one of them. Admin included — there is no override here:
       an admin has no business claiming to have personally signed somebody else's request."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    for who in ("mgr", "management", "editor", "admin"):
        pid = _payment(api, tokens, "staff", "PR-MINT-" + who)
        st, b = _sign(api, tokens[who], pid, "Reviewed and endorsed by me")
        assert st == 403, (who, st, b)
        assert not _row(pid).get("signatures") or all(
            s.get("userId") != app.db.get_employee(
                {"mgr": "HML-MGR", "management": "HML-MGT", "editor": "HML-EDT", "admin": "HML-ADM"}[who]
            ).get("id") for s in _row(pid)["signatures"]), (who, "signature landed")


def test_a_decided_request_accepts_no_further_submission_signatures(api, tokens, monkeypatch):
    """Even the OWNER cannot keep signing their own request once it has been decided — that is the
       second half of the guard, and it is what stops a signature being minted onto a Paid record to
       manufacture something to point at."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _payment(api, tokens, "staff", "PR-MINT-DEC")
    assert _sign(api, tokens["management"], pid, "Approve", "Approved")[0] == 200
    st, b = _sign(api, tokens["staff"], pid, "Adding a note after the fact")
    assert st == 403, (st, b)
    assert "decided" in (b.get("error") or "").lower(), b


# ── what must still work, or the fix is worse than the hole ───────────────────────────────────────

def test_the_owner_can_still_sign_their_own_pending_request(api, tokens, monkeypatch):
    """The submission signature is the whole Part 11 trail — breaking it would break every submit."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _payment(api, tokens, "staff", "PR-MINT-OK")
    st, b = _sign(api, tokens["staff"], pid, "Submitted — payment request")
    assert st == 200, b
    sigs = _row(pid).get("signatures") or []
    assert sigs and sigs[-1]["name"] == "Staff One"


def test_the_owner_can_still_sign_an_amendment_after_review(api, tokens, monkeypatch):
    """Amending a reviewed request drops it back to Submitted and re-signs — that path must survive."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _payment(api, tokens, "staff", "PR-MINT-AMEND")
    assert _sign(api, tokens["mgr"], pid, "Review", "Reviewed")[0] == 200
    st, b = _sign(api, tokens["staff"], pid, "Amendment — corrected the amount")
    assert st == 200, b


def test_a_manager_can_still_approve_someone_elses_request(api, tokens, monkeypatch):
    """Ownership gates the STATUS-LESS path only. Approving other people's requests is the job."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    pid = _payment(api, tokens, "staff", "PR-MINT-APPR")
    st, b = _sign(api, tokens["management"], pid, "Approve — payment", "Approved")
    assert st == 200, b
    assert _row(pid)["status"] == "Approved"


def test_ownership_is_recognised_on_a_record_with_no_empid(api, tokens, monkeypatch):
    """Ownership is spelled differently per collection — empId, createdById, owner, name. The guard
       reuses the SAME expression the record gate already computed, so a record identified only by
       name is still signable by the person it belongs to. Keying it on empId alone would have
       silently broken submissions on every record that does not carry one."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    st, b = api("POST", "/api/coll/travel", tokens["staff"],
                {"dest": "Da Nang", "purpose": "Site visit", "cost": 500})
    assert st == 200, b
    tid = b["item"]["id"]
    row = next(x for x in db.list_collection("travel") if x.get("id") == tid)
    assert row.get("empId") or row.get("name"), "fixture assumption: the record identifies its owner"
    st, b = api("POST", "/api/esign", tokens["staff"],
                {"coll": "travel", "id": tid, "meaning": "Submitted — travel request"})
    assert st == 200, b
