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

## P0‑4 · Back up the **Procurement Postgres** + uploads — ✅ DONE (code side)
`backup.sh` now covers **both** databases. It `pg_dump`s `procdb` (all PO/GRN, the approval matrix and
Procurement's own Part‑11 e‑signature chain) using the container's own credentials, and tars
`proc_storage` (uploaded invoices/bills) — resolving the volume from the running container rather than
guessing its compose‑prefixed name. Both are encrypted with the same key and **decrypt‑verified**
before the plaintext is deleted. A `pg_dump` that succeeds but contains no tables is discarded and the
run exits non‑zero; a portal‑only install with no `procdb` skips it and still exits 0.
Restore with **`./restore-procurement.sh`** (validates before touching anything, keeps a pre‑restore
snapshot, `--dry-run` to check a snapshot changes nothing).

**Your remaining actions:**
1. **Install the nightly job** — this is still just a script on disk until cron runs it:
   ```bash
   ( crontab -l 2>/dev/null | grep -v 'backup.sh'; \
     echo '0 2 * * * /opt/humiley-timekeeping/backup.sh >> /var/log/humiley-backup.log 2>&1' ) | crontab - && crontab -l
   ```
2. ✅ **Off‑box copy is built** — `offsite.sh`, called automatically at the end of every `backup.sh`.
   It uploads ONLY the encrypted artefacts and can never carry `.backup-key` or a plaintext snapshot
   off the box, verifies by hash that the newest one actually landed, and prunes remote copies by age.
   **Your remaining action** — back up into **your own SharePoint**, which needs no new consent and
   no browser sign‑in. The portal already holds an app‑only Graph secret (that is how approved
   invoices reach the Finance folder), and `Sites.ReadWrite.All` is already granted.
   1. In SharePoint, make a folder for it — e.g. `Finance → Shared Documents → Portal Backups`.
      Restrict who can open it: it holds encrypted payroll and HR data.
   2. On the VPS, run this — it asks for the folder link and writes it into `.env` for you:
   ```bash
   cd /opt/humiley-timekeeping && ./setup-sharepoint-backup.sh
   ```
      Do **not** try to add the line by hand: the URL contains a space ("Shared Documents"), so
      pasting it as a shell command makes the shell split it in half.
   3. It finishes with a dry run. To copy for real, then check on it later:
   ```bash
   cd /opt/humiley-timekeeping && python3 backup_sharepoint.py
   cd /opt/humiley-timekeeping && python3 backup_sharepoint.py --status
   ```
   To use Tony's OneDrive instead, set `BACKUP_SP_USER=tony.nguyen@humiley.com` — but note that route
   needs `Files.ReadWrite.All`, a **broader** grant reaching every user's OneDrive. Prefer the
   SharePoint folder.

   ⚠️ Two things this does NOT protect against, worth knowing rather than discovering later:
   the `.backup-key` must live in a password manager, never in that same SharePoint — ciphertext plus
   key in one place is not encryption; and because the uploader uses the portal's own Graph secret, a
   full compromise of the VPS could also reach and delete these copies. That is still vastly better
   than no off‑box copy, but it is why a periodic manual download to somewhere the server cannot
   touch is worth doing.

   (`setup-b2.sh` + `offsite.sh` remain available if you ever want a provider outside M365.)

## P0‑5 · Move the live DB out of the OneDrive‑synced tree
`*.db`/`.env` are gitignored (good, not in git), but the working tree is under `OneDrive‑Humiley/…`. Any
local run writes `tk.db` (national IDs, bank details, salaries) into a folder that auto‑syncs plaintext PII
to consumer cloud. Set `TK_DB_PATH` to a path **outside** any synced folder, and exclude the DB path from
OneDrive selective‑sync. (Prod on the VPS is unaffected; this is about local/dev copies.)

---

## P1‑1 · The public repo still contains employee PII ⚠️ read the ORDER before doing anything

**Corrected 2026‑08‑07** after checking the repository directly. The previous version of this section
was wrong in ways that mattered, and following it verbatim would have produced a false sense of
remediation while breaking production.

**What is actually true**
- The repo **is public** (`Humiley/humiley-timekeeping`, 563 commits, 0 forks).
- **HEAD is NOT clean.** Commit `0b7fc20` removed only 5 demo files from the repo root. Still tracked
  today: `deliverables/pin-guides/*.docx` (15 files, each named after a real person),
  `deliverables/screenshots/*.jpg` (15 files — all show a real name and job title in the sidebar;
  two also show roster and payroll content), `seed_data.py` (15 real employees with phone, DOB, tax
  ID, bank and address) and `import_csv.py` (a real name→mailbox table).
- **One earlier claim was overstated, and the correction matters:** the removed `demo_data.json` had
  bank, tax‑ID and salary fields **empty for all 54 records**. It carried names, work emails, 53
  dates of birth and 6 personal IDs. Bad, but not the payroll dump it was described as.
- Also present and invisible to any name/email search: a **real personal name in the XMP metadata**
  of the base64 logo embedded in `templates/index.html`, and author metadata (`dc:creator`) in 18
  tracked Office files.
- **Neither `git-filter-repo` nor BFG is installed** on this Mac, and there is no Java runtime.

**Do it in this order. The order is the whole point.**

1. **Fix the VPS credentials FIRST — before making the repo private.** The server pulls over plain
   HTTPS with no token. The moment the repo turns private, `git pull` returns 403, `deploy.sh` exits
   1, and `autodeploy.sh` gives up permanently after five tries. Add a read‑only deploy key or a
   fine‑grained PAT to the remote URL on the VPS, and do the same for the `humiley-procurement`
   clone that `update.sh` also pulls. Verify with a manual `git -C /opt/humiley-timekeeping pull`.
2. **Take a mirror backup**, onto a disk outside the OneDrive‑synced tree:
   ```bash
   git clone --mirror https://github.com/Humiley/humiley-timekeeping.git repo-backup.git
   ```
3. **Make the repo private.** GitHub → Settings → Danger Zone → Change visibility → Private. This is
   the highest‑value single action and it is not destructive. It ends the public exposure of
   everything at once — history, HEAD, and the pull refs — which a history rewrite alone does **not**
   do (see step 5).
4. **Clean HEAD.** This is an ordinary commit and needs no rewrite:
   ```bash
   git rm -r --cached deliverables/pin-guides deliverables/screenshots   # already in .gitignore; files stay on disk
   ```
   then replace the 15 real records in `seed_data.py` with synthetic ones and strip the real
   name→mailbox tables in `import_csv.py`.
5. **Only then consider a history rewrite — and know its limit.** There are **9 open PRs**, and
   GitHub keeps their commits reachable under `refs/pull/*` regardless of a force‑push. Close them
   and delete the `snapshot/pre-session-2026-06-25` branch (it still carries `demo_data.json` and the
   1.8 MB `Humiley-Portal-DEMO.html`) **before** rewriting, or the rewrite erases nothing. You would
   also need to install the tool first (`brew install git-filter-repo`), widen the path list well
   beyond what this document used to say — add `seed_data.py`, `import_csv.py`,
   `Humiley-Portal-DEMO.html` — and use `--replace-text` for addresses embedded in
   `templates/index.html` rather than deleting the file. Afterwards, repair the VPS with
   `git fetch origin && git reset --hard origin/main` (never `rm -rf` that directory — `.env` lives
   there, and regenerating `TK_ESIGN_PEPPER` invalidates every enrolled signing PIN), and ask GitHub
   Support to garbage‑collect the orphaned objects, without which the old commits stay fetchable by
   SHA.
6. **The disclosure question is separate and does not go away.** Named employees' dates of birth,
   personal IDs and work addresses were publicly available for roughly seven weeks. That is a Vietnam
   PDPD (Decree 13/2023) matter; a rewrite does not undo it. Engage counsel, and reconcile whatever
   is decided with `static/privacy.html`, which currently says nothing about it.

## P1‑1b · Microsoft 365 consent for offboarding, and the two classifications ✅ screens now exist

**Granting the Microsoft permissions.** Revoking a leaver's Microsoft access needs application
permissions the portal did not previously ask for. I originally told you to grant
`User.ReadWrite.All`; **that was wrong**, and Microsoft's own tables are the reason:

| What it does | Application permission required |
|---|---|
| Revoke sign‑in sessions (kills issued refresh tokens) | **`User.RevokeSessions.All`** — `User.ReadWrite.All` is listed as *"Not available"* for app‑only |
| Block sign‑in (`accountEnabled = false`) | **`User.EnableDisableAccount.All` + `User.Read.All`** (least privilege), or the broader `User.ReadWrite.All` |
| Read whether an account is still enabled (the "Access still open" register) | `User.Read.All` |

Entra admin centre → **App registrations** → the Humiley portal app → **API permissions** → **Add a
permission** → **Microsoft Graph** → **Application permissions** → add the three above → **Grant
admin consent for Humiley**.

⚠️ **Blocking sign‑in also needs a directory role, which no permission grant provides.** Microsoft
treats `accountEnabled` as a sensitive action: in app‑only scenarios the app itself must additionally
hold a privileged administrator role. Entra → **Roles and administrators** → **User Administrator** →
**Add assignments** → choose the portal's application. Without it the step fails with
`Authorization_RequestDenied`. The portal cannot see directory roles in its token, so it says so
plainly on the step rather than pretending to have checked.

**To verify it worked:** Access & Permissions → **Integrations & health** → the *Microsoft Graph
permissions* row lists exactly what is granted and names anything still missing. It now re‑reads with
a fresh token when something looks unconsented — a token minted before consent is cached for up to an
hour, so this screen used to tell you your consent had not worked for the rest of that hour.

**The two statutory classifications.** These had no input anywhere in the portal, so every employee
read as normal‑conditions office staff to both the leave and the certificate reviews. They are now on
**Human Resource Hub → Employees → Edit** (Admin only — they are legal classifications, not fields a
line manager edits):

- **Working conditions** — Normal (12 days annual leave) / Heavy, hazardous, dangerous (14) /
  Especially heavy (16), per Art. 113(1). It also moves the health‑check cadence from 12 months to 6.
  Classify against the MOLISA occupational list, not against job titles.
- **OSH group** — Decree 44/2016 Art. 24, groups 1–6. Safety training is required and chased **only**
  where a group is set; blank asserts the requirement for nobody.
- **Person with disabilities** — raises the leave base to at least 14 days.
- **Fixed‑term renewal exemption** — the Art. 20(2)(c) case that applies (elderly / foreign worker /
  appointed state‑enterprise director / union officer), or "not exempt". It records *which*, because
  that is what an inspector asks.
- **Bank details** — name, account, holder, branch. All four employees' salary files depend on these.

**The bank file layout.** Also previously unreachable — it was a setting nothing could set, so "your
bank's template" was whatever had been guessed. Now at Access & Permissions → **Integrations &
health** → **Bank salary‑file layout**: pick the columns and headings your bank publishes, with a live
preview of the file's first line. Download your bank's own sample (Techcombank F@st EBank:
**Payroll → Bulk transfer → Download template**) and copy the headings exactly — banks match on the
heading text. Admin only, audited, and it refuses a layout with no amount column or an unknown field.

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
Procurement Postgres + uploads are now covered by backup.sh / restore-procurement.sh (P0‑4) — but the
nightly job still has to be INSTALLED on the VPS, and the restore still has to be rehearsed once.

---

*Generated from the 2026‑08 maturity audit. The code‑side items are already committed on `main` (not yet
deployed — deploy with `./deploy.sh` when ready).*
