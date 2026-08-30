# The orthography rule, applied to the WHOLE platform rather than one dictionary.
#
#   python3 tools/i18n/ortho-platform.py      exits non-zero if anything is found
#
# This does NOT replace tools/i18n/ortho-scan.js -- the two cover different blind spots and both
# are needed. ortho-scan.js reads templates/index.html and DECODES \uXXXX escapes, which is the
# only way to see _t2('Cancel', 'Hu\u1ef7'); this reads raw file text, so it cannot. In exchange
# it opens the other 47 files that carry Vietnamese, which ortho-scan.js never looks at -- the
# backend that writes VAT questions, credit-note statuses and HR decisions had been on the old
# spelling the entire time the JS gate was reporting the platform clean.
#
#   old style: mark on the SECOND vowel  -> hoá, khoá, xoá, thuỷ, luỹ, hoà, toà, khoẻ
#   new style: mark on the FIRST  vowel  -> hóa, khóa, xóa, thủy, lũy, hòa, tòa, khỏe
#
# Same three exclusions as tools/i18n/ortho-scan.js, and they matter as much here:
#   * "qu" is one onset digraph, so "quá" is correct either way
#   * the syllable must be OPEN -- "hoàn"/"toàn"/"khoán" are identical in both conventions
#   * the nucleus case ("của") cannot match, because this looks for a PLAIN o/u
#
# Also flags the four shapes a boundaryless rewrite produces, so a corrupted file can never
# read as clean.
import os, io, re, sys

SKIP = {'node_modules', '.git', '.next', '__pycache__', 'dist', 'build', 'venv', '.venv', '.claude'}
ACC = 'àáảãạèéẻẽẹỳýỷỹỵÀÁẢÃẠÈÉẺẼẸỲÝỶỸỴ'
OLD = re.compile('(?<![qQ])[ouOU][' + ACC + '](?![a-zà-ỹA-ZÀ-Ỹ])')
BAD = re.compile('hòan|tòan|khóan|súyt', re.I)
WORD = re.compile('[a-zà-ỹA-ZÀ-Ỹ]*$')

# vendored third-party bundles are not ours to restyle. The i18n tools themselves are excluded for
# a different reason: they have to CONTAIN both spellings -- style.js holds the old->new table and
# ortho-scan.js documents the rule with worked examples, including the corrupted "hòan" that a
# boundaryless rewrite produces. Flagging those is the scanner reading its own documentation.
VENDOR = re.compile(r'/vendor/|\.min\.js$|tools/i18n/(style|ortho-scan|consist|t2|integrity)\.js$|tools/i18n/ortho-platform\.py$')

total_old = 0
total_bad = 0
per_file = {}
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if not re.search(r'\.(py|js|json|html|md|ts|tsx|txt)$', f):
            continue
        p = os.path.join(root, f)
        if VENDOR.search(p.replace(os.sep, '/')):
            continue
        try:
            s = io.open(p, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        hits = {}
        for m in OLD.finditer(s):
            start = WORD.search(s[:m.start()]).group(0)
            w = start + m.group(0)
            ln = s[:m.start()].count('\n') + 1
            hits.setdefault(w, []).append(ln)
        bad = [(m.group(0), s[:m.start()].count('\n') + 1) for m in BAD.finditer(s)]
        if hits or bad:
            per_file[p] = (hits, bad)
            total_old += sum(len(v) for v in hits.values())
            total_bad += len(bad)

print('files with old-style or corrupted syllables: %d' % len(per_file))
print('old-style occurrences: %d    corrupted: %d\n' % (total_old, total_bad))
for p in sorted(per_file, key=lambda k: -sum(len(v) for v in per_file[k][0].values())):
    hits, bad = per_file[p]
    n = sum(len(v) for v in hits.values())
    print('  %-46s old=%-4d corrupted=%d' % (p, n, len(bad)))
    for w, lines in sorted(hits.items(), key=lambda kv: -len(kv[1]))[:8]:
        print('        %-10s x%-3d  lines %s' % (w, len(lines), ','.join(str(x) for x in lines[:6])))
    for w, ln in bad[:4]:
        print('        CORRUPT %s line %d' % (w, ln))
sys.exit(1 if per_file else 0)
