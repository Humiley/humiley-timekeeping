# Updating the Live Portal (Vietnix VPS) — without losing data

The portal is **LIVE** at <https://portal.humiley.com> on the Vietnix VPS.
This is the routine "ship the latest changes" runbook. It updates **only the code** —
**all employees, attendance, claims, projects, devices, settings stay exactly as they are**.

> **Why your data is safe:** the SQLite database lives on a Docker named volume
> (`humiley_data` → `/data/timekeeping.db`). Rebuilding the app only replaces the
> program; the volume is left untouched. New code only *adds* tables/columns, never
> drops them. So you never lose what you've entered.

---

## Server facts (for reference)

| Thing | Value |
|-------|-------|
| URL | https://portal.humiley.com |
| VPS IP | 221.132.16.110 (Ubuntu 22.04) |
| App folder on server | `/opt/humiley-timekeeping` |
| App container | `humiley_portal` |
| Web/HTTPS container | `humiley_caddy` |
| Database (persists) | volume `humiley_data` → `/data/timekeeping.db` |
| Code source | GitHub `main` branch (server pulls from it) |

> The office network **blocks SSH (port 22)**. Connect via the **Vietnix browser console**:
> Vietnix panel → your VPS → **Open Xterm.js Console** → log in as `root`.

---

## ⚡ The easy way (one command)

After connecting (Step 0), just run the helper script — it does **backup → pull → rebuild →
health-check** for you:

```bash
cd /opt/humiley-timekeeping && git pull && ./update.sh
```

(The first `git pull` is only so you have the latest `update.sh`; after that, `./update.sh`
alone is enough since it pulls again internally.) Then hard-refresh your browser. ✅
The manual steps below are the same thing, broken out, in case you ever want to do it by hand.

---

## STEP 0 — Connect to the server

Vietnix panel → VPS → **Open Xterm.js Console** (browser terminal) → log in as `root`.

## STEP 1 — Back up the database first (safety net, ~2 seconds)

Always take a quick snapshot before updating, so you can roll back if anything looks wrong:

```bash
docker exec humiley_portal python3 -c "import sqlite3,os; s=sqlite3.connect(os.environ.get('TK_DB_PATH','/data/timekeeping.db')); d=sqlite3.connect('/data/_backup.db'); s.backup(d); d.close(); s.close()"
docker cp humiley_portal:/data/_backup.db /root/portal-backup-$(date +%F-%H%M).db
docker exec humiley_portal rm -f /data/_backup.db
ls -lh /root/portal-backup-*.db
```

(The last line just shows your saved backups.)

## STEP 2 — Pull the latest code + rebuild

```bash
cd /opt/humiley-timekeeping
git pull
docker compose up -d --build
```

- `git pull` downloads the new code from GitHub `main`.
- `docker compose up -d --build` rebuilds the app and restarts it. **The `humiley_data`
  volume (your database) is NOT rebuilt — your data stays.**

This takes ~1–3 minutes the first time, faster after.

## STEP 3 — Verify it's up

```bash
docker compose ps
curl -sI https://portal.humiley.com | head -1
```

- `docker compose ps` → both `humiley_portal` and `humiley_caddy` should say **Up**.
- The `curl` line should show **`HTTP/2 200`**.

## STEP 4 — Hard-refresh your browser

Open <https://portal.humiley.com> and press **Ctrl + Shift + R** (Windows) or
**Cmd + Shift + R** (Mac) so the browser loads the new version, not a cached one.
Log in and confirm your employees/data are all still there. Done. ✅

---

## If something looks wrong — roll back

**A) Roll back the CODE to the previous version** (data untouched):

```bash
cd /opt/humiley-timekeeping
git reset --hard HEAD~1        # undo the last pull (go back one release)
docker compose up -d --build
```

**B) Restore the DATABASE from a backup** (only if data got affected):

```bash
# pick the backup you want from:  ls -lh /root/portal-backup-*.db
docker cp /root/portal-backup-YYYY-MM-DD-HHMM.db humiley_portal:/data/timekeeping.db
docker restart humiley_portal
```

---

## Notes

- **Restart just the web layer** (rarely needed, e.g. after a cert/DNS change):
  `docker restart humiley_caddy`
- **Free up disk** from old image builds occasionally: `docker image prune -f`
- **Nightly automatic backups**: see `backup.sh` (Docker-aware online backup → host,
  gzip, 14-day retention). Add to cron once: `0 2 * * * /opt/humiley-timekeeping/backup.sh >> /var/log/humiley-backup.log 2>&1`
- If `git pull` ever complains about local changes on the server (it shouldn't —
  the server only pulls), reset to match GitHub then pull:
  `git reset --hard origin/main && git pull`
