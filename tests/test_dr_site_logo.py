# -*- coding: utf-8 -*-
"""The contractor's mark on its own form.

Two things to keep true. The logo must not be reachable before sign-in — a valid-shaped unknown
token has to render exactly what a real one does, and a logo appearing early would tell somebody
holding a guess both that the link is real and whose it is. And it must not be inlined into the day
payload, which the site refetches every time it changes date on a plant-room connection.
"""
import base64
import json
import urllib.error
import urllib.request

import pytest

import app
import db
import dr_access

PID = "P-LOGO"
TOKEN = "tok" + "L" * 30
BARE_TOKEN = "tok" + "N" * 30          # a real contractor that has no logo
EMAIL = "site@taikisha.example"

# A 1x1 PNG is enough: the endpoint's job is to decode, type and gate it, not to look at it.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
URI = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")

WITH_LOGO = {"id": "C-LOGO", "name": "Taikisha", "projectId": PID, "token": TOKEN,
             "emails": EMAIL, "logo": URI,
             "mgmtRoles": ["Site Manager"], "workerTrades": ["HVAC"], "categories": ["HVAC Works"]}
NO_LOGO = {"id": "C-BARE", "name": "Newtecons", "projectId": PID, "token": BARE_TOKEN,
           "emails": EMAIL, "logo": "",
           "mgmtRoles": [], "workerTrades": [], "categories": []}


@pytest.fixture(autouse=True)
def _seed(base_url):
    db.put_collection_item("pm_projects", {"id": PID, "name": "Mega", "manager": "Dept Manager"})
    db.put_collection_item("dr_contractors", dict(WITH_LOGO))
    db.put_collection_item("dr_contractors", dict(NO_LOGO))
    yield
    for c in ("C-LOGO", "C-BARE"):
        db.delete_collection_item("dr_contractors", c)
    db.delete_collection_item("pm_projects", PID)


def _get(base_url, path, cookie=None):
    req = urllib.request.Request(base_url + path)
    if cookie:
        req.add_header("Cookie", dr_access.COOKIE + "=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def _cookie(cid="C-LOGO", email=EMAIL):
    con = db.get_collection_item("dr_contractors", cid) or {}
    return dr_access.sign_session(app.Handler._dr_secret(app.Handler), cid, email,
                                  dr_access.session_epoch(con))


def test_the_logo_is_not_served_before_sign_in(base_url):
    """The oracle property. If this ever 200s without a session, the link stops being 'a page that
    asks who you are' and becomes 'a page that confirms which contractor you guessed'."""
    st, _b, _h = _get(base_url, "/api/dr/site/logo?token=" + TOKEN)
    assert st == 401, "a real contractor's logo was served to an anonymous caller"


def test_a_guessed_token_and_a_real_one_answer_identically_when_signed_out(base_url):
    st_real, b_real, _ = _get(base_url, "/api/dr/site/logo?token=" + TOKEN)
    st_fake, b_fake, _ = _get(base_url, "/api/dr/site/logo?token=tok" + "Z" * 30)
    assert st_real == st_fake, "the status distinguishes a real token from a guess"
    assert b_real == b_fake, "the body distinguishes a real token from a guess"


def test_a_signed_in_site_gets_its_own_logo(base_url):
    st, body, h = _get(base_url, "/api/dr/site/logo?token=" + TOKEN, cookie=_cookie())
    assert st == 200, body
    assert body == PNG, "the bytes are not the stored image"
    assert h.get("Content-Type") == "image/png"
    assert "private" in (h.get("Cache-Control") or ""), \
        "one contractor's mark must not sit in a shared cache"
    assert h.get("X-Content-Type-Options") == "nosniff"


def test_one_contractor_cannot_fetch_anothers_logo(base_url):
    """Same binding as everything else behind this link: the cookie says who, the token says which,
    and both have to agree."""
    st, _b, _h = _get(base_url, "/api/dr/site/logo?token=" + TOKEN, cookie=_cookie("C-BARE"))
    assert st == 401


def test_a_contractor_with_no_logo_says_so_rather_than_serving_something(base_url):
    st, _b, _h = _get(base_url, "/api/dr/site/logo?token=" + BARE_TOKEN,
                      cookie=_cookie("C-BARE"))
    assert st == 404


def test_the_day_payload_carries_a_flag_and_not_the_image(base_url):
    """The image is base64 on the row. Inlining it would ship the whole logo in the JSON every time
    the site changes date — the shape that timed the Quality tab out."""
    st, body, _h = _get(base_url, "/api/dr/site/day?token=" + TOKEN, cookie=_cookie())
    assert st == 200, body
    payload = json.loads(body.decode())
    assert payload["contractor"]["hasLogo"] is True
    raw = body.decode()
    assert "data:image" not in raw, "the day payload inlines the image"
    assert URI[:40] not in raw

    st, body, _h = _get(base_url, "/api/dr/site/day?token=" + BARE_TOKEN, cookie=_cookie("C-BARE"))
    assert json.loads(body.decode())["contractor"]["hasLogo"] is False


def test_a_stored_value_that_is_not_an_image_is_refused(base_url):
    """The field is written by the portal, but it is still a string in a blob store. A javascript:
    URI or a stray HTML fragment must not come back with an image content-type."""
    for bad in ("javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "not a uri", "  "):
        db.put_collection_item("dr_contractors", dict(WITH_LOGO, logo=bad))
        st, _b, _h = _get(base_url, "/api/dr/site/logo?token=" + TOKEN, cookie=_cookie())
        assert st == 404, "served %r as an image" % bad
    db.put_collection_item("dr_contractors", dict(WITH_LOGO))
