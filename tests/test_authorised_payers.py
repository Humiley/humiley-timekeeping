"""Releasing money is a NAMED duty: only the configured authorised payers can mark a request paid.

Holding Editor/Admin is what lets you APPROVE. It is not, on its own, what lets you RELEASE THE MONEY.
`portal_apprPayers` names the people who may — being on the list is the grant, so a payer does not need
Editor/Admin, and an Editor/Admin who is NOT listed loses that one power while keeping the rest.

A blank list keeps the historical rule (any Editor/Admin), so an unconfigured install can still pay.
That blank default matters: an earlier draft shipped the company's real emails as the code default and
instantly broke every other install — six tests caught it. The company's payers are seeded into the
DATABASE once at boot instead (_seed_default_payers), which an admin can then edit.

The per-request rules are unchanged and still stack on top: never your own request, never one you
approved (unless payerSeparation is off), only from Approved, and always with a bank slip.
"""
import app
import db

SLIP = "data:application/pdf;base64,YmFuay1zbGlw"


def _approved_payment(api, tokens, ref="PR-PAYER", approved_by="Finance Approver"):
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": ref, "payee": "Vendor", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    pid = b["item"]["id"]
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    row["status"] = "Approved"
    row["approvedBy"] = approved_by
    db.put_collection_item("payments", row)
    return pid


def _pay(api, token, pid, ref="PR-PAYER"):
    return api("POST", "/api/esign", token,
               {"coll": "payments", "id": pid, "meaning": "Paid — " + ref, "setStatus": "Paid",
                "attach": {"bankSlip": SLIP, "bankSlipName": "slip.pdf"}})


def test_blank_list_keeps_the_historical_any_editor_rule(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "")
    pid = _approved_payment(api, tokens)
    st, b = _pay(api, tokens["editor"], pid)
    assert st == 200, b
    assert app._payer_emails() == set(), "a blank setting must mean no allow-list at all"


def test_a_listed_payer_may_release(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "editor@humiley.com")
    pid = _approved_payment(api, tokens)
    st, b = _pay(api, tokens["editor"], pid)
    assert st == 200, b


def test_an_editor_who_is_not_listed_cannot_release(api, tokens, monkeypatch):
    """The whole point of naming payers — Editor/Admin alone is no longer enough."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "nancy.duong@humiley.com")
    pid = _approved_payment(api, tokens)
    st, b = _pay(api, tokens["editor"], pid)
    assert st == 403 and "authorised payer" in (b.get("error") or "").lower(), b
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    assert row.get("status") == "Approved", "a refused disbursement must not flip the status"
    assert not any((s.get("setStatus") or "").lower() == "paid" for s in (row.get("signatures") or [])), \
        "a refused disbursement must not leave an orphan Paid signature"


def test_the_list_is_parsed_case_insensitively_and_on_any_separator(api, tokens, monkeypatch):
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "  Tony.Nguyen@Humiley.com ;\n EDITOR@humiley.com , ")
    assert app._payer_emails() == {"tony.nguyen@humiley.com", "editor@humiley.com"}
    pid = _approved_payment(api, tokens)
    st, b = _pay(api, tokens["editor"], pid)
    assert st == 200, b


def test_listing_does_not_defeat_the_hard_rules(api, tokens, monkeypatch):
    """Being a named payer never lets you pay your OWN request, or one you approved."""
    monkeypatch.setattr(app, "DEMO_MODE", True)
    db.set_setting("portal_apprPayers", "editor@humiley.com,staff1@humiley.com")

    # (a) own request
    st, b = api("POST", "/api/coll/payments", tokens["editor"],
                {"reqNo": "PR-OWN", "payee": "Vendor", "amount": 1000,
                 "attachment": "data:application/pdf;base64,QQ=="})
    assert st == 200, b
    own = b["item"]["id"]
    row = next(x for x in db.list_collection("payments") if x.get("id") == own)
    row["status"] = "Approved"
    db.put_collection_item("payments", row)
    st, b = _pay(api, tokens["editor"], own, "PR-OWN")
    assert st == 403 and "own request" in (b.get("error") or "").lower(), b

    # (b) a request this same person gave final approval to (payerSeparation on by default)
    db.set_setting("portal_payerSeparation", "1")
    pid = _approved_payment(api, tokens, "PR-SELFAPPR")
    row = next(x for x in db.list_collection("payments") if x.get("id") == pid)
    row.setdefault("signatures", []).append(
        {"userId": "HML-EDT", "setStatus": "Approved", "meaning": "Approved — PR-SELFAPPR"})
    db.put_collection_item("payments", row)
    st, b = _pay(api, tokens["editor"], pid, "PR-SELFAPPR")
    assert st == 403 and "final approval" in (b.get("error") or "").lower(), b


def test_only_an_admin_can_read_or_change_the_payer_list(api, tokens):
    """It is an authorization list: a manager neither sees it nor can rewrite it — and their own
       settings save must still succeed while echoing the blank they were given."""
    db.set_setting("portal_apprPayers", "editor@humiley.com")

    st, b = api("GET", "/api/portal", tokens["admin"])
    assert st == 200 and b.get("apprPayers") == "editor@humiley.com", b
    st, b = api("GET", "/api/portal", tokens["mgr"])
    assert st == 200 and b.get("apprPayers") == "", "a non-admin must not read the payer list"

    # A manager echoing the blank back must NOT clear the list, and must NOT 403 the whole save.
    st, b = api("PATCH", "/api/portal", tokens["mgr"], {"apprPayers": ""})
    assert st == 200, b
    assert db.get_setting("portal_apprPayers", "") == "editor@humiley.com", \
        "a non-admin echo must leave the payer list untouched"

    st, b = api("PATCH", "/api/portal", tokens["admin"], {"apprPayers": "nancy.duong@humiley.com"})
    assert st == 200, b
    assert db.get_setting("portal_apprPayers", "") == "nancy.duong@humiley.com"


def test_canpay_flag_matches_the_server_gate(api, tokens):
    """The UI hides Mark-paid using this flag, so it must never disagree with the e-sign gate."""
    db.set_setting("portal_apprPayers", "editor@humiley.com")
    st, b = api("GET", "/api/portal", tokens["editor"])
    assert st == 200 and b.get("canPay") is True, b
    st, b = api("GET", "/api/portal", tokens["management"])
    assert st == 200 and b.get("canPay") is False, "a listed-out approver must not see Mark paid"
    st, b = api("GET", "/api/portal", tokens["staff"])
    assert st == 200 and b.get("canPay") is False, b


def test_seed_runs_once_and_respects_a_deliberate_clear(monkeypatch):
    """First boot names the company's payers; clearing the list afterwards must stay cleared."""
    db.set_setting("portal_apprPayers", "")
    db.set_setting("portal_apprPayersSeeded", "")
    app._seed_default_payers()
    assert db.get_setting("portal_apprPayers", "") == app._APPR_PAYERS_SEED
    assert "nancy.duong@humiley.com" in app._payer_emails()

    db.set_setting("portal_apprPayers", "")          # an admin deliberately empties it
    app._seed_default_payers()                        # a later restart must not undo that
    assert db.get_setting("portal_apprPayers", "") == ""


def test_no_real_payer_emails_are_baked_into_the_authorization_default():
    """Regression: shipping the company's emails as the CODE default locked every other install out."""
    assert app._APPR_SETTING_DEFAULTS["apprPayers"] == "", \
        "the payer allow-list default must stay blank — seed the database instead"
