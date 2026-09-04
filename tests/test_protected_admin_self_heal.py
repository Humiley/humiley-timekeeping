# -*- coding: utf-8 -*-
"""A protected super-admin cannot be locked out — on every request, not just at sign-in.

ADMIN_EMAILS exists so a mistaken demotion can never shut the company out of its own portal, and
_auth_m365 restores level/role when one of those addresses signs in with Microsoft. That promotion
runs ONCE, at the moment of sign-in. Sessions here are 30-day sliding and renew silently, so an
account demoted mid-session stayed demoted for as long as the session lived.

That is not hypothetical. The owner of this portal signs in as an address already in ADMIN_EMAILS,
sat at level `manager` with no department, and watched the Payment Register report that the company
had never raised a payment — every scoped register answers with nothing for a manager with no
department. The self-heal was working exactly as written and had simply not run since.

_session_user re-reads the employee row on every request, which is what makes a demotion take
effect immediately. The exemption now takes effect just as immediately.

WHAT MUST NOT DRIFT: this promotes on the address in the EMPLOYEE ROW, and only for the addresses
hard-coded in ADMIN_EMAILS. If it ever promoted on something a request could influence, it would be
a privilege escalation rather than a safety net — so the tests below check the negative cases as
hard as the positive one.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402
import db   # noqa: E402

PROTECTED = sorted(app.Handler.ADMIN_EMAILS)[0]


@pytest.fixture
def demoted(base_url):
    """A protected super-admin sitting at manager level with a live session — the exact state that
    produced the report."""
    eid = "HML-PROT"
    db.create_employee({"id": eid, "name": "Protected Admin", "email": PROTECTED,
                        "role": "manager", "level": "manager", "title": "Managing Director"})
    tok = app.new_session(eid, "manager")
    yield eid, tok
    try:
        db.delete_employee(eid)
    except Exception:
        pass


def test_the_next_request_restores_them_without_signing_in_again(api, demoted):
    eid, tok = demoted
    assert db.get_employee(eid)["level"] == "manager", "the fixture did not take"

    st, b = api("GET", "/api/me", tok)
    assert st == 200, b

    row = db.get_employee(eid)
    assert row["level"] == "admin", (
        "a protected super-admin was left at %r on a live session — the whole point of the list is "
        "that this cannot happen, and it is what emptied the owner's registers" % row["level"])
    assert row["role"] == "manager"


def test_a_scoped_register_answers_again_immediately(api, demoted):
    """The symptom, not just the flag. A manager with no department sees no payments; an admin sees
    them all, and the restore has to be what closes that gap."""
    eid, tok = demoted
    made = []
    try:
        for i in range(2):
            rid = "heal-%d" % i
            db.put_collection_item("payments", {"id": rid, "reqNo": "PR-H%d" % i, "empId": "HML-STF",
                                                "name": "Staff One", "department": "Engineering",
                                                "payee": "Supplier", "amount": 1000 + i,
                                                "status": "Submitted"})
            made.append(rid)
        st, b = api("GET", "/api/coll/payments", tok)
        assert st == 200, b
        got = {r["id"] for r in b["items"]}
        assert {"heal-0", "heal-1"} <= got, (
            "the register is still empty for a restored super-admin: %r" % sorted(got))
        assert b["scoped"] is False
    finally:
        for rid in made:
            try:
                db.delete_collection_item("payments", rid)
            except Exception:
                pass


def test_it_promotes_nobody_else(api, tokens):
    """The negative case, and the one that matters most: an ordinary account must come out of a
    request at exactly the level it went in with."""
    for who, eid in (("staff", "HML-STF"), ("mgr", "HML-MGR"), ("management", "HML-MGT")):
        before = db.get_employee(eid)["level"]
        st, _ = api("GET", "/api/me", tokens[who])
        assert st == 200, who
        after = db.get_employee(eid)["level"]
        assert after == before, "%s was promoted from %r to %r" % (who, before, after)


def test_the_address_comes_from_the_employee_row_not_from_the_request(api, base_url):
    """A promotion driven by anything a caller can set would be an escalation, not a safety net."""
    eid = "HML-IMP"
    db.create_employee({"id": eid, "name": "Impostor", "email": "impostor@humiley.com",
                        "role": "staff", "level": "staff"})
    tok = app.new_session(eid, "staff")
    try:
        # every plausible way of claiming to be the protected address
        for hdrs in ({"X-Forwarded-Email": PROTECTED}, {"X-User-Email": PROTECTED},
                     {"From": PROTECTED}):
            st, _ = api("GET", "/api/me", tok, None, hdrs)
            assert st == 200
            assert db.get_employee(eid)["level"] == "staff", \
                "a header promoted an account to admin: %r" % hdrs
        st, _ = api("POST", "/api/coll/acks", tok, {"email": PROTECTED, "level": "admin"})
        assert db.get_employee(eid)["level"] == "staff", "a request body promoted an account"
    finally:
        try:
            db.delete_employee(eid)
        except Exception:
            pass


def test_the_address_matches_however_it_was_typed_into_the_record(api, base_url):
    """An admin adding the employee types the address by hand. ADMIN_EMAILS is lowercase, so the
    comparison lowercases the row — every other use of this list in app.py does, and the one in
    _auth_m365 gets away with it only because Graph already returns a lowercased address."""
    eid = "HML-CASE"
    db.create_employee({"id": eid, "name": "Protected Admin", "email": PROTECTED.upper(),
                        "role": "manager", "level": "manager"})
    tok = app.new_session(eid, "manager")
    try:
        st, _ = api("GET", "/api/me", tok)
        assert st == 200
        assert db.get_employee(eid)["level"] == "admin", (
            "the row holds %r and the list holds %r — a super-admin typed in capitals is a "
            "super-admin" % (PROTECTED.upper(), PROTECTED))
    finally:
        try:
            db.delete_employee(eid)
        except Exception:
            pass


def test_a_deactivated_protected_admin_still_gets_in(api, demoted):
    """The neighbouring exemption, which this change sits directly above and must not disturb."""
    eid, tok = demoted
    db.update_employee(eid, {"status": "Inactive"})
    try:
        st, _ = api("GET", "/api/me", tok)
        assert st == 200, "a protected super-admin was locked out by a deactivation"
        assert db.get_employee(eid)["level"] == "admin"
    finally:
        db.update_employee(eid, {"status": "Active"})
