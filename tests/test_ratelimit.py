"""Rate limiting: sliding-window guard on login + writes, keyed by the real client IP, with loopback
(health probes / this test harness / the server itself) exempt."""
import app


def test_rate_allow_blocks_over_limit_then_recovers():
    key = "unit:test-a"
    app._RATE.pop(key, None)
    # 5 in a 10s window are allowed; the 6th is blocked.
    assert all(app._rate_allow(key, 5, 10) for _ in range(5))
    assert app._rate_allow(key, 5, 10) is False
    # A fresh, independent key is unaffected.
    assert app._rate_allow("unit:test-b", 5, 10) is True
    app._RATE.pop(key, None)
    app._RATE.pop("unit:test-b", None)


def test_rate_window_slides(monkeypatch):
    key = "unit:slide"
    app._RATE.pop(key, None)
    t = [1000.0]
    monkeypatch.setattr(app.time, "time", lambda: t[0])
    assert app._rate_allow(key, 2, 60) and app._rate_allow(key, 2, 60)
    assert app._rate_allow(key, 2, 60) is False           # 3rd within the window: blocked
    t[0] += 61                                            # window passes
    assert app._rate_allow(key, 2, 60) is True            # allowed again
    app._RATE.pop(key, None)


def test_auth_bucket_returns_429_for_a_real_client_ip(base_url):
    """A non-loopback client (spoofed X-Forwarded-For, as Caddy would set) that hammers sign-in is
    blocked with 429 once past the ~20/min limit — the brute-force guard actually fires."""
    import app, urllib.request, urllib.error
    ip = "203.0.113.7"
    for b in list(app._RATE):
        if b.endswith(":" + ip):
            app._RATE.pop(b, None)

    def hit():
        req = urllib.request.Request(base_url + "/api/auth/demo", data=b'{"role":"staff"}', method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Forwarded-For", ip)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    codes = [hit() for _ in range(26)]
    assert 429 in codes, "auth flood should be rate-limited (got %r)" % sorted(set(codes))
    assert codes[:15].count(429) == 0, "the first requests must pass before the limit trips"
    assert codes.index(429) >= 20, "429 should only trip after the ~20/min budget (first at %d)" % codes.index(429)
    for b in list(app._RATE):
        if b.endswith(":" + ip):
            app._RATE.pop(b, None)


def test_writes_never_throttled_from_loopback(api, tokens):
    """The test harness hits from 127.0.0.1, which is exempt — a burst well over the 240/min write cap
    must never return 429 (proves the limiter never throttles server-local / health-probe traffic)."""
    for i in range(300):
        st, _b = api("POST", "/api/coll/claims", tokens["staff"], {"title": "rl-%d" % i, "amount": 1})
        assert st != 429, "loopback traffic must never be rate-limited (got 429 at #%d)" % i
        assert st in (200, 400, 403), st
