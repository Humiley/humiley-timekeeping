"""The Finance SharePoint archive files from the SERVER, like Invoice Tracking does.

It used to run entirely in the browser, through the signed-in user's delegated Microsoft token. That
meant it only worked while somebody happened to be signed in to Microsoft in that tab — and it
swallowed every error — so the Year/Month folders frequently never appeared at all, while Invoice
Tracking (server-side, app-only) filed reliably into the same library. Same tenant, same credentials,
completely different behaviour, and nothing on screen explained the difference.

Now the request's PDF is filed by the server on submit:
    <configured folder>/<Payments|Claims|Travel>/<YYYY>/<MM>/<reference>/
"""
import base64
import os

import app

PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 test").decode()


def _capture(monkeypatch, folder="https://x.sharepoint.com/sites/FC/Shared%20Documents/Finance"):
    """Stub Graph and record the folders created + the file path written."""
    made, put = [], []
    monkeypatch.setattr(app, "_graph_app_token", lambda force=False: "TOK")
    monkeypatch.setattr(app, "_graph_get",
                        lambda u, t: {"id": "SITE"} if "/drive" not in u else {"id": "DRV"})
    monkeypatch.setattr(app, "_invtrack_sp_ensure_dir", lambda d, rel, t: made.append(rel))
    monkeypatch.setattr(app, "_graph_put_bytes",
                        lambda u, t, raw, ct: put.append(u) or {"webUrl": "https://sp/file"})
    monkeypatch.setattr(app, "_invtrack_app_ready", lambda: True)
    monkeypatch.setattr(app.db, "get_setting",
                        lambda k, d=None: (folder if k == "portal_financeSpUrl" else d))
    app._finsp_reset()
    app._FINSP_HEALTH.update({"ok": 0, "failed": 0, "lastError": ""})
    return made, put


def test_it_creates_the_year_month_tree(monkeypatch):
    made, put = _capture(monkeypatch)
    url = app._finsp_archive({"reqNo": "PR-2026-018", "attachment": PDF,
                              "attachmentName": "PR-2026-018.pdf"}, "payment")
    assert url == "https://sp/file"
    assert len(made) == 1
    parts = made[0].split("/")
    assert parts[0] == "Finance" and parts[1] == "Payments"
    assert parts[2].isdigit() and len(parts[2]) == 4          # year
    assert parts[3].isdigit() and len(parts[3]) == 2          # month
    assert parts[4] == "PR-2026-018"                          # reference folder
    assert app._FINSP_HEALTH["ok"] == 1


def test_each_kind_gets_its_own_top_folder(monkeypatch):
    for kind, want in (("payment", "Payments"), ("claim", "Claims"), ("travel", "Travel")):
        made, _ = _capture(monkeypatch)
        app._finsp_archive({"reqNo": "R1", "attachment": PDF}, kind)
        assert made[0].split("/")[1] == want, (kind, made[0])


def test_it_does_not_nest_payments_inside_payments(monkeypatch):
    """Admins point the setting straight at the folder for the dominant kind."""
    made, _ = _capture(monkeypatch, "https://x.sharepoint.com/sites/FC/Shared%20Documents/Payments")
    app._finsp_archive({"reqNo": "PR-1", "attachment": PDF}, "payment")
    assert made[0].startswith("Payments/2"), made[0]
    assert not made[0].startswith("Payments/Payments"), "doubled folder name"
    # a DIFFERENT kind still gets its own subfolder under there
    made2, _ = _capture(monkeypatch, "https://x.sharepoint.com/sites/FC/Shared%20Documents/Payments")
    app._finsp_archive({"reqNo": "CL-1", "attachment": PDF}, "claim")
    assert made2[0].startswith("Payments/Claims/"), made2[0]


def test_the_reference_matches_the_browser_normalisation(monkeypatch):
    """Server and browser must produce the SAME folder name or requests split across two trees."""
    assert app._finsp_ref({"title": "Chi phí Hà Nội"}, "claim") == "Chi_phi_Ha_Noi"
    assert app._finsp_ref({"dest": "Đà Nẵng"}, "travel") == "Da_Nang"
    assert app._finsp_ref({}, "payment") == "payment"
    assert len(app._finsp_ref({"reqNo": "x" * 200}, "payment")) <= 60


def test_it_never_raises_and_records_the_failure(monkeypatch):
    """A submission must never fail because SharePoint is unreachable."""
    _capture(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("graph exploded")
    monkeypatch.setattr(app, "_graph_put_bytes", boom)
    assert app._finsp_archive({"reqNo": "PR-9", "attachment": PDF}, "payment") is None
    assert app._FINSP_HEALTH["failed"] == 1
    assert "graph exploded" in app._FINSP_HEALTH["lastError"]


def test_no_folder_configured_is_a_silent_no_op(monkeypatch):
    made, put = _capture(monkeypatch, "")
    assert app._finsp_archive({"reqNo": "PR-1", "attachment": PDF}, "payment") is None
    assert not made and not put


def test_a_record_without_an_attachment_is_skipped(monkeypatch):
    made, put = _capture(monkeypatch)
    assert app._finsp_archive({"reqNo": "PR-1"}, "payment") is None
    assert app._finsp_archive({"reqNo": "PR-1", "attachment": "https://elsewhere/x.pdf"}, "payment") is None
    assert not made and not put


def test_the_browser_no_longer_uploads_the_attachment_itself():
    """Both paths running would file the same PDF twice."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "templates", "index.html")
    with open(p, encoding="utf-8") as fh:
        src = fh.read()
    # the helper may remain (approval-time voucher archiving still uses the browser), but nothing
    # should CALL it for the submit-time attachment any more
    calls = [ln for ln in src.splitlines()
             if "_finSpUploadAttachment(" in ln and "function _finSpUploadAttachment" not in ln]
    assert not calls, "browser still uploads the attachment: %s" % calls[:2]
