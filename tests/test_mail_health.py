# -*- coding: utf-8 -*-
"""Per-mailbox send health.

The aggregate `_APPR_EMAIL_HEALTH` answers "is email working" and goes green the moment ANY send
succeeds. Under an Exchange application access policy that is precisely the wrong shape: the policy
is a per-mailbox whitelist, so leaving one address out of its scope group leaves the portal sending
happily as the others while one department's mail is refused. Approval mail is fire-and-forget — it
returns True before it tries — so nothing else in the product would show it.
"""
import app
import db


def _reset():
    app._MAIL_HEALTH.clear()
    app._APPR_EMAIL_HEALTH.update({"at": "", "ok": 0, "failed": 0, "lastError": ""})


def test_the_senders_list_names_every_mailbox_the_token_touches(base_url):
    """One list feeds the health rows and any advice about narrowing the app's reach. If it drifts
    from what the code actually uses, a mailbox goes unwatched — or gets left out of a policy."""
    got = {m["address"] for m in app._mail_senders()}
    for coll in ("leave", "padr", "hrdocs", "claims", "travel", "payments", "payroll", "proc_x"):
        assert app._appr_email_sender(coll).lower() in got, \
            "%s sends as a mailbox the health panel does not know about" % coll
    assert app.Handler._dr_mail_sender(app.Handler).lower() in got, \
        "the daily report's sender is not in the list"
    assert app.INVTRACK["mailbox"].lower() in got, "the invoice mailbox is not in the list"


def test_one_mailbox_failing_does_not_hide_behind_another_succeeding():
    """The defect this whole panel exists for."""
    _reset()
    app._mail_note("hr@humiley.com", True)
    app._mail_note("finance@humiley.com", False, "ErrorAccessDenied: not allowed")

    assert app._MAIL_HEALTH["hr@humiley.com"]["ok"] == 1
    assert app._MAIL_HEALTH["hr@humiley.com"]["lastError"] == ""
    assert app._MAIL_HEALTH["finance@humiley.com"]["failed"] == 1
    assert "AccessDenied" in app._MAIL_HEALTH["finance@humiley.com"]["lastError"]


def test_a_success_clears_only_that_mailboxs_error():
    """A mailbox that recovers must not clear the error on one that has not."""
    _reset()
    app._mail_note("finance@humiley.com", False, "ErrorAccessDenied")
    app._mail_note("hr@humiley.com", True)
    assert app._MAIL_HEALTH["finance@humiley.com"]["lastError"], \
        "a send from a different mailbox cleared this one's failure"


def test_the_address_is_matched_regardless_of_case():
    """Settings are typed by hand. `Finance@Humiley.com` and `finance@humiley.com` are one mailbox,
    and two rows for the same address would let one of them sit green forever."""
    _reset()
    app._mail_note("Finance@Humiley.com", True)
    app._mail_note("finance@humiley.com", False, "boom")
    assert len(app._MAIL_HEALTH) == 1, "case produced two rows for one mailbox"
    assert app._MAIL_HEALTH["finance@humiley.com"]["lastError"] == "boom"


def test_two_departments_on_one_mailbox_produce_one_row(base_url):
    """A legitimate configuration — and drawing it twice would mean two rows disagreeing about the
    same address the moment one of them is updated."""
    prev = db.get_setting("portal_apprSenderHr", "")
    try:
        db.set_setting("portal_apprSenderHr", "shared@humiley.com")
        db.set_setting("portal_apprSenderFinance", "shared@humiley.com")
        rows = app._mail_senders()
        addrs = [m["address"] for m in rows]
        assert len(addrs) == len(set(addrs)), "duplicate mailbox rows: %s" % addrs
        shared = [m for m in rows if m["address"] == "shared@humiley.com"][0]
        assert ";" in shared["purpose"], "the merged row lost one of its two purposes"
    finally:
        db.set_setting("portal_apprSenderHr", prev)
        db.set_setting("portal_apprSenderFinance", "")


def test_a_mailbox_nobody_has_used_is_not_reported_as_working(base_url, api, tokens):
    """Never-tried is not the same as working. Colouring an untouched mailbox green would make the
    panel most confident exactly when it knows least — right after a deploy, when the counters are
    empty and an access policy has never been exercised."""
    _reset()
    st, b = api("GET", "/api/health/integrations", tokens["admin"])
    assert st == 200, b
    mb = [r for r in b["rows"] if r["key"].startswith("mbx:")]
    assert mb, "the panel has no per-mailbox rows at all"
    sends = [r for r in mb if "Nothing sent" in (r.get("detail") or "")]
    assert sends, "no untouched mailbox row, so this test proved nothing"
    for r in sends:
        assert r["status"] == "warn", "an untouched mailbox is coloured %s" % r["status"]


def test_a_denied_mailbox_names_the_access_policy(base_url, api, tokens):
    """The fix hint has to name the thing an admin must go and change. 'Send failed' would send
    somebody to the Entra consent screen, which is where this is NOT wrong."""
    _reset()
    app._mail_note(app._appr_email_sender("claims"), False,
                   "ErrorAccessDenied: Access to OData is disabled")
    st, b = api("GET", "/api/health/integrations", tokens["admin"])
    assert st == 200, b
    row = [r for r in b["rows"]
           if r["key"] == "mbx:" + app._appr_email_sender("claims").lower()][0]
    assert row["status"] == "down"
    assert "application access policy" in (row["hint"] or "").lower(), \
        "the hint does not name the access policy: %r" % row["hint"]
    _reset()


def test_a_partial_failure_names_the_refused_mailbox_and_the_policy(base_url, api, tokens,
                                                                    monkeypatch):
    """The branch an access policy actually produces, and the one a single-mailbox test could never
    reach: some mailboxes send, one is refused. If the message only said "send failed" an admin
    would go looking at the Entra consent — which is exactly where nothing is wrong."""
    _reset()
    refused = app._appr_email_sender("claims")

    def fake_send(sender, to, subject, html, cc=None):
        if sender == refused:
            return False, "ErrorAccessDenied: Access to OData is disabled"
        return True, ""

    monkeypatch.setattr(app, "_graph_send_now", fake_send)
    st, b = api("POST", "/api/appr/emailtest", tokens["admin"], {})
    assert st == 200, b

    assert b["ok"] is False, "a partial failure reported overall success"
    msg = b["message"]
    assert refused in msg, "the message does not name the refused mailbox: %r" % msg
    assert "application access policy" in msg.lower(), \
        "a partial failure does not point at the policy: %r" % msg
    ok_boxes = [r["mailbox"] for r in b["results"] if r["ok"]]
    assert ok_boxes, "this test proved nothing — no mailbox succeeded"
    for good in ok_boxes:
        assert good in msg, "the message does not say which mailboxes DID work"
    _reset()
