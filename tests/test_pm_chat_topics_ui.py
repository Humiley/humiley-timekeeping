"""The browser half of topics: which topic a message belongs to, and where Send will file it.

Two questions decide whether this feature is trustworthy, and both are answered in the browser:

  * "what topic is this thread in?" -- a reply must answer with its ROOT's topic, always. If a reply
    could answer with its own stored value, re-filing a thread would leave its replies scattered
    behind it, which is the exact failure the whole design exists to prevent.
  * "where will Send put this?" -- one function feeds BOTH the dropdown's rendered selection and the
    POST body. The classic bug in this shape of feature is the dropdown reading Site while the
    message quietly lands in General, and the only defence is that there is nowhere for the two to
    disagree.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


VI_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "static", "i18n", "vi.js")


def _src():
    # The _VI dictionary moved to static/i18n/vi.js (it was 12% of the boot download and was built
    # even for English users, who are the default). test_every_topic_has_a_vietnamese_label looks up
    # its keys in this string, so both files belong in it — the app loads both too.
    with open(IDX, encoding="utf-8") as fh:
        html = fh.read()
    with open(VI_JS, encoding="utf-8") as fh:
        return html + "\n" + fh.read()


def _fn(src, name):
    for prefix in ("\nfunction %s(", "\nasync function %s("):
        at = src.find(prefix % name)
        if at >= 0:
            i = at + 1
            break
    else:
        raise AssertionError("no top-level function " + name)
    depth, j, started = 0, i, False
    while j < len(src):
        if src[j] == "{":
            depth += 1
            started = True
        elif src[j] == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unterminated function " + name)


def _catalogue(src):
    """The topic list itself, lifted verbatim -- so a drifting label or key fails a test."""
    m = re.search(r"const _PM_CHAT_TOPICS = \[.*?\n\];", src, re.S)
    assert m, "the topic catalogue is not where the tests expect it"
    return m.group(0)


def _run(js):
    src = _src()
    harness = (
        "function _t(s){return s;}\n"
        "function _pmEsc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}\n"
        "function _pmBadge(t,h){return '<span class=\"badge\" style=\"background:'+h+'1f;color:'+h+'\">'+_pmEsc(t)+'</span>';}\n"
        "const _HR = { pm_chat: [] };\n"
        "let _pmChatReplyTo = '', _pmChatEditId = '', _pmChatTopicPick = '';\n"
        + _catalogue(src) + "\n"
        + "function _pmChatCtx(){}\n"
        + "const document = { getElementById: function(){ return null; } };\n"
        + "\n".join(_fn(src, n) for n in ("_pmChatTopicDef", "_pmChatTopicOf", "_pmChatTopicChip",
                                          "_pmChatPostTopic", "_pmChatTopicLocked", "pmChatEdit"))
        + "\n" + js
    )
    p = os.path.join(tempfile.mkdtemp(prefix="tk-topics-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── which topic a message is in ───────────────────────────────────────────────────────────────────

def test_a_root_reports_its_own_topic():
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'hse' }];
      console.log(JSON.stringify({ t: _pmChatTopicOf(_HR.pm_chat[0]) }));
    """)
    assert out["t"] == "hse"


def test_a_reply_reports_its_root_s_topic_not_its_own():
    """THE invariant. The reply below carries a stale 'cost' from before its thread was re-filed;
       it must still read as part of the Safety thread it actually belongs to."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'hse' }, { id: 'k1', parentId: 'r1', topic: 'cost' }];
      console.log(JSON.stringify({ t: _pmChatTopicOf(_HR.pm_chat[1]) }));
    """)
    assert out["t"] == "hse", "a reply answered with its own stale label and left its thread behind"


def test_re_filing_a_root_carries_its_whole_thread():
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'hse' },
                     { id: 'k1', parentId: 'r1', topic: 'hse' },
                     { id: 'k2', parentId: 'r1', topic: 'hse' }];
      _HR.pm_chat[0].topic = 'qaqc';                       // the PM re-files the root
      console.log(JSON.stringify({ all: _HR.pm_chat.map(_pmChatTopicOf) }));
    """)
    assert out["all"] == ["qaqc", "qaqc", "qaqc"], "replies were left behind in the old topic"


def test_an_unfiled_message_is_general():
    out = _run("""
      console.log(JSON.stringify({ none: _pmChatTopicOf({ id: 'a' }),
                                   empty: _pmChatTopicOf({ id: 'b', topic: '' }) }));
    """)
    assert out["none"] == "" and out["empty"] == ""


def test_a_key_that_is_no_longer_in_the_catalogue_degrades_to_general():
    """Removing a key is a one-way door, so it must fail soft. A message filed under a retired topic
       still reads, it just loses its label -- it never renders a raw key at somebody."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'retired-in-2027' }];
      console.log(JSON.stringify({ t: _pmChatTopicOf(_HR.pm_chat[0]),
                                   chip: _pmChatTopicChip(_pmChatTopicOf(_HR.pm_chat[0])) }));
    """)
    assert out["t"] == "" and out["chip"] == ""


def test_an_orphaned_reply_does_not_crash():
    """Its parent was deleted. It must still render, as General."""
    out = _run("""
      _HR.pm_chat = [{ id: 'k1', parentId: 'gone', topic: 'hse' }];
      console.log(JSON.stringify({ t: _pmChatTopicOf(_HR.pm_chat[0]) }));
    """)
    assert out["t"] == "hse"      # falls back to its own value rather than throwing


def test_general_wears_no_chip():
    """A chip on every message is wallpaper. A chip should mean somebody deliberately filed it."""
    out = _run("""
      console.log(JSON.stringify({ general: _pmChatTopicChip(''), safety: _pmChatTopicChip('hse') }));
    """)
    assert out["general"] == ""
    assert "Safety" in out["safety"]


# ── where Send will file it ───────────────────────────────────────────────────────────────────────

def test_a_new_message_goes_where_the_composer_says():
    out = _run("""
      _pmChatTopicPick = 'materials';
      console.log(JSON.stringify({ t: _pmChatPostTopic(), locked: _pmChatTopicLocked() }));
    """)
    assert out["t"] == "materials" and out["locked"] is False


def test_a_reply_is_forced_into_its_thread_s_topic():
    """Even if the composer was armed for something else -- a thread cannot split."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'qaqc' }];
      _pmChatTopicPick = 'cost';
      _pmChatReplyTo = 'r1';
      console.log(JSON.stringify({ t: _pmChatPostTopic(), locked: _pmChatTopicLocked() }));
    """)
    assert out["t"] == "qaqc", "a reply escaped its thread's topic"
    assert out["locked"] is True, "the picker was left enabled on a reply"


def test_replying_to_a_reply_still_lands_on_the_root_topic():
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'programme' }, { id: 'k1', parentId: 'r1', topic: 'programme' }];
      _pmChatReplyTo = 'k1';
      console.log(JSON.stringify({ t: _pmChatPostTopic() }));
    """)
    assert out["t"] == "programme"


def test_editing_a_root_can_re_file_it_but_editing_a_reply_cannot():
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'site' }, { id: 'k1', parentId: 'r1', topic: 'site' }];
      _pmChatTopicPick = 'client';
      _pmChatEditId = 'r1';
      const root = { t: _pmChatPostTopic(), locked: _pmChatTopicLocked() };
      _pmChatEditId = 'k1';
      const reply = { t: _pmChatPostTopic(), locked: _pmChatTopicLocked() };
      console.log(JSON.stringify({ root: root, reply: reply }));
    """)
    assert out["root"] == {"t": "client", "locked": False}, "a root could not be re-filed from Edit"
    assert out["reply"] == {"t": "site", "locked": True}, "a reply could be re-filed on its own"


def test_the_catalogue_matches_the_server():
    """The browser offers what the server accepts. If these drift, a topic somebody picks is silently
       stored as General -- the worst kind of failure, because it looks like it worked."""
    src = _src()
    ui = set(re.findall(r"\{ k: '([a-z]*)'", _catalogue(src)))
    app = os.path.join(os.path.dirname(IDX), "..", "app.py")
    with open(app, encoding="utf-8") as fh:
        m = re.search(r"PM_CHAT_TOPICS = \(([^)]*)\)", fh.read())
    server = set(re.findall(r'"([a-z]+)"', m.group(1)))
    assert ui - {""} == server, (
        "the browser's topic list and app.py's PM_CHAT_TOPICS disagree: "
        "only in UI %s, only on server %s" % (sorted(ui - {""} - server), sorted(server - ui)))


def test_every_topic_has_a_vietnamese_label():
    """Half the site staff read the portal in Vietnamese. A topic that stays English there is a topic
       they will not use."""
    src = _src()
    labels = re.findall(r"en: '([^']+)'", _catalogue(src))
    assert len(labels) >= 9
    missing = [l for l in labels if ("'" + l.replace("&", "&") + "':") not in src.replace("&amp;", "&")]
    assert not missing, "no _VI entry for: %s" % missing


# ── fixing a typo must not move the message ───────────────────────────────────────────────────────
#
# The composer's topic is a standing arming, not a per-message value: it follows whichever pill you
# are reading. Entering Edit therefore has to point it at the message you are editing, or Send
# overwrites that message's real topic with whatever you happened to be reading.

def test_editing_a_filed_message_does_not_move_it():
    """THE one. Somebody files a message under Safety, later fixes a typo while reading All, and
       presses Send without touching the dropdown. It must still be under Safety."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'hse', body: 'Scafold blocking the riser' }];
      _pmChatTopicPick = '';                       // reading All, which is the default
      pmChatEdit('r1');
      console.log(JSON.stringify({ willFileAs: _pmChatPostTopic() }));
    """)
    assert out["willFileAs"] == "hse", "a typo fix would have dumped the message into General"


def test_the_dropdown_shows_the_message_s_own_topic_while_editing_it():
    """The label says "Move to", so it has to start on where the message actually is. Starting on
       General reads as an instruction to move it there."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'cost', body: 'variation for the extra FFU' }];
      _pmChatTopicPick = 'programme';              // armed from a pill the reader tapped earlier
      pmChatEdit('r1');
      console.log(JSON.stringify({ shows: _pmChatPostTopic() }));
    """)
    assert out["shows"] == "cost", "the dropdown offered to move a message the user only wanted to fix"


def test_you_can_still_deliberately_re_file_while_editing():
    """The fix must not take the ability away — picking a topic during an edit is how a re-file is
       done at all."""
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', topic: 'cost', body: 'x' }];
      pmChatEdit('r1');
      _pmChatTopicPick = 'qaqc';                   // the user changes the dropdown
      console.log(JSON.stringify({ willFileAs: _pmChatPostTopic() }));
    """)
    assert out["willFileAs"] == "qaqc"


def test_editing_an_unfiled_message_leaves_it_unfiled():
    out = _run("""
      _HR.pm_chat = [{ id: 'r1', body: 'no topic' }];
      _pmChatTopicPick = 'hse';                    // armed from a pill
      pmChatEdit('r1');
      console.log(JSON.stringify({ willFileAs: _pmChatPostTopic() }));
    """)
    assert out["willFileAs"] == "", "reading Safety re-filed an unrelated message into Safety"
