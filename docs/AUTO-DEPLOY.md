# One-click (really: zero-click) deploy

Normal deploy is two manual steps: `git push` (from your laptop) **and** pasting `./deploy.sh` into
the Vietnix console (because the office blocks SSH port 22, so nothing can push *into* the VPS).

`autodeploy.sh` removes the second step. It runs **on the VPS** on a 2-minute timer, only makes
**outbound** `git fetch`/`pull` calls (so the blocked port 22 doesn't matter), and when it sees the
GitHub repo has moved it runs the same one-click `./deploy.sh` for you.

> **After the one-time install below, deploying is just `git push`.** The server picks it up within
> ~2 minutes and updates itself — Portal **and** Procurement.

---

## Install — paste ONCE in the Vietnix "Open Xterm.js Console"

The whole install runs as a single fail-fast `bash` block: if `git pull` fails (e.g. a dirty tree on
the VPS) it aborts **before** touching systemd, so you can never end up half-installed. The final line
kicks off an immediate deploy of whatever is currently on GitHub, so your pushed commits go live now
instead of waiting for the first tick (it blocks for the length of that first build — a few minutes).

```bash
bash <<'INSTALL'
set -euo pipefail
cd /opt/humiley-timekeeping
git pull --ff-only
chmod +x autodeploy.sh
cat >/etc/systemd/system/humiley-autodeploy.service <<'EOF'
[Unit]
Description=Humiley auto-deploy (poll GitHub, run ./deploy.sh on change)
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
TimeoutStartSec=1800
WorkingDirectory=/opt/humiley-timekeeping
ExecStart=/opt/humiley-timekeeping/autodeploy.sh
EOF
cat >/etc/systemd/system/humiley-autodeploy.timer <<'EOF'
[Unit]
Description=Humiley auto-deploy poll timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
AccuracySec=20s
Unit=humiley-autodeploy.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now humiley-autodeploy.timer
echo "timer installed — running the first deploy now (this can take a few minutes)…"
systemctl start humiley-autodeploy.service
echo "done — watch it with:  tail -f /root/humiley-backups/autodeploy.log"
INSTALL
```

## Everyday use

```bash
git push origin main
```

That's it. Within ~2 minutes the VPS rebuilds + restarts the stack itself. Watch a deploy land
(`cat -v`/`less`, not raw `cat` — the log holds unfiltered git/docker output):

```bash
tail -f /root/humiley-backups/autodeploy.log
```

## Manage it

```bash
systemctl list-timers humiley-autodeploy.timer   # next/last run
systemctl start humiley-autodeploy.service       # force a check right now
systemctl disable --now humiley-autodeploy.timer # turn auto-deploy OFF (back to manual ./deploy.sh)
```

## How it decides to deploy

* Fetches `origin/main` (Portal) and the Procurement repo's upstream (each bounded by a 120 s timeout),
  and compares the pair against the SHA pair in `/root/humiley-backups/autodeploy-last`.
* Equal → does nothing (cheap; the common case every 2 min).
* Different → runs `./deploy.sh` (which is `git pull --ff-only` → `./update.sh --bootstrap`: DB backup,
  build, migrate, restart, Caddy reload, health check — all idempotent), bounded by a 20-minute
  `timeout` so a wedged build can never hold the lock forever.
* The marker is written **only after a successful deploy**, and records the **actually-built** HEADs, so
  (a) a failed build automatically retries and (b) the first run after a fresh Procurement clone doesn't
  trigger a needless second rebuild.

## When a deploy keeps failing

A genuinely broken commit (bad `docker build`, or a dirty/divergent VPS tree that blocks
`git pull --ff-only`) does **not** hammer the server every 2 minutes. autodeploy.sh retries the *same*
failing commit with exponential backoff (2, 4, 8, 16, 32 min…), and after `AUTODEPLOY_MAX_TRIES`
(default 5) it **gives up until the next push** and drops a `/root/humiley-backups/autodeploy-ALERT`
file (something a monitor can watch for). Pushing a new commit clears the failure state and deploys
immediately. Check `autodeploy.log` for the reason, fix it, and push again.

## Notes / safety

* **No secrets, no inbound access.** It only fetches a **public** repo outbound (`GIT_TERMINAL_PROMPT=0`,
  so it can never hang on an auth prompt). Who can deploy = who can push to the GitHub repo (Humiley org
  write access). The manual flow already trusts the same thing; this just removes the human keystroke.
* Runs as **root** (same as when you paste `./deploy.sh`) — needs Docker + `/root/humiley-backups`.
* Tunables via environment (systemd `Environment=` or a drop-in): `AUTODEPLOY_MAX_TRIES`,
  `AUTODEPLOY_TIMEOUT`, `AUTODEPLOY_FETCH_TIMEOUT`, `DEPLOY_BRANCH`, `AUTODEPLOY_STATE`.
* Prefer cron over systemd? Drop the two unit files and instead:
  `( crontab -l 2>/dev/null; echo '*/2 * * * * /opt/humiley-timekeeping/autodeploy.sh' ) | crontab -`
  (autodeploy.sh has its own lock + timeouts, so a 2-minute cron is safe — but you lose systemd's
  boot-ordering and the `TimeoutStartSec` backstop.)
