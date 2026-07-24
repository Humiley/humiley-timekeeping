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


def test_writes_never_throttled_from_loopback(api, tokens):
    """The test harness hits from 127.0.0.1, which is exempt — a burst well over the 240/min write cap
    must never return 429 (proves the limiter never throttles server-local / health-probe traffic)."""
    for i in range(300):
        st, _b = api("POST", "/api/coll/claims", tokens["staff"], {"title": "rl-%d" % i, "amount": 1})
        assert st != 429, "loopback traffic must never be rate-limited (got 429 at #%d)" % i
        assert st in (200, 400, 403), st
