"""Scheduled monthly report pack — the branded month-end summary emailed to leadership."""
import app


def _clear_payments(db):
    for d in list(db.list_collection("payments")):
        if d.get("id"):
            db.delete_collection_item("payments", d["id"])


def test_monthly_gather_scopes_to_month(base_url):
    import db
    ym = "2026-05"
    _clear_payments(db)
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-M1", "status": "Approved", "approvedOn": ym + "-10", "amount": 1000000})
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-M2", "status": "Paid", "paidOn": ym + "-20", "amount": 500000})
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-APR", "status": "Approved", "approvedOn": "2026-04-01", "amount": 9999999})   # other month
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-PEND", "status": "Submitted", "submittedOn": ym + "-05", "amount": 7777})     # not approved
    g = app._monthly_gather(ym)
    assert g["payCount"] == 2 and g["payTotal"] == 1500000.0, g
    assert g["ym"] == ym and isinstance(g["headcount"], int)


def test_monthly_gather_reads_invoice_items(base_url):
    """invtrack is ONE dataset doc with an .items array — the gather must read .items (month-scoped),
       not treat each collection row as an invoice (which would always report zero)."""
    import db
    for d in list(db.list_collection("invtrack")):
        if d.get("id"):
            db.delete_collection_item("invtrack", d["id"])
    db.put_collection_item("invtrack", {"kind": "invtrack-dataset", "items": [
        {"dateISO": "2026-05-10", "before": 1000000, "vat": 100000, "after": 1100000, "invNo": "INV-1"},
        {"dateISO": "2026-05-22", "before": 2000000, "vat": 200000, "after": 2200000, "invNo": "INV-2"},
        {"dateISO": "2026-04-01", "before": 9000000, "vat": 900000, "after": 9900000, "invNo": "INV-OLD"},
    ]})
    g = app._monthly_gather("2026-05")
    assert g["invCount"] == 2, "reads the dataset doc's .items, month-scoped"
    assert g["invTotal"] == 3300000.0 and g["invVat"] == 300000.0
    assert len(app._invtrack_all_items()) == 3


def test_monthly_off_switch(monkeypatch, base_url):
    import db
    db.set_setting("portal_monthlyReports", "0")
    calls = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda *a, **k: calls.append(1) or True)
    assert app._monthly_send() == 0, "off (opt-in) → nothing sent on the schedule path"
    assert not calls


def test_monthly_preview_is_branded_and_scoped(monkeypatch, base_url):
    import db
    db.set_setting("portal_monthlyReports", "0")   # off, but the preview override still sends
    db.set_setting("portal_apprEmail", "1")
    _clear_payments(db)
    db.put_collection_item("payments", {"empId": "E1", "reqNo": "PAY-P", "status": "Paid", "paidOn": "2026-05-15", "amount": 2500000})
    sent = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda sender, to, subject, html, cc=None: sent.append((to[0], subject, html)) or True)
    n = app._monthly_send(preview_to="boss@h.com", ym="2026-05")
    assert n == 1 and sent[0][0] == "boss@h.com"
    assert "Month-end pack" in sent[0][1] and "May 2026" in sent[0][1]
    assert "2,500,000" in sent[0][2] and "Humiley_Logo_White.png" in sent[0][2]

    db.set_setting("portal_apprEmail", "0")        # Mail.Send master off → even preview sends nothing
    sent2 = []
    monkeypatch.setattr(app, "_graph_send_mail", lambda *a, **k: sent2.append(1) or True)
    assert app._monthly_send(preview_to="boss@h.com", ym="2026-05") == 0 and not sent2
    db.set_setting("portal_apprEmail", "1")
