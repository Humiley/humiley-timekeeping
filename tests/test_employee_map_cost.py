"""Reading the employee table once per row is the same defect as reading a collection once per unit.

`_sales_may_write` resolves a document owner's department, and `_emp_id_for_resource` resolves a
name to an employee id. Both did it by reading the WHOLE employee table, once per row of whatever
register the caller was looping over.

Unlike the AHU board, connection reuse did not help this one: measured at 80 employees a
`list_employees()` costs ~3 ms and roughly 2.4 ms of that is Python building 80x53 dicts, not
anything SQLite or the connection does. Over a few hundred contracts it is most of a second spent
deriving the same map again and again.

These count CALLS, not seconds — the same instrument as tests/test_ahu_board_cost.py, and for the
same reason: a stopwatch passes on a fast machine with the bug still in place. It is also the only
instrument that works here, because the static scanner that found this cannot see the fix (the
helper is still called inside the loop; it just no longer does the expensive thing).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db     # noqa: E402


class _CountingEmployeeReads:
    """Counts db.list_employees() calls while the block runs."""

    def __enter__(self):
        self.n = 0
        self._real = db.list_employees

        def spy():
            self.n += 1
            return self._real()

        db.list_employees = spy
        return self

    def __exit__(self, *exc):
        db.list_employees = self._real
        return False


def _seed_contracts(n, prefix):
    """n ACTIVE contracts owned by somebody other than the caller, so the manager-scope branch —
    the one that reads the employee table — is the branch actually taken."""
    for i in range(n):
        db.put_collection_item("sales_contracts", {
            "id": "%s-c%d" % (prefix, i), "contractNo": "%s-%03d" % (prefix, i),
            "title": "Contract %d" % i, "accountName": "Some Customer",
            "owner": "Somebody Else", "status": "active",
            "value": 1000000, "retentionPct": 5})


def _seed_resources(n, prefix):
    """n project-resource rows carrying a NAME and no empId — the case that has to be resolved."""
    for i in range(n):
        db.put_collection_item("pm_resources", {
            "id": "%s-r%d" % (prefix, i), "projectId": "p1",
            "name": "Person %d" % i, "allocationPct": 50})


def test_the_retention_screen_reads_the_employee_table_a_bounded_number_of_times(api, tokens):
    """THE regression: the same number of employee reads at 4 contracts as at 24."""
    _seed_contracts(4, "empmap-a")
    with _CountingEmployeeReads() as small:
        st, _ = api("GET", "/api/sales/retention", tokens["mgr"])
    assert st == 200

    _seed_contracts(20, "empmap-b")
    with _CountingEmployeeReads() as large:
        st, _ = api("GET", "/api/sales/retention", tokens["mgr"])
    assert st == 200

    assert large.n == small.n, (
        "employee-table reads grew with the contract count: %d at 4 contracts, %d at 24"
        % (small.n, large.n))
    assert small.n <= 2, "expected the map to be built once per request, saw %d reads" % small.n


def test_the_labour_cost_screen_does_not_reread_the_roster_per_resource(api, tokens):
    """Same shape, different register: pm_resources rows resolved by name."""
    _seed_resources(4, "empmap-c")
    with _CountingEmployeeReads() as small:
        st, _ = api("GET", "/api/hr/labour-cost?period=2026-08", tokens["admin"])
    assert st == 200

    _seed_resources(20, "empmap-d")
    with _CountingEmployeeReads() as large:
        st, _ = api("GET", "/api/hr/labour-cost?period=2026-08", tokens["admin"])
    assert st == 200

    assert large.n == small.n, (
        "employee-table reads grew with the resource count: %d at 4 rows, %d at 24"
        % (small.n, large.n))


def test_resolving_a_name_still_gives_the_same_answer_as_the_scan_it_replaced(api, tokens):
    """The map is only worth having if it answers identically. Checked against the linear scan for
    every real employee, plus the two cases that are not a match at all."""
    import app
    idof = app.Handler._id_by_lower_name()
    for e in db.list_employees():
        row = {"name": e.get("name")}
        assert (app.Handler._emp_id_for_resource(row, idof)
                == app.Handler._emp_id_for_resource(row)), e.get("name")
    assert app.Handler._emp_id_for_resource({"name": "Nobody At All"}, idof) == ""
    assert app.Handler._emp_id_for_resource({"name": ""}, idof) == ""


def test_an_explicit_emp_id_still_wins_over_the_name(api, tokens):
    """empId is the authoritative field; the map is only the fallback for rows that lack one."""
    import app
    idof = app.Handler._id_by_lower_name()
    assert app.Handler._emp_id_for_resource({"empId": "HML-ADM", "name": "Nobody"}, idof) == "HML-ADM"


def test_the_owner_and_management_shortcuts_do_not_need_the_map_at_all(api, tokens):
    """Both return before the department lookup, so neither should touch the employee table —
    passing no map must not make them read one."""
    import app
    # A Handler without __init__: BaseHTTPRequestHandler's constructor serves a whole request, so
    # skipping it is the only way to exercise one method in isolation.
    h = object.__new__(app.Handler)
    mgmt = {"name": "Boss", "role": "manager", "level": "management"}
    staff = {"name": "Owner", "role": "staff", "level": "staff"}
    with _CountingEmployeeReads() as c:
        assert h._sales_may_write(mgmt, {"owner": "Anyone"}) is True
        assert h._sales_may_write(staff, {"owner": "Owner"}) is True
    assert c.n == 0, "a short-circuit path read the employee table anyway (%d reads)" % c.n
