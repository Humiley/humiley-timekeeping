#!/usr/bin/env python3
"""Find loops that do collection-scale work once per row.

    python3 tools/scan_read_cost.py app.py ahu.py db.py
    python3 tools/scan_read_cost.py *.py

`db.list_collection` loads and `json.loads`-es a WHOLE collection on every call; only
`db.get_collection_item` is an indexed single-row lookup. A `list_collection` inside a loop whose
iterable is itself a collection is therefore quadratic — and because both sides grow together, it is
invisible in testing and arrives all at once when the data does.

── Why this exists ──────────────────────────────────────────────────────────────────────────────

On 2026-09-02 alone, main took FOUR fixes for this one shape, from two people who found it
independently:

    #150  the AHU board read six collections per unit          0.06 s at 10 units, 1.98 s at 100
    #162  a name -> department map rebuilt per contract        622.7 ms -> 9.2 ms, 251 reads -> 1
    #204  the whole attendance table on every sign-in
    #209  once per activity, again per node it recursed into   26 M reads -> 9,600

Four in a day is not four accidents; it is a shape the codebase invites. This finds it in seconds.

── The important limitation: this is a FINDER, not a GATE ───────────────────────────────────────

**It cannot see its own fix.** The usual repair is to hoist the expensive call out of the loop and
pass the result in — after which the helper is STILL CALLED inside the loop and simply stops doing
the expensive thing. The scan reports identically before and after. That happened with #162: the
report stayed at four hits while the endpoint went from 251 reads to 1.

So a hit here means "go and look", never "this is broken", and a still-red scan is NOT evidence a
fix failed. Do not wire this into CI as a pass/fail check — it would fail forever on correct code.

What CAN confirm a fix is a test that COUNTS the reads. `tests/test_ahu_board_cost.py` and
`tests/test_employee_map_cost.py` are the two worked examples: they monkeypatch the db function,
assert the same call count at 4 rows as at 24, and were mutation-checked before being trusted.

── How it works ─────────────────────────────────────────────────────────────────────────────────

Two passes, because the defect usually hides one call deep. #150 was not a bare `list_collection`
in a loop — it was `ahu.load_ctx(uid)`, which reads six of them. So the scan first works out which
functions are expensive (transitively, to a fixpoint), then flags loops over a collection that call
any of them.

It over-reports on purpose: a loop over a fixed six-element list will show up. Over-reporting costs
a glance; under-reporting is what let this ship four times.
"""
import ast
import sys

# Functions that read a WHOLE table or collection. get_collection_item is deliberately absent — it
# is an indexed single-row lookup and is the right thing to call in a loop.
WHOLE_READS = {"list_collection", "list_employees", "list_attendance"}


def _call_name(node):
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _first_arg(node):
    if node.args and isinstance(node.args[0], ast.Constant):
        return str(node.args[0].value)
    return "?"


def expensive_functions(trees):
    """Every function that reads a whole collection, directly or through anything it calls."""
    funcs = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls, reads = set(), 0
            for sub in ast.walk(node):
                if sub is node:
                    continue
                nm = _call_name(sub)
                if nm is None:
                    continue
                if nm in WHOLE_READS:
                    reads += 1
                calls.add(nm)
            # A method and a module function can share a name. Merging them over-reports and never
            # under-reports, and under-reporting is the failure that matters here.
            f = funcs.setdefault(node.name, {"calls": set(), "reads": 0})
            f["calls"] |= calls
            f["reads"] += reads

    expensive = {n for n, f in funcs.items() if f["reads"]}
    while True:                                   # fixpoint: callers of expensive things are too
        grown = {n for n, f in funcs.items() if n not in expensive and (f["calls"] & expensive)}
        if not grown:
            return expensive
        expensive |= grown


def scan(paths):
    trees = {}
    for p in paths:
        try:
            trees[p] = ast.parse(open(p).read())
        except (SyntaxError, OSError) as exc:
            print("!! could not read %s: %s" % (p, exc))
    expensive = expensive_functions(trees)

    total = 0
    for path, tree in trees.items():
        stack = []

        class V(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_For(self, node):
                nonlocal total
                outer = _call_name(node.iter)
                if outer not in WHOLE_READS:
                    self.generic_visit(node)
                    return
                inner = {}
                for sub in ast.walk(node):
                    if sub is node.iter:
                        continue
                    nm = _call_name(sub)
                    if nm and (nm in WHOLE_READS or nm in expensive):
                        inner.setdefault(nm, sub.lineno)
                if inner:
                    total += 1
                    print("%s:%d  %s()" % (path, node.lineno,
                                           stack[-1] if stack else "<module>"))
                    print("    loops over %s(%s)" % (outer, _first_arg(node.iter)))
                    for nm, ln in sorted(inner.items(), key=lambda kv: kv[1]):
                        kind = "whole-collection read" if nm in WHOLE_READS else "expensive helper"
                        print("    L%-7d %-30s %s" % (ln, nm + "()", kind))
                self.generic_visit(node)

        V().visit(tree)

    print("\n%d loop(s) doing collection-scale work per iteration." % total)
    if total:
        print("A hit is 'go and look', NOT 'this is broken' — and a hit that REMAINS after a fix is\n"
              "expected, because hoisting the call out leaves it called in the loop. Confirm any fix\n"
              "with a test that counts the reads (see tests/test_ahu_board_cost.py).")
    # Always 0: this reports, it does not judge. Wiring it into CI as pass/fail would fail forever
    # on correct code, for the reason printed above.
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(scan(args))
