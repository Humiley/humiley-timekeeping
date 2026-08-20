"""The Power BI feed: the arithmetic, and who is allowed to read it.

bi.py is a PORT of the frontend's _pdPlanned/_pdWeight/_pdAcc/_pdDaily. Two implementations of one
rule drift unless something holds them together — these are deliberately the same cases as
tests/detail_schedule_math.js, with the same expected numbers. If you change one, this file should
fail until you change the other.
"""
import base64
import json

import pytest

import bi
import db


TODAY = "2026-08-15"


def _item(**kw):
    d = {"id": "d1", "projectId": "P1", "category": "HVAC Works", "name": "Install ceiling support",
         "start": "2026-08-11", "finish": "2026-08-25", "log": []}
    d.update(kw)
    return d


# ── same cases as the JavaScript harness ─────────────────────────────────────────────────────────

def test_nothing_reported_today_means_zero_daily():
    it = _item(start="2026-06-21", finish="2026-09-15", log=[{"d": "2026-08-12", "pct": 88}])
    assert bi.daily_at(it, TODAY) == 0
    assert bi.accumulated_at(it, TODAY) == 88


def test_reported_today_is_the_increment():
    it = _item(log=[{"d": "2026-08-14", "pct": 90}, {"d": TODAY, "pct": 95}])
    assert bi.daily_at(it, TODAY) == 5
    assert bi.accumulated_at(it, TODAY) == 95
    assert bi.accumulated_at(it, "2026-08-14") == 90, "an earlier day must not see the future"


@pytest.mark.parametrize("day,want", [("2026-08-01", 0), ("2026-08-11", 7), ("2026-08-25", 100), ("2026-09-01", 100)])
def test_planned_is_a_straight_line_inclusive_of_both_ends(day, want):
    assert bi.planned_pct(_item(), day) == want


def test_weighting_is_not_an_average():
    """The number this whole module exists to get right — and the one a BI user will get wrong if the
    weight does not travel with the row."""
    short = _item(id="s", start="2026-08-14", finish=TODAY, log=[{"d": TODAY, "pct": 100}])
    long_ = _item(id="l", start="2026-06-17", finish=TODAY, log=[{"d": TODAY, "pct": 0}])
    rows = [r for r in bi.progress_fact([short, long_], {"id": "P1"}, TODAY, TODAY)]
    acc = sum(r["weightedAccum"] for r in rows) / sum(r["weight"] for r in rows)
    assert round(acc) == 3, "weighted roll-up"
    naive = sum(r["accumulatedPct"] for r in rows) / len(rows)
    assert round(naive) == 50, "the naive average is the wrong answer this design guards against"


@pytest.mark.parametrize("bad", [{"log": "nonsense"}, {"log": None}, {"log": [{"pct": 50}]}, {}])
def test_malformed_logs_do_not_explode(bad):
    assert bi.accumulated_at(_item(**bad), TODAY) == 0


def test_a_percentage_over_100_is_clamped():
    assert bi.accumulated_at(_item(log=[{"d": TODAY, "pct": 9999}]), TODAY) == 100


# ── the fact table's own properties ──────────────────────────────────────────────────────────────

def test_the_series_is_dense_and_carried_forward():
    """A reading on one day only. Power BI needs a row for every day in between, or the line chart
    has holes and the cumulative curve is wrong."""
    it = _item(start="2026-08-11", finish="2026-08-20", log=[{"d": "2026-08-12", "pct": 40}])
    rows = bi.progress_fact([it], {"id": "P1"}, "2026-08-11", "2026-08-15")
    assert [r["date"] for r in rows] == ["2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"]
    assert [r["accumulatedPct"] for r in rows] == [0, 40, 40, 40, 40]
    assert [r["dailyPct"] for r in rows] == [0, 40, 0, 0, 0], "daily must not repeat on later days"
    assert [r["reportedToday"] for r in rows] == [0, 1, 0, 0, 0]


def test_the_window_never_runs_past_today():
    """A fact table that asserts progress for dates that have not happened is worse than a short one."""
    it = _item(start="2026-08-01", finish="2027-12-31", log=[{"d": "2026-08-10", "pct": 10}])
    lo, hi = bi.window([it], None, None, today="2026-08-15")
    assert hi == "2026-08-15"


def test_the_window_is_bounded():
    it = _item(start="2020-01-01", finish="2029-01-01", log=[])
    lo, hi = bi.window([it], None, None, today="2026-08-15")
    assert len(bi._days(lo, hi)) <= bi.MAX_DAYS


def test_csv_carries_a_bom_for_vietnamese():
    out = bi.to_csv([{"item": "Lắp đặt ống ngầm"}], ["item"])
    assert out.startswith("﻿".encode("utf-8")), "Excel and Power BI mis-read UTF-8 without it"
    assert "Lắp đặt ống ngầm" in out.decode("utf-8")


def test_activities_join_key_matches_the_frontend_rule():
    """_pdTaskRef: the WBS code where there is one, else the activity name."""
    rows = bi.activities_dim([{"id": "t1", "wbs": "1.2.3", "name": "Ductwork"},
                              {"id": "t2", "name": "Testing"}])
    assert [r["masterRef"] for r in rows] == ["1.2.3", "Testing"]


# ── who may read it ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def bikey(api, tokens):
    st, b = api("POST", "/api/bi/key", tokens["admin"], {})
    assert st == 200, b
    yield b["key"]
    api("POST", "/api/bi/key", tokens["admin"], {"revoke": True})


def test_the_feed_is_closed_without_a_key(api, tokens, bikey):
    st, _ = api("GET", "/api/bi/progress", None)
    assert st == 401


def test_staff_cannot_read_the_feed(api, tokens, bikey):
    st, _ = api("GET", "/api/bi/progress", tokens["staff"])
    assert st == 401, "a signed-in employee is not a BI consumer"


def test_a_manager_can_preview_it_in_the_app(api, tokens, bikey):
    st, b = api("GET", "/api/bi/progress", tokens["mgr"])
    assert st == 200, b
    assert "columns" in b


def test_only_management_may_mint_a_key(api, tokens):
    st, _ = api("POST", "/api/bi/key", tokens["staff"], {})
    assert st in (403, 401)


def test_the_key_is_stored_hashed_only(api, tokens, bikey):
    stored = str(db.get_setting("portal_biKeyHash") or "")
    assert stored and bikey not in stored, "the raw key must never be at rest"


def test_revoking_actually_closes_the_door(api, tokens):
    st, b = api("POST", "/api/bi/key", tokens["admin"], {})
    assert st == 200
    api("POST", "/api/bi/key", tokens["admin"], {"revoke": True})
    assert not (db.get_setting("portal_biKeyHash") or ""), "revoke must clear the hash"


def test_an_unknown_dataset_is_a_404_not_a_leak(api, tokens, bikey):
    st, _ = api("GET", "/api/bi/employees", tokens["mgr"])
    assert st == 404


# ── the path Power BI actually uses ──────────────────────────────────────────────────────────────
# Power BI's connector offers Anonymous / Basic / OAuth. Basic is the one a person can configure in
# thirty seconds, so it has to work — and a feature nobody exercised is a feature that does not.

def _raw(base_url, path, header=None):
    import urllib.request, urllib.error
    req = urllib.request.Request(base_url + path)
    if header:
        req.add_header("Authorization", header)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def _basic(key, user="bi"):
    return "Basic " + base64.b64encode(("%s:%s" % (user, key)).encode()).decode()


def test_basic_auth_is_accepted(base_url, api, tokens, bikey):
    st, body, _ = _raw(base_url, "/api/bi/progress", _basic(bikey))
    assert st == 200, body[:300]
    assert json.loads(body)["dataset"] == "schedule_progress"


def test_the_username_is_not_the_secret(base_url, api, tokens, bikey):
    """Only the password half is the key, so any username works — that is deliberate, and this
    records it rather than leaving it a surprise."""
    st, _, _ = _raw(base_url, "/api/bi/progress", _basic(bikey, user="anything"))
    assert st == 200


def test_a_wrong_key_is_refused(base_url, api, tokens, bikey):
    st, _, _ = _raw(base_url, "/api/bi/progress", _basic("not-the-key"))
    assert st == 401


def test_the_401_carries_a_challenge_so_power_bi_prompts(base_url, api, tokens, bikey):
    st, _, hdrs = _raw(base_url, "/api/bi/progress")
    assert st == 401
    assert "Basic" in (hdrs.get("WWW-Authenticate") or ""), \
        "without a challenge Power BI fails opaquely instead of asking for credentials"


def test_bearer_also_works_for_everything_else(base_url, api, tokens, bikey):
    st, _, _ = _raw(base_url, "/api/bi/progress", "Bearer " + bikey)
    assert st == 200


def test_the_key_never_travels_in_the_url(base_url, api, tokens, bikey):
    """A key in a query string lands in browser history, proxy logs and the saved .pbix file."""
    st, _, _ = _raw(base_url, "/api/bi/progress?key=" + bikey)
    assert st == 401


def test_csv_is_served_as_csv(base_url, api, tokens, bikey):
    st, body, hdrs = _raw(base_url, "/api/bi/progress?format=csv", _basic(bikey))
    assert st == 200
    assert "text/csv" in (hdrs.get("Content-Type") or "")
    text = body.decode("utf-8-sig") if not (hdrs.get("Content-Encoding") == "gzip") else ""
    if text:
        assert text.splitlines()[0].startswith("date,projectId,project,category")


def test_a_revoked_key_stops_working_immediately(base_url, api, tokens):
    st, b = api("POST", "/api/bi/key", tokens["admin"], {})
    key = b["key"]
    assert _raw(base_url, "/api/bi/progress", _basic(key))[0] == 200
    api("POST", "/api/bi/key", tokens["admin"], {"revoke": True})
    assert _raw(base_url, "/api/bi/progress", _basic(key))[0] == 401


# ── quantity-measured progress reaches the model ─────────────────────────────────────────────────

def test_quantity_drives_the_percentage():
    it = _item(qtyPlan=500, unit="m", log=[{"d": "2026-08-10", "pct": 0, "qty": 350}])
    assert bi.accumulated_at(it, TODAY) == 70
    assert bi.qty_at(it, TODAY) == (350.0, False)


def test_a_reading_without_a_quantity_keeps_its_percentage():
    """Per-reading, not per-item — a line that gained a quantity partway must not lose its history."""
    it = _item(qtyPlan=500, log=[{"d": "2026-08-05", "pct": 40}, {"d": "2026-08-10", "pct": 0, "qty": 350}])
    assert bi.accumulated_at(it, "2026-08-05") == 40
    assert bi.accumulated_at(it, TODAY) == 70


def test_no_quantity_leaves_the_judged_path_alone():
    assert bi.accumulated_at(_item(log=[{"d": "2026-08-10", "pct": 62}]), TODAY) == 62
    assert bi.qty_plan({"qtyPlan": 0}) == 0 and bi.qty_plan({"qtyPlan": -5}) == 0 and bi.qty_plan({}) == 0


def test_the_fact_table_marks_inferred_quantities():
    measured = _item(id="m", qtyPlan=500, log=[{"d": TODAY, "pct": 0, "qty": 350}])
    judged = _item(id="j", qtyPlan=500, log=[{"d": TODAY, "pct": 50}])
    rows = {r["itemId"]: r for r in bi.progress_fact([measured, judged], {"id": "P1"}, TODAY, TODAY)}
    assert rows["m"]["qtyAtSite"] == 350 and rows["m"]["qtyMeasured"] == 1
    assert rows["j"]["qtyAtSite"] == 250 and rows["j"]["qtyMeasured"] == 0, \
        "a back-calculated quantity must be flagged, or a BI user sums it as if it were measured"
    assert rows["m"]["qtyPlanned"] == 500


def test_the_python_port_agrees_with_the_javascript():
    """Same cases, same numbers as tests/detail_schedule_math.js. If these drift, one of the two
    implementations changed alone."""
    qp = _item(qtyPlan=500, log=[{"d": "2026-08-14", "pct": 0, "qty": 300}, {"d": TODAY, "pct": 0, "qty": 350}])
    assert bi.daily_at(qp, TODAY) == 10
    assert bi.accumulated_at(_item(qtyPlan=500, log=[{"d": TODAY, "pct": 0, "qty": 900}]), TODAY) == 100
