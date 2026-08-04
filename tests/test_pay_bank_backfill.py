"""Finance backfills beneficiary bank details on an ALREADY-DECIDED payment.

Payments created before these fields existed carry no beneficiary details, so Finance cannot release a
transfer or file the accounting export from them. The generic PATCH path correctly refuses to edit a
decided money record (it is signed evidence), so this is a separate, deliberately narrow endpoint:

  * it can set ONLY the six beneficiary fields — never amount, payee, status, signatures, attachment;
  * Finance (Editor) level only — 'management' (the Approver persona) is excluded on purpose;
  * before payment, values may be set OR corrected — the people who can do this are the same people
    who execute the transfer, so restricting them further would not prevent anything;
  * once PAID, blanks may still be filled but a RECORDED value can never be altered, because it is the
    historical record of where the money actually went;
  * every change is audited with its before and after value, account number masked.
"""
import app
import db

FIELDS = {"payeeCompany": "ACME Company Ltd", "payeeMst": "0312345678", "bankName": "Vietcombank",
          "bankAcc": "007100123456", "bankHolder": "ACME COMPANY LTD", "bankBranch": "HCM D1"}


def _payment(api, tokens, ref="PR-BANK", status="Approved", **extra):
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": ref, "payee": "Vendor", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    pid = b["item"]["id"]
    row = _row(pid)
    row["status"] = status
    row.update(extra)
    db.put_collection_item("payments", row)
    return pid


def _row(pid):
    return next(x for x in db.list_collection("payments") if x.get("id") == pid)


def _fill(api, token, pid, fields=None, rev=None):
    body = {"id": pid, "fields": FIELDS if fields is None else fields}
    if rev is not None:
        body["_rev"] = rev
    return api("POST", "/api/payments/bankdetails", token, body)


# ── the happy path ────────────────────────────────────────────────────────────────────────────────

def test_finance_can_backfill_an_approved_payment(api, tokens):
    pid = _payment(api, tokens)
    st, b = _fill(api, tokens["editor"], pid)
    assert st == 200, b
    assert sorted(b["changed"]) == sorted(FIELDS)
    row = _row(pid)
    for k, v in FIELDS.items():
        assert row[k] == v


def test_a_correction_is_allowed_before_payment(api, tokens):
    pid = _payment(api, tokens, status="Approved", bankAcc="999")
    st, b = _fill(api, tokens["editor"], pid, {"bankAcc": "007100123456"})
    assert st == 200, b
    assert _row(pid)["bankAcc"] == "007100123456"


def test_re_sending_the_same_values_is_a_no_op_not_an_error(api, tokens):
    """A retried request (flaky field connection) must not 403 on the paid path either."""
    pid = _payment(api, tokens, status="Paid", **FIELDS)
    st, b = _fill(api, tokens["editor"], pid)
    assert st == 200, b
    assert b["changed"] == []


# ── the paid rule: fill blanks, never rewrite history ─────────────────────────────────────────────

def test_a_paid_payment_accepts_a_blank_being_filled(api, tokens):
    pid = _payment(api, tokens, status="Paid", bankName="Vietcombank")
    st, b = _fill(api, tokens["editor"], pid, {"bankAcc": "007100123456"})
    assert st == 200, b
    assert _row(pid)["bankAcc"] == "007100123456"


def test_a_paid_payment_refuses_to_change_a_recorded_value(api, tokens):
    pid = _payment(api, tokens, status="Paid", bankAcc="007100123456")
    st, b = _fill(api, tokens["editor"], pid, {"bankAcc": "666600009999"})
    assert st == 403 and "already been released" in (b.get("error") or ""), b
    assert _row(pid)["bankAcc"] == "007100123456", "the recorded destination must be untouched"


def test_a_rejected_batch_applies_nothing_at_all(api, tokens):
    """One illegal field must not let the legal ones through — validate the batch, then write."""
    pid = _payment(api, tokens, status="Paid", bankAcc="007100123456")
    st, b = _fill(api, tokens["editor"], pid, {"bankBranch": "HCM D1", "bankAcc": "666600009999"})
    assert st == 403, b
    row = _row(pid)
    assert row["bankAcc"] == "007100123456"
    assert not row.get("bankBranch"), "a refused batch must not half-apply"


# ── authorization ─────────────────────────────────────────────────────────────────────────────────

def test_staff_and_managers_are_refused(api, tokens):
    pid = _payment(api, tokens)
    for who in ("staff", "mgr", "management"):
        st, b = _fill(api, tokens[who], pid)
        assert st == 403, (who, st, b)
    assert not _row(pid).get("bankAcc")


def test_admin_may_also_backfill(api, tokens):
    pid = _payment(api, tokens)
    st, b = _fill(api, tokens["admin"], pid)
    assert st == 200, b


# ── the endpoint stays narrow ─────────────────────────────────────────────────────────────────────

def test_only_the_six_fields_can_be_written(api, tokens):
    """The whole point of a narrow endpoint: it must never become a second full-document PATCH."""
    pid = _payment(api, tokens)
    before = _row(pid)
    st, b = api("POST", "/api/payments/bankdetails", tokens["editor"],
                {"id": pid, "fields": dict(FIELDS, amount=999999999, status="Paid", payee="Attacker",
                                           signatures=[], attachment="", empId="HML-EDT")})
    assert st == 200, b
    row = _row(pid)
    assert row["amount"] == before["amount"]
    assert row["status"] == before["status"]
    assert row["payee"] == before["payee"]
    assert row["empId"] == before["empId"]
    assert row.get("attachment") == before.get("attachment")
    assert sorted(b["changed"]) == sorted(FIELDS), "only whitelisted keys may be reported as changed"


def test_values_are_sanitized_and_bounded(api, tokens):
    pid = _payment(api, tokens)
    st, b = _fill(api, tokens["editor"], pid,
                  {"bankHolder": "<script>alert(1)</script>ACME", "bankName": "x" * 500})
    assert st == 200, b
    row = _row(pid)
    assert "<" not in row["bankHolder"] and ">" not in row["bankHolder"]
    assert len(row["bankName"]) <= 120


def test_the_generic_patch_path_still_refuses_a_decided_payment(api, tokens):
    """The invariant this endpoint exists to route around narrowly must remain in force."""
    pid = _payment(api, tokens, status="Approved")
    row = _row(pid)
    st, b = api("PATCH", "/api/coll/payments/" + pid, tokens["editor"], dict(row, payee="Attacker"))
    assert st == 403 and "no longer be edited" in (b.get("error") or ""), b


# ── malformed input, concurrency, audit ───────────────────────────────────────────────────────────

def test_a_truncated_body_never_blanks_the_fields(api, tokens):
    """_body() is fail-soft and returns {} — without the guards that reads as 'clear everything'."""
    pid = _payment(api, tokens, **FIELDS)
    for bad in ({}, {"id": pid}, {"id": pid, "fields": "nope"}, {"id": pid, "fields": {}},
                {"fields": FIELDS}):
        st, b = api("POST", "/api/payments/bankdetails", tokens["editor"], bad)
        assert st == 400, (bad, st, b)
    row = _row(pid)
    for k, v in FIELDS.items():
        assert row[k] == v, "a rejected request must leave the record untouched"


def test_unknown_payment_is_404(api, tokens):
    st, b = _fill(api, tokens["editor"], "does-not-exist")
    assert st == 404, b


def test_a_stale_rev_conflicts_instead_of_clobbering(api, tokens):
    pid = _payment(api, tokens)
    stale = int(_row(pid).get("_rev") or 0)
    st, b = _fill(api, tokens["editor"], pid, {"bankName": "First"}, rev=stale)
    assert st == 200, b
    st, b = _fill(api, tokens["editor"], pid, {"bankName": "Second"}, rev=stale)
    assert st == 409 and b.get("conflict") is True, b
    assert "currentRev" in b, "the frontend's 409 branch reads currentRev"
    assert _row(pid)["bankName"] == "First"


def test_every_change_is_audited_with_before_and_after_and_a_masked_account(api, tokens):
    pid = _payment(api, tokens, bankName="Old Bank")
    st, b = _fill(api, tokens["editor"], pid, {"bankName": "Vietcombank", "bankAcc": "007100123456"})
    assert st == 200, b
    rows = [a for a in db.list_collection("audit")
            if a.get("action") == "Payment beneficiary bank details updated"
            and a.get("target") == "payments/" + pid]
    assert len(rows) == 1, rows
    detail = rows[0]["detail"]
    assert "Old Bank → Vietcombank" in detail, detail
    assert "0071" not in detail, "the full beneficiary account number must not be stored in the audit"
    assert "3456" in detail, "the last 4 digits identify the account without exposing it"
    assert rows[0].get("hash") and rows[0].get("seq") is not None, "must join the tamper-evident chain"
