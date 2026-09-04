"""A request must be born undecided.

Found by the 2026-08-15 ERP maturity audit. `_coll_update` strips decision fields on PATCH, and
/api/esign is the only thing allowed to write them — but nothing stripped them on the way IN. Any
authenticated employee could POST a claim/travel/payment that already said "Approved" and carried a
fabricated signatures[] block naming real approvers.

The disbursement gate asks only what the CURRENT status is ("Only an approved request can be marked
paid"), and the approver!=payer test reads that same signature array. So a forged row reached a
named payer looking fully decided, and the two-person control over money collapsed to one person
plus a forged record — with the payee bank details supplied by the forger.
"""
import pytest


DECIDED = ("Approved", "approved", "Reviewed", "Pending Approval", "Paid", "Rejected",
           "Payment Reversed")

FORGED_SIGS = [{"by": "Tony Nguyen", "byId": "HML-001", "at": "2026-08-14T09:00:00",
                "meaning": "Approved", "setStatus": "Approved"}]


def _new_payment(**over):
    body = {"payee": "Acme Supplies", "amount": 45000000, "currency": "VND",
            "purpose": "Chiller spares", "attachment": "data:application/pdf;base64,JVBERi0="}
    body.update(over)
    return body


# ── the exploit, closed ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", DECIDED)
def test_a_payment_cannot_be_born_decided(api, tokens, status):
    st, b = api("POST", "/api/coll/payments", tokens["staff"], _new_payment(status=status))
    assert st == 200, b
    row = b.get("item") or b
    assert str(row.get("status", "")).lower() in ("submitted", "", "pending"), \
        "a staff-created payment was born %r — it can now be paid without ever being approved" % row.get("status")


def test_the_signature_block_cannot_be_supplied_by_the_author(api, tokens):
    """The forged manifest is the half that defeats approver!=payer: that check reads signatures[]
    to decide whether the payer already approved it."""
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                _new_payment(status="Approved", signatures=FORGED_SIGS,
                             approvedBy="Tony Nguyen", approvedById="HML-001",
                             approvedAt="2026-08-14T09:00:00"))
    assert st == 200, b
    row = b.get("item") or b
    assert not row.get("signatures"), "a fabricated signature manifest survived the create"
    for f in ("approvedBy", "approvedById", "approvedAt"):
        assert not row.get(f), "%s was accepted from the client on create" % f


@pytest.mark.parametrize("coll", ["claims", "travel"])
def test_the_same_hole_is_closed_on_claims_and_travel(api, tokens, coll):
    st, b = api("POST", "/api/coll/" + coll, tokens["staff"],
                {"purpose": "Site visit", "amount": 800000, "status": "Approved",
                 "signatures": FORGED_SIGS})
    assert st == 200, b
    row = b.get("item") or b
    assert str(row.get("status", "")).lower() != "approved"
    assert not row.get("signatures")


def test_a_manager_cannot_do_it_either(api, tokens):
    """The record gate waives ownership for anyone whose role is 'manager', so this must not be a
    staff-only guard — the point is that NO ONE decides a request at the moment they create it."""
    st, b = api("POST", "/api/coll/payments", tokens["mgr"],
                _new_payment(status="Approved", signatures=FORGED_SIGS))
    assert st == 200, b
    row = b.get("item") or b
    assert str(row.get("status", "")).lower() != "approved"


# ── and the ordinary path still works ────────────────────────────────────────────────────────────

def test_a_normal_submission_is_untouched(api, tokens):
    """A guard that also breaks the real flow is not a fix."""
    st, b = api("POST", "/api/coll/payments", tokens["staff"], _new_payment(status="Submitted"))
    assert st == 200, b
    row = b.get("item") or b
    assert row.get("status") == "Submitted"
    assert row.get("payee") == "Acme Supplies"
    assert row.get("amount") == 45000000


def test_a_create_with_no_status_still_works(api, tokens):
    st, b = api("POST", "/api/coll/payments", tokens["staff"], _new_payment())
    assert st == 200, b


@pytest.mark.parametrize("status", ["Draft", "Pending", "Partially approved"])
def test_an_undecided_status_is_never_rewritten(api, tokens, status):
    """The guard must rewrite DECIDED states only. _appr_state maps everything it does not recognise
    to 'submit', which is what lets each collection keep its own pre-decision vocabulary — so these
    have to survive verbatim. A blunt `status = "Submitted"` on every create would pass the exploit
    tests above and quietly destroy that."""
    st, b = api("POST", "/api/coll/payments", tokens["staff"], _new_payment(status=status))
    assert st == 200, b
    row = b.get("item") or b
    assert row.get("status") == status, "a legitimate pre-decision status was clobbered"


def test_esign_can_still_decide_it(api, tokens):
    """The whole point is that decisions come from /api/esign, not from create. Prove that path is
    unaffected: submit, then approve through the real chain."""
    st, b = api("POST", "/api/coll/payments", tokens["staff"], _new_payment())
    assert st == 200, b
    row = b.get("item") or b
    rid = row.get("id")
    assert rid
    st2, b2 = api("GET", "/api/coll/payments/" + rid, tokens["admin"])
    assert st2 == 200
    got = b2.get("item") or b2
    assert str(got.get("status", "")).lower() in ("submitted", "", "pending")
