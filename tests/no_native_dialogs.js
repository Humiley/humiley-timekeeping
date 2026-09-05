/* The portal never calls window.prompt / alert / confirm.
 *
 * Not a style rule. The portal is an installable PWA, and in an installed app — iOS home-screen
 * especially — the browser SUPPRESSES these dialogs. Nothing appears, nothing throws, the value
 * simply never arrives and the handler returns. The button does nothing at all, forever, and
 * reports nothing to anybody.
 *
 * That is what happened to "Add contractor" on the Daily Report: three native prompt() calls
 * survived the migration to the platform's own dialogs (tkPrompt / tkConfirm / tkAlert, which had
 * 19 other call sites), so on a phone or an installed app a contractor could not be created and the
 * screen gave no reason at all. It took four attempts before anybody looked at the mechanism rather
 * than at the person pressing the button.
 *
 * The word appears legitimately in comments (an XSS example carries "foo'+alert(1)+'.pdf") and in
 * _tkDialog's own mode wiring, so this blanks comments and string literals before scanning rather
 * than guessing from how a line is indented — the first version of this check failed on exactly
 * that comment.
 */
const fs = require('fs');
const path = require('path');

/* Replace every comment and string literal with spaces, preserving offsets and newlines, so a
   match is a real call site and line numbers still mean something. */
function blankOut(s) {
  const out = s.split('');
  let i = 0, n = s.length;
  const keep = c => (c === '\n' ? '\n' : ' ');
  while (i < n) {
    const c = s[i], d = s[i + 1];
    if (c === '/' && d === '/') {
      while (i < n && s[i] !== '\n') { out[i] = keep(s[i]); i++; }
    } else if (c === '/' && d === '*') {
      out[i] = ' '; out[i + 1] = ' '; i += 2;
      while (i < n && !(s[i] === '*' && s[i + 1] === '/')) { out[i] = keep(s[i]); i++; }
      if (i < n) { out[i] = ' '; out[i + 1] = ' '; i += 2; }
    } else if (c === '"' || c === "'" || c === '`') {
      const q = c; out[i] = ' '; i++;
      while (i < n) {
        if (s[i] === '\\') { out[i] = ' '; out[i + 1] = keep(s[i + 1]); i += 2; continue; }
        if (s[i] === q) { out[i] = ' '; i++; break; }
        out[i] = keep(s[i]); i++;
      }
    } else { i++; }
  }
  return out.join('');
}

// A call, not a mention: preceded by something that cannot be part of an identifier or a property
// access, so tkPrompt(, _prompt(, this.alert( and x.confirm( are all excluded.
const CALL = /(^|[^A-Za-z0-9_$.])(prompt|alert|confirm)\s*\(/;

function scan(src) {
  const bad = [];
  blankOut(src).split('\n').forEach((line, i) => {
    if (CALL.test(line)) bad.push((i + 1) + ': ' + line.trim().slice(0, 110));
  });
  return bad;
}

/* Guards the guard, twice: the detector must still catch a real call, and must NOT catch the
   comment that broke its first version. A check that stopped matching anything would pass on a page
   full of native dialogs and report that somebody had looked. */
const mustCatch = "  const x = prompt('hello');";
const mustIgnore = "/* an example: \"foo'+alert(1)+'.pdf\" is fine */\nvar y = 1;";
if (scan(mustCatch).length !== 1) {
  console.error('FAIL: the detector no longer catches a native prompt()');
  process.exit(1);
}
if (scan(mustIgnore).length !== 0) {
  console.error('FAIL: the detector fires on a mention inside a comment');
  process.exit(1);
}

const P = path.join(__dirname, '..', 'templates', 'index.html');
const src = fs.readFileSync(P, 'utf8');
const bad = scan(src);

if (bad.length) {
  console.error('FAIL: native dialog(s) — suppressed in an installed PWA, so these do NOTHING:');
  bad.forEach(b => console.error('  ' + b));
  console.error('\nUse the platform dialogs: await tkPrompt(...) / tkConfirm(...) / tkAlert(...)');
  process.exit(1);
}

const n = (src.match(/await tkPrompt\(/g) || []).length;
console.log('OK — no native prompt/alert/confirm; ' + n + ' await tkPrompt call sites');
