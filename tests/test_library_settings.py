"""The Library board, the Company Wiki and the Knowledge Hub — their settings round-trip.

Nothing in this feature stores a document: the board carries links and the two hub pages read
SharePoint live in the browser. So the ONLY thing the server owns is four addresses and two
content lists, and every way this feature can break silently is a break in that round-trip.

Four of them have already cost a day each elsewhere in this file's neighbours, which is why each
gets its own test rather than one "settings work" assertion:

  * a write path with no matching READ — the form loads blank, the admin saves, and a working
    link is cleared while the toast says Saved (wageRegion did exactly this),
  * a GET default that _portal_update does not know about — the form echoes the effective value
    back, the server compares it against "" and 403s a manager for a change nobody made,
  * a non-admin able to repoint a URL the whole company is told is the company's own,
  * a list content key missing from PORTAL_KEYS, so it saves nowhere and reads back as absent.
"""
import pytest

import app
import db


@pytest.fixture(autouse=True)
def _restore_library_settings():
    """These are company-wide settings in one shared test database."""
    keys = ["portal_wikiPageUrl", "portal_wikiSpUrl", "portal_knowledgePageUrl",
            "portal_knowledgeSpUrl", "portal_library", "portal_wiki"]
    before = {k: db.get_setting(k) for k in keys}
    yield
    for k, v in before.items():
        db.set_setting(k, v)


LINK_KEYS = ("wikiPageUrl", "wikiSpUrl", "knowledgePageUrl", "knowledgeSpUrl")


def test_the_four_addresses_are_readable_by_everyone(api, tokens):
    """A staff account is who the wiki is FOR. If the address only reached managers, the page
    would render its "not configured" panel for most of the company."""
    for who in ("staff", "mgr", "admin"):
        st, b = api("GET", "/api/portal", tokens[who])
        assert st == 200, b
        for k in LINK_KEYS:
            assert b.get(k), "%s got no %s" % (who, k)
            assert b[k].startswith("https://"), b[k]


def test_an_unset_address_answers_with_the_shipped_default():
    """The GET default and the SAVE default must be the same object, or a manager who opens the
    settings form and presses Save is told "Admin access required" for a change they never made:
    the form echoes back what the GET sent, and the comparison is against a different default."""
    for k in LINK_KEYS:
        assert k in app._APPR_SETTING_DEFAULTS, (
            "%s is defaulted in _portal_get but not in _APPR_SETTING_DEFAULTS, so _portal_update "
            "compares the echoed value against \"\" and treats it as a change." % k)


def test_only_an_admin_can_repoint_a_library(api, tokens):
    st, b = api("PATCH", "/api/portal", tokens["mgr"],
                {"wikiSpUrl": "https://evil.example.com/sites/HRRP"})
    assert st == 403, b
    assert "admin" in str(b).lower()
    st2, b2 = api("GET", "/api/portal", tokens["staff"])
    assert b2["wikiSpUrl"] == app._APPR_SETTING_DEFAULTS["wikiSpUrl"], "the refused change took effect"


def test_a_manager_saving_the_form_unchanged_is_not_refused(api, tokens):
    """What the settings form actually does: read every value, then send them all back. Only an
    ACTUAL change may require admin — otherwise a manager can never save any other setting on
    that form, because one echoed URL 403s the whole request."""
    _, live = api("GET", "/api/portal", tokens["mgr"])
    echo = {k: live[k] for k in LINK_KEYS}
    echo["apprReminderDays"] = "2"
    st, b = api("PATCH", "/api/portal", tokens["mgr"], echo)
    assert st == 200, b


def test_an_admin_can_repoint_and_it_reads_back(api, tokens):
    new = "https://humileyvietnam.sharepoint.com/sites/HRRP/Shared Documents/Wiki"
    st, b = api("PATCH", "/api/portal", tokens["admin"], {"wikiSpUrl": new})
    assert st == 200, b
    _, live = api("GET", "/api/portal", tokens["staff"])
    assert live["wikiSpUrl"] == new, "saved but not read back — the form would load blank and clear it"


def test_the_board_and_the_pinned_pages_survive_a_save(api, tokens):
    """`library` and `wiki` are list content like `resources`, so they must be in PORTAL_KEYS —
    a key that is not there is dropped without an error and reads back as absent."""
    assert "library" in app.Handler.PORTAL_KEYS and "wiki" in app.Handler.PORTAL_KEYS
    tiles = [{"label": "IT Knowledge Page", "url": "https://humileyvietnam.sharepoint.com/sites/IT",
              "desc": "IT guides", "icon": "it"},
             {"label": "Wiki", "url": "view:wiki", "desc": "", "icon": "wiki"}]
    st, b = api("PATCH", "/api/portal", tokens["mgr"],
                {"library": tiles, "wiki": [{"label": "Leave policy", "url": "https://x.sharepoint.com/p", "desc": ""}]})
    assert st == 200, b
    _, live = api("GET", "/api/portal", tokens["staff"])
    assert [t["label"] for t in live["library"]] == ["IT Knowledge Page", "Wiki"]
    assert live["library"][1]["url"] == "view:wiki", "the internal target must survive the sanitiser"
    assert live["wiki"][0]["label"] == "Leave policy"


def test_a_script_pasted_into_a_tile_does_not_come_back_as_markup(api, tokens):
    """These tiles render on every employee's Library page, so they go through the same strip as
    any other company-wide content."""
    st, _ = api("PATCH", "/api/portal", tokens["mgr"],
                {"library": [{"label": "<img src=x onerror=alert(1)>", "url": "https://a.sharepoint.com",
                              "desc": "<script>alert(2)</script>", "icon": "link"}]})
    assert st == 200
    _, live = api("GET", "/api/portal", tokens["staff"])
    blob = str(live["library"])
    # What the strip guarantees is that no ANGLE BRACKET survives, so the value can never be a tag
    # however it is inserted. The words inside are left as text on purpose — "onerror=alert(1)" is
    # a silly tile name, not a script — and asserting their absence would be asserting a rule the
    # sanitiser does not have, which is the kind of test that passes until somebody reads it.
    assert "<" not in blob and ">" not in blob, blob
