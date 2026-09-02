/* Nothing on the boot path comes from someone else's server.
 *
 * Every asset the browser needs before the app is usable now comes from our own origin. That is a
 * speed property first — a third-party asset costs a DNS lookup, a TCP connection and a TLS handshake
 * to an origin the browser has no connection to yet, before a single byte of the thing arrives — but
 * it is also an availability one. Vietnam is the network these people are actually on, and unpkg.com
 * or fonts.gstatic.com being slow, throttled or blocked used to mean the brand font never arrived and
 * the map silently never worked.
 *
 * Two things were moved and both are easy to put back by accident, because pasting a CDN <link> is
 * how everyone adds a library:
 *   1. Poppins came from Google — a request to fonts.googleapis.com for the CSS, and only once that
 *      arrived could the browser learn the font URLs and open a SECOND connection to a SECOND origin.
 *      Two sequential round trips before any text could be drawn in the brand face.
 *   2. Leaflet came from unpkg.com on EVERY page load — 147 KB of JS and 15 KB of CSS for a map that
 *      only the GPS check-in screen opens.
 *
 * This file fails if either comes back, and it checks the things that make the replacement actually
 * work rather than just look right: the files exist, the server names their type, the CSP no longer
 * stands open for origins nothing uses, and the service worker caches the right subset.
 *
 *   node tests/boot_no_third_party.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(ROOT, 'app.py'), 'utf8');
const sw = fs.readFileSync(path.join(ROOT, 'static', 'sw.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* Everything the parser acts on before the app runs. Comments are stripped FIRST: this change left
   long explanations behind naming the very origins it removed, and a test that greps the raw text
   would read its own documentation as a regression. */
const head = src.slice(0, src.indexOf('</head>')).replace(/<!--[\s\S]*?-->/g, '');

// ══ 1. no third-party asset on the boot path ═══════════════════════════════════════════════════
console.log('\nEvery boot asset is ours\n');
{
  const ext = [...head.matchAll(/<(?:link|script)\b[^>]*\b(?:href|src)="(https?:\/\/[^"]+)"/g)].map(m => m[1]);
  ok('the document head loads nothing from another origin', ext.length === 0,
     'found: ' + ext.join(', ') + ' — each one is a DNS lookup, a TCP connection and a TLS ' +
     'handshake to a host the browser has no connection to yet');

  /* Deliberately the WHOLE file, not just the head: a <script src> for a library can sit anywhere,
     and Leaflet's was at line 3292, far below </head>. */
  const tags = [...src.matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)].map(m => m[1]);
  ok('every <script src> in the whole file is same-origin',
     tags.every(u => u.startsWith('/')),
     'found: ' + tags.filter(u => !u.startsWith('/')).join(', '));
  ok('and Leaflet is not one of them — it loads only when a map opens',
     !tags.some(u => /leaflet/i.test(u)),
     'a <script> tag for Leaflet is 147 KB downloaded and parsed by every session, including the ' +
     'ones that never open a map');
}

// ══ 2. the font is really vendored, not just re-pointed ════════════════════════════════════════
console.log('\nThe brand font is served from here\n');
{
  const faces = [...src.matchAll(/@font-face\{[^}]*\}/g)].map(m => m[0]).filter(f => /Poppins/i.test(f));
  ok('the Poppins @font-face rules are inline, so there is no CSS round trip', faces.length > 0,
     'a separate stylesheet would put back a request that has to complete before the font URL is ' +
     'even known');
  ok('every one of them points at our own origin',
     faces.length > 0 && faces.every(f => /url\(\/static\/vendor\/fonts\//.test(f)),
     faces.filter(f => !/url\(\/static\/vendor\/fonts\//.test(f)).join('\n'));
  ok('they swap rather than hiding text while the font loads',
     faces.every(f => /font-display:\s*swap/.test(f)),
     'without swap the browser blanks the text for up to 3s waiting for the font');
  /* unicode-range is what keeps this CHEAPER than what it replaced: the browser fetches only the
     subset the page's characters need, so a page of Latin text never pays for latin-ext. */
  ok('and each keeps its unicode-range, so only the needed subset is fetched',
     faces.every(f => /unicode-range:/.test(f)),
     'without it the browser downloads every vendored file regardless of what is on screen');

  /* A @font-face pointing at a file that is not there does not error — it renders the fallback and
     says nothing. The only way to know is to look for the file. */
  const missing = faces
    .map(f => (/url\((\/static\/vendor\/fonts\/[^)]+)\)/.exec(f) || [])[1])
    .filter(Boolean)
    .filter(u => !fs.existsSync(path.join(ROOT, u.replace(/^\//, ''))));
  ok('and every referenced file actually exists on disk', missing.length === 0,
     'missing: ' + missing.join(', ') + ' — a @font-face with no file silently renders the fallback');

  ok('the two weights the page preloads are among them',
     /rel="preload"[^>]*poppins-400-latin\.woff2/.test(head) &&
     /rel="preload"[^>]*poppins-600-latin\.woff2/.test(head));
  ok('devanagari is not vendored — 192 KB this app never renders',
     !fs.readdirSync(path.join(ROOT, 'static/vendor/fonts')).some(f => /devanagari/.test(f)));
}

// ══ 3. the server describes the font correctly ═════════════════════════════════════════════════
console.log('\nThe server names the type and does not re-compress it\n');
{
  ok('.woff2 has a real MIME type', /"\.woff2":\s*"font\/woff2"/.test(app),
     'served as application/octet-stream, `<link rel=preload as=font>` is a type mismatch and the ' +
     'browser discards the preload and fetches the file a second time');
  const gz = /GZIP_TYPES = \(([^)]*)\)/.exec(app);
  ok('and it is NOT gzipped', gz && !/font\//.test(gz[1]),
     'GZIP_TYPES: ' + (gz && gz[1]) + ' — woff2 is Brotli-compressed internally, so gzipping it ' +
     'spends CPU to make the file slightly bigger');
}

// ══ 4. the CSP stops standing open for origins nothing uses ════════════════════════════════════
console.log('\nAnd the allow-list shrank to match\n');
{
  const csp = /_CSP = \(([\s\S]*?)\n\)/.exec(app);
  const body = (csp ? csp[1] : '').replace(/#[^\n]*/g, '');   // strip comments — they name the removed origins
  ['unpkg.com', 'fonts.googleapis.com', 'fonts.gstatic.com'].forEach(o => {
    ok('the CSP no longer allows ' + o, !body.includes(o),
       'nothing loads from it any more, and an allow-listed origin nobody uses is standing ' +
       'permission for injected markup to fetch from somewhere we do not control');
  });
  ok('the origins still in use are untouched',
     body.includes('login.microsoftonline.com') && body.includes('graph.microsoft.com') &&
     body.includes('nominatim.openstreetmap.org'),
     'sign-in, Graph and the geocoder still need theirs');
}

// ══ 5. the service worker caches the right subset ══════════════════════════════════════════════
console.log('\nThe offline cache holds the font, not the map\n');
{
  const shell = /const SHELL = \[([\s\S]*?)\];/.exec(sw);
  const list = shell ? shell[1].replace(/\/\/[^\n]*/g, '') : '';
  ok('the preloaded weights are precached, so the brand font survives offline',
     /poppins-400-latin\.woff2/.test(list) && /poppins-600-latin\.woff2/.test(list),
     'SHELL: ' + list.replace(/\s+/g, ' ').trim());
  ok('Leaflet is NOT precached',
     !/leaflet/i.test(list),
     'precaching it would put back exactly the boot cost that loading it on demand removed');
}

// ══ 6. the map still has a way to get its library ══════════════════════════════════════════════
console.log('\nAnd a map that is opened still gets one\n');
{
  ok('there is an on-demand loader', /function _tkLoadLeaflet\(\)/.test(src));
  ok('it fetches both the script and the stylesheet',
     /_tkLoadLeaflet[\s\S]{0,900}\/static\/vendor\/leaflet\/leaflet\.js/.test(src) &&
     /_tkLoadLeaflet[\s\S]{0,900}\/static\/vendor\/leaflet\/leaflet\.css/.test(src),
     'Leaflet without its stylesheet stacks every tile at the origin — it looks broken, not unstyled');
  ok('and the map init awaits it instead of giving up',
     /if \(!\(await _tkLoadLeaflet\(\)\)\) return;/.test(src),
     'the old line was `if (typeof L === \'undefined\') return;` — with no <script> tag left, that ' +
     'is a map that never loads');
  /* The stylesheet asks for images/ RELATIVE to itself, so the vendored copy has to keep Leaflet's
     own folder layout or every default marker 404s. */
  ['leaflet.js', 'leaflet.css', 'images/marker-icon.png', 'images/layers.png'].forEach(f => {
    ok('vendored: ' + f, fs.existsSync(path.join(ROOT, 'static/vendor/leaflet', f)));
  });
}

// ══ 7. and nothing invisible is downloaded ═════════════════════════════════════════════════════
console.log('\nA hidden image is not downloaded\n');
{
  /* `display:none` on an <img> does NOT stop the fetch — only a CSS background on a hidden element is
     skipped. The collapsed-sidebar mark is 228 KB, sits ~94 KB into the document so the preload
     scanner queues it AHEAD of the vendor JS and the login photo, and is only ever seen after sign-in
     AND after the sidebar is collapsed, drawn at 34px. */
  const marks = [...src.matchAll(/<img[^>]*class="sidebar-logo-mark"[^>]*>/g)].map(m => m[0]);
  ok('the collapsed-sidebar mark is in the page', marks.length === 1,
     'found ' + marks.length);
  ok('and it carries no src at boot', marks.length === 1 && !/\ssrc=/.test(marks[0]),
     marks[0] + ' — display:none does not suppress the fetch, so a src here is 228 KB every session');
  ok('it holds the URL in data-src instead', marks.length === 1 && /data-src="\/static\/brand\//.test(marks[0]));
  /* Read toggleSidebar's OWN BODY. A "_sbMarkSrc appears within N characters of toggleSidebar"
     regex is the same loose proximity check that let a dropped SRI pin through elsewhere in this
     change — it passes on any nearby mention and needs its N tuned every time the function grows. */
  const tsAt = src.indexOf('function toggleSidebar() {');
  const tsBody = tsAt < 0 ? '' : src.slice(tsAt, src.indexOf('\nfunction ', tsAt + 10));
  ok('and something assigns it when the sidebar collapses',
     /function _sbMarkSrc\(\)/.test(src) && /m\.src = m\.dataset\.src;/.test(src) &&
     /_sbMarkSrc\(\)/.test(tsBody),
     'toggleSidebar body:\n' + tsBody.slice(0, 400) +
     '\n        without the call the mark is permanently blank once collapsed');
  /* The letterhead reads querySelector('.sidebar-logo img').src — the FIRST match. That must still be
     the full logo, which is why .sidebar-logo-full has to stay ahead of the mark in the DOM. */
  /* Both indexes have to be FOUND before comparing them. A bare `indexOf(a) < indexOf(b)` is true
     whenever `a` is missing, because indexOf returns -1 — so this passed when the mutation renamed
     .sidebar-logo-full out of the file entirely, which is the exact breakage it exists to catch. */
  /* Match the <img> TAGS, not the bare class names. Both names also appear in CSS rules near the top
     of the file, so `indexOf('sidebar-logo-full')` found a STYLESHEET SELECTOR at ~line 60 and
     compared that — it stayed green when the mutation renamed the actual <img> away, because the
     thing it was measuring was never the img at all. */
  const tagAt = (cls) => {
    const m = new RegExp('<img[^>]*class="' + cls + '"').exec(src);
    return m ? m.index : -1;
  };
  const iFull = tagAt('sidebar-logo-full'), iMark = tagAt('sidebar-logo-mark');
  ok('the full logo <img> still precedes the mark, so the letterhead keeps picking it',
     iFull >= 0 && iMark >= 0 && iFull < iMark,
     'full <img> at ' + iFull + ', mark <img> at ' + iMark +
     ' (-1 means the tag is missing) — _lhLogo reads querySelector(\'.sidebar-logo img\').src, the ' +
     'FIRST match, so if the mark comes first the letterhead gets an image with no src');
}

// ══ the service worker must not download the shell a second time ═══════════════════════════════
console.log('\nInstalling the service worker revalidates; it does not re-download\n');
{
  /* Both 'reload' and 'no-cache' bypass a stale precache, which is why neither can simply be
     dropped. The difference is what an UNCHANGED file costs. With 'reload' a first visit fetched
     the 832 KB shell TWICE — once for the page, once for the install — and every deploy did it
     again, because activate() drops the old cache and CACHE bumps on every release. */
  ok('the precache uses a conditional request', /cache: 'no-cache'/.test(sw),
     "static/sw.js still installs with cache: 'reload', so every first visit and every deploy " +
     'downloads the whole shell a second time');
  ok('and it is not simply cacheless', !/cache: 'reload'/.test(sw),
     "'reload' is still in the file — if a second addAll kept it, the saving is only partial");
  ok('the shell is still precached at install', /SHELL\.map\(u => new Request\(u,/.test(sw),
     'the offline claim depends on this list being fetched at install');
  ok("and '/' is still in that list", /const SHELL = \['\/'/.test(sw),
     'without the document itself the PWA cannot open offline');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
