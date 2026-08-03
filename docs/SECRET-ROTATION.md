# Secret rotation runbook

Which secrets can be rotated, which must **never** be, and the 5-minute procedure for the one that
expires on a clock.

---

## The two classes — read this first

### 🔴 NEVER rotate (rotating destroys data you cannot recover)

| Secret | Rotating it breaks |
|---|---|
| `TK_ESIGN_PEPPER` | Every enrolled e-signature **PIN** stops verifying. PINs are hashed with this pepper folded in; there is no re-derivation path. |
| `TK_AUDIT_PEPPER` | The audit **hash chain** can no longer be verified — the admin badge flips to "Reseal required". *Recoverable*, but only by re-sealing the whole chain under the new key: start once with `TK_AUDIT_RESEAL=1`, then unset it. |
| `ESIGN_SIGNING_SECRET` (Procurement) | Existing v2 e-signature chain entries fail `verifyChain`. |

Set these **once**, escrow them off-box, and leave them alone. If one is ever *exposed*, treat it as an
incident: you must weigh re-enrolment (PINs) or re-sealing (audit) against the exposure.

### 🟡 Rotatable (with a short, planned outage window)

| Secret | Notes |
|---|---|
| `TK_M365_CLIENT_SECRET` | **Expires on a clock** — see below. This is the one you must diarise. |
| `POSTGRES_PASSWORD` | Must be changed in Postgres **and** `.env` together, or Procurement can't reach its DB. |
| `AUTH_SECRET` | Rotating invalidates active Procurement sessions (users re-login). Otherwise safe. |
| `TK_SSO_SECRET` | Shared portal↔Procurement. Both read the *same* `.env` variable, so they can't drift — but rotating logs everyone out of the Procurement handoff. |
| backup key (`.backup-key`) | New key only applies to **future** snapshots. **Keep the old key** as long as you retain snapshots encrypted with it, or those become unreadable. |

---

## ⏰ `TK_M365_CLIENT_SECRET` — the one that expires

Entra client secrets have a **maximum ~24-month** lifetime. When it expires, these all fail:

- approval e-mail, the invoice-mailbox (`hd@humiley.com`) sync, daily digests, the monthly pack, overdue nudges.

**The dangerous part:** the app only checks the secret is *present*, not *valid*. On expiry every Graph
call returns 401 and the features stop **silently** — no error banner, no alert. You find out when
someone asks why approvals stopped arriving.

### Put it on a calendar
Create a reminder **30 days before** the expiry date shown in Entra, repeating. Record the expiry date
here when you rotate:

> **Current secret expires:** `____-__-__`  (fill this in — last rotated: `____-__-__`)

### Rotation procedure (~5 minutes, brief mail/sync interruption)

1. **Entra portal** → *App registrations* → **Humiley Portal** → *Certificates & secrets*
   → **New client secret**. Description e.g. `portal-2028`. Choose the longest allowed expiry.
   **Copy the VALUE immediately** — it is shown only once.
2. **Escrow it** in the password manager *before* touching the server.
3. **Update the VPS**:
   ```bash
   cd /opt/humiley-timekeeping
   cp .env .env.bak                                   # keep a rollback
   sed -i 's|^TK_M365_CLIENT_SECRET=.*|TK_M365_CLIENT_SECRET=<NEW VALUE>|' .env
   grep TK_M365_CLIENT_SECRET .env                    # confirm it took
   docker compose up -d app                           # restart the portal with the new value
   ```
4. **Verify** (don't skip — a typo here fails silently):
   ```bash
   curl -s https://portal.humiley.com/api/health      # app is up
   docker logs --tail 50 humiley_portal | grep -i -E "graph|401|invtrack"
   ```
   Then in the UI: trigger an **invoice mailbox sync** (Finance → Invoice Tracking → Sync) and confirm
   it completes without a Graph 401. Approve a test request and confirm the e-mail arrives.
5. **Delete the OLD secret in Entra** once verified — otherwise a leaked old value stays live.
6. Update the expiry date recorded above, and reset the calendar reminder.

### Rollback
If mail/sync breaks after the change:
```bash
cd /opt/humiley-timekeeping && cp .env.bak .env && docker compose up -d app
```
The old secret keeps working until its own expiry (as long as you haven't deleted it in Entra yet —
which is why step 5 comes *after* verification).

---

## Also verify while you're in Entra

- **SPA redirect URI** is exactly `https://portal.humiley.com` (no trailing slash).
- **Graph `Mail.Read` APPLICATION permission** still has admin consent (needed for the 24/7 mailbox sync).
- No unexpected extra secrets/certificates are registered on the app.
