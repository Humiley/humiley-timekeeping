"""The outcome rules through the real boundary.

Three things are checked here that the pure tests cannot see:

  * the win/loss reason is enforced on /api/coll, not only in the form — that route takes a full
    record and overwrites the stored one, so a rule living only in the browser is a rule anyone can
    PATCH around;
  * the signature threshold survives the whole settings round-trip — a JSON number saves NOTHING
    through this endpoint while the screen says "Saved";
  * the price a signature stands behind is stamped by the SERVER from the tender's own rows.
"""
import pytest

import app
import db
import tender


@pytest.fixture(autouse=True)
def _signable(monkeypatch):
    """The signing re-authentication is a live M365 round-trip; DEMO_MODE is what the other
    signature tests use to reach the rules behind it. Every authority check still runs."""
    monkeypatch.setattr(app, "DEMO_MODE", True)


def _tender(tid="TND-OUT", **kw):
    row = {"id": tid, "estNo": "EST-2026-900", "quoteNo": "QT-2026-900", "title": "Chiller plant",
           "costingType": "trading", "status": "Draft", "client": "Acme",
           "clientTaxCode": "0123456789", "issueDate": "2026-02-01", "validUntil": "2026-03-01",
           "exclusions": "Crane hire", "quotedPrice": 1000}
    row.update(kw)
    db.put_collection_item("est_projects", row)
    return row


def _priced(tid):
    """A tender with a real priced line, so the server can compute a gross for it."""
    _tender(tid)
    db.put_collection_item("est_local", {
        "id": tid + "-l1", "estId": tid, "itemCode": "LOC-1", "desc": "Frame",
        "unit": "SET", "qty": 1, "unitPrice": 100000000, "vatPct": 8})
    return tid



def _xlsx(base_url, token, tid):
    """Fetch the workbook raw.

    The shared `api` fixture json-decodes every response, and a SUCCESSFUL workbook is a binary
    xlsx — so the fixture blows up on exactly the case these tests care about. Returns
    (status, error-text-or-empty); an empty string means real bytes came back.
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(base_url + "/api/tender/quote.xlsx?id=" + tid)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# ── the reason is enforced where the writing happens ─────────────────────────────────────────────

def test_marking_a_tender_lost_through_the_collection_route_needs_a_reason(api, tokens):
    """THE point of putting the guard on this route. A rule only in the form is a rule anyone can
    PATCH around — that is how the HR decision checks became optional."""
    t = _tender("TND-OUT-1")
    t["status"] = "Lost"
    st, r = api("PATCH", "/api/coll/est_projects/TND-OUT-1", tokens["admin"], t)
    assert st == 400, r
    assert "why" in (r.get("error") or "").lower()


def test_a_reason_off_the_list_is_refused_too(api, tokens):
    t = _tender("TND-OUT-2")
    t.update(status="Lost", outcomeReason="they didn't like us", decidedOn="2026-05-01")
    st, r = api("PATCH", "/api/coll/est_projects/TND-OUT-2", tokens["admin"], t)
    assert st == 400


def test_with_a_reason_it_goes_through(api, tokens):
    t = _tender("TND-OUT-3")
    t.update(status="Lost", outcomeReason="Delivery / lead time", decidedOn="2026-05-01")
    st, r = api("PATCH", "/api/coll/est_projects/TND-OUT-3", tokens["admin"], t)
    assert st == 200, r
    assert db.get_collection_item("est_projects", "TND-OUT-3")["outcomeReason"] == "Delivery / lead time"


def test_an_ordinary_edit_is_not_blocked(api, tokens):
    """The rule applies to an outcome, not to every save. Blocking a draft edit would make the
    module unusable."""
    t = _tender("TND-OUT-4")
    t["title"] = "Chiller plant rev B"
    st, _ = api("PATCH", "/api/coll/est_projects/TND-OUT-4", tokens["admin"], t)
    assert st == 200


def test_cancelling_a_tender_needs_no_reason(api, tokens):
    t = _tender("TND-OUT-5")
    t["status"] = "Cancelled"
    st, _ = api("PATCH", "/api/coll/est_projects/TND-OUT-5", tokens["admin"], t)
    assert st == 200


# ── the outcomes view ────────────────────────────────────────────────────────────────────────────

def test_staff_cannot_read_the_hit_rate(api, tokens):
    st, r = api("GET", "/api/tender/outcomes", tokens["staff"])
    assert st == 403


def test_the_hit_rate_reports_both_numbers(api, tokens):
    _tender("TND-OUT-W", status="Won", outcomeReason="Price", decidedOn="2026-05-01",
            quotedPrice=100)
    _tender("TND-OUT-L", status="Lost", outcomeReason="Price", decidedOn="2026-05-01",
            quotedPrice=900)
    st, r = api("GET", "/api/tender/outcomes", tokens["admin"])
    assert st == 200
    hit = r["hit"]
    assert hit["byCount"] is not None and hit["byValue"] is not None
    assert hit["byCount"] != hit["byValue"]      # the whole reason both are reported


def test_the_outcome_view_offers_the_reason_list_the_guard_enforces(api, tokens):
    """If the screen offered a reason the guard rejects, every save from it would 400."""
    st, r = api("GET", "/api/tender/outcomes", tokens["admin"])
    assert r["reasons"] == list(__import__("tender_outcome").REASONS)


# ── the threshold survives the settings round-trip ───────────────────────────────────────────────

def test_the_threshold_saves_and_reads_back(api, tokens):
    st, _ = api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "500000000"})
    assert st == 200
    st, r = api("GET", "/api/portal", tokens["admin"])
    assert r.get("tenderSignThreshold") == "500000000"


def test_a_threshold_sent_as_a_NUMBER_does_not_silently_vanish(api, tokens):
    """The write loop drops any non-string. A JSON number would save nothing while the screen said
    'Saved' — so the browser must send a string, and this is what proves it matters."""
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "700000000"})
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": 900000000})
    st, r = api("GET", "/api/portal", tokens["admin"])
    # The number was ignored — the earlier string is still in force. Documented, not endorsed.
    assert r.get("tenderSignThreshold") == "700000000"


def test_the_threshold_actually_gates_the_workbook(api, tokens):
    """The export is the document leaving the building. If the gate is not on this path it is
    decoration."""
    tid = _priced("TND-OUT-SIGN")
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "1"})
    st, r = api("GET", "/api/tender/quote.xlsx?id=" + tid, tokens["admin"])
    assert st == 400, r
    assert "signature" in str(r.get("error") or "").lower()


def test_with_no_threshold_the_workbook_is_not_gated_on_a_signature(api, tokens, base_url):
    tid = _priced("TND-OUT-NOSIGN")
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": ""})
    st, err = _xlsx(base_url, tokens["admin"], tid)
    assert "signature" not in err.lower(), err


def test_the_summary_reports_the_signature_state(api, tokens):
    tid = _priced("TND-OUT-STATE")
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "1"})
    st, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert st == 200
    assert r["issue"]["signature"]["required"] is True
    assert r["issue"]["signature"]["signed"] is False


# ── the signed price is the server's number ──────────────────────────────────────────────────────

def test_signing_stamps_the_total_from_the_tenders_own_rows(api, tokens):
    """Not from the request body. A client-supplied figure would let the signer decide what they
    had signed for, which is the thing the stamp exists to prevent."""
    tid = _priced("TND-OUT-STAMP")
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "est_projects", "id": tid, "meaning": tender.ISSUE_MEANING,
                 "signedFor": 1})            # a lie in the body
    assert st == 200, r
    rec = db.get_collection_item("est_projects", tid)
    sig = tender.issue_signature(rec)
    assert sig is not None
    assert sig["signedFor"] != 1
    _, s = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert sig["signedFor"] == s["quote"]["gross"]


def test_a_signature_then_lets_the_workbook_out(api, tokens, base_url):
    """The gate must OPEN as well as shut. A test that only proves the refusal would pass against a
    door that is welded closed."""
    tid = _priced("TND-OUT-OK")
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "1"})
    st, r = api("POST", "/api/esign", tokens["admin"],
                {"coll": "est_projects", "id": tid, "meaning": tender.ISSUE_MEANING})
    assert st == 200, r
    st, err = _xlsx(base_url, tokens["admin"], tid)
    assert st == 200, err
    assert err == "", err          # real bytes, not a JSON refusal


def test_repricing_after_signing_shuts_the_door_again(api, tokens):
    """The failure that looks completely fine: a real name and a real timestamp, now standing
    behind a total nobody approved."""
    tid = _priced("TND-OUT-STALE")
    api("PATCH", "/api/portal", tokens["admin"], {"tenderSignThreshold": "1"})
    api("POST", "/api/esign", tokens["admin"],
        {"coll": "est_projects", "id": tid, "meaning": tender.ISSUE_MEANING})
    # the price moves
    row = db.get_collection_item("est_local", tid + "-l1")
    row["unitPrice"] = 500000000
    db.put_collection_item("est_local", row)
    st, r = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert r["issue"]["signature"]["stale"] is True
    assert r["issue"]["canIssue"] is False
    st, r = api("GET", "/api/tender/quote.xlsx?id=" + tid, tokens["admin"])
    assert st == 400
    assert "fresh electronic signature" in str(r.get("error") or "")
