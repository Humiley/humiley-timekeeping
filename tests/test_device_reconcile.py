"""An asset register has to add up: total owned = issued + in stock.

One item can be signed out to several people at once — 4 drills, two to one engineer and one each to
two others — so the register is a stock line with a list of holders, not a single assignee. That only
works if the arithmetic is honest at every level:

  * per row: qty === sum(assignment quantities) + in stock
  * in the KPI strip: Total items === Assigned + In stock

It stopped being honest in two places. The KPI strip counted a row with no quantity as ONE item while
counting its stock as zero, so every such row quietly widened the gap. And "in stock" was clamped at
zero, so a line with more signed out than the company owns — an import, a quantity edited down, two
managers assigning at the same moment — showed a tidy 0 and the discrepancy disappeared instead of
being raised. A register that hides a shortfall is worse than one that has none.
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
    p = os.path.join(tempfile.mkdtemp(prefix="tk-dev-"), "t.js")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(harness)
    r = subprocess.run(["node", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── one item, several holders ─────────────────────────────────────────────────────────────────────

def test_one_item_can_be_held_by_several_people_at_once():
    """4 drills: 2 with one engineer, 1 each with two others, 0 left in the store."""
    out = _run("""
      const d = { qty: 4, assignments: [{ empId: 'A', qty: 2 }, { empId: 'B', qty: 1 }, { empId: 'C', qty: 1 }] };
      console.log(JSON.stringify({ holders: d.assignments.length, total: _devTotalQty(d),
                                   assigned: _devAssignedQty(d), stock: _devRemaining(d), avail: _devAvail(d) }));
    """)
    assert out["holders"] == 3
    assert out["assigned"] == 4 and out["stock"] == 0
    assert out["assigned"] + out["stock"] == out["total"]
    assert out["avail"] == "Fully assigned"


def test_part_of_a_line_can_stay_in_the_store():
    out = _run("""
      const d = { qty: 10, assignments: [{ empId: 'A', qty: 3 }, { empId: 'B', qty: 2 }] };
      console.log(JSON.stringify({ total: _devTotalQty(d), assigned: _devAssignedQty(d),
                                   stock: _devRemaining(d), avail: _devAvail(d) }));
    """)
    assert (out["total"], out["assigned"], out["stock"]) == (10, 5, 5)
    assert out["avail"] == "Partially assigned"


# ── the invariant ─────────────────────────────────────────────────────────────────────────────────

def test_every_row_shape_adds_up():
    """Including the shapes that used to break it."""
    out = _run("""
      const rows = [
        { label: 'no quantity, nothing out',   d: {} },
        { label: 'no quantity, one out',       d: { assignments: [{ qty: 1 }] } },
        { label: 'explicit zero',              d: { qty: 0 } },
        { label: 'string quantity',            d: { qty: '6', assignments: [{ qty: 2 }] } },
        { label: 'over-issued',                d: { qty: 2, assignments: [{ qty: 3 }, { qty: 1 }] } },
        { label: 'legacy single assignee',     d: { qty: 1, empId: 'A', assignedTo: 'A', status: 'Assigned' } }
      ];
      console.log(JSON.stringify(rows.map(r => ({
        label: r.label, total: _devTotalQty(r.d), assigned: _devAssignedQty(r.d),
        stock: _devRemaining(r.d), over: _devOver(r.d)
      }))));
    """)
    for r in out:
        assert r["assigned"] + r["stock"] == r["total"], (
            "%s: %d issued + %d in stock != %d owned" % (r["label"], r["assigned"], r["stock"], r["total"]))


def test_a_row_with_no_quantity_counts_as_one_everywhere():
    """It used to count 1 in Total and 0 in stock — the original off-by-one that made the strip drift."""
    out = _run("""
      const d = {};
      console.log(JSON.stringify({ total: _devTotalQty(d), stock: _devRemaining(d) }));
    """)
    assert out["total"] == 1 and out["stock"] == 1


def test_an_explicit_zero_is_respected():
    """A line deliberately set to 0 owned is not silently 1."""
    out = _run("console.log(JSON.stringify({ total: _devTotalQty({ qty: 0 }) }));")
    assert out["total"] == 0


# ── a shortfall must surface, not vanish ──────────────────────────────────────────────────────────

def test_issuing_more_than_we_own_is_reported_not_clamped():
    """THE one. Four units signed out against a line of two. Clamping stock to 0 made the register
       look balanced while two units were unaccounted for."""
    out = _run("""
      const d = { qty: 2, assignments: [{ empId: 'A', qty: 3 }, { empId: 'B', qty: 1 }] };
      console.log(JSON.stringify({ total: _devTotalQty(d), assigned: _devAssignedQty(d),
                                   stock: _devRemaining(d), over: _devOver(d) }));
    """)
    assert out["over"] == 2, "the shortfall was absorbed instead of raised"
    assert out["stock"] == -2, "in stock was clamped and stopped reconciling"
    assert out["assigned"] + out["stock"] == out["total"]


def test_a_balanced_register_reports_no_shortfall():
    out = _run("""
      console.log(JSON.stringify({
        exact: _devOver({ qty: 3, assignments: [{ qty: 3 }] }),
        spare: _devOver({ qty: 3, assignments: [{ qty: 1 }] }),
        empty: _devOver({ qty: 3 })
      }));
    """)
    assert out == {"exact": 0, "spare": 0, "empty": 0}


# ── the KPI strip uses the same basis as the rows ─────────────────────────────────────────────────

def test_the_kpi_strip_and_the_table_count_quantity_the_same_way():
    """They disagreed: `qty || 1` in the strip, `qty || 0` in the stock helper. One definition now."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("const units = d.reduce(")
    block = src[i:i + 700]
    assert "_devTotalQty(x)" in block, "the KPI strip is not using the shared quantity helper"
    assert "(+x.qty || 1)" not in block, "the old inconsistent basis is back in the KPI strip"


def test_the_page_shows_the_sum_it_is_claiming():
    """Assigned + In stock = N of M owned, written out, so it can be checked at a glance."""
    with open(IDX, encoding="utf-8") as fh:
        src = fh.read()
    assert "_t('In stock')" in src
    assert "_t('owned')" in src and "_t('Balanced')" in src
    assert "issued beyond stock" in src


# ── a legacy holder does not own the whole line ───────────────────────────────────────────────────
#
# Rows created before the multi-holder model — and by the Excel import, the quick-add form and
# onboarding provisioning — record one NAME and a status, with no per-person quantity. Reading that
# as "this person has every unit" is what made the register unusable: buying four more of something
# already issued to somebody moved all four into their name, pinned in-stock at zero, and the assign
# dialog then refused to give the item to anybody else.

def test_a_legacy_holder_counts_as_one_unit_not_the_whole_line():
    out = _run("""
      const one  = { qty: 1, assignedTo: 'Dung', status: 'Assigned' };
      const five = { qty: 5, assignedTo: 'Dung', status: 'Assigned' };   // four more bought later
      console.log(JSON.stringify({
        one:  { owned: _devTotalQty(one),  assigned: _devAssignedQty(one),  stock: _devRemaining(one) },
        five: { owned: _devTotalQty(five), assigned: _devAssignedQty(five), stock: _devRemaining(five) }
      }));
    """)
    assert out["one"] == {"owned": 1, "assigned": 1, "stock": 0}
    assert out["five"]["assigned"] == 1, "buying more stock silently credited it to the existing holder"
    assert out["five"]["stock"] == 4, "the new units were not available to assign to anybody else"


def test_a_legacy_holder_never_exceeds_the_line():
    """The shim must not invent stock either — one unit, or the whole line if the line is smaller."""
    out = _run("""
      console.log(JSON.stringify({
        zero: _devAssignedQty({ qty: 0, assignedTo: 'Dung', status: 'Assigned' }),
        noQty: _devAssignedQty({ assignedTo: 'Dung', status: 'Assigned' })
      }));
    """)
    assert out["zero"] == 0 and out["noQty"] == 1


def test_a_stock_line_stays_assignable_to_more_people():
    """The whole point. Ten drills, two already out, eight still available to hand to others."""
    out = _run("""
      const d = { qty: 10, assignments: [{ empId: 'A', qty: 2 }] };
      console.log(JSON.stringify({ stock: _devRemaining(d), avail: _devAvail(d) }));
    """)
    assert out["stock"] == 8 and out["avail"] == "Partially assigned"
