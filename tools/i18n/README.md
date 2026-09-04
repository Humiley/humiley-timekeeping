# Vietnamese translation checks

```bash
node tools/i18n/check.js dups      # duplicate keys — CI gate, exits non-zero
node tools/i18n/check.js quality   # mechanical defects (advisory)
node tools/i18n/check.js terms     # terminology consistency (advisory)
node tools/i18n/check.js all
```

Runs from the main checkout or any worktree — it resolves the repo from its own path, not your
working directory.

## What each one is for

**`dups`** is the only gate, because a duplicate key is the only failure here that loses work
*silently*: `_VI` is one object literal, so the later entry wins with no parse error, and the diff
shows only additions. The damage lands on a translation nobody in that PR touched. 159 duplicates
existed at one point; three more arrived later from a three-way merge that appended both sides'
new-key blocks — a shape no pre-merge check can catch, which is why this runs in CI.

**`quality`** and **`terms`** are advisory. They surface things a person has to judge, and a gate
that cries wolf is a gate people learn to skip. Expect findings that are correct as they stand:

- *parenthetical dropped* — English marks plurals `(s)` and Vietnamese does not inflect, so
  dropping it is right. An earlier version counted parentheses and was **67 for 67 false
  positives**, which buried the real findings.
- *one Vietnamese for N English keys* — usually casing variants of one concept. But this is also
  where a genuinely two-sense word shows up: `Calibration` is **hiệu chuẩn** for an instrument and
  **hiệu chỉnh** for HR rating alignment, and both are correct. Check the call site before
  "fixing" one.
- *identical to English* — `Microsoft 365`, `Incoterms 2020`, `Eurovent` should stay English.

## What none of this can tell you

Whether a string ever reaches the screen. The DOM-walk translates text nodes plus `title`,
`aria-label`, `alt` and `placeholder`; anything built another way needs a browser with the language
switched.

Measuring coverage from source alone has been wrong here before, in a way worth remembering: four
separate scanners all reported zero gaps while **826 strings** were still English on screen. Every
one of them matched text between `>` and `<`, and those 826 were built from JS properties —
`label:`, `options: [...]`, `toast('...')` — which never take that shape. The scanners agreed with
each other because they shared one assumption, not because they were right.

So the last check is always: open the app, switch to Vietnamese, and walk the DOM for text nodes
where `_VI[text]` exists but the node still reads English. That set must be empty.
