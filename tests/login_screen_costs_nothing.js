/* The sign-in screen paints its backdrop instead of downloading one — and still reads.
 *
 * It used to load one of four photographs, chosen by the day of the month and the screen's
 * orientation, weighing 152,165 to 405,188 bytes. That made it the largest single thing a first-time
 * visitor downloaded after the app itself, on the one screen where somebody is already waiting.
 *
 * THE TRAP, and the reason this file checks colours at all. The logo was hidden deliberately:
 *
 *     #login-main-logo{display:none !important}   // the background photo already carries the
 *                                                 // Humiley logo + tagline
 *
 * so deleting the photograph silently deleted the branding, and left a title still coloured for a
 * bright image. Nothing errors. The screen simply stops being Humiley's and gets hard to read, and
 * only somebody looking at it would ever know. It happened once here, exactly like that.
 *
 * So rather than pin one palette — this screen has now been dark and light within a day — the
 * checks pin the RELATIONSHIP: whatever the card's ground is, the logo artwork, the title, the
 * body text and the button must all be on the right side of it. That survives the next redesign and
 * still catches the thing that actually went wrong.
 *
 *   node tests/login_screen_costs_nothing.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const raw = fs.readFileSync(path.join(ROOT, 'templates', 'index.html'), 'utf8');
/* Comments first: this change's own comments name the file it removed, and a check that greps the
   raw text reads its own explanation as a regression. That has already happened once. */
const src = raw.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '');

let pass = 0, fail = 0;
const ok = (n, c, extra) => {
  if (c) { pass++; console.log('  ok    ' + n); }
  else { fail++; console.log('  FAIL  ' + n + (extra ? '\n        ' + extra : '')); }
};

const rule = (sel) => {
  const m = new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}').exec(src);
  return m ? m[1] : null;
};

/* Relative luminance of the first colour a declaration block resolves to, 0 (black) to 1 (white).
   Handles #rgb, #rrggbb, rgba(), and the two brand variables this screen uses. */
const VARS = { '--navy': '#205090', '--emerald': '#00B060', '--text': '#1F2937' };
function luminance(decl) {
  if (!decl) return null;
  let v = decl.trim();
  const varm = /var\((--[a-z-]+)\)/.exec(v);
  if (varm && VARS[varm[1]]) v = VARS[varm[1]];
  let r, g, b;
  let m = /#([0-9a-f]{6})\b/i.exec(v);
  if (m) { r = parseInt(m[1].slice(0, 2), 16); g = parseInt(m[1].slice(2, 4), 16); b = parseInt(m[1].slice(4, 6), 16); }
  else if ((m = /#([0-9a-f]{3})\b/i.exec(v))) {
    r = parseInt(m[1][0] + m[1][0], 16); g = parseInt(m[1][1] + m[1][1], 16); b = parseInt(m[1][2] + m[1][2], 16);
  } else if ((m = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(v))) {
    r = +m[1]; g = +m[2]; b = +m[3];
  } else if (/\bwhite\b/i.test(v)) { r = g = b = 255; }
  else if (/\bblack\b/i.test(v)) { r = g = b = 0; }
  else return null;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}
const prop = (block, name) => {
  if (!block) return null;
  const m = new RegExp('(?:^|;)\\s*' + name + '\\s*:\\s*([^;]+)').exec(block);
  return m ? m[1].trim() : null;
};

// ══ 1. nothing fetches a login photograph ══════════════════════════════════════════════════════
console.log('\nThe backdrop is painted, not fetched\n');
{
  ok('no stylesheet or script points at a login photo', !/\/static\/brand\/login\//.test(src),
     'a reference is back — that is 152 KB to 405 KB on the sign-in screen');
  ok('and the day-of-month picker is gone', !/_setLoginBg/.test(src));
  ok('nothing assigns a backgroundImage to the overlay',
     !/login-overlay[\s\S]{0,400}?backgroundImage/.test(src));

  const ov = rule('#login-overlay');
  ok('the overlay still declares a background', ov && /background:/.test(ov),
     'without one the screen is whatever the browser paints by default');
  ok('and that background fetches nothing', ov && !/url\(/.test(ov),
     'a url() here is a download on the sign-in screen, whatever it points at');
}

// ══ 2. the card and everything on it agree about which way up they are ═════════════════════════
console.log('\nThe card and its contents are the same colourway\n');
const cardBg = luminance(prop(rule('.login-card'), 'background'));
{
  ok('the card declares a background this test can read', cardBg !== null,
     'add the format to luminance() rather than deleting the checks below');
  if (cardBg !== null) {
    const light = cardBg > 0.5;
    console.log('        (card ground reads as ' + (light ? 'LIGHT' : 'DARK') +
                ', luminance ' + cardBg.toFixed(2) + ')');

    const title = luminance(prop(rule('.login-title'), 'color'));
    ok('the title contrasts with it', title !== null && Math.abs(title - cardBg) > 0.35,
       'title luminance ' + (title === null ? '?' : title.toFixed(2)) + ' against a card at ' +
       cardBg.toFixed(2) + ' — that is the heading reading as a blur');

    const sub = luminance(prop(rule('.login-sub'), 'color'));
    ok('so does the body text', sub !== null && Math.abs(sub - cardBg) > 0.3,
       'sub luminance ' + (sub === null ? '?' : sub.toFixed(2)));

    const btn = rule('.login-ms-btn');
    const btnBg = luminance(prop(btn, 'background'));
    const btnFg = luminance(prop(btn, 'color'));
    ok('and the button label contrasts with the button',
       btnBg !== null && btnFg !== null && Math.abs(btnFg - btnBg) > 0.35,
       'button ' + (btnFg === null ? '?' : btnFg.toFixed(2)) + ' on ' +
       (btnBg === null ? '?' : btnBg.toFixed(2)) + ' — a transparent button inherits the card, ' +
       'which is how white-on-white happens');

    ok('no text still wears a glow from the photograph era',
       !/text-shadow/.test(rule('.login-title') || '') && !/text-shadow/.test(rule('.login-sub') || '') &&
       !/text-shadow/.test(btn || ''),
       'a halo exists to lift text off a busy image; over a flat ground it just smears the letters');

    // the lock-up has two colourways and only one is right for each ground
    const img = /<img[^>]*id="login-main-logo"[^>]*>/.exec(src);
    ok('the logo is in the markup', !!img);
    ok('and is not hidden', !/#login-main-logo\s*\{[^}]*display:\s*none/.test(src),
       'it was hidden BECAUSE the photograph carried the logo. Hidden now, the screen has no ' +
       'brand mark on it at all');
    if (img) {
      const m = /src="(\/static\/[^"]+)"/.exec(img[0]);
      ok('with a src', !!m, img[0].slice(0, 120));
      if (m) {
        const file = path.join(ROOT, m[1].replace(/^\//, ''));
        ok('pointing at a file that exists: ' + m[1], fs.existsSync(file),
           'a typo renders nothing, and an invisible logo on a transparent PNG looks exactly like ' +
           'a design choice — no console error, no broken-image icon');
        if (fs.existsSync(file)) {
          ok('that is small enough to be worth showing (' + fs.statSync(file).size + ' B)',
             fs.statSync(file).size < 60000);
        }
        const isWhiteArtwork = /white/i.test(m[1]) || /reverse/i.test(m[1]);
        ok('in the colourway the card calls for', light ? !isWhiteArtwork : isWhiteArtwork,
           light ? 'a white lock-up on a light card is an invisible logo: ' + m[1]
                 : 'a navy lock-up on a dark card is an invisible logo: ' + m[1]);
      }
    }
  }
}

// ══ 3. the photographs are kept ════════════════════════════════════════════════════════════════
console.log('\nThe photographs are kept, not deleted\n');
{
  const dir = path.join(ROOT, 'static', 'brand', 'login');
  const jpgs = fs.existsSync(dir) ? fs.readdirSync(dir).filter(f => /\.jpe?g$/i.test(f)) : [];
  ok('all four are still in the repository', jpgs.length >= 4,
     'found ' + jpgs.length + '. Nothing references them, but deleting brand photography to make ' +
     'a page faster is not a decision a speed change gets to make on its own');
}

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
