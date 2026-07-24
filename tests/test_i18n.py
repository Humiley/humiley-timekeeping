"""EN ↔ VN localization gate for the single-file frontend.

Measures how many user-facing _t('literal') strings have a Vietnamese entry in the _VI dict and holds
a floor so coverage can never silently regress. (Actual coverage is ~99%.) A _VI key defined twice is
harmless — JS object literals are last-wins and the shadowed value is an equivalent spelling variant.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "templates", "index.html")

# Coverage floor: actual is ~99%; this guard fails the build if a change drops it meaningfully.
MIN_COVERAGE = 0.92


def _load():
    with open(HTML, encoding="utf-8") as f:
        return f.read()


def _vi_entries(src):
    """(key -> value) pairs from the _VI dict body, tolerating single/double quotes."""
    m = re.search(r"const _VI\s*=\s*\{", src)
    assert m, "could not locate the _VI dict"
    body = src[m.end():]
    pairs = []
    # 'key': 'value'  |  "key": "value"  (values may contain escaped quotes)
    for mm in re.finditer(r"""(['"])((?:\\.|(?!\1).)*?)\1\s*:\s*(['"])((?:\\.|(?!\3).)*?)\3""", body):
        pairs.append((mm.group(2), mm.group(4)))
    return pairs


def test_en_vn_coverage_floor():
    src = _load()
    vi_keys = {k for k, _ in _vi_entries(src)}
    # every _t('...') / _t("...") literal (skip _t2, dynamic _t(var), and template literals)
    strings = set()
    for mm in re.finditer(r"""\b_t\(\s*(['"])((?:\\.|(?!\1).)*?)\1\s*\)""", src):
        s = mm.group(2)
        if s and not s.isspace():
            strings.add(s)
    assert len(strings) > 200, "sanity: expected many translatable strings, found %d" % len(strings)
    covered = sum(1 for s in strings if s in vi_keys)
    coverage = covered / len(strings)
    assert coverage >= MIN_COVERAGE, (
        "EN/VN coverage %.1f%% (%d/%d) fell below the %.0f%% floor"
        % (coverage * 100, covered, len(strings), MIN_COVERAGE * 100)
    )
