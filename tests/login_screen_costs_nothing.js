/* The sign-in screen paints its backdrop instead of downloading one.
 *
 * It used to load one of four photographs — chosen by the day of the month and the screen's
 * orientation — weighing 152,165 to 405,188 bytes depending on which day it happened to be. That
 * made it the largest single thing a first-time visitor downloaded after the app itself, on the one
 * screen where somebody is already standing still waiting.
 *
 * THE TRAP THIS FILE EXISTS FOR. The logo was hidden, deliberately, with a comment saying why:
 *
 *     #login-main-logo{display:none !important}   // the background photo already carries the
 *                                                 // Humiley logo + tagline
 *
 * So deleting the photograph silently deleted the branding from the sign-in screen — no logo, and a
 * title still coloured navy with a white halo because it had been drawn to sit on a bright
 * photograph, which on the dark card is navy on navy. Nothing errors. The page just quietly stops
 * being Humiley's and becomes hard to read, and only a person looking at it would ever know.
 *
 * So this checks the screen still HAS a brand mark and a legible title, not merely that the photo
 * is gone. Removing a thing is easy to verify; noticing what the thing was also doing is not.
 *
 *   node tests/login_screen_costs_nothing.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const raw = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
/* Comments first. This change's own comments name the file it removed, and a check that greps the
   raw text reads its own explanation as a regression — which has already happened once today. */
const src = raw.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

// ══ 1. nothing fetches a login photograph ══════════════════════════════════════════════════════
console.log('\nThe backdrop is painted, not fetched\n');
{
  ok('no stylesheet or script points at a login photo',
     !/\/static\/brand\/login\//.test(src),
     'a reference to /static/brand/login/ is back — that is 152 KB to 405 KB on the sign-in screen');
  ok('and the day-of-month picker is gone', !/_setLoginBg/.test(src),
     'the function that chose between the four photographs still exists');
  ok('nothing assigns a backgroundImage to the overlay',
     !/login-overlay[\s\S]{0,400}?backgroundImage/.test(src));

  const css = /#login-overlay\{([^}]*)\}/.exec(src);
  ok('the overlay still declares a background', css && /background:/.test(css[1]),
     'without one the sign-in screen is whatever the browser paints by default');
  ok('and it is a gradient rather than a flat fill',
     css && /gradient\(/.test(css[1]),
     'a flat colour would work, but the card and its text were composed against something with ' +
     'depth — this is the thing that keeps the screen looking designed');
}

// ══ 2. the branding the photograph used to carry ═══════════════════════════════════════════════
console.log('\nThe screen is still Humiley\'s\n');
{
  ok('the login logo is not hidden', !/#login-main-logo\s*\{[^}]*display:\s*none/.test(src),
     'it was hidden BECAUSE the photograph carried the logo. With the photograph gone and this ' +
     'rule still in place, the sign-in screen has no brand mark on it at all');

  const img = /<img[^>]*id="login-main-logo"[^>]*>/.exec(src) ||
              /<img[^>]*src="\/static\/brand\/[^"]+"[^>]*id="login-main-logo"[^>]*>/.exec(src);
  ok('and it is actually in the markup', !!img);
  if (img) {
    const m = /src="(\/static\/[^"]+)"/.exec(img[0]);
    ok('with a src', !!m, img[0].slice(0, 120));
    if (m) {
      const file = path.join(ROOT, m[1].replace(/^\//, ''));
      ok('pointing at a file that exists: ' + m[1], fs.existsSync(file),
         'a typo here renders nothing at all, and an invisible logo looks exactly like a design ' +
         'choice — no console error, no broken-image icon on a transparent PNG');
      if (fs.existsSync(file)) {
        const n = fs.statSync(file).size;
        ok('that is small enough to be worth showing (' + n + ' B)', n < 60000,
           'the point of this change was bytes on the sign-in screen; a big logo gives them back');
      }
      /* The card is dark navy. portal-logo-login.png is the NAVY lock-up drawn for a white card —
         correct before, invisible now. */
      ok('and it is not the navy lock-up drawn for a white card',
         !/portal-logo-login\.png/.test(m[1]),
         'navy artwork on a dark navy card is an invisible logo');
    }
  }
}

// ══ 3. the title was coloured for a photograph ═════════════════════════════════════════════════
console.log('\nAnd the title is legible on it\n');
{
  const t = /\.login-title\{([^}]*)\}/.exec(src);
  ok('the title rule is still there', !!t);
  if (t) {
    ok('it no longer wears a white glow',
       !/text-shadow[^;]*rgba\(255,\s*255,\s*255/.test(t[1]),
       'a white halo exists to lift text off a busy photograph. Over a plain dark card it just ' +
       'smears the letters: ' + t[1]);
    ok('and it is not navy on a dark card',
       !/color:\s*var\(--navy\)/.test(t[1]) && !/color:\s*#205090/i.test(t[1]),
       'navy on the dark sign-in card is the heading reading as a blur: ' + t[1]);
    ok('it is a light colour', /color:\s*#[EeDdFfCc][0-9A-Fa-f]{5}/.test(t[1]) ||
       /color:\s*#fff/i.test(t[1]) || /color:\s*white/i.test(t[1]),
       'expected something light for a dark card, got: ' + t[1]);
  }
}

// ══ 4. and the files are still there, because this is reversible ═══════════════════════════════
console.log('\nThe photographs are kept, not deleted\n');
{
  const dir = path.join(ROOT, 'static', 'brand', 'login');
  const jpgs = fs.existsSync(dir) ? fs.readdirSync(dir).filter(f => /\.jpe?g$/i.test(f)) : [];
  ok('all four are still in the repository', jpgs.length >= 4,
     'found ' + jpgs.length + '. Nothing referenced them any more, but deleting brand photography ' +
     'to make a page faster is not a decision a speed change gets to make on its own');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
