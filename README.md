# Humiley Portal — People & Workplace Platform

The internal operations platform for **Humiley Engineering & Solutions**, live at
**portal.humiley.com**. What began as a timekeeping app is now a broad HR / Finance /
Projects / CRM system of record for the company, built on the Python standard library
(`http.server` + `sqlite3`) with a single-file vanilla-JS PWA front end.

> **Architecture & the non-obvious internals are documented in [ARCHITECTURE.md](ARCHITECTURE.md).**
> Read that before making backend changes — the generic JSON store, the auth boundary,
> the e-signature chain, and the invoice-register shape all have important gotchas.

---

## What's in it

- **Timekeeping** — GPS-aware check in/out, attendance, work schedules, overtime, push nudges.
- **Leave** — requests with working-day calculation and balance tracking.
- **HR** — employee database, recruitment, onboarding, performance/PADR, talent, offboarding, training, org.
- **Payroll** — Vietnam statutory computation (3P, social-insurance cap, 7-bracket PIT, reliefs), payslips.
- **Finance** — payment requests, Invoice Tracking (VN TT78 e-invoice capture + reconciliation), accounting export.
- **Approvals** — a server-enforced 3-level workflow (Perform → Review → Approve) with escalation,
  weekly digests, and a monthly leadership pack, across claims / travel / payments / leave.
- **E-signatures** — FDA-Part-11-style: fresh Microsoft 365 re-authentication + a PIN (scrypt + pepper),
  a keyed HMAC signature chain, on every submit and approval.
- **Projects / PMC** — portfolio, EVM, RACI, risk (P–I), IPC certification.
- **CRM** — pipeline, leads, companies, contacts, products, a quotation builder.
- **Assets** — device & asset register with signed assignment/return.
- **Executive Dashboard** — company-wide people / approvals / finance / project rollups (management-only).
- **Procurement** — a **separate** Next.js / Prisma app embedded via iframe (not in this repo's Python).

**Access model:** role (staff / manager / director) **and** access level, re-derived from the
database on every request, with default-deny reads, staff self-owner scoping, and per-user app
gating. See [ARCHITECTURE.md](ARCHITECTURE.md) → *Authorization*.

---

## Run it locally

```bash
pip install -r requirements-dev.txt        # pytest only (the app itself is stdlib + a couple of optional wheels)
python3 app.py                             # serves http://localhost:8000
```

- Microsoft 365 SSO is used when `TK_M365_CLIENT_ID` / `TK_M365_TENANT_ID` are set; otherwise a
  local development sign-in path is available. See [M365_SETUP.md](M365_SETUP.md).
- Set `TK_BOOTSTRAP_ADMIN=1` to seed a first admin on an empty database.
- **Never** run against real data inside a cloud-synced folder — keep `TK_DB_PATH` outside any
  OneDrive/Dropbox tree (`*.db` is gitignored, but a synced folder still auto-uploads plaintext PII).

### Tests

```bash
python3 -m pytest -q
```

The suite boots the real HTTP / auth / e-sign stack in-thread (see `tests/conftest.py`). CI runs it
on Python 3.9 + 3.12, plus an axe-core accessibility scan and a Lighthouse budget
(`.github/workflows/`).

---

## Configuration (environment)

| Variable | Purpose |
|---|---|
| `TK_DB_PATH` | SQLite database path (keep it out of any synced folder) |
| `TK_PORT` / `PORT` · `TK_HOST` | Listen port / bind address (default `8000` / `0.0.0.0`) |
| `TK_M365_CLIENT_ID` / `TK_M365_TENANT_ID` | Microsoft 365 / Entra SSO |
| `TK_M365_CLIENT_SECRET` | App-only Graph (approval mail, SharePoint archive, invoice mailbox sync) — **prod `.env` only** |
| `TK_ESIGN_PEPPER` | Server-side pepper for e-signature PIN hashing — **escrow this; losing it invalidates every PIN** |
| `TK_ESIGN_REQUIRE_VERIFIED_TOKEN` | Hard-fail e-sign token verification (recommended `1` in prod) |
| `TK_SSO_SECRET` | Signs the portal↔procurement SSO handoff |
| `TK_BOOTSTRAP_ADMIN` | Seed a first admin on an empty DB |

Secrets live only in the VPS `.env` — **the repo is public; never commit secrets or real data.**

---

## Deployment & operations

Production runs in Docker behind Caddy on a single VPS, auto-deploying on push to `main`.
See **[DEPLOY.md](DEPLOY.md)**, **[UPDATE.md](UPDATE.md)**, and **[GO_LIVE_GUIDE.md](GO_LIVE_GUIDE.md)**.
Mobile app scaffolding: **[IOS-APP.md](IOS-APP.md)**, **[ANDROID-APP.md](ANDROID-APP.md)**.

---

## Repository layout

```
app.py            HTTP server + REST API + request handler (the backend core)
db.py             SQLite access, schema, migrations
tkutil.py         pure leaf utilities (extracted from app.py)
einv.py           Vietnam TT78 e-invoice XML/ZIP parser
ratelimit.py      in-process sliding-window rate limiter
templates/        index.html — the entire single-file PWA front end
static/           service worker, icons, manifest, brand assets
tests/            pytest regression suite
.github/workflows CI (tests) + a11y + Lighthouse
```

---

*Humiley Engineering & Solutions — internal platform. Not for public distribution.*
