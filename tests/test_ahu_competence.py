"""Competence: was the person who signed it qualified to.

A different question from authority, which the module already asks. The tests that matter here are
the ones separating "no certificate on file" from "certificate expired" from "certificate with no
expiry date" — three different problems that a single boolean would report identically.
"""
import ahu_competence as Q


RECS = [
    {"person": "Pham Thi Mai", "scope": "ipqc", "expiresOn": "2027-01-01", "certRef": "Q-1"},
    {"person": "Pham Thi Mai", "scope": "T7", "expiresOn": "2026-01-01", "certRef": "Q-2"},
    {"person": "Tran Van Long", "scope": "test", "certRef": "Q-3"},
]
SPEC_IPQC = {"code": "IPQC-2", "kind": "ipqc"}
SPEC_T7 = {"code": "T7", "kind": "test"}
SPEC_WS = {"code": "WS-03", "kind": "op"}


# ── scope ────────────────────────────────────────────────────────────────────────────────────────

def test_a_qualification_for_a_kind_covers_every_step_of_that_kind():
    """How a factory says "signed off for hold points" without listing five codes."""
    assert Q.status("Pham Thi Mai", "IPQC-2", "ipqc", RECS, "2026-08-21")["status"] == Q.QUALIFIED
    assert Q.status("Pham Thi Mai", "IPQC-5", "ipqc", RECS, "2026-08-21")["status"] == Q.QUALIFIED


def test_a_qualification_for_one_code_does_not_cover_another():
    assert Q.status("Tran Van Long", "IPQC-2", "ipqc", RECS, "2026-08-21")["status"] == Q.NONE_ON_FILE


def test_a_scope_listing_several_codes_covers_all_of_them():
    recs = [{"person": "A", "scope": "T3, T4; T5", "expiresOn": "2099-01-01"}]
    for code in ("T3", "T4", "T5"):
        assert Q.status("A", code, "test", recs, "2026-08-21")["status"] == Q.QUALIFIED
    assert Q.status("A", "T6", "test", recs, "2026-08-21")["status"] == Q.NONE_ON_FILE


def test_a_record_with_no_scope_covers_nothing():
    """Otherwise a half-filled record would silently qualify somebody for the entire test matrix."""
    assert Q.status("A", "T3", "test", [{"person": "A"}], "2026-08-21")["status"] == Q.NONE_ON_FILE


# ── the three states ─────────────────────────────────────────────────────────────────────────────

def test_an_expired_qualification_is_expired_not_missing():
    s = Q.status("Pham Thi Mai", "T7", "test", RECS, "2026-08-21")
    assert s["status"] == Q.EXPIRED and "expired on 2026-01-01" in s["why"]


def test_a_qualification_with_no_expiry_is_neither_current_nor_expired():
    """Three different problems. A boolean would report the third as one of the first two."""
    s = Q.status("Tran Van Long", "T3", "test", RECS, "2026-08-21")
    assert s["status"] == Q.NO_EXPIRY and "no expiry date recorded" in s["why"]


def test_nobody_on_file_says_so():
    assert Q.status("Nguyen Van Nobody", "T3", "test", RECS, "2026-08-21")["status"] == Q.NONE_ON_FILE


def test_a_renewal_beside_an_old_certificate_wins():
    """Somebody who renewed still holds the expired one. Letting the old record decide would refuse
    a qualified inspector on the strength of paperwork they already replaced."""
    recs = [{"person": "A", "scope": "test", "expiresOn": "2020-01-01"},
            {"person": "A", "scope": "test", "expiresOn": "2099-01-01"}]
    assert Q.status("A", "T3", "test", recs, "2026-08-21")["status"] == Q.QUALIFIED
    assert Q.status("A", "T3", "test", list(reversed(recs)), "2026-08-21")["status"] == Q.QUALIFIED


def test_the_name_match_survives_case():
    assert Q.status("pham thi mai", "IPQC-2", "ipqc", RECS, "2026-08-21")["status"] == Q.QUALIFIED


# ── the check at sign time ───────────────────────────────────────────────────────────────────────

def test_the_rule_does_nothing_until_it_is_switched_on():
    """Turning this on against an empty register would stop every test in the building, and a
    control switched off again on its first morning is one nobody trusts afterwards."""
    assert Q.check_step("Nobody", SPEC_T7, RECS, "2026-08-21") is None
    assert Q.check_step("Nobody", SPEC_T7, RECS, "2026-08-21", require=True) is not None


def test_an_expired_qualification_refuses_with_the_date():
    err = Q.check_step("Pham Thi Mai", SPEC_T7, RECS, "2026-08-21", require=True)
    assert err and "expired on 2026-01-01" in err and "Renew it" in err


def test_a_current_qualification_signs():
    assert Q.check_step("Pham Thi Mai", SPEC_IPQC, RECS, "2026-08-21", require=True) is None


def test_a_qualification_with_no_expiry_does_not_stop_the_test():
    """On file. Chase the date; do not halt a test mid-way over a records gap."""
    assert Q.check_step("Tran Van Long", SPEC_T7, RECS, "2026-08-21", require=True) is None


def test_a_workstation_never_needs_a_certificate():
    """An operation is signed by whoever did the work, and that signature MEANS "I did this".
    Demanding a certificate there would put the wrong name on it."""
    assert Q.check_step("Nobody", SPEC_WS, RECS, "2026-08-21", require=True) is None


# ── the register's own gaps ──────────────────────────────────────────────────────────────────────

def test_expired_and_no_expiry_are_reported_separately_worst_first():
    g = Q.gaps(RECS, "2026-08-21")
    assert [r["certRef"] for r in g[Q.EXPIRED]] == ["Q-2"]
    assert [r["certRef"] for r in g[Q.NO_EXPIRY]] == ["Q-3"]
    assert g[Q.EXPIRED][0]["daysAgo"] == 232


def test_a_current_qualification_is_not_a_gap():
    assert "Q-1" not in str(Q.gaps(RECS, "2026-08-21"))


def test_signed_tests_by_unqualified_people_are_named():
    steps = [{"id": "s1", "unitId": "u1", "code": "T7", "signedBy": "Pham Thi Mai",
              "signedOn": "2026-08-21"},
             {"id": "s2", "unitId": "u1", "code": "IPQC-2", "signedBy": "Pham Thi Mai",
              "signedOn": "2026-08-21"},
             {"id": "s3", "unitId": "u1", "code": "WS-01", "signedBy": "Anyone",
              "signedOn": "2026-08-21"},
             {"id": "s4", "unitId": "u1", "code": "T7", "signedBy": ""}]
    kinds = {"T7": "test", "IPQC-2": "ipqc", "WS-01": "op"}
    out = Q.unqualified_signatures(steps, RECS, lambda c: kinds.get(c))
    assert [r["stepId"] for r in out] == ["s1"]        # expired; IPQC-2 is current, WS-01 exempt


def test_nothing_here_raises_on_empty_input():
    assert Q.gaps(None, "2026-08-21")[Q.EXPIRED] == []
    assert Q.unqualified_signatures(None, None, lambda c: "test") == []
    assert Q.status("A", "T1", "test", None, "2026-08-21")["status"] == Q.NONE_ON_FILE
