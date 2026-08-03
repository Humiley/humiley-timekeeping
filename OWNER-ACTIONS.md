# Owner Actions — the items only you can safely do

These close the highest‑severity gaps from the 2026‑08 maturity audit that live **outside the code** —
on the VPS, on GitHub, or as irreversible operations. Claude implemented everything doable in code
(see the recent commits); these need your hands because they touch production infrastructure, GitHub
settings, or history you must not have an agent force‑push.

Ordered by severity. **P0 = do this week.**

---

## P0‑1 · Turn on the CI gate (GitHub)
The workflows are now committed, but nothing enforces them yet.
1. GitHub → repo **Settings → Branches → Add branch protection rule** for `main`:
   - ✅ *Require status checks to pass before merging* → select **Backend tests (py3.9)** and **(py3.12)**.
   - ✅ *Require a pull request before merging* (so nothing lands on `main` unreviewed).
2. Make `autodeploy.sh` refuse a SHA whose CI isn't green before deploying (query the GitHub checks API for
   the commit status; only `docker compose up` when it's `success`). Today it deploys any `origin/main` ref
   and `update.sh` only *warns* on an unhealthy boot.
3. GitHub → **Settings → Code security → enable Secret scanning + Push protection** (this repo is public and
   auto‑deploys — one committed secret is both a permanent leak and instantly live).

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
`TK_ESIGN_PEPPER` (lose it → every enrolled e‑sign PIN is unverifiable), `POSTGRES_PASSWORD`
(lose it → the restored Procurement DB is locked), `TK_SSO_SECRET`, and the `TK_M365_CLIENT_SECRET`.

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
on expiry every Graph call 401s **silently**. Put the expiry date on a calendar reminder ~30 days out, and
write the 5‑minute rotation steps (Entra → new secret → update VPS `.env` → restart) next to it.

## P1‑4 · Set the two production env flags
In the VPS `.env`:
- `TK_ESIGN_REQUIRE_VERIFIED_TOKEN=1` — so an e‑signature token is accepted only when its RS256 signature is
  fully verified (the app now warns at boot when this is unset).
- Decide on `portal_payerSeparation` (default **on**): the same person can no longer approve **and** pay a
  request — a second Editor/Admin must release payment. If your finance function is genuinely one person, an
  admin can set it to `0` in the portal's approval settings (paying your *own* request stays blocked either
  way). **Confirm you have ≥2 Editor/Admin users before relying on the default.**

## P1‑5 · Full‑host‑rebuild runbook + a stated RTO
Write (and once rehearse) the steps to rebuild a lost VPS from zero: re‑provision, restore `.env`, restore
both databases, re‑consent the M365 secret, re‑point DNS, re‑issue the Caddy cert. Put a target **RTO** (how
long recovery takes) next to it — leadership will ask, and it's currently undefined.

---

*Generated from the 2026‑08 maturity audit. The code‑side items are already committed on `main` (not yet
deployed — deploy with `./deploy.sh` when ready).*
