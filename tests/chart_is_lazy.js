/* Chart.js must not be on the boot path.
 *
 * It was a <script defer> in the document head, so every first visit downloaded 60 KB on the wire
 * — 200 KB decoded, and every byte parsed — before anybody had signed in, for a login screen that
 * has never contained a chart. Measured on production it was the second-largest thing after the
 * document itself.
 *
 * Making it lazy is easy; making it lazy WITHOUT silently losing charts is the whole job. Roughly
 * twenty chart builders in this file guard with `if (typeof Chart === 'undefined') return;` and
 * return quietly, so a naive change would have left blank canvases and nothing in the console.
 * Three things stop that, and this file holds all three:
 *
 *   1. the fetch starts the moment a session exists — long before any view with a canvas can be
 *      opened by hand;
 *   2. _mkChart, which 60 call sites go through, fetches and retries itself instead of returning;
 *   3. a failed load SETTLES, so a caller waiting on it is never left hanging and a later attempt
 *      can try again.
 *
 *   node tests/chart_is_lazy.js
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates', 'index.html'), 'utf8');
const sw = fs.readFileSync(path.join(root, 'static', 'sw.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

/* The <head> only — a match anywhere in a 4 MB file would also hit the loader's own src string,
   which is the thing we WANT, and the test would then pass on the bug it exists to catch. */
const head = html.slice(0, html.indexOf('</head>'));

console.log('\nNot on the boot path\n');

ok('no <script> tag pulls Chart.js at boot',
  !/<script[^>]+src="\/static\/vendor\/chart\.umd\.min\.js"/.test(html),
  'a defer tag still costs the download and the parse on a login screen');
ok('...and nothing preloads or prefetches it either',
  !/rel="(?:preload|prefetch|modulepreload)"[^>]*chart\.umd/.test(head) &&
  !/chart\.umd[^>]*rel="(?:preload|prefetch|modulepreload)"/.test(head),
  'a preload is the same bytes at the same moment under a different tag name');
ok('MSAL is still loaded up front — it is what signing in needs',
  /<script[^>]+src="\/static\/vendor\/msal-browser\.min\.js"/.test(html),
  'this test is about the chart library, not about stripping the boot to nothing');

console.log('\nStill pinned\n');

const sri = /const _CHART_SRI = '([^']+)'/.exec(html);
ok('the loader carries an integrity hash', !!sri && /^sha384-/.test(sri[1]),
  'a lazily injected script is exactly as pinnable as a static one, and this page signs payments');
ok('the loader actually applies it to the element',
  /el\.integrity = _CHART_SRI/.test(html));

console.log('\nCharts still appear\n');

const loader = html.slice(html.indexOf('function _chartJs()'),
                          html.indexOf('function _mkChart('));
ok('_chartJs is found where the rest of this file can see it', loader.length > 200,
  'marker moved — update this test, do NOT delete it');
ok('a successful load registers the plugins and the defaults',
  /_registerChartPlugins\(\)/.test(loader) && /_tuneChartDefaults\(\)/.test(loader),
  'these used to run off a poll; the load event is the one moment Chart is known to exist');
/* Read the onerror HANDLER, not 120 characters after the word. The catch block a few lines below
   also contains `_chartJsP = null; resolve(false);`, so the loose version matched that instead and
   two mutants — an onerror that never settles, and one that settles but caches the promise so
   nothing can ever retry — both survived it. */
const onerr = /el\.onerror = function \(\) \{([^}]*)\}/.exec(loader);
ok('the onerror handler was found', !!onerr, loader.slice(0, 200));
ok('A FAILED LOAD SETTLES', !!onerr && /resolve\(false\)/.test(onerr[1]),
  'a promise that never resolves leaves every _mkChart caller waiting for ever');
ok('...and clears the cached promise so a later chart can try again',
  !!onerr && /_chartJsP = null/.test(onerr[1]),
  'otherwise one failed load disables charts for the rest of the session');

const mk = html.slice(html.indexOf('function _mkChart('),
                      html.indexOf('function _mkChart(') + 1400);
ok('_mkChart fetches and retries instead of returning empty-handed',
  /typeof Chart === 'undefined'[\s\S]{0,220}_chartJs\(\)[\s\S]{0,120}_mkChart\(id, cfg, extra\)/.test(mk),
  'sixty call sites go through this one function; without the retry they render nothing, silently');
/* PRESENT *and* before. indexOf returns -1 for something that is not there at all, and -1 is
   less than every real position — so the first version of this passed when the a11y call was
   DELETED outright, which is the worst version of the bug it was written to catch. A mutant found
   it; an ordering assertion has to establish both operands exist. */
const iA11y = mk.indexOf('_a11yChart(ctx, cfg)');
const iLoad = mk.indexOf('_chartJs()');
ok('...and the accessible data table is still built first',
  iA11y >= 0 && iLoad >= 0 && iA11y < iLoad,
  'the numbers must reach a screen reader whether or not the library ever arrives ' +
  '(a11y at ' + iA11y + ', fetch at ' + iLoad + ')');

ok('the fetch starts as soon as there is a session',
  /_chartJs\(\)\.then\(function \(ok\) \{[\s\S]{0,220}initDashChart\(\)/.test(html),
  'so it is in flight long before a view with a canvas can be opened by hand');

console.log('\nThe old polling loop is gone\n');

ok('nothing polls for Chart on a 400 ms timer any more',
  !/_armChartTune/.test(html),
  'with a lazy library that poll never stops on a login screen — it just runs for ever');

console.log('\nAnd the service worker does not put the cost back\n');

const shell = /const SHELL = \[([\s\S]*?)\];/.exec(sw);
const list = shell ? shell[1].replace(/\/\/[^\n]*/g, '') : '';
ok('the SHELL list was found', !!shell, 'marker moved — update this test');
ok('Chart.js is not precached at install',
  !/chart\.umd\.min\.js/.test(list),
  'precaching downloads it at install time, which is the boot cost this change just removed — ' +
  'the same reason Leaflet is excluded, written in sw.js itself');
ok('MSAL and the two preloaded font weights still are',
  /msal-browser\.min\.js/.test(list) &&
  /poppins-400-latin\.woff2/.test(list) && /poppins-600-latin\.woff2/.test(list),
  'offline sign-in and the brand face are not what this change is trading away');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
