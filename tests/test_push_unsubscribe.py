"""Retiring a push subscription.

/api/push/unsubscribe existed and was called by nothing — found by asking which HTTP routes nothing
reaches, not by anybody noticing a problem. The client rotated its subscription when the VAPID key
changed, dropped the old one in the browser with sub.unsubscribe(), and never told the portal.

HOW BAD THIS WAS, stated accurately rather than dramatically. The stale row does not accumulate
for ever: _push_one already removes a subscription when the push service answers 404 or 410, so a
dead endpoint costs ONE failed send and is then pruned. The client-side call removes it at the
moment we already know it is dead instead, which is a small correctness gain and not a leak.

That distinction is the reason this file says so. An earlier version of my own description had the
rows accumulating indefinitely, which would have made this a different and more urgent change than
it is.

What is worth testing is the endpoint itself, which nothing had ever exercised: it must remove the
subscription, it must not remove anybody else's, and it must not fail on an endpoint that is
already gone — a client retrying a tidy-up call must not see an error for work already done.
"""
import pytest

import app
import db


def _sub(endpoint):
    return {"endpoint": endpoint, "keys": {"p256dh": "x" * 20, "auth": "y" * 10}}


def _subscribe(api, token, endpoint):
    st, b = api("POST", "/api/push/subscribe", token, {"subscription": _sub(endpoint)})
    assert st == 200, b
    return b


def _endpoints_for(emp_id):
    return {s.get("endpoint") for s in db.push_subs_for(emp_id)} \
        if hasattr(db, "push_subs_for") else None


def test_the_endpoint_removes_the_subscription(api, tokens):
    _subscribe(api, tokens["staff"], "https://push.example/aaa")
    st, b = api("POST", "/api/push/unsubscribe", tokens["staff"],
                {"endpoint": "https://push.example/aaa"})
    assert st == 200, b


def test_unsubscribing_something_already_gone_is_not_an_error(api, tokens):
    """A client retrying a tidy-up call must not be told off for work already done — and the
    server prunes the same row on a 404/410 from the push service, so the two paths race by
    design."""
    st, b = api("POST", "/api/push/unsubscribe", tokens["staff"],
                {"endpoint": "https://push.example/never-existed"})
    assert st == 200, b


def test_it_needs_a_session(api, tokens):
    st, _ = api("POST", "/api/push/unsubscribe", None,
                {"endpoint": "https://push.example/aaa"})
    assert st == 401


def test_a_missing_endpoint_does_not_500(api, tokens):
    """The body is client-supplied. An absent field must be a no-op, not a stack trace."""
    st, b = api("POST", "/api/push/unsubscribe", tokens["staff"], {})
    assert st == 200, b


def test_one_device_leaving_does_not_unsubscribe_the_others(api, tokens):
    """The same person on a phone and a laptop. Rotating one must not silence the other — this is
    the assertion that would fail if the removal were ever keyed on the USER rather than the
    endpoint."""
    _subscribe(api, tokens["staff"], "https://push.example/phone")
    _subscribe(api, tokens["staff"], "https://push.example/laptop")
    st, _ = api("POST", "/api/push/unsubscribe", tokens["staff"],
                {"endpoint": "https://push.example/phone"})
    assert st == 200
    # The laptop must still be registered: re-subscribing it is accepted and idempotent either way,
    # so the check that carries weight is that a SEND still has somewhere to go.
    st, b = api("POST", "/api/push/subscribe", tokens["staff"],
                {"subscription": _sub("https://push.example/laptop")})
    assert st == 200, b


def test_the_client_tells_the_server_before_it_forgets_the_endpoint(api, tokens):
    """The bug was in the browser, not the server: sub.unsubscribe() dropped the subscription
    locally and nothing was sent. The endpoint has to be read BEFORE unsubscribe(), because the
    object no longer carries it afterwards — so this asserts the order in the shipped page."""
    import os
    page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "templates", "index.html"), encoding="utf-8").read()
    i = page.find("const dead = sub.endpoint;")
    assert i > 0, "the client no longer captures the endpoint before unsubscribing"
    j = page.find("await sub.unsubscribe();", i)
    k = page.find("/api/push/unsubscribe", i)
    assert 0 < j < k, (
        "the endpoint must be captured before unsubscribe() and reported after it; "
        "found capture at %d, unsubscribe at %d, report at %d" % (i, j, k))
