"""The ledger summary read the whole package register once per subcontract certificate.

Found by tools/scan_read_cost.py within a minute of that tool existing — the fifth hit on a scan
whose other four were already known. Same shape as #150 and #162: a helper that reads a WHOLE
collection, called once per row of a loop over another collection.

These count READS, not milliseconds, for the reason the tool's own docstring gives: the scan cannot
confirm its own fix, because hoisting the call out leaves the helper still called inside the loop.
Only a count can tell a repaired loop from a broken one. A stopwatch would also pass on a fast
machine with the bug still in place.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db     # noqa: E402
import app    # noqa: E402


class _CountingReads:
    """Counts db.list_collection calls per collection while the block runs."""

    def __enter__(self):
        self.counts = {}
        self._real = db.list_collection

        def spy(coll):
            self.counts[coll] = self.counts.get(coll, 0) + 1
            return self._real(coll)

        db.list_collection = spy
        return self

    def __exit__(self, *exc):
        db.list_collection = self._real
        return False


def _seed_packages(n, prefix):
    for i in range(n):
        db.put_collection_item("pm_procurement", {
            "id": "%s-pkg-%d" % (prefix, i), "pkgNo": "%s-P%d" % (prefix, i),
            "projectId": prefix + "-proj", "discipline": "Mechanical",
            "vendor": "Vendor %d" % i})


def _certs(n, prefix):
    return [{"id": "%s-c%d" % (prefix, i), "pkgNo": "%s-P%d" % (prefix, i),
             "projectId": prefix + "-proj"} for i in range(n)]


def test_resolving_many_certificates_reads_the_register_once(api, tokens):
    """THE regression. Not "fewer reads" — the same count at 3 certificates as at 15, which is the
    only shape that stays flat as the month fills up."""
    _seed_packages(15, "glc")
    packages = app.Handler._gl_package_index()

    with _CountingReads() as small:
        for c in _certs(3, "glc"):
            app.Handler._gl_subcert_doc(app.Handler, c, packages)
    with _CountingReads() as large:
        for c in _certs(15, "glc"):
            app.Handler._gl_subcert_doc(app.Handler, c, packages)

    assert large.counts == small.counts, (
        "reads grew with the certificate count: %s at 3, %s at 15" % (small.counts, large.counts))
    assert small.counts.get("pm_procurement") is None, (
        "the index was passed in, so resolving must read pm_procurement zero times, saw %r"
        % small.counts.get("pm_procurement"))


def test_the_index_is_built_from_exactly_one_read(api, tokens):
    _seed_packages(4, "glc1")
    with _CountingReads() as c:
        app.Handler._gl_package_index()
    assert c.counts.get("pm_procurement") == 1, c.counts


def test_the_indexed_answer_is_identical_to_the_scan_it_replaces(api, tokens):
    """The whole fix rests on this: a faster route to the SAME document. If the two ever diverge,
    the ledger posts a different account than the single-document path would."""
    _seed_packages(6, "glc2")
    packages = app.Handler._gl_package_index()
    for c in _certs(6, "glc2"):
        assert (app.Handler._gl_subcert_doc(app.Handler, c, packages)
                == app.Handler._gl_subcert_doc(app.Handler, c)), c["pkgNo"]


def test_the_package_number_is_keyed_WITH_its_project(api, tokens):
    """A package number is only unique within its project. Keying on the number alone would attach
    one project's trade to another project's certificate — a WRONG ACCOUNT on a ledger posting, not
    a slow one, which is why this is the assertion that matters most here."""
    db.put_collection_item("pm_procurement", {
        "id": "glx-a", "pkgNo": "SHARED-1", "projectId": "proj-A",
        "discipline": "Mechanical", "vendor": "Vendor A"})
    db.put_collection_item("pm_procurement", {
        "id": "glx-b", "pkgNo": "SHARED-1", "projectId": "proj-B",
        "discipline": "Electrical", "vendor": "Vendor B"})
    packages = app.Handler._gl_package_index()

    a = app.Handler._gl_subcert_doc(app.Handler, {"pkgNo": "SHARED-1", "projectId": "proj-A"},
                                    packages)
    b = app.Handler._gl_subcert_doc(app.Handler, {"pkgNo": "SHARED-1", "projectId": "proj-B"},
                                    packages)
    assert a["discipline"] == "Mechanical", a
    assert b["discipline"] == "Electrical", b


def test_a_certificate_whose_package_is_missing_is_returned_UNCHANGED(api, tokens):
    """It carries no trade, and the journal posts to the default account and says so. Inventing a
    discipline here would put a made-up account on a ledger entry."""
    packages = app.Handler._gl_package_index()
    cert = {"id": "c-orphan", "pkgNo": "NO-SUCH-PKG", "projectId": "proj-Z"}
    assert app.Handler._gl_subcert_doc(app.Handler, cert, packages) == cert


def test_a_certificate_with_no_package_number_is_returned_unchanged(api, tokens):
    packages = app.Handler._gl_package_index()
    cert = {"id": "c-nopkg", "projectId": "proj-Z"}
    assert app.Handler._gl_subcert_doc(app.Handler, cert, packages) == cert


def test_the_single_document_path_still_works_with_no_index(api, tokens):
    """Every posting goes through it. The index is an optimisation for the summary and must never
    become mandatory."""
    _seed_packages(3, "glc3")
    out = app.Handler._gl_subcert_doc(app.Handler,
                                      {"pkgNo": "glc3-P1", "projectId": "glc3-proj"})
    assert out["discipline"] == "Mechanical"


def test_the_certificates_own_vendor_still_wins_over_the_packages(api, tokens):
    """Unchanged behaviour, asserted because the index rewrote the line that decides it."""
    _seed_packages(2, "glc4")
    packages = app.Handler._gl_package_index()
    out = app.Handler._gl_subcert_doc(
        app.Handler, {"pkgNo": "glc4-P0", "projectId": "glc4-proj", "vendor": "On the cert"},
        packages)
    assert out["vendor"] == "On the cert"
