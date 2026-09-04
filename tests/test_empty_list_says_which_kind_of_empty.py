# -*- coding: utf-8 -*-
"""An empty register must not tell you the company has no records when you simply cannot see them.

Reported from production, and it cost the owner of the system a bad few minutes: the Payment Register
showed 0 requests, ₫0 approved, ₫0 paid and the sentence

    "No payment requests yet — click 'New Payment Request'."

while every row was still in the database. app.py scopes claims / travel / payments by DEPARTMENT for
a caller at level `manager`, and a manager with no department set sees only their own records. The
account said "Managing Director" — a job title, not a portal level.

Two sentences, one true and one false, and no way to tell them apart from the screen. So the list
read now says which kind of empty it is, and it says it ONLY when it is true: the flag is set when
the answer is empty AND there were rows before scoping. It carries no row, no field and no count —
knowing that something exists is the whole of what it reveals, and the alternative was a screen that
lied about the company's own money.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402


@pytest.fixture
def payments(base_url):
    """Three payments raised by two people in two departments; none by the caller under test.

    The whole collection is put back afterwards. Other tests in this suite leave payments behind and
    read them later, so a fixture that owned the table by wiping it would break them — and the first
    version of this file did exactly that.
    """
    _before = {r["id"]: r for r in db.list_collection("payments")}
    made = []
    for i, (emp, nm, dept) in enumerate([("HML-STF", "Staff One", "Engineering"),
                                         ("HML-OTH", "Other Staff", "Operation"),
                                         ("HML-STF", "Staff One", "Engineering")]):
        rid = "scoped-%d" % i
        db.put_collection_item("payments", {
            "id": rid, "reqNo": "PR-%04d" % i, "empId": emp, "name": nm, "department": dept,
            "payee": "Supplier %d" % i, "category": "Equipment", "amount": 145800000 + i,
            "status": "Submitted"})
        made.append(rid)
    yield
    for row in db.list_collection("payments"):
        try:
            db.delete_collection_item("payments", row["id"])
        except Exception:
            pass
    for row in _before.values():
        db.put_collection_item("payments", row)


def test_a_manager_with_no_department_is_told_the_rows_are_out_of_scope(api, tokens, payments):
    """HML-MGR is level `manager`. The conftest roster gives it no dept, which is exactly the
    account shape that produced the report."""
    emp = db.get_employee("HML-MGR") or {}
    assert not (emp.get("dept") or ""), \
        "this test needs a manager with no department — the fixture roster has changed"

    st, b = api("GET", "/api/coll/payments", tokens["mgr"])
    assert st == 200, b
    assert b["items"] == [], "the scoping itself has changed; re-check this whole file"
    assert b["scoped"] is True, (
        "the response does not say the list was emptied by scope, so the register will print "
        '"No payment requests yet" at somebody whose company has three')


def test_management_sees_them_and_is_not_told_anything_about_scope(api, tokens, payments):
    st, b = api("GET", "/api/coll/payments", tokens["management"])
    assert st == 200, b
    # The three seeded rows are present — not "exactly three rows exist". Other tests leave payments
    # in this shared database, and asserting the total made this pass alone and fail in the suite.
    got = {r["id"] for r in b["items"]}
    assert {"scoped-0", "scoped-1", "scoped-2"} <= got, sorted(got)
    assert b["scoped"] is False, "nothing was hidden, so nothing should be claimed"


def test_a_genuinely_empty_register_is_not_called_a_scoping_problem(api, tokens, base_url):
    """The other half. If this ever returns True the message flips the other way and a company with
    no payments is told it cannot see its own — the same defect wearing the other face."""
    _before = {r["id"]: r for r in db.list_collection("payments")}
    for rid in _before:
        db.delete_collection_item("payments", rid)
    try:
        _assert_nobody_is_told_about_scope(api, tokens)
    finally:
        for row in _before.values():
            db.put_collection_item("payments", row)


def _assert_nobody_is_told_about_scope(api, tokens):
    for who in ("admin", "management", "mgr", "staff"):
        st, b = api("GET", "/api/coll/payments", tokens[who])
        assert st == 200, (who, b)
        assert b["items"] == [], who
        assert b["scoped"] is False, (
            "%s was told records exist that they cannot see, and there are none at all" % who)


def test_the_flag_never_leaks_what_is_behind_it(api, tokens, payments):
    """It is a yes/no. A count, an id or a department name would each be a way of reading records
    the scoping exists to withhold."""
    st, b = api("GET", "/api/coll/payments", tokens["mgr"])
    assert st == 200
    assert b["scoped"] is True
    assert set(b.keys()) <= {"items", "scoped"}, \
        "the list response grew a field: %r — check it says nothing about the hidden rows" % (
            sorted(b.keys()),)
    blob = repr(b)
    for secret in ("Supplier 0", "Supplier 1", "145800000", "Engineering", "Operation",
                   "Staff One", "Other Staff", "PR-0000"):
        assert secret not in blob, "the response carries %r from a row this caller cannot see" % secret
