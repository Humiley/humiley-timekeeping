"""Kit that is lost or broken must stop being issuable.

The register balanced owned = assigned + in stock, which is true right up until somebody hands a
helmet back as Lost. The condition was stored as a label nobody read, the units went straight back
into the available count, and the next person could be signed out a helmet that does not exist. So
the equation needs a third term — written off — that stays inside the owned total (the company paid
for it, and it has to keep reconciling against the purchase record) but never reaches the shelf.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

IDX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "templates", "index.html")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _fn(src, name):
    at = src.find("\nfunction %s(" % name)
    assert at >= 0, "no top-level function " + name
    i, depth, j, started = at + 1, 0, at + 1, False
    while j < len(src):
        if src[j] == "{":
            depth += 1
            started = True
        elif src[j] == "}":
            depth -= 1
            if started and depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unterminated " + name)


def _run(js):
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    harness = "\n".join(_fn(src, n) for n in
                        ("_devAssigns", "_devTotalQty", "_devAssignedQty", "_devWrittenQty",
                         "_devRemaining", "_devOver", "_devAvail")) + "\n" + js
    p = os.path.join(tempfile.mkdtemp(prefix="tk-wo-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_written_off_unit_is_not_in_stock():
    """10 helmets, 5 held, 2 written off after a Lost return → 3 on the shelf, not 5."""
    out = _run("""
      const d = { qty: 10, writtenOff: 2, assignments: [{ empId: 'A', qty: 5 }] };
      console.log(JSON.stringify({ total: _devTotalQty(d), assigned: _devAssignedQty(d),
                                   written: _devWrittenQty(d), stock: _devRemaining(d) }));
    """)
    assert out["stock"] == 3, "written-off units must not be counted as available"
    assert out["assigned"] + out["stock"] + out["written"] == out["total"]


def test_the_last_unit_lost_leaves_nothing_to_issue():
    """The bug that made this worth fixing: qty 1, returned Lost, and the register still offered it."""
    out = _run("""
      const d = { qty: 1, writtenOff: 1, status: 'Lost', assignments: [] };
      console.log(JSON.stringify({ stock: _devRemaining(d), avail: _devAvail(d) }));
    """)
    assert out["stock"] == 0, "a lost item must not be issuable to the next employee"
    assert out["avail"] == "Lost"


def test_a_fully_written_off_line_does_not_read_as_available():
    out = _run("""
      const d = { qty: 4, writtenOff: 4, assignments: [] };
      console.log(JSON.stringify({ avail: _devAvail(d), stock: _devRemaining(d) }));
    """)
    assert out["avail"] == "Written off"
    assert out["stock"] == 0


def test_a_partial_write_off_still_leaves_the_rest_assignable():
    out = _run("""
      const d = { qty: 6, writtenOff: 1, assignments: [{ empId: 'A', qty: 2 }] };
      console.log(JSON.stringify({ stock: _devRemaining(d), avail: _devAvail(d) }));
    """)
    assert out["stock"] == 3
    assert out["avail"] == "Partially assigned"


def test_no_write_off_field_behaves_exactly_as_before():
    """Every existing row has no writtenOff key — the maths must not move under them."""
    out = _run("""
      const rows = [ { qty: 4, assignments: [{ qty: 2 }] }, { qty: 1 }, { qty: 0 },
                     { qty: 3, writtenOff: '', assignments: [] },
                     { qty: 3, writtenOff: 'x', assignments: [] },
                     { qty: 3, writtenOff: -2, assignments: [] } ];
      console.log(JSON.stringify(rows.map(d => ({ w: _devWrittenQty(d), stock: _devRemaining(d) }))));
    """)
    assert [r["w"] for r in out] == [0, 0, 0, 0, 0, 0], "a missing or junk value is zero, never negative"
    assert [r["stock"] for r in out] == [2, 1, 0, 3, 3, 3]


def test_over_issue_is_still_surfaced_not_hidden():
    """The earlier fix must survive: more signed out than owned stays visible as a shortfall."""
    out = _run("""
      const d = { qty: 2, writtenOff: 1, assignments: [{ empId: 'A', qty: 3 }] };
      console.log(JSON.stringify({ stock: _devRemaining(d), over: _devOver(d) }));
    """)
    assert out["stock"] == -2 and out["over"] == 2


def test_the_release_and_return_paths_are_wired_up():
    """Un-assign did not exist at all: offboarding was the only way to remove an assignment, so a
    mistaken assign was permanent for anyone still employed."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    for fn in ("tkDeviceUnassign", "tkDeviceUnassignSave", "_devUnasgBtn", "_devWrittenQty"):
        assert ("function " + fn) in src, "%s is referenced but not defined" % fn
    assert "_devUnasgBtn(x.id, a.id)" in src, "the release button is not wired into the Assignments tab"
    assert "assignmentHistory" in src, "a released assignment must be archived, not deleted"
    # Partial return: the modal has to offer a quantity, or a holder of 5 can only hand back all 5.
    assert 'data-ar-qty="' in src, "the return modal has no quantity input"
