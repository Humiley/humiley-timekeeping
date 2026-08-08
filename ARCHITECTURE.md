# Architecture

How the Humiley Portal is built, and the non-obvious things that will bite you if you
change the backend without knowing them. Written for an engineer onboarding from the repo
alone. (Reflects the codebase as of 2026-08; verify against the code before relying on any
specific line.)

---

## 1. Shape

Two artifacts do almost everything:

- **`app.py`** (~5.4k lines) — a pure-stdlib `ThreadingHTTPServer` with one `Handler` class that
  routes the REST API by URL-prefix. No web framework. Storage is SQLite via `db.py` (WAL,
  `busy_timeout`, `synchronous=NORMAL`, `foreign_keys=ON`; one fresh connection per request).
- **`templates/index.html`** (~21k lines) — the entire front end: a single-file vanilla-JS PWA.
  No build step, no framework. A service worker (`static/sw.js`) makes it installable + offline-capable.

Leaf modules already extracted (strict one-way imports, `app.py → module`, never back):
`tkutil.py` (pure helpers), `einv.py` (VN TT78 e-invoice parser), `ratelimit.py` (rate limiter).
The next natural extraction is `invtrack.py` (~25% of `app.py`).

---

## 2. Request lifecycle & authorization (the real security boundary)

Auth is **Bearer-token**, designed so CSRF isn't a concern (no cookie ambient authority). The token
maps to a session; **the user's role and access level are re-derived from the database on every
request** — a client cannot assert its own privileges.

Layers, all enforced server-side in `app.py` (the UI hiding things is cosmetic only):

- **Default-deny reads.** Collection reads are gated; staff are **self-owner-scoped** (they see only
  their own rows). ⚠️ Some collections (e.g. `pm_*`, `schedules`) are currently *fail-open* — audit
  before assuming a collection is restricted.
- **Per-user app gating** (`appsDenied`) — an admin can disable CRM/HR/Finance/etc. for a user.
- **3-level approval / segregation of duties** — for `claims / travel / payments / leave`
  (`THREE_LEVEL_COLLS`): Perform → Review → Approve, with reviewer ≠ approver, no self-review/approve,
  and direct-manager review. Approved records are immutable/undeletable. The generic write path is
  barred from forging `status`/`signatures`.
  ⚠️ **Payroll (`payruns`/`payadjust`) is NOT in this set** — it's editor-only with no dual control.
  ⚠️ The disbursement (`paid`) transition historically lacked a payer≠approver/owner guard — check
  `_appr_check` before touching it.

## 3. The generic JSON-document store (`/api/coll/<name>`)

Most business data lives in **one `collections` table of JSON documents**, CRUD'd through
`/api/coll/<name>`. This buys velocity (add a "table" with no migration) at the cost of integrity:

- **No foreign keys / no schema.** `empId`, payee, vendor are free-text strings copied into each doc,
  not references. Deleting an employee orphans their finance/asset history.
- **Full-collection loads.** `list_collection` reads + `json.loads` **every** row; scoping, single-item
  lookup, and filtering happen in Python — there is no SQL `WHERE`/`LIMIT`/pagination. Cost grows
  linearly with history.
- **`PATCH` is a blind full-document overwrite** — no version check, so concurrent edits silently
  last-writer-wins.
- **A create always mints a fresh `id`** — no idempotency, so a retried POST can duplicate a record.

### ⚠️ The invoice register (`invtrack`) gotcha
`invtrack` is **not** one row per invoice. It is a **single dataset document holding an `.items[]`
array**. Aggregating invoices means flattening `.items` (`_invtrack_all_items()`), **never** iterating
`db.list_collection("invtrack")` rows (doing so returns 0 — this bug shipped once, commit `3efb770`).
A background mailbox sync rewrites the whole blob under a lock; a manual edit goes through the generic
(un-locked) overwrite path — a real write race.

## 4. E-signatures (FDA Part 11-style)

The strongest subsystem. Every submit and approval is signed with:

- **Fresh Microsoft 365 ID-token re-auth** (RS256, JWKS-verified, `alg=none` rejected) — proves *who*.
- **A personal PIN** — scrypt + an external server pepper (`TK_ESIGN_PEPPER`), with lockout, expiry,
  and constant-time compare.
- **A keyed HMAC signature chain** with version + reason, stored on the record.

⚠️ Losing `TK_ESIGN_PEPPER` makes **every** enrolled PIN unverifiable — escrow it. JWKS verification
soft-fails unless `TK_ESIGN_REQUIRE_VERIFIED_TOKEN=1` — set it in prod.

## 5. Background schedulers

Five daemon threads start inside `main()` (approval reminders/escalation, weekly digest, timekeeping
nudges, monthly pack, invoice mailbox sync). ⚠️ They are **gated on M365 being ready** and run
**in-process** — so (a) they silently do nothing without the mail secret, (b) a second app replica
would double-send every email, and (c) if `TK_M365_CLIENT_SECRET` expires, every Graph call 401s in
silence (readiness checks presence, not validity).

## 6. Microsoft 365 / Graph integration

- **SSO** (MSAL) for login and e-sign re-auth.
- **App-only Graph** (`TK_M365_CLIENT_SECRET`): sends approval mail, archives approved
  payments/claims/travel to SharePoint (Year/Month/reqNo folders, voucher + invoice), and syncs the
  Invoice-Tracking mailbox (`Mail.Read`).

---

## 7. Front end

- One `index.html`; views are toggled by `showView()`. Data loads via `/api/*` after auth.
- **i18n** EN/VN via a `_VI` dictionary + `_t`/`_t2` and a DOM-walk `MutationObserver`. ⚠️ A missing
  key silently renders the English key.
- **Design tokens** in `:root`, but a large global `!important` "retheme" layer overrides many base
  rules — any override of a re-themed selector must itself be `!important`. Thousands of inline styles
  still bypass the tokens (design-system drift; blocks a clean dark mode).
- **Service worker** is network-first for the HTML shell (fresh deploy wins) with a cached-shell
  fallback. Bump `CACHE = 'hml-pwa-vN'` in `static/sw.js` after any shell change.
- Heavy libs (xlsx / jsPDF / html2canvas / pdf.js) idle-load after `window.load`; keep the
  `if (!window.XLSX) …` guards at call sites.

## 8. Infrastructure

Single VPS, Docker + Caddy (auto-TLS), **auto-deploy on push to `main`**. Nightly encrypted SQLite
backup script + restore doc. The **Procurement** app is a separate Next.js/Prisma service (its own
Postgres) reverse-proxied under `/procurement` and embedded via iframe with a signed SSO handoff.

⚠️ **Single points of failure to keep in mind:** one VPS (no HA), in-process state (sessions,
schedulers, rate limiter), and — as of the 2026-08 audit — the Procurement Postgres DB was not yet in
the backup set. See `DEPLOY.md` / the maturity-audit for the operational runbook.

---

## 9. "Read before you change" checklist

- Touching **money flow** (payments/payroll/claims)? Re-read `_appr_check` and the SoD rules; add a
  test — the pytest suite boots the real stack.
- Touching **`invtrack`**? Remember the single-doc `.items[]` shape and the sync write-lock.
- Touching **`/api/coll`** writes? The status/signature-forgery guard and owner-scoping live there.
- Adding a **collection**? Decide its read policy explicitly — the default is not deny.
- Changing the **shell**? Bump the SW cache version.
- Adding a **scheduled job**? It must run in exactly one process and not depend on the mail secret to exist.
