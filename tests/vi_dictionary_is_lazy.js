/* The Vietnamese dictionary is not part of what the app downloads to start.
 *
 * It used to be a 444 KB object literal inline in templates/index.html — 145 KB gzipped, about 12% of
 * everything a browser downloaded to show a login screen — and it was constructed on every boot,
 * including for the English users who are the default and who never read a key of it.
 *
 * It lives in static/i18n/vi.js now and is fetched the first time the UI is actually Vietnamese.
 *
 * The mechanism is small and easy to break by accident:
 *   · index.html declares `var _VI = {}`. It must stay `var`, because a top-level `var` IS a window
 *     property — that is the only reason vi.js assigning `window._VI = {...}` reaches the same
 *     binding every `_VI[key]` lookup already reads. `let` or `const` here silently breaks it: the
 *     assignment lands on window, the lookups keep reading the empty placeholder, and every screen
 *     stays English with no error anywhere.
 *   · an unloaded dictionary must DEGRADE, not throw. _t() returns the English key on a miss, which
 *     is what a missing translation has always done. A throw here would leave a blank panel, which
 *     this codebase has shipped before without anyone reporting it.
 *
 *   node tests/vi_dictionary_is_lazy.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
const VI_PATH = path.join(ROOT, 'static', 'i18n', 'vi.js');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

// ══ 1. it is out of the boot document ══════════════════════════════════════════════════════════
console.log('\nThe dictionary is not in the boot document\n');
{
  ok('index.html no longer carries the literal',
     !/\bconst _VI\s*=\s*\{[\s\S]{2000}/.test(src),
     'a 444 KB object literal is back inline, and every English boot pays for it again');
  /* Size is the whole point, so measure it rather than trusting that the literal is gone. Anything
     near the old 3.97 MB means the dictionary — or something the size of it — is back. */
  const mb = Buffer.byteLength(src) / 1048576;
  ok('and the document is meaningfully smaller for it', mb < 3.8,
     'templates/index.html is ' + mb.toFixed(2) + ' MB; it was 3.97 MB with the dictionary inline');
  ok('the dictionary file exists', fs.existsSync(VI_PATH));
}

// ══ 2. the binding mechanism ═══════════════════════════════════════════════════════════════════
console.log('\nvi.js can actually reach the lookups\n');
{
  ok('index.html declares the placeholder with var, not let/const',
     /^var _VI = \{\};$/m.test(src),
     'a top-level `var` IS a window property. With `let` or `const`, vi.js assigning window._VI ' +
     'lands somewhere the _VI[key] lookups never read — every screen stays English, silently');
  const vi = fs.readFileSync(VI_PATH, 'utf8');
  ok('and vi.js assigns through window', /^window\._VI = \{/m.test(vi),
     'assigning a bare `_VI` inside vi.js would create its own binding and change nothing here');
  ok('the file parses', (() => {
    try { new Function('window', vi)({}); return true; } catch (e) { return 'threw: ' + e.message; }
  })() === true);
  /* Run it for real and count. A file that parses but yields an empty object would satisfy every
     assertion above while translating nothing. */
  const w = {};
  new Function('window', vi)(w);
  ok('and yields a dictionary with the whole catalogue in it',
     w._VI && Object.keys(w._VI).length > 5000,
     'got ' + (w._VI ? Object.keys(w._VI).length : 'no _VI') + ' keys');
}

// ══ 3. both ways into Vietnamese fetch it ══════════════════════════════════════════════════════
console.log('\nBoth entry points load it before translating\n');
{
  ok('there is a loader', /function _viLoad\(\)/.test(src));
  ok('it fetches the right file', /_viLoad[\s\S]{0,700}\/static\/i18n\/vi\.js/.test(src));

  const tsAt = src.indexOf('function tkSetLang(lang) {');
  const ts = tsAt < 0 ? '' : src.slice(tsAt, src.indexOf('\nfunction ', tsAt + 10));
  ok('tkSetLang waits for it before doing any work',
     /_viLoad\(\)/.test(ts) && /return;/.test(ts),
     'body:\n' + ts.slice(0, 300) + '\n        translating against an empty dictionary paints the ' +
     'screen English and leaves it there — the observer only reacts to CHANGES');
  /* Without a bound, a failed fetch recurses forever: the .then fires, the dictionary is still
     empty, and tkSetLang calls itself again. */
  ok('and it cannot loop forever when the fetch fails',
     /_viRetried/.test(ts) && /_viRetried = true;/.test(src) && /_viRetried = false;/.test(src),
     'body:\n' + ts.slice(0, 400));

  ok('a VN user landing on the app gets it too',
     /_initLang[\s\S]{0,400}_viLoad\(\)/.test(src),
     'otherwise the stored VN preference shows an English screen until something else asks');
}

// ══ 4. a missing dictionary degrades to English ════════════════════════════════════════════════
console.log('\nAnd without it, the app is English rather than broken\n');
{
  const tAt = src.indexOf('function _t(x) {');
  const t = tAt < 0 ? '' : src.slice(tAt, src.indexOf('\nfunction ', tAt + 10));
  ok('_t returns the key when the dictionary has no entry',
     /if \(_VI\[x\] && _VI\[x\] !== x\) return _VI\[x\];/.test(t),
     'a bare `return _VI[x]` would render undefined across the whole UI while the fetch is in flight');
  ok('and it is wrapped so a lookup can never throw a render away',
     /^\s*try \{/m.test(t) && /catch \(e\) \{ return x; \}/.test(t),
     'a render that throws in this app leaves an empty panel and reports nothing');

  /* Prove it rather than reading it: run _t with an empty dictionary and a VN language. */
  const runT = new Function(
    'var _VI = {};\n' +
    "var _LANG = { cur: 'vi' };\n" +
    'var _isDevHost = false; var _tMissWarned = new Set();\n' +
    t + '\nreturn _t;')();
  ok('proved: with an empty dictionary and lang=vi, _t returns English',
     runT('Settings') === 'Settings',
     'got ' + JSON.stringify(runT('Settings')));
}

// ══ 5. everything that reads the dictionary followed it ════════════════════════════════════════
console.log('\nEvery consumer follows it to the new file\n');
{
  /* I searched tests/ and missed tools/i18n/vi.js, which CI runs as a required check — it threw
     `could not find "const _VI = {" in templates/index.html` and failed the build. A dictionary this
     widely read has consumers outside the test folder, so scan the REPO, not one directory. */
  const walk = (dir, out) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === '.git' || e.name === 'node_modules' || e.name === 'static') continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p, out);
      else if (/\.(js|py)$/.test(e.name)) out.push(p);
    }
    return out;
  };
  const stale = walk(ROOT, [])
    .filter(p => p !== __filename)
    .filter(p => /const _VI\s*=\s*\{/.test(fs.readFileSync(p, 'utf8')))
    .map(p => path.relative(ROOT, p));
  ok('nothing still looks for the literal inside index.html', stale.length === 0,
     'these still hunt for `const _VI = {`: ' + stale.join(', ') +
     ' — they will either throw or, worse, quietly find nothing and assert against an empty string');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
