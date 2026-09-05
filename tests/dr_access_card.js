/* Report Setup's contractor-link card really carries its controls.
 *
 * The card is built by string concatenation inside a 4 MB template.  A lost quote or a stray '+'
 * still *parses* — `tools/check_index_js.py` stays green — and what it stops doing is emitting the
 * button.  A blank panel in an admin screen is exactly the class of failure nobody reports, so the
 * assertion here is on the rendered HTML, not on the source text.
 *
 * The address box is the access boundary: `_drCollect()` reads every `[data-drlistfield]`, so if
 * that attribute is lost the emails silently stop being saved and the allow-list empties.
 */
const fs = require('fs');
const path = require('path');

const P = path.join(__dirname, '..', 'templates', 'index.html');
const src = fs.readFileSync(P, 'utf8');

const start = src.indexOf('function _drAccessCard(c) {');
if (start < 0) { console.error('FAIL: _drAccessCard is not in index.html'); process.exit(1); }
const end = src.indexOf('\nfunction _drLinkOut()', start);
if (end < 0) { console.error('FAIL: could not find the end of _drAccessCard'); process.exit(1); }

const _t = s => s;
const _tp = (s, ...a) => a.reduce((x, v, i) => x.split('{' + i + '}').join(v), s);
const _crmEsc = v => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const _tkEscA = v => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
const _drLinkOut = () => '';

const card = new Function('_t', '_tp', '_crmEsc', '_tkEscA', '_drLinkOut',
                          src.slice(start, end) + '\nreturn _drAccessCard;')(
  _t, _tp, _crmEsc, _tkEscA, _drLinkOut);

let bad = 0;
function want(html, needle, why) {
  const ok = html.indexOf(needle) >= 0;
  if (!ok) bad++;
  console.log((ok ? '  ok    ' : '  MISS  ') + why);
}

const html = card({ id: 'DRC-1', name: 'Taikisha',
                    emails: ['site@taikisha.example', 'coordinator@humiley.com'] });

want(html, 'tkDrShowLink()', 'Show the link');
want(html, 'tkDrSendLink()', 'Email the link');
want(html, 'tkDrSignOutAll()', 'Sign everyone out');
want(html, 'tkDrNewLink()', 'Issue a new link');
want(html, 'data-drlistfield="emails"', 'the address box is collected by _drCollect');
want(html, 'id="dr-link-out"', 'the link/receipt panel the actions write into');
want(html, 'site@taikisha.example\ncoordinator@humiley.com', 'existing addresses, one per line');

// A record edited by hand — or imported — holds a string, not an array.
want(card({ id: 'DRC-2', name: 'X', emails: 'a@b.com; c@d.com' }), 'a@b.com\nc@d.com',
     'a string of addresses is split, not printed raw');

// Nothing set yet: the card must still offer the controls, or a new contractor can never be let in.
const empty = card({ id: 'DRC-3', name: 'New' });
want(empty, 'tkDrShowLink()', 'a contractor with no addresses still gets the controls');
want(empty, 'data-drlistfield="emails"', 'a contractor with no addresses still gets the box');

if (bad) { console.log('\nFAIL ' + bad); process.exit(1); }
console.log('  ok    (card)');


/* ── the state that cost a morning ───────────────────────────────────────────────────────────────
 * A contractor with no SAVED addresses cannot be signed into by anybody. The form still answers
 * "a six-digit code is on its way" — it must, or it would reveal who is on the list — so the state
 * is invisible from the site's end AND, until this, from Report Setup's. The box shows whatever was
 * last typed, which looks identical to an address already in force.
 */
const inForce = new Function('_t', '_crmEsc',
  src.slice(src.indexOf('function _drSavedEmails('),
            src.indexOf('\nfunction _drLinkOut()')) + '\nreturn _drInForce;')(_t, _crmEsc);

let n2 = 0;
function w2(html, needle, why) {
  const ok = html.indexOf(needle) >= 0;
  if (!ok) n2++;
  console.log((ok ? '  ok    ' : '  MISS  ') + why);
}
function mustNot(html, needle, why) {
  if (html.indexOf(needle) >= 0) { n2++; console.log('  MISS  ' + why); }
  else console.log('  ok    ' + why);
}

const none = inForce({ id: 'C-1', name: 'X' });
w2(none, 'Nobody can open this link yet.', 'an empty list says so, loudly');
w2(none, 'Save setup', 'and says what to do about it');

const one = inForce({ id: 'C-2', name: 'Y', emails: ['a@b.com', 'c@d.com'] });
w2(one, 'Saved and in force', 'a saved list is labelled as saved');
w2(one, 'a@b.com, c@d.com', 'and lists what is actually in force');
w2(one, 'until Save setup is pressed', 'and warns that typing alone changes nothing');
mustNot(one, 'Nobody can open', 'a saved list does not warn');

// A record edited by hand, or imported, holds a string rather than an array.
const str = inForce({ id: 'C-3', name: 'Z', emails: 'a@b.com; c@d.com' });
w2(str, 'Saved and in force', 'a string of addresses counts as saved');
mustNot(str, 'Nobody can open', 'a string list does not warn');

// Whitespace and separators are not an address.
const blank = inForce({ id: 'C-4', name: 'W', emails: '  ,  ; \n ' });
w2(blank, 'Nobody can open this link yet.', 'whitespace does not count as a saved address');

if (n2) { console.log('\nFAIL ' + n2); process.exit(1); }
console.log('\nOK (in-force)');
