# Deploying the Humiley People & Workplace Portal

The app is a single Python process (standard library only) serving an HTML portal
backed by SQLite. It reads `$PORT` and binds `0.0.0.0`, so it runs on any host.

---

## Option A — Free always-on (Render) — recommended stopgap

A free, public HTTPS URL. (Free plan sleeps after ~15 min idle; the first visit
after a nap takes ~30–60s to wake, then it's instant.)

1. Go to **https://render.com** and sign in with **GitHub**.
2. **New ▸ Blueprint** → pick the **Humiley/humiley-timekeeping** repo → **Apply**.
   (Render reads `render.yaml` automatically — free plan, Singapore region.)
3. Wait ~2 min for the first build. You'll get a URL like
   `https://humiley-portal.onrender.com` that is public 24/7.

> Note: Render's free disk is ephemeral — the demo data re-seeds on each redeploy.
> That's fine for a demo; permanent data lives on Mat Bao (below).

---

## Option B — Permanent home: Mat Bao VPS / Cloud Server

> Use a **VPS / Cloud Server**, **not** shared cPanel "Hosting" — shared hosting
> runs PHP/MySQL and cannot run a long-lived Python server.

**Minimum sizing for this app:**

| Resource | Minimum | Comfortable |
|----------|---------|-------------|
| Disk (SSD) | 10 GB | **20 GB** |
| RAM | 1 GB | **2 GB** |
| vCPU | 1 | 1–2 |

The app + Python + Ubuntu use only a few GB; the rest is headroom for the SQLite
database, uploaded photos/attachments, logs, and backups.

### Run it with Docker (simplest, data persists)
```bash
# on the VPS, in the repo folder
docker build -t humiley .
docker run -d --name humiley \
  -p 80:8000 \
  -v humiley_data:/data \
  --restart unless-stopped \
  humiley
```
Open `http://YOUR_VPS_IP/`. Point your domain at the IP and add HTTPS with
Caddy or Nginx + Let's Encrypt (free).

### Or run it directly (no Docker)
```bash
sudo apt update && sudo apt install -y python3
git clone <repo> humiley && cd humiley
sudo TK_PORT=80 TK_DB_PATH=/var/lib/humiley.db python3 app.py
```
For auto-start on reboot, wrap it in a systemd service.

---

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `PORT` / `TK_PORT` | `8000` | Listen port |
| `TK_HOST` | `0.0.0.0` | Bind address |
| `TK_DB_PATH` | next to `db.py` | SQLite file location (point at a volume to persist) |

Leaving Microsoft 365 keys unset runs the portal in **DEMO mode** (Manager / Staff
quick-login). Set the M365 client ID/tenant to enable real sign-in.
