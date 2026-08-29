// Locate and parse the _VI dictionary out of static/i18n/vi.js.
//
// It used to live inline in templates/index.html and was moved out: 145 KB gzipped, ~12% of the boot
// document, built on every load for an app whose default language is English.
//
// _VI mixes '...' and "..." quoting and carries comments between entries, so a regex over lines
// mis-parses it — this walks the object literal properly and keeps each entry's source line.
// Resolves the repo from this file's own location, so it works from the main checkout or any
// worktree without arguments.
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const INDEX = path.join(REPO, 'static', 'i18n', 'vi.js');

function extractBlock(src) {
  const lines = src.split('\n');
  const start = lines.findIndex(l => l === 'window._VI = {');
  if (start < 0) throw new Error('could not find "window._VI = {" in static/i18n/vi.js');
  let end = -1;
  for (let i = start + 1; i < lines.length; i++) if (lines[i] === '};') { end = i; break; }
  if (end < 0) throw new Error('could not find the end of the _VI object literal');
  return { text: lines.slice(start, end + 1).join('\n'), startLine: start + 1, endLine: end + 1 };
}

function parseVI(src) {
  const i0 = src.indexOf('{');
  let i = i0 + 1; const out = []; const n = src.length;
  const skipWs = () => {
    while (i < n) {
      const c = src[i];
      if (c === ' ' || c === '\n' || c === '\t' || c === '\r') { i++; continue; }
      if (c === '/' && src[i + 1] === '*') { i = src.indexOf('*/', i + 2) + 2; continue; }
      if (c === '/' && src[i + 1] === '/') { i = src.indexOf('\n', i) + 1; continue; }
      break;
    }
  };
  const readStr = () => {
    const q = src[i];
    if (q !== '"' && q !== "'" && q !== '`') throw new Error('expected a string at offset ' + i + ' near: ' + src.slice(i - 50, i + 50));
    i++; let s = '';
    while (i < n) {
      const c = src[i];
      if (c === '\\') { s += c + src[i + 1]; i += 2; continue; }
      if (c === q) { i++; break; }
      s += c; i++;
    }
    return { val: s, q };
  };
  while (i < n) {
    skipWs();
    if (src[i] === '}') break;
    const line = src.slice(0, i).split('\n').length;
    const k = readStr();
    skipWs();
    if (src[i] !== ':') throw new Error('expected ":" at offset ' + i);
    i++; skipWs();
    const v = readStr();
    out.push({ key: k.val, val: v.val, kq: k.q, vq: v.q, line });
    skipWs();
    if (src[i] === ',') i++;
  }
  return out;
}

// Turn the source-level escaping back into what the DOM actually carries. Comparing an escaped
// key against real DOM text is how a present, well-formed entry gets reported as missing.
function unescape(s) {
  return s
    .replace(/\\u([0-9a-fA-F]{4})/g, (m, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\(['"\\nt])/g, (m, c) => ({ "'": "'", '"': '"', '\\': '\\', n: '\n', t: '\t' }[c]));
}

function load() {
  const src = fs.readFileSync(INDEX, 'utf8');
  const block = extractBlock(src);
  const raw = parseVI(block.text);
  // block.startLine is where "window._VI = {" sits; entry lines are relative to the block
  const entries = raw.map(e => ({
    key: unescape(e.key),
    val: unescape(e.val),
    rawKey: e.key,
    rawVal: e.val,
    line: block.startLine + e.line - 1,
  }));
  return { entries, block, src, indexPath: INDEX, repo: REPO };
}

module.exports = { load, parseVI, unescape, extractBlock, REPO, INDEX };
