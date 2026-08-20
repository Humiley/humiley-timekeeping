"""Every module family must be wired into every list that governs it.

Four times now a new module has been added to COLLECTIONS and missed one of the places that
decides who may touch it. Each was found by hand, after merge, and two were live in production:

  * eng_    — missing from the staff-write exclusion in _coll_update, so design engineers were
              refused every edit with "Manager access required".
  * ahu_    — missing from the delete-ownership guard, so any staff account could delete another
              operator's signed gate; and missing from all four Access & Permissions sites, so the
              app could not be switched off.
  * sales_  — missing from the delete-ownership guard, and with no signed-record guard, so a
              Contributor-tier manager could delete a signed, applied variation.
  * est_    — missing from the delete-ownership guard.

The failure is always silent: the record still saves, the screen still renders, and the missing
guard is only visible if somebody thinks to try the request. These tests make the omission loud at
the point it is introduced, which is the only cheap moment to fix it.

Adding a genuinely exempt family? Put it in the EXEMPT set below WITH a reason. An exemption that
has to be written down is a decision; a missing entry is an accident.
"""
import re
import app


SRC = None


def _src():
    global SRC
    if SRC is None:
        with open(app.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            SRC = fh.read()
    return SRC


def _families(literal_name):
    """The `xxx_` prefixes present in one of app.py's big set literals."""
    lit = re.search(literal_name + r" = \{(.*?)\}", _src(), re.S)
    assert lit, "could not find %s in app.py" % literal_name
    names = re.findall(r'"([a-z]+_[a-zA-Z_]+)"', lit.group(1))
    return {n.split("_")[0] + "_" for n in names}


def _guard_families(pattern):
    """The `xxx_` prefixes a guard expression tests with name.startswith(...)."""
    m = re.search(pattern, _src(), re.S)
    assert m, "could not find the guard matching %r — if it moved, update this test" % pattern
    return set(re.findall(r'startswith\("([a-z]+_)"\)', m.group(1)))


# hrdoc_ never reaches the ownership guard: hrdoc_acks is refused outright ("a signed
# acknowledgement is a permanent record"), which is stricter, and hrdocs has its own HR-admin gate.
# review_ is review_cycles, a manager-level configuration list with no per-user ownership.
EXEMPT_FROM_DELETE_OWNERSHIP = {
    "hrdoc_": "refused outright earlier in _coll_delete — stricter than ownership",
    "review_": "review_cycles is manager-level configuration, not a per-person record",
}


def test_every_collection_family_is_in_the_delete_ownership_guard():
    fams = _families("COLLECTIONS")
    guard = _guard_families(r"if \(name in self\.SELF_OWNED(.*?)\) and not mine:")
    missing = sorted(f for f in fams
                     if f not in guard and f not in EXEMPT_FROM_DELETE_OWNERSHIP)
    assert not missing, (
        "these module families are in COLLECTIONS but not in the delete-ownership guard, so a "
        "user who did not create the record can delete it: %s. Add them to the guard in "
        "_coll_delete, or to EXEMPT_FROM_DELETE_OWNERSHIP with a reason." % ", ".join(missing))


def test_every_staff_writable_family_is_in_the_delete_ownership_guard():
    """The sharp case: a family staff may WRITE and the guard misses is deletable by any staff user.

    This is the one that let a signed AHU gate be deleted by somebody with no connection to it.
    """
    fams = _families("STAFF_WRITE")
    guard = _guard_families(r"if \(name in self\.SELF_OWNED(.*?)\) and not mine:")
    missing = sorted(f for f in fams
                     if f not in guard and f not in EXEMPT_FROM_DELETE_OWNERSHIP)
    assert not missing, (
        "staff may create records in %s, but the delete-ownership guard does not cover them — so "
        "any staff account can delete anybody's record in those families." % ", ".join(missing))


def test_app_key_ternaries_all_know_the_same_families():
    """The four app-access ternaries must agree.

    They gate read, create, update and delete. A family present in three of them and missing from
    the fourth is an app that can be switched off for reading and still written to.
    """
    ternaries = re.findall(r'= "crm" if name\.startswith\("crm_"\)(.*?)\n', _src())
    assert len(ternaries) >= 4, "expected the four app-key ternaries, found %d" % len(ternaries)
    seen = [set(re.findall(r'"([a-z]+)" if name\.startswith', t)) for t in ternaries]
    first = seen[0]
    for i, s in enumerate(seen[1:], start=2):
        assert s == first, (
            "app-key ternary #%d gates a different set of apps than the first: %s vs %s. All four "
            "must agree or an app is enforced on some routes and not others."
            % (i, sorted(s), sorted(first)))


# ── and the behaviour those lists are there to produce ───────────────────────────────────────────
import pytest
import db


@pytest.fixture(autouse=True)
def _demo(monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)


def test_a_signed_sell_side_record_cannot_be_deleted(api, tokens):
    """An applied variation raised the value every later progress claim is measured against.

    Deletable, before this, by any manager-tier account — Contributor level is past the blanket
    staff gate, and the ownership guard did not list sales_ at all.
    """
    db.put_collection_item("sales_variations", {
        "id": "V-SIGNED", "contractId": "C-1", "owner": "Someone Else", "status": "applied",
        "amount": 500_000_000, "appliedBy": "Finance Approver",
        "signatures": [{"name": "Finance Approver", "meaning": "variation applied"}]})
    st, b = api("DELETE", "/api/coll/sales_variations/V-SIGNED", tokens["mgr"])
    assert st == 403, "a signed, applied variation must not be deletable"
    assert "evidence" in str(b).lower()
    assert db.get_collection_item("sales_variations", "V-SIGNED")

    # admin included — the same rule the claims/travel/payments guard already applies
    st2, _ = api("DELETE", "/api/coll/sales_variations/V-SIGNED", tokens["admin"])
    assert st2 == 403
    assert db.get_collection_item("sales_variations", "V-SIGNED")


def test_an_unsigned_draft_is_still_deletable_by_its_owner(api, tokens):
    """The guard must not freeze ordinary working data — only what has been signed or issued."""
    # seeded rather than POSTed: a quotation is issued through /api/sales/quote, which the generic
    # create route refuses on purpose. Deleting a DRAFT is the behaviour under test here.
    db.put_collection_item("sales_quotes", {
        "id": "Q-DRAFT", "title": "Draft quote", "status": "draft", "owner": "Dept Manager"})
    st2, b2 = api("DELETE", "/api/coll/sales_quotes/Q-DRAFT", tokens["mgr"])
    assert st2 == 200, b2
    assert not db.get_collection_item("sales_quotes", "Q-DRAFT")


def test_estimates_are_scoped_to_whoever_raised_them(api, tokens):
    db.put_collection_item("est_items", {
        "id": "E-OTHER", "projectId": "P-1", "owner": "Someone Else", "rate": 1_200_000})
    st, _ = api("DELETE", "/api/coll/est_items/E-OTHER", tokens["mgr"])
    assert st == 403, "a Contributor-tier manager must not delete somebody else's estimate line"
    assert db.get_collection_item("est_items", "E-OTHER")
