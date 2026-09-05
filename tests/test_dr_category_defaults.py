# -*- coding: utf-8 -*-
"""A contractor with no work categories gets the standard set.

The photo section, 5.1 and 5.3 all group under these. A contractor set up in a hurry with none
entered used to get a ONE-OPTION dropdown — which looks configured and is not, so every photo of
that site landed under whatever that single option happened to be. An empty list would at least
have been obviously wrong; a list of one is quietly wrong, which is worse on a document the client
reads daily.

Same contract as SAFETY_DEFAULTS: the shipped set applies only while the contractor has none of its
own, and stops the moment it does.
"""
import json
import urllib.error
import urllib.request

import pytest

import app
import daily_report
import db
import dr_access

PID = "P-CAT"
TOKEN = "tok" + "C" * 30
EMAIL = "site@x.example"
BASE = {"id": "C-CAT", "name": "Newtechcon", "projectId": PID, "token": TOKEN, "emails": EMAIL,
        "mgmtRoles": [], "workerTrades": []}


@pytest.fixture(autouse=True)
def _seed(base_url):
    db.put_collection_item("pm_projects", {"id": PID, "name": "Mega", "manager": "Dept Manager"})
    yield
    db.delete_collection_item("dr_contractors", "C-CAT")
    db.delete_collection_item("pm_projects", PID)


def _day(categories):
    db.put_collection_item("dr_contractors", dict(BASE, categories=categories))
    con = db.get_collection_item("dr_contractors", "C-CAT")
    cookie = dr_access.sign_session(app.Handler._dr_secret(app.Handler), "C-CAT", EMAIL,
                                    dr_access.session_epoch(con))
    req = urllib.request.Request(app_base() + "/api/dr/site/day?token=" + TOKEN)
    req.add_header("Cookie", dr_access.COOKIE + "=" + cookie)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())["setup"]["categories"]


_BASE_URL = {"v": ""}


def app_base():
    return _BASE_URL["v"]


@pytest.fixture(autouse=True)
def _capture(base_url):
    _BASE_URL["v"] = base_url


def test_no_categories_gets_the_standard_set():
    assert _day([]) == list(daily_report.CATEGORY_DEFAULTS)


def test_a_missing_field_gets_the_standard_set_too():
    """`categories` absent is the same situation as `categories: []` — a contractor nobody
    configured — and must not behave differently."""
    db.put_collection_item("dr_contractors", dict(BASE))
    con = db.get_collection_item("dr_contractors", "C-CAT")
    cookie = dr_access.sign_session(app.Handler._dr_secret(app.Handler), "C-CAT", EMAIL,
                                    dr_access.session_epoch(con))
    req = urllib.request.Request(app_base() + "/api/dr/site/day?token=" + TOKEN)
    req.add_header("Cookie", dr_access.COOKIE + "=" + cookie)
    with urllib.request.urlopen(req, timeout=10) as r:
        got = json.loads(r.read().decode())["setup"]["categories"]
    assert got == list(daily_report.CATEGORY_DEFAULTS)


def test_a_contractors_own_list_wins_and_the_default_stops_applying():
    """The whole point of the contract. A site that has said 'we do two things' must not be handed
    seven more, or the dropdown stops meaning anything."""
    own = ["HVAC Works", "Plumbing Works"]
    assert _day(own) == own


def test_a_single_category_is_respected_rather_than_topped_up():
    """One IS a configuration — an MEP subcontractor on one package. The default fills an ABSENCE,
    it does not pad a short list, or a deliberate choice gets overruled."""
    assert _day(["HVAC Works"]) == ["HVAC Works"]


def test_the_default_covers_both_kinds_of_package_on_this_job():
    """Drawn from the two reports the module was built against — Taikisha MEP-led, Newtecons
    civil-led. If it ever covered only one, half the contractors on a job would be filing under
    'Other Works'."""
    d = set(daily_report.CATEGORY_DEFAULTS)
    assert {"HVAC Works", "Electrical Works", "Plumbing Works"} <= d, "no MEP categories"
    assert {"Civil Structure Works", "Architectural Finishing Works"} <= d, "no civil categories"
    assert "Other Works" in d, "nothing to file the unclassifiable under"
    assert len(d) == len(daily_report.CATEGORY_DEFAULTS), "the default list repeats itself"
