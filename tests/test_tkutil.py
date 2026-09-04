"""Table-driven tests for the pure leaf helpers extracted into tkutil.py.

These have no app/db dependency, so they're tested in isolation. They underpin money display, the
VN e-invoice parser, and the approval-status rollups that drive My Space counts — a one-character
error here is silent and wide-reaching, and they previously had no direct coverage.
"""
import re
import pytest
import tkutil as tk


@pytest.mark.parametrize("v,expected", [
    (1000, "1,000 ₫"),
    (1234567, "1,234,567 ₫"),
    ("1,234,567", "1,234,567 ₫"),
    ("₫ 2,500", "2,500 ₫"),
    (0, "0 ₫"),
    (None, ""),          # None -> "" (not the literal "None")
    ("abc", "abc"),      # non-numeric falls back to the raw string
])
def test_money_vnd(v, expected):
    assert tk._money_vnd(v) == expected


def test_now_iso_shape():
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", tk._now_iso())


@pytest.mark.parametrize("s,expected", [
    ("HĐĐT", "hddt"),          # HĐĐT -> hddt (đ -> d)
    ("Hóa đơn", "hoa don"),  # Hóa đơn -> hoa don (drop accents, horn, đ->d)
    ("ABC", "abc"),
    ("", ""),
    (None, ""),
])
def test_vn_fold(s, expected):
    assert tk._vn_fold(s) == expected


@pytest.mark.parametrize("iso,mins,expected", [
    ("2026-01-01T10:30:00Z", 30, "2026-01-01T10:00:00Z"),
    ("2026-01-01T10:30:00Z", 0, "2026-01-01T10:30:00Z"),
    ("2026-01-01T00:05:00Z", 10, "2025-12-31T23:55:00Z"),   # crosses midnight/year
    ("not-a-date", 30, "not-a-date"),                        # best-effort: bad input passes through
])
def test_iso_minus(iso, mins, expected):
    assert tk._iso_minus(iso, mins) == expected


@pytest.mark.parametrize("x,expected", [
    ("1234.56", 1234.56),
    ("1,234.56", 1234.56),
    ("1.234.567", 1234567.0),           # all dots = thousands grouping
    ("1.234.567,89", 1234567.89),       # VN display: dot thousands, comma decimal
    ("2736000", 2736000.0),
    ("-500", -500.0),
    ("", 0.0),
    ("abc", 0.0),
])
def test_einv_num(x, expected):
    assert tk._einv_num(x) == expected


@pytest.mark.parametrize("x,expected", [
    ("2736000.000000", 2736000.0),      # xs:decimal fixed 6 places — dot is the DECIMAL point
    ("23.790000", 23.79),
    ("1.234.567,89", 1234567.89),       # both -> dot thousands, comma decimal
    ("1,5", 1.5),                        # comma-only decimal
    ("", 0.0),
])
def test_einv_xml_num(x, expected):
    assert tk._einv_xml_num(x) == expected


@pytest.mark.parametrize("status,expected", [
    ("Reviewed", "review"),
    ("Pending Approval", "review"),
    ("Approved", "approved"),
    ("Paid", "paid"),
    ("Rejected", "rejected"),
    ("Submitted", "submit"),
    ("", "submit"),
    (None, "submit"),
])
def test_appr_state_of(status, expected):
    assert tk._appr_state_of(status) == expected


@pytest.mark.parametrize("v,expected", [
    ("1970-01-01", 0.0),
    ("1970-01-02", 86400.0),
    ("1970-01-01T00:00:00Z", 0.0),
    ("", None),
    (None, None),
    ("garbage", None),
])
def test_appr_epoch(v, expected):
    assert tk._appr_epoch(v) == expected


def test_claim_items_falls_back_to_one_synthetic_line():
    assert tk._claim_items({}) == [{"status": "Submitted"}]
    assert tk._claim_items({"status": "Reviewed"}) == [{"status": "Reviewed"}]
    assert tk._claim_items({"items": [{"status": "Approved"}]}) == [{"status": "Approved"}]


@pytest.mark.parametrize("claim,expected", [
    ({"items": [{"status": "Approved"}, {"status": "Approved"}]}, "Approved"),
    ({"items": [{"status": "Rejected"}, {"status": "Rejected"}]}, "Rejected"),
    ({"items": [{"status": "Reviewed"}, {"status": "Reviewed"}]}, "Reviewed"),
    ({"items": [{"status": "Submitted"}, {"status": "Approved"}]}, "Partially approved"),
    ({"items": [{"status": "Submitted"}, {"status": "Submitted"}]}, "Submitted"),
    ({}, "Submitted"),
])
def test_claim_rollup(claim, expected):
    assert tk._claim_rollup(claim) == expected
