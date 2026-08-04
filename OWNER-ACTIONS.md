# Owner Actions — the items only you can safely do

These close the highest‑severity gaps from the 2026‑08 maturity audit that live **outside the code** —
on the VPS, on GitHub, or as irreversible operations. Claude implemented everything doable in code
(see the recent commits); these need your hands because they touch production infrastructure, GitHub
settings, or history you must not have an agent force‑push.

Ordered by severity. **P0 = do this week.**

---

## P0‑0 · Ship the pending release (this session's commits) — blocked on you
`main` is ~25 commits ahead of `origin/main` (scrollbar fix → ERP‑maturity + security hardening → payroll
dual‑control → optimistic concurrency → the tamper‑evident audit hash chain), full suite **268 passing**.
The push is blocked **only** by a GitHub credential‑scope rule, not by the code:

1. **Grant the `workflow` scope, then push.** The commit that adds `.github/workflows/*.yml` (the CI files)
   is rejected because the current push credential lacks the `workflow` scope. Fix once, then push:
   ```bash
   gh auth refresh -h github.com -s workflow    # or just: git push origin main  (from your own creds)
   ```
   The zero‑click auto‑deploy runs on push (see [production deploy notes]).
2. **Back up BEFORE the deploy.** This release runs one‑way DB migrations on the live SQLite (the audit‑chain
   backfill adds seq/hash to every audit row; `PRAGMA user_version → 2`; session tokens re‑hash). Confirm a
   fresh `backup.sh` snapshot exists first (see P0‑2).
3. **Set `TK_AUDIT_PEPPER` in the VPS `.env` BEFORE this deploy** (`openssl rand -hex 32`). If it's set first,
   the audit history seals **tamper‑evident (keyed)** on the first run. If you deploy without it, the chain
   forms **unkeyed** (amber "Chain intact (unkeyed)" badge) — then set the pepper and restart **once** with
   `TK_AUDIT_RESEAL=1` to seal it, and unset that flag afterward. Escrow the pepper off‑box (P0‑3).

## P0‑1 · Turn on the CI gate (GitHub) — ✅ DONE 2026‑08‑04
1. ✅ **Branch ruleset "main protection"** is active on `main` (id 20347314): requires the **`CI`** status
   check, blocks force‑pushes (`non_fast_forward`) and deletion. **Repository admin is on the bypass list**
   so your direct pushes and the auto‑deploy still work — verified with a real push. Remove that bypass if
   you ever want strict PR‑only merges.
   *Only `CI` is required — the Accessibility and Lighthouse jobs drive a real browser and are prone to
   runner‑image drift (they failed on day one for exactly that reason), so they report without gating.*
2. ✅ **Secret scanning + Push protection** enabled (confirmed via the API).
3. ⏳ **STILL OPEN:** make `autodeploy.sh` refuse a SHA whose CI isn't green before deploying (query the
   GitHub checks API; only `docker compose up` when it's `success`). Today it deploys any `origin/main` ref
   and `update.sh` only *warns* on an unhealthy boot. The ruleset gates **merges**, not the deploy poller.
4. Optional: **Settings → Advanced Security → CodeQL analysis → Set up → Default** — free on public repos,
   and worth having on an app holding payroll, national IDs and bank details. Leave it unrequired at first.

## P0‑2 · Make backups real, verified, and off‑box (VPS)
`backup.sh`/`restore.sh` are correct but **not installed** (the cron line is a comment) and fail open to
plaintext when the key is missing.
1. Create the AES key **once**, and copy it somewhere OFF the server (password manager):
   ```bash
   openssl rand -hex 32 > /opt/humiley/.backup-key && chmod 600 /opt/humiley/.backup-key
   ```
2. Install a nightly **systemd timer** (or cron) that runs `backup.sh` with `BACKUP_KEYFILE=/opt/humiley/.backup-key`.
3. Add an **off‑box copy** (rclone to OneDrive/S3/Backblaze) of the encrypted snapshot right after it's written.
4. **Verify at creation**, not only at restore: after each snapshot, run `PRAGMA integrity_check` + a row‑count
   sanity, and **fail‑closed if the key file is missing** (no silent plaintext dump of payroll/PII).
5. **Quarterly restore drill:** actually run `restore.sh` into a scratch dir and boot the app against it.

## P0‑3 · Escrow the `.env` crown jewels (off‑box)
Store these **off the VPS** (password manager / sealed vault) today — a lost disk is otherwise unrecoverable
even *with* a perfect DB backup:
`TK_ESIGN_PEPPER` (lose it → every enrolled e‑sign PIN is unverifiable), `TK_AUDIT_PEPPER` (keys the
tamper‑evident audit hash chain — set it once in the VPS `.env` with `openssl rand -hex 32`; lose or
change it → the audit trail can no longer be verified), `POSTGRES_PASSWORD` (lose it → the restored
Procurement DB is locked), `TK_SSO_SECRET`, and the `TK_M365_CLIENT_SECRET`.

## P0‑4 · Back up the **Procurement Postgres** + uploads (VPS) — currently 100% unbacked
`backup.sh` snapshots only the portal SQLite. `docker-compose.yml` also runs `procdb` (all PO/GRN, the
approval matrix, and Procurement's own Part‑11 e‑signature chain) and `proc_storage` (uploaded invoices/bills).
Add to your nightly job (encrypt + copy off‑box + restore‑test one):
```bash
docker exec humiley_proc_db pg_dump -U "${POSTGRES_USER:-procurement}" "${POSTGRES_DB:-humiley_procurement}" \
  | gzip | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/opt/humiley/.backup-key \
  > /opt/humiley/backups/proc_$(date +%F).sql.gz.enc
docker run --rm -v proc_storage:/data -v /opt/humiley/backups:/out alpine \
  tar czf /out/proc_storage_$(date +%F).tgz -C /data .
```

## P0‑5 · Move the live DB out of the OneDrive‑synced tree
`*.db`/`.env` are gitignored (good, not in git), but the working tree is under `OneDrive‑Humiley/…`. Any
local run writes `tk.db` (national IDs, bank details, salaries) into a folder that auto‑syncs plaintext PII
to consumer cloud. Set `TK_DB_PATH` to a path **outside** any synced folder, and exclude the DB path from
OneDrive selective‑sync. (Prod on the VPS is unaffected; this is about local/dev copies.)

---

## P1‑1 · Scrub PII + secrets from git history, then make the repo private ⚠️ irreversible
The public repo's **history** still contains real employee PII (`deliverables/pin-guides/*.docx`,
`deliverables/screenshots/02_employee_database.jpg` + `03_payroll.jpg`, and the now‑removed
`demo_data.json`). Deleting from HEAD (done) is **not** enough. This is a **destructive history rewrite +
force‑push** — Claude will not run it for you. Do it deliberately:
```bash
# 1) Mirror-clone a backup first:  git clone --mirror <repo> repo-backup.git
# 2) Install git-filter-repo, then from a fresh clone:
git filter-repo --path deliverables/pin-guides --path deliverables/screenshots \
                --path demo_data.json --invert-paths
# 3) Force-push all refs (coordinate with anyone who has a clone — everyone must re-clone):
git push --force --all && git push --force --tags
```
Then GitHub → **Settings → Danger Zone → Change visibility → Private** (strongly recommended for a repo
holding payroll/HR logic). Rotate any secret that ever touched a commit. If unsure, engage counsel — this is
a Vietnam PDPD (Decree 13/2023) exposure.

## P1‑2 · External, off‑box monitoring (survives a full‑host outage)
All current alerting fires from a daemon *inside* the app, so a kernel panic / disk‑full / OOM pages nobody.
- An **external uptime probe** of `https://portal.humiley.com/api/health` (UptimeRobot / healthchecks.io / a
  second cheap box).
- A **backup dead‑man's‑switch**: your nightly job pings a healthchecks.io URL on success; it alerts you if a
  night is missed.

## P1‑3 · M365 client‑secret expiry + rotation runbook
Entra client secrets expire (max ~24 months). Approval mail, invoice‑mailbox sync, digests, the monthly pack,
and overdue nudges all depend on `TK_M365_CLIENT_SECRET`, and the app checks it's *present*, not *valid* — so
on expiry every Graph call 401s **silently**.
✅ **The runbook is now written: [`docs/SECRET-ROTATION.md`](docs/SECRET-ROTATION.md)** — the 5‑minute
rotation procedure, verification steps, rollback, and (important) which secrets must **never** be rotated.
**Your remaining action:** open Entra, read the current secret's expiry date, write it into that doc, and
set a calendar reminder ~30 days before it.

## P1‑4 · Set the two production env flags
In the VPS `.env`:
- `TK_ESIGN_REQUIRE_VERIFIED_TOKEN=1` — so an e‑signature token is accepted only when its RS256 signature is
  fully verified (the app now warns at boot when this is unset).
- Decide on `portal_payerSeparation` (default **on**): the same person can no longer approve **and** pay a
  request — a second Editor/Admin must release payment. If your finance function is genuinely one person, an
  admin can set it to `0` in the portal's approval settings (paying your *own* request stays blocked either
  way). **Confirm you have ≥2 Editor/Admin users before relying on the default.**

## P1‑5 · Full‑host‑rebuild runbook + a stated RTO
✅ **The runbook is now written: [`docs/DISASTER-RECOVERY.md`](docs/DISASTER-RECOVERY.md)** — provision →
restore `.env` from escrow → build → restore both databases → DNS → TLS → M365, with a verification
checklist, the DNSSEC gotcha, and a quarterly drill. Stated **RTO 4 h / RPO 24 h** (RPO = the nightly
backup interval).
**Your remaining actions:** (1) **rehearse it once** — an unrehearsed recovery path is a hypothesis, not a
plan, and the RTO above is only credible after a real run; (2) close the honest gap it documents — the
Procurement Postgres + uploads are still unbacked (P0‑4), so today a full host loss loses that data.

---

*Generated from the 2026‑08 maturity audit. The code‑side items are already committed on `main` (not yet
deployed — deploy with `./deploy.sh` when ready).*
