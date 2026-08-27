#!/usr/bin/env node
//
// Vietnamese translation checks for templates/index.html.
//
//   node tools/i18n/check.js dups      duplicate keys — the one failure that loses work SILENTLY
//   node tools/i18n/check.js quality   mechanical translation defects
//   node tools/i18n/check.js terms     terminology consistency across the dictionary
//   node tools/i18n/check.js all       all three
//
// `dups` exits non-zero and is wired into CI. The other two are advisory: they report things a
// human has to judge, and a gate that cries wolf is a gate people learn to skip.
//
// What none of this can tell you: whether a string reaches the screen at all. The DOM-walk
// translates text nodes plus title/aria-label/alt/placeholder; anything built some other way needs
// checking in a browser with the language switched. Coverage measured only from source has been
// wrong here before — 826 strings built from JS `label:` / `options:` / `toast()` properties were
// invisible to four separate source scans that all agreed with each other.
const { load } = require('./vi.js');

const VN = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;

function dups(entries) {
  const seen = new Map(); const found = [];
  for (const e of entries) {
    if (seen.has(e.key)) found.push({ key: e.key, first: seen.get(e.key), dup: e });
    else seen.set(e.key, e);
  }
  console.log('entries ' + entries.length + '   unique ' + seen.size + '   duplicates ' + found.length);
  for (const d of found) {
    const same = d.first.val === d.dup.val;
    console.log('  line ' + d.first.line + ' -> ' + d.dup.line + '  ' + JSON.stringify(d.key));
    console.log('      ' + (same ? 'same value — one is redundant' : 'DIFFERENT values, the later one silently wins:'));
    if (!same) {
      console.log('      kept:    ' + JSON.stringify(d.dup.val));
      console.log('      LOST:    ' + JSON.stringify(d.first.val));
    }
  }
  if (found.length) {
    console.log('\nA duplicate key is last-wins with no parse error and a diff that shows only');
    console.log('additions, so the damage is to a translation nobody touched. Remove one copy.');
  }
  return found.length;
}

function quality(entries) {
  const out = {};
  const add = (b, s) => (out[b] = out[b] || []).push(s);
  for (const { key: k, val: v, line } of entries) {
    if (v === k && /[A-Za-z]{3}/.test(k) && !/^[A-Z0-9_.\-\/ &]+$/.test(k) && k.split(/\s+/).length > 1)
      add('identical to English (renders English)', line + '  ' + JSON.stringify(k));
    // whitespace is load-bearing: these keys get concatenated into a sentence
    if (/^\s/.test(k) !== /^\s/.test(v)) add('leading space differs', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v));
    if (/\s$/.test(k) !== /\s$/.test(v)) add('TRAILING space differs', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v));
    for (const ch of [':', '…', '—', '·', '?']) {
      if (k.trim().endsWith(ch) !== v.trim().endsWith(ch)) { add('trailing "' + ch + '" differs', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v)); break; }
    }
    for (const ch of ['₫', '%']) {
      const a = (k.split(ch).length - 1), b = (v.split(ch).length - 1);
      if (a !== b) { add('symbol "' + ch + '" count differs', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v)); break; }
    }
    // NOT a raw paren count: English marks plurals "(s)" and Vietnamese does not inflect, so
    // dropping it is correct. Counting parens made this 90% false positives, which hid the rest.
    const parens = (k.match(/\(([^)]{2,})\)/g) || []).filter(p => !/^\((s|es|ies|s\/n)\)$/i.test(p));
    if (parens.length && !/[()]/.test(v)) add('parenthetical dropped (often fine — absorbed)', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v));
    if (v !== k && !VN.test(v) && /[A-Za-z]{3}/.test(v) && v.trim().split(/\s+/).length > 2)
      add('no Vietnamese diacritics (>2 words)', line + '  ' + JSON.stringify(k) + ' -> ' + JSON.stringify(v));
    const leftover = (v.match(/\b(the|and|of|with|for|from|this|that|which|when|your|their|been|will|not)\b/gi) || []);
    if (VN.test(v) && leftover.length >= 2) add('English words inside the Vietnamese', line + '  ' + JSON.stringify(v.slice(0, 76)));
  }
  // one Vietnamese string serving several English keys: usually harmless casing variants, but this
  // is where a genuine two-sense word shows up as one translation covering both senses
  const byVal = new Map();
  for (const e of entries) { if (!VN.test(e.val)) continue; if (!byVal.has(e.val)) byVal.set(e.val, []); byVal.get(e.val).push(e.key); }
  for (const [v, ks] of byVal)
    if (ks.length > 2 && v.length > 12)
      add('one Vietnamese for ' + ks.length + ' English keys', JSON.stringify(v.slice(0, 44)) + '  <- ' + ks.slice(0, 4).map(x => JSON.stringify(x.slice(0, 24))).join(', '));

  let total = 0;
  for (const [b, list] of Object.entries(out)) {
    console.log('\n=== ' + b + ' — ' + list.length + ' ===');
    list.slice(0, 25).forEach(x => console.log('  ' + x));
    if (list.length > 25) console.log('  ... and ' + (list.length - 25) + ' more');
    total += list.length;
  }
  console.log('\nentries checked: ' + entries.length + '   findings: ' + total + '  (advisory — read them, most are fine)');
  return 0;
}

// [English term, Vietnamese renderings that count as consistent]
const TERMS = [
  ['deliverable', ['sản phẩm']], ['revision', ['phiên bản']], ['gate', ['cổng']],
  ['overtime', ['làm thêm']], ['baseline', ['mốc chuẩn']], ['stakeholder', ['bên liên quan']],
  ['milestone', ['cột mốc', 'mốc']], ['contractor', ['nhà thầu']], ['tender', ['thầu']],
  ['estimate', ['dự toán', 'ước tính']], ['margin', ['tỷ suất', 'biên lợi nhuận']],
  ['mark-up', ['cộng giá', 'cộng thêm']], ['retention', ['giữ lại', 'lưu']],
  ['severance', ['trợ cấp thôi việc']], ['probation', ['thử việc']],
  ['transmittal', ['phiếu chuyển']], ['discipline', ['bộ môn']],
  ['calibration', ['hiệu chuẩn', 'hiệu chỉnh', 'đối chiếu']], ['hold point', ['điểm dừng']],
];
function terms(entries) {
  let flagged = 0;
  for (const [term, ok] of TERMS) {
    const re = new RegExp('\\b' + term.replace(/[-\s]/g, '[-\\s]') + '\\b', 'i');
    const hits = entries.filter(e => re.test(e.key));
    if (!hits.length) continue;
    const bad = hits.filter(e => !ok.some(o => e.val.toLowerCase().includes(o.toLowerCase())));
    if (!bad.length) continue;
    flagged += bad.length;
    console.log('\n=== "' + term + '" — ' + bad.length + ' of ' + hits.length + ' use none of [' + ok.join(' | ') + '] ===');
    bad.slice(0, 8).forEach(e => console.log('   ' + e.line + '  ' + JSON.stringify(e.key.slice(0, 42)) + ' -> ' + JSON.stringify(e.val.slice(0, 46))));
    if (bad.length > 8) console.log('   ... and ' + (bad.length - 8) + ' more');
  }
  if (!flagged) console.log('every term renders consistently');
  else console.log('\n' + flagged + ' flagged (advisory — a word with two real senses SHOULD differ; check the call site)');
  return 0;
}

const { entries, block } = load();
const cmd = process.argv[2] || 'all';
let code = 0;
if (cmd === 'dups' || cmd === 'all') { console.log('=== duplicate keys (_VI lines ' + block.startLine + '..' + block.endLine + ') ==='); code |= dups(entries) ? 1 : 0; }
if (cmd === 'quality' || cmd === 'all') { console.log('\n=== quality ==='); quality(entries); }
if (cmd === 'terms' || cmd === 'all') { console.log('\n=== terminology ==='); terms(entries); }
if (!['dups', 'quality', 'terms', 'all'].includes(cmd)) { console.error('usage: check.js [dups|quality|terms|all]'); process.exit(2); }
process.exit(code);
