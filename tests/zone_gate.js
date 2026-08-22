/* A zone that is switched off must stop authorising check-in.
 *
 * The GPS Locations register has had an "Active" column and a "Department" select since it was
 * written, and _checkGeofence consulted neither — it looped every zone and matched on distance
 * alone. So an administrator could retire a decommissioned site, watch the row grey out, and have
 * that zone go on clearing punches; and a zone scoped to Factory authorised the whole company.
 *
 * The store side is tests/test_zone_controls.py. This is the GATE: the function that decides whether
 * somebody standing on a spot is at an approved site.
 *
 * Both fields DEFAULT OPEN — a missing `active` means on, a missing or 'All' dept means everybody —
 * because this migration lands on live zones. A default that closed would stop every check-in in the
 * company, which is exactly the kind of silent, total failure the audit that found this was for.
 *
 *   node tests/zone_gate.js
 */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const take = (mark, what) => {
  const i = src.indexOf(mark);
  if (i < 0) { console.error('Could not find ' + what + ' — update the marker, do NOT delete this test.'); process.exit(2); }
  const j = src.indexOf('\nfunction ', i + 10);
  if (j < 0) { console.error('Could not find the end of ' + what + '.'); process.exit(2); }
  return src.slice(i, j);
};

/* TK is the signed-in user. _checkGeofence falls back to it when the caller names no department, so
   the harness must provide one or the fallback throws instead of defaulting open. */
const F = new Function(
  'const TK = { user: { dept: "Engineering" } };\n' +
  take('function _haversineMetres(', '_haversineMetres') +
  take('function _zoneApplies(', '_zoneApplies') +
  take('function _checkGeofence(', '_checkGeofence') +
  '\nreturn { _zoneApplies, _checkGeofence };')();

// One zone, and a point 10 m from its centre — comfortably inside a 200 m radius.
const HQ = { name: 'HQ Tower', lat: 10.7769, lon: 106.7009, radius: 200 };
const AT = [10.77699, 106.70099];
const zone = extra => Object.assign({}, HQ, extra);
const at = (zones, dept) => F._checkGeofence(AT[0], AT[1], zones, dept);

console.log('\nA switched-off zone authorises nothing\n');

// -- the control that did nothing -----------------------------------------------------------------
ok('standing inside an active zone is in-zone', at([zone({ active: 1 })]).ok === true);
ok('standing inside a SWITCHED-OFF zone is not', at([zone({ active: 0 })]).ok === false,
   'this is the whole finding: the toggle greyed the row and changed no decision');
ok('and the off zone does not name itself on the punch', at([zone({ active: 0 })]).zone === null);

// -- defaults must stay open, because this lands on live data -------------------------------------
ok('a zone with no active field at all still authorises', at([zone({})]).ok === true,
   'every zone in production predates the column; a closed default would stop the company');
ok('active as the string "1" is honoured', at([zone({ active: '1' })]).ok === true);
ok('active as the string "0" is honoured', at([zone({ active: '0' })]).ok === false,
   'SQLite and JSON both round-trip these as strings often enough to matter');

// -- department scoping ---------------------------------------------------------------------------
console.log('\nA scoped zone applies to the department it names\n');
ok('an unscoped zone applies to everybody', at([zone({ dept: 'All' })], 'Factory').ok === true);
ok('a blank dept is the same as All', at([zone({ dept: '' })], 'Factory').ok === true);
ok('a zone scoped to my department applies to me', at([zone({ dept: 'Factory' })], 'Factory').ok === true);
ok('a zone scoped elsewhere does not', at([zone({ dept: 'Factory' })], 'Engineering').ok === false);
ok('the match is case- and space-insensitive',
   at([zone({ dept: ' factory ' })], 'Factory').ok === true,
   'departments are typed by hand in this app — see tkFillDeptSelects');
ok('an off zone stays off even when it names my department',
   at([zone({ active: 0, dept: 'Factory' })], 'Factory').ok === false);

// -- and the caller that names no department falls back to the signed-in user ---------------------
ok('with no department argument it uses the signed-in user',
   at([zone({ dept: 'Engineering' })]).ok === true && at([zone({ dept: 'Factory' })]).ok === false,
   'the harness signs in as Engineering');

// -- the first APPLICABLE zone wins, not the first zone ------------------------------------------
{
  const far = { name: 'Far site', lat: 21.02, lon: 105.85, radius: 200 };
  ok('an inactive zone does not shadow an active one covering the same spot',
     at([zone({ active: 0 }), far, zone({ active: 1, name: 'HQ Annex' })]).zone === 'HQ Annex',
     'a `continue` that was a `break` would report out-of-zone while standing in an approved one');
}

// -- and the wiring, so the fields reach the gate at all -----------------------------------------
console.log('\nThe fields reach the gate\n');
ok('the bootstrap carries active and dept off the wire',
   /active: z\.active == null \? 1 : \(\+z\.active \? 1 : 0\)/.test(src) && /dept: z\.dept \|\| 'All'/.test(src),
   'the zone mapping is an explicit key list — a field missing from it can never be read');
/* Scope this to the LIVE renderer. The file also holds ~20 of these decorative toggles in static
   placeholder markup — demo rows that tkRenderZones/tkRenderSchedules overwrite on first paint, and
   the whole unreachable "Settings & Configuration" page. Those are a separate finding (dead demo
   scaffolding); asserting against the whole file here would convict them and make this test report
   on something it is not measuring. */
{
  const rz = take('function tkRenderZones(', 'tkRenderZones');
  ok('the register renders the stored state, not a hardcoded "on"',
     !/class="toggle on" onclick="this\.classList\.toggle/.test(rz),
     'the old markup said class="toggle on" for every row and toggled two CSS classes');
  ok('and it says which state, to a screen reader too',
     /role="switch"/.test(rz) && /aria-checked/.test(rz));
}
ok('the toggle calls a handler that writes',
   /onclick="tkToggleZone\(/.test(src) && /method: 'PATCH', body: \{ active:/.test(src));
ok('and re-evaluates the gate afterwards',
   /_reEvalGate\(\)/.test(take('async function tkToggleZone(', 'tkToggleZone')),
   'the spot the user is standing on may have just stopped being in-zone');
{
  const save = src.slice(src.indexOf('const editing = _tkZoneEditId;'), src.indexOf('const editing = _tkZoneEditId;') + 900);
  ok('saving sends the department and notes the form collected',
     /\{ name, lat, lon, radius, dept, notes \}/.test(save),
     'they were read into variables and then dropped from the request body');
  ok('and Edit patches the zone it opened instead of appending a copy',
     /editing \? \('\/api\/zones\/' \+ editing\) : '\/api\/zones'/.test(save) &&
     /editing \? 'PATCH' : 'POST'/.test(save));
}
ok('opening Add clears the edit target',
   /_tkZoneEditId = '';[\s\S]{0,400}loc-name/.test(take('function tkOpenLocationModal(', 'tkOpenLocationModal')),
   'otherwise an Add straight after an Edit overwrites the zone the previous click left behind');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
