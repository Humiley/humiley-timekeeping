"""The variation — the document two refusals in this codebase have been pointing at all along.

    sales_contract.application: "Raise a variation first, or certify less."
    the contract terms endpoint:  "Raise a variation instead."

Neither had anywhere to send you. On a fit-out job a contract that grows is not the exception, it is
most of them, so the only ways past the ceiling were to certify less than was actually built, or to
quietly edit the contract — and the second destroys the thing a contract is for.
"""
import pytest

import sales_doc as S
import sales_variation as V


def _c(**kw):
    return dict({"id": "sal-1", "value": 1_000_000_000, "certifiedToDate": 0,
                 "lines": [S.new_line("l1", desc="Works", qty=1, unitPrice=1_000_000_000)]}, **kw)


def _uid(i):
    return "v%d" % (i + 1)


# ── what it does ─────────────────────────────────────────────────────────────────────────────────

def test_new_lines_raise_the_contract_by_what_they_are_worth():
    v = {"lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]}
    e = V.effect(_c(), v)
    assert e["ok"] and e["delta"] == 80_000_000 and e["newValue"] == 1_080_000_000


def test_a_value_delta_can_be_stated_without_any_lines():
    """A negotiated round-down, or an omission agreed on site, has no new scope to list."""
    e = V.effect(_c(), {"valueDelta": -50_000_000})
    assert e["ok"] and e["newValue"] == 950_000_000


def test_both_at_once_is_one_document():
    """₫80m of new work AND ₫20m negotiated off the original scope is one variation, not two."""
    e = V.effect(_c(), {"valueDelta": 60_000_000,
                        "lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]})
    assert e["delta"] == 60_000_000, "the stated delta governs; the lines are what was added"
    assert e["linesValue"] == 80_000_000


def test_applying_appends_lines_and_leaves_the_originals_alone():
    out = V.apply_to(_c(), {"id": "var-1", "variationNo": "VO-2026-0001",
                            "lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]}, _uid)
    assert out["ok"]
    assert [l["uid"] for l in out["contract"]["lines"]] == ["l1", "v1"]
    assert out["contract"]["lines"][0]["unitPrice"] == 1_000_000_000, "the original is untouched"
    assert out["contract"]["value"] == 1_080_000_000


def test_every_added_line_points_back_at_the_variation_that_introduced_it():
    """Without this a bill of quantities becomes a flat list nobody can explain a year later."""
    out = V.apply_to(_c(), {"id": "var-1", "variationNo": "VO-2026-0001",
                            "lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]}, _uid)
    src = out["contract"]["lines"][1]["src"]
    assert src["doc"] == "variation" and src["no"] == "VO-2026-0001"


def test_a_heading_on_a_variation_is_worth_nothing():
    e = V.effect(_c(), {"lines": [{"desc": "SECTION C", "kind": S.HEADING},
                                  {"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]})
    assert e["delta"] == 80_000_000


def test_the_statement_reads_like_the_document_somebody_signs():
    e = V.effect(_c(), {"lines": [{"desc": "Extra AHU", "qty": 1, "unitPrice": 80_000_000}]})
    assert "₫80,000,000 added to the contract" in e["statement"]
    assert "₫1,000,000,000 → ₫1,080,000,000" in e["statement"]


def test_a_reduction_says_taken_off_rather_than_added():
    e = V.effect(_c(), {"valueDelta": -50_000_000})
    assert "taken off the contract" in e["statement"]


# ── what it refuses ──────────────────────────────────────────────────────────────────────────────

def test_it_cannot_shrink_a_contract_below_what_is_already_certified():
    """That work is signed off. A variation cannot un-sign it, and clamping to zero would hide the
    fact that somebody just tried to."""
    e = V.effect(_c(certifiedToDate=600_000_000), {"valueDelta": -500_000_000})
    assert e["ok"] is False
    assert "already certified" in e["why"]


def test_the_refusal_names_the_instrument_that_WOULD_work():
    """Being told "no" without being told what to do instead is how the last dead end happened."""
    e = V.effect(_c(certifiedToDate=600_000_000), {"valueDelta": -500_000_000})
    assert "credit note" in e["why"]


def test_a_reduction_down_to_exactly_what_is_certified_is_allowed():
    """De-scoping the rest of a job that stopped is a real and common variation."""
    e = V.effect(_c(certifiedToDate=600_000_000), {"valueDelta": -400_000_000})
    assert e["ok"] is True and e["newValue"] == 600_000_000


def test_a_variation_that_changes_nothing_is_refused():
    e = V.effect(_c(), {})
    assert e["ok"] is False and "changes nothing" in e["why"]


def test_a_contract_cannot_be_worth_less_than_nothing():
    """And it is refused by the certified check, not by a separate negative-value guard — which
    would be unreachable, since certifiedToDate is never negative. This asserts the REASON, because
    a test that passes down a different branch than it claims is how dead code survives."""
    e = V.effect(_c(), {"valueDelta": -2_000_000_000})
    assert e["ok"] is False
    assert "already certified" in e["why"]


def test_a_colliding_line_id_is_refused_rather_than_overwriting():
    """Lines already carry certified balances; a collision would move money claimed against one."""
    out = V.apply_to(_c(), {"id": "var-1", "lines": [{"desc": "X", "qty": 1, "unitPrice": 1}]},
                     lambda i: "l1")
    assert out["ok"] is False and "already exists" in out["why"]


def test_apply_refuses_whatever_effect_refuses():
    out = V.apply_to(_c(certifiedToDate=600_000_000), {"valueDelta": -500_000_000}, _uid)
    assert out["ok"] is False and "contract" not in out


def test_it_returns_a_NEW_contract_rather_than_mutating_the_old_one():
    """The caller writes it under compare-and-swap; a half-applied variation is the one failure
    mode that would be invisible afterwards."""
    original = _c()
    out = V.apply_to(original, {"id": "v", "lines": [{"desc": "X", "qty": 1, "unitPrice": 5}]}, _uid)
    assert len(original["lines"]) == 1 and original["value"] == 1_000_000_000
    assert len(out["contract"]["lines"]) == 2


# ── the status machine ───────────────────────────────────────────────────────────────────────────

def test_a_variation_cannot_be_applied_before_it_is_issued():
    assert V.APPLIED not in V.TRANSITIONS[V.DRAFT]


def test_applied_and_rejected_are_both_final():
    assert V.TRANSITIONS[V.APPLIED] == () and V.TRANSITIONS[V.REJECTED] == ()


def test_every_status_has_a_vietnamese_label():
    for k in V.TRANSITIONS:
        assert V.STATUS_LABELS[k][1], k


# ── the register: why is this contract worth more than the quotation? ───────────────────────────

def test_the_register_reconstructs_the_original_value():
    r = V.register(_c(value=1_080_000_000),
                   [{"status": V.APPLIED, "delta": 80_000_000},
                    {"status": V.ISSUED, "delta": 999}])
    assert r["originalValue"] == 1_000_000_000 and r["variedBy"] == 80_000_000
    assert r["applied"] == 1 and r["open"] == 1


def test_an_unvaried_contract_says_so():
    assert "what was quoted" in V.register(_c(), [])["statement"]


def test_only_APPLIED_variations_move_the_reconstruction():
    """An issued-but-unsigned variation is a proposal. Counting it would misreport the original."""
    r = V.register(_c(), [{"status": V.ISSUED, "delta": 500_000_000}])
    assert r["originalValue"] == 1_000_000_000 and r["variedBy"] == 0


def test_the_open_question_travels_with_the_module():
    assert V.UNRESOLVED and all(u.get("topic") and u.get("action") for u in V.UNRESOLVED)
