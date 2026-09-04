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


def test_metrics_collapses_real_item_ids_in_routes(api, tokens):
    # The app's item ids look like 'pay-1a2b3c4d' (coll[:3] + '-' + 8 hex). If they aren't collapsed to
    # :id, every per-item PATCH/DELETE is a distinct route and the cardinality cap eventually defeats
    # the whole metrics feature. Create + PATCH a payment, then assert the concrete id never appears.
    st, b = api("POST", "/api/coll/payments", tokens["staff"],
                {"reqNo": "PR-METRIC", "payee": "V", "amount": 100,
                 "attachment": "data:application/pdf;base64,QQ==", "status": "Submitted"})
    pid = b["item"]["id"]
    api("PATCH", "/api/coll/payments/" + pid, tokens["staff"], {"purpose": "x"})   # records PATCH /api/coll/payments/<id>
    st, m = api("GET", "/api/admin/metrics", tokens["admin"])
    assert st == 200, m
    routes = [r["route"] for r in m["routes"]]
    assert not any(pid in r for r in routes), "the concrete item id must be collapsed, not recorded verbatim"
    assert any(":id" in r and "/api/coll/payments" in r for r in routes), "expected a collapsed PATCH /api/coll/payments/:id route"
