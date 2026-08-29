"""Every key the tender screens read off the summary is a key the server actually sends.

This generalises a bug I made building the Overview tab: I wrote `cash.peak` where the server sends
`peakFunding`. It does not throw. The guard skips it, the panel renders perfectly, and the fact is
silently absent — so nothing ever reports it, in tests or in production.

A per-screen render test catches it for one screen. This catches it for ALL of them, against the
REAL response rather than a stub: the browser's field names are read out of index.html and looked up
in the JSON `/api/tender/summary` genuinely returns.

It deliberately checks only TOP-LEVEL keys. Nested paths would need the whole shape of every branch
and would fail on optional blocks; the top level is where a rename actually happens, because that is
the contract between the endpoint and the screens.
"""
import io
import os
import re

import pytest

import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    return io.open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()


def _fields_the_browser_reads():
    """Top-level summary keys index.html reads, however it spells the access."""
    s = _page()
    found = set()
    found |= set(re.findall(r"\(_tndSum \|\| \{\}\)\.([a-zA-Z]+)", s))
    found |= set(re.findall(r"\b_tndSum\.([a-zA-Z]+)", s))
    # `const S = _tndSum || {}` inside the tender tabs, then S.foo
    if re.search(r"const S = _tndSum \|\| \{\}", s):
        found |= set(re.findall(r"\bS\.([a-zA-Z]+)", s))
    return found


#: `S.` is also a local in renderers that have nothing to do with the summary (a status descriptor
#: with label/color/glyph/subj). Named here rather than pattern-matched, so a genuinely new summary
#: key can never be waved through by a loose rule.
NOT_SUMMARY_KEYS = {"color", "glyph", "label", "subj"}

#: Sent only on some tenders. Each is named with the CONDITION, and `test_the_conditional_keys_do_
#: appear_when_their_condition_holds` proves that condition really produces it — an exemption list
#: nobody re-checks is how a genuinely missing field hides forever.
CONDITIONAL = {
    "rollup": "EPC and services price by cost centre / work package; trading has `master` instead",
    "costCentres": "EPC only",
    "master": "trading only; EPC and services have `rollup` instead",
    "fxExposure": "only when the tender names a presentation currency",
    "milestones": "only when payment milestones are set",
}


def _tender(tid="TND-CONTRACT"):
    db.put_collection_item("est_projects", {
        "id": tid, "estNo": "EST-2026-CT", "quoteNo": "QT-2026-CT", "title": "Contract check",
        "costingType": "trading", "status": "Draft", "client": "Acme",
        "clientTaxCode": "0123456789", "issueDate": "2026-08-01", "validUntil": "2026-09-01",
        "exclusions": "Crane hire", "overheadPct": 10, "profitPct": 20})
    db.put_collection_item("est_local", {
        "id": tid + "-l1", "estId": tid, "itemCode": "LOC-1", "desc": "Frame",
        "unit": "SET", "qty": 1, "unitPrice": 100000000, "vatPct": 8})
    return tid


def test_the_browser_really_reads_some_summary_fields():
    """If the extraction returned nothing, every assertion below would pass while checking nothing."""
    got = _fields_the_browser_reads() - NOT_SUMMARY_KEYS
    assert len(got) >= 10, "only found %r — the extraction is broken, not the code" % (got,)
    assert "quote" in got and "pnl" in got


def test_every_field_the_screens_read_is_a_key_the_server_sends(api, tokens):
    """THE check. A name the server does not send renders as `undefined`, every guard skips it, and
    the screen looks fine with the fact missing."""
    tid = _tender()
    st, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert st == 200, summary
    wanted = _fields_the_browser_reads() - NOT_SUMMARY_KEYS - set(CONDITIONAL)
    missing = sorted(k for k in wanted if k not in summary)
    assert not missing, (
        "the tender screens read these off the summary and the server does not send them: %s\n"
        "They will render as `undefined` — no error, just a fact quietly absent." % ", ".join(missing))


def test_the_exclusion_list_names_only_things_that_are_not_summary_keys(api, tokens):
    """A key excluded here that the server DOES send would be a real field nobody is checking."""
    tid = _tender("TND-CONTRACT-2")
    _, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    overlap = sorted(k for k in NOT_SUMMARY_KEYS if k in summary)
    assert not overlap, "excluded from the check but really sent: %s" % ", ".join(overlap)


def test_the_specific_key_that_caused_this(api, tokens):
    """`cash.peak` vs `cash.peakFunding`. Named on its own so the reason this file exists cannot be
    lost in a general assertion."""
    tid = _tender("TND-CONTRACT-3")
    _, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert "peakFunding" in (summary.get("cash") or {})
    assert "peak" not in (summary.get("cash") or {})
    page = _page()
    assert "cash.peakFunding" in page
    assert not re.search(r"cash\.peak\b(?!Funding)", page), \
        "something reads cash.peak — the funding figure would silently vanish"


def test_the_page_reads_the_risk_key_the_register_actually_carries(api, tokens):
    """The second bug this file found. The register carries `expectedValue`; its per-risk ROWS carry
    `expected`, so a scan of the source finds both and the wrong one looks right. The Overview read
    `risk.expected` and the exposure line never appeared.

    Paired with the cash.peakFunding check above: the top-level assertions cannot see a NESTED key a
    renderer reads, so the two known traps are each named."""
    tid = _tender("TND-CONTRACT-RISKKEY")
    _, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert "expectedValue" in (summary.get("risk") or {})
    page = _page()
    assert "risk.expectedValue" in page
    assert not re.search(r"risk\.expected\b(?!Value)", page), \
        "something reads risk.expected — the exposure line would silently vanish"


@pytest.mark.parametrize("block,keys", [
    ("quote", ("gross", "net", "vat", "cogs", "lineCount", "grossMarginPct")),
    ("pnl", ("revenue", "grossProfit", "opexTotal", "ebit", "cit", "netProfit")),
    ("contribution", ("rows", "totalProfit", "shareMeaningful", "carriers", "belowCostCount")),
    ("issue", ("canIssue", "missing", "warnings", "signature")),
    ("accuracy", ("stated", "label", "low", "high")),
    ("risk", ("expectedValue", "openCount")),   # NOT `expected` — that is a per-risk ROW key
    ("cash", ("peakFunding", "cumulative")),
])
def test_the_blocks_the_overview_screen_reads_carry_what_it_expects(api, tokens, block, keys):
    """The Overview draws all of these. A rename inside a block is the same silent failure one level
    down, and the render test's stub cannot see it because the stub is written by hand."""
    tid = _tender("TND-CONTRACT-" + block)
    _, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    got = summary.get(block)
    assert isinstance(got, dict), "%s is %r, not a block" % (block, type(got).__name__)
    for k in keys:
        assert k in got, "summary['%s'] has no '%s' — the screen reading it shows nothing" % (block, k)


def test_the_conditional_keys_do_appear_when_their_condition_holds(api, tokens):
    """An exemption list nobody re-checks is how a genuinely missing field hides forever. A trading
    tender must really send `master`; an EPC one must really send `rollup`."""
    tid = _tender("TND-CONTRACT-COND")
    _, trading = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert "master" in trading, "a trading tender sends `master` — the exemption is wrong"
    assert "rollup" not in trading

    eid = "TND-CONTRACT-EPC"
    db.put_collection_item("est_projects", {
        "id": eid, "estNo": "EST-CT-EPC", "quoteNo": "QT-CT-EPC", "title": "EPC",
        "costingType": "epc", "status": "Draft", "client": "Acme", "clientTaxCode": "1",
        "issueDate": "2026-08-01", "validUntil": "2026-09-01", "exclusions": "Crane"})
    db.put_collection_item("est_bom", {
        "id": eid + "-b1", "estId": eid, "costCentre": "CIV", "code": "X-1",
        "descEn": "Civil", "unit": "set", "qty": 10, "unitCostUsd": 100})
    _, epc = api("GET", "/api/tender/summary?id=" + eid, tokens["admin"])
    assert "rollup" in epc, "an EPC tender sends `rollup` — the exemption is wrong"
    assert "master" not in epc


def test_rate_drift_is_not_something_the_tender_summary_sends(api, tokens):
    """The Overview read `S.rateDrift` and it was ALWAYS undefined: drift is stale_rates over
    est_resources.rateId, the BoQ path, and a trading/EPC/services tender prices from est_landed /
    est_bom / est_wbs. The line rendered nothing, always, and read as "no rates have moved"."""
    tid = _tender("TND-CONTRACT-DRIFT")
    _, summary = api("GET", "/api/tender/summary?id=" + tid, tokens["admin"])
    assert "rateDrift" not in summary
    assert "S.rateDrift" not in _page(), "the Overview is reading a key that is never sent"
