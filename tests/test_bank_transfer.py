"""The salary payment file.

The failure this exists to prevent is not a crash. It is a file that looks complete, uploads cleanly,
and quietly does not contain one person — who then does not get paid on the 5th and finds out from
their own bank. So the tests that matter most are the ones about refusing to produce a partial file.
"""
import bank_transfer as B


def _emp(eid="HML-STF", name="Nguyễn Đức Huy", acc="19012345678901",
         bank="Techcombank", branch="Chi nhánh Sài Gòn", holder=None):
    return {"id": eid, "name": name, "bankAcc": acc, "bankName": bank,
            "bankBranch": branch, "bankHolder": holder}


def _run(lines, period="August 2026"):
    return {"period": period, "status": "Finalised", "lines": lines}


def _ln(eid="HML-STF", net=18_400_000, name="Nguyễn Đức Huy"):
    return {"empId": eid, "name": name, "calc": {"net": net}, "net": net}


# ── unaccented ASCII, because bank files reject the rest ─────────────────────────────────────────

def test_vietnamese_names_are_folded_to_plain_ascii():
    assert B.fold("Nguyễn Đức Huy") == "Nguyen Duc Huy"
    assert B.fold("Đặng Thị Ngọc Ánh") == "Dang Thi Ngoc Anh"


def test_the_capital_d_with_stroke_folds_too():
    assert B.fold("ĐÀ NẴNG") == "DA NANG"


def test_characters_a_bank_file_rejects_are_stripped_from_the_narrative():
    assert "&" not in B.safe_text("Sales & Tender #1 (bonus)")
    assert "#" not in B.safe_text("Sales & Tender #1 (bonus)")


def test_the_narrative_is_recognisable_on_a_bank_statement():
    """The employee should be able to see what the credit is without ringing HR."""
    n = B.narrative("Humiley", "August 2026", "Nguyễn Đức Huy")
    assert n == "HUMILEY LUONG T08/2026 NGUYEN DUC HUY"


def test_the_period_becomes_the_form_a_vietnamese_payslip_uses():
    assert B._period_short("August 2026") == "T08/2026"
    assert B._period_short("January 2027") == "T01/2027"


def test_an_unrecognised_period_is_passed_through_rather_than_invented():
    assert "Q3" in B._period_short("Q3 2026")


def test_the_narrative_is_length_bounded():
    n = B.narrative("A very long company name indeed" * 5, "August 2026", "X" * 200)
    assert len(n) <= B.NARRATIVE_MAX


# ── the account number ───────────────────────────────────────────────────────────────────────────

def test_spaces_and_dashes_typed_into_an_account_number_are_not_part_of_it():
    assert B.account_of({"bankAcc": "1901 2345 6789 01"}) == "19012345678901"
    assert B.account_of({"bankAcc": "1901-2345-678901"}) == "19012345678901"


def test_an_empty_account_is_empty_rather_than_a_stray_string():
    assert B.account_of({}) == ""
    assert B.account_of({"bankAcc": "n/a"}) == ""


# ── the refusal that matters ─────────────────────────────────────────────────────────────────────

def test_a_complete_run_produces_a_row_per_employee():
    b = B.build(_run([_ln(), _ln("HML-OTH", 22_000_000, "Trần Thị Mai")]),
                [_emp(), _emp("HML-OTH", "Trần Thị Mai", "19099998888", "Techcombank")])
    assert b["count"] == 2 and not b["blocked"]
    assert b["total"] == 40_400_000


def test_an_employee_with_no_account_number_blocks_the_whole_file():
    """The one that matters. A file missing a row is indistinguishable from a complete one, and the
    person finds out when their salary does not arrive."""
    b = B.build(_run([_ln(), _ln("HML-OTH", 22_000_000, "Trần Thị Mai")]),
                [_emp(), _emp("HML-OTH", "Trần Thị Mai", acc="")])
    assert b["blocked"]
    assert b["blocked"][0]["name"] == "Trần Thị Mai"
    assert "no bank account number" in " ".join(b["blocked"][0]["why"])


def test_a_missing_bank_name_blocks_too():
    b = B.build(_run([_ln()]), [_emp(bank="")])
    assert b["blocked"] and "no bank name" in " ".join(b["blocked"][0]["why"])


def test_an_employee_with_no_record_at_all_is_blocked_not_skipped():
    b = B.build(_run([_ln("GHOST", 5_000_000, "Nobody")]), [])
    assert b["count"] == 0 and len(b["blocked"]) == 1


def test_a_zero_or_negative_net_is_blocked_rather_than_sent():
    assert B.build(_run([_ln(net=0)]), [_emp()])["blocked"]
    assert B.build(_run([_ln(net=-100)]), [_emp()])["blocked"]


def test_junk_lines_do_not_become_rows():
    b = B.build(_run([_ln(), "not a dict", None]), [_emp()])
    assert b["count"] == 1


# ── the row content ──────────────────────────────────────────────────────────────────────────────

def test_the_beneficiary_name_is_the_account_holder_where_one_is_recorded():
    """The bank matches this against the account, and a mismatch is what makes a transfer bounce.
    The holder here is deliberately NOT just the HR name unaccented — banks often hold a shortened
    or differently-ordered form, and a test where the two fold to the same string cannot tell whether
    the holder field is being read at all."""
    b = B.build(_run([_ln()]), [_emp(holder="NGUYEN D HUY")])
    assert b["rows"][0]["name"] == "NGUYEN D HUY"


def test_the_employee_name_is_used_when_no_holder_is_recorded():
    b = B.build(_run([_ln()]), [_emp()])
    assert b["rows"][0]["name"] == "NGUYEN DUC HUY"


def test_the_amount_is_the_net_from_the_frozen_calc():
    b = B.build(_run([{"empId": "HML-STF", "calc": {"net": 17_777_777}, "net": 999}]), [_emp()])
    assert b["rows"][0]["amount"] == 17_777_777


def test_rows_are_numbered_from_one():
    b = B.build(_run([_ln(), _ln("HML-OTH", 1_000_000, "B")]),
                [_emp(), _emp("HML-OTH", "B", "1902", "Techcombank")])
    assert [r["no"] for r in b["rows"]] == [1, 2]


# ── the file ─────────────────────────────────────────────────────────────────────────────────────

def test_the_header_row_is_the_banks_own_wording():
    b = B.build(_run([_ln()]), [_emp()])
    first = B.to_csv(b).split("\n")[0]
    assert "So tai khoan" in first and "So tien" in first


def test_the_column_layout_is_data_so_another_bank_is_a_setting_not_a_release():
    cols = [{"key": "account", "header": "Beneficiary A/C"},
            {"key": "amount", "header": "Amount"},
            {"key": "name", "header": "Beneficiary"}]
    b = B.build(_run([_ln()]), [_emp()], columns=cols)
    rows = B.to_csv(b, cols).split("\n")
    assert rows[0] == '"Beneficiary A/C","Amount","Beneficiary"'
    assert rows[1].startswith('"19012345678901","18400000"')


def test_the_file_ends_with_a_control_row_that_can_be_checked_against_the_run():
    """The last moment the whole month can still be caught: whoever releases the batch in the bank's
    portal compares this against the pay run."""
    b = B.build(_run([_ln(), _ln("HML-OTH", 22_000_000, "B")]),
                [_emp(), _emp("HML-OTH", "B", "1902", "Techcombank")])
    last = B.to_csv(b).strip().split("\n")[-1]
    assert "TOTAL" in last and "2 rows" in last and "40400000" in last


def test_a_comma_in_a_branch_name_does_not_shift_the_columns():
    import csv, io
    b = B.build(_run([_ln()]), [_emp(branch="Chi nhánh Sài Gòn, Quận 1")])
    rows = list(csv.reader(io.StringIO(B.to_csv(b))))
    assert all(len(r) == len(B.COLUMNS) for r in rows), rows

# ── the control row must fit the template it is written into ─────────────────────────────────────

def _cols(*pairs):
    return [{"key": k, "header": h} for k, h in pairs]


def _built():
    return B.build(_run([_ln()]), {"HML-STF": _emp()})


def _parsed(csv_text):
    import csv as _csv
    import io as _io
    return list(_csv.reader(_io.StringIO(csv_text)))


def test_the_control_row_is_never_wider_than_the_header():
    """It used to be built as four fixed fields padded up to the column count, so any template with
    fewer than four columns produced a trailer WIDER than its header — a malformed CSV, in the one
    file where malformed means a month's salaries."""
    built = _built()
    for cols in (_cols(("account", "A/C"), ("amount", "Amount")),
                 _cols(("amount", "Amount")),
                 _cols(("no", "No"), ("name", "Name"), ("amount", "Amount"))):
        rows = _parsed(B.to_csv(built, columns=cols))
        assert len(rows[-1]) == len(rows[0]) == len(cols), \
            "trailer %r does not fit header %r" % (rows[-1], rows[0])


def test_the_batch_total_sits_under_the_amount_column_wherever_it_is():
    """The total used to be written at a fixed index 3. With the amount column anywhere else the
    control total appeared under a different heading — under the account number, in the very row a
    bank reads back to check the batch before releasing it."""
    built = _built()
    cols = _cols(("no", "No"), ("name", "Name"), ("bank", "Bank"), ("account", "A/C"),
                 ("amount", "Amount"))
    rows = _parsed(B.to_csv(built, columns=cols))
    hdr, trailer = rows[0], rows[-1]
    assert trailer[hdr.index("Amount")] == str(int(built["total"])), "the total belongs under Amount"
    assert trailer[hdr.index("A/C")] == "", "and not under the account number"


def test_the_default_layout_is_unchanged_by_the_fix():
    """The shipped layout was already correct; a fix for custom templates must not move it."""
    built = _built()
    rows = _parsed(B.to_csv(built))
    assert rows[0][0] == "STT" and rows[-1][0] == "TOTAL"
    assert rows[-1][3] == str(int(built["total"])), "So tien still carries the total"
    assert len(rows[-1]) == len(rows[0])


def test_the_row_count_never_overwrites_the_total():
    """Both live in the control row; on a two-column template they would collide."""
    built = _built()
    rows = _parsed(B.to_csv(built, columns=_cols(("account", "A/C"), ("amount", "Amount"))))
    assert rows[-1][1] == str(int(built["total"]))
