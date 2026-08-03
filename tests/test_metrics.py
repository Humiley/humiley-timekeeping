"""Request telemetry at /api/admin/metrics — the app was previously metric-blind."""


def test_metrics_requires_admin(api, tokens):
    st, _ = api("GET", "/api/admin/metrics", tokens["staff"])
    assert st == 403
    st, _ = api("GET", "/api/admin/metrics", tokens["mgr"])
    assert st == 403


def test_metrics_reports_per_route_counts_and_latency(api, tokens):
    api("GET", "/api/health")                 # generate at least one recorded request
    st, b = api("GET", "/api/admin/metrics", tokens["admin"])
    assert st == 200, b
    assert b["totalRequests"] >= 1
    assert "errorRate" in b and "avgMs" in b and "uptime_s" in b
    assert isinstance(b["routes"], list) and b["routes"]
    r0 = b["routes"][0]
    assert {"route", "n", "err", "avgMs", "maxMs"} <= set(r0.keys())
    # ids are collapsed so route cardinality stays bounded
    assert all(seg not in r0["route"] for seg in ("HML-ADM",))
