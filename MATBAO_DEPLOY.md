# Deploy the Humiley Portal on Mat Bao "Deploy" (tinhgon PaaS)

The app is a Python `http.server` (single `app.py`) with a **SQLite** database and a
**Dockerfile**. A fresh start is **clean**: one admin account, **no demo data**, live
Microsoft 365 login. (Verified: fresh DB → 1 employee `HML-001`, 0 collection rows,
`seed_disabled=1`, `demo=false`.)

---

## ⚠️ STEP 0 — Confirm 3 things first (make‑or‑break)

The Mat Bao Deploy wiki doesn't document these. Check them in the dashboard or ask
**Mat Bao support (1900 1830)** BEFORE you commit real data:

1. **Runtime — does Deploy build/run a Dockerfile?** (or at least auto‑run a Python app?)
   Our repo has a `Dockerfile`; that's the cleanest path. If it only runs Node/PHP/static,
   Deploy is the wrong product → use a **Mat Bao VPS / Cloud Server** instead (see "Plan B").
2. **Persistent storage — does the app's disk survive a *Redeploy*?** This is the biggest risk.
   Our data lives in a SQLite file at `/data/timekeeping.db`. If Deploy wipes the container
   filesystem on each redeploy (typical for this kind of PaaS), **all HR/payroll data is lost
   every deploy.** You need a **persistent disk/volume** mounted at a path you control. If there
   is none, use Plan B (VPS) — don't run real users without confirmed persistence.
3. **Environment variables — is there an ENV / "biến môi trường" field?** Not required (we baked
   safe defaults into the Dockerfile), but you'll want it to point the DB at the persistent path
   and to change the admin email.

> Good news already confirmed from the wiki: Deploy gives **automatic HTTPS/SSL + a subdomain +
> custom‑domain binding**. So you do **not** need your own reverse proxy — the platform terminates
> TLS and routes to the app. The app serves plain HTTP inside; that's correct here.

---

## STEP 1 — Deploy from GitHub

1. Log in to the Mat Bao **Deploy** dashboard → **+ Thêm Website** (Deploy Website).
2. Source = **GitHub** → authorize → pick repo **`Humiley/humiley-timekeeping`**, branch **`main`**.
   (Or use **Git URL** with the repo's HTTPS clone URL.)
3. If a runtime/build screen appears, choose **Docker / Dockerfile**. Port: our app honors an
   injected `PORT`, and the Dockerfile `EXPOSE 8000` — if it asks, use **8000**.
4. **Environment variables** (only if the field exists — otherwise the Dockerfile defaults apply):
   | Key | Value | Why |
   |---|---|---|
   | `TK_DB_PATH` | the **persistent** mount path, e.g. `/data/timekeeping.db` | keep data across redeploys |
   | `TK_ADMIN_EMAIL` | your real M365 admin, e.g. `tony.nguyen@humiley.com` | first admin = this email |
   | `TK_ADMIN_NAME` | `Tony Nguyen` | display name |
   | `TK_BOOTSTRAP_ADMIN` | `1` | bootstrap one clean admin (already baked) |
   | **do NOT set** `TK_ALLOW_SEED` | — | leaving it unset keeps demo data OFF |
5. **Attach persistent storage** at the path you set in `TK_DB_PATH` (Step 0.2). If Deploy can't,
   stop and use Plan B.
6. **Deploy** → wait for *Build → configure env → run server → issue SSL*. You get a subdomain.
7. Open the subdomain. You should see the **login screen with the Microsoft 365 button** and no
   demo data. If the build fails, use **"Xem log lỗi"** (view error logs) and send me the log.

---

## STEP 2 — Wire Microsoft 365 to the live URL (so login works)

1. **portal.azure.com → Entra ID → App registrations → "Humiley Portal"** (clientId
   `8810a31e‑788a‑4f96‑881c‑c522fdc5b338`) → **Authentication**.
2. Under **Single‑page application → Redirect URIs**, add your live address **with NO trailing slash**
   (must match the browser's origin exactly):
   - the Mat Bao subdomain, e.g. `https://humiley-portal.tinhgon.xyz`
   - and your custom domain later, e.g. `https://portal.humiley.com`
3. **API permissions** → ensure a **Global Admin** has granted admin consent for
   `User.Read`, `Sites.ReadWrite.All`, `Mail.Send`, `User.Read.All`.
4. Open the live URL → **Sign in with Microsoft 365** as **tony.nguyen@humiley.com** → you land on
   the Company Dashboard as **Admin** (the only account so far).

> A user can only sign in if their `@humiley.com` email already exists as an employee — otherwise
> they get *"No employee record."* So add your team next (Step 3).

---

## STEP 3 — Add your team

As Admin: **People & Talent → Employee Database** → either **Sync from Microsoft 365**, or
**Import (Excel/CSV)**, or **Add** each person (email must match their M365 sign‑in). Set each
person's **Access & Permissions** level under **System Setting → Access & Permissions**.

---

## STEP 4 — Custom domain (optional)

Deploy dashboard → **Thêm tên miền mới** → create a DNS record (**CNAME** for a subdomain like
`portal.humiley.com`, or **A** for a root) pointing to the value Mat Bao shows → **Kiểm tra DNS** →
**Kích hoạt domain này** → wait for automatic SSL. Then add that URL to the Entra redirect URIs
(Step 2.2).

---

## STEP 5 — Backups

Once persistent storage is confirmed, schedule **`backup.sh`** (daily `sqlite3 .backup`, see the
script) via the platform's scheduler/cron if available, and copy snapshots off‑box (OneDrive). If
the host has no cron, run `backup.sh` from any machine that can reach the DB volume, or take
periodic manual snapshots. `restore.sh` documents the restore runbook.

---

## Plan B — Mat Bao VPS / Cloud Server (use if Deploy can't run Docker or can't persist data)

A VPS is the most reliable home for a SQLite app (full disk, Docker, cron). On the VPS:

```bash
# one-time
sudo apt-get update && sudo apt-get install -y docker.io git
git clone https://github.com/Humiley/humiley-timekeeping.git && cd humiley-timekeeping

# build + run with a PERSISTENT named volume (data survives redeploys)
docker build -t humiley-portal .
docker run -d --name humiley_portal --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v humiley_data:/data \
  -e TK_ADMIN_EMAIL=tony.nguyen@humiley.com \
  humiley-portal

# HTTPS: put Caddy in front (auto Let's Encrypt) — /etc/caddy/Caddyfile:
#   portal.humiley.com {
#       reverse_proxy 127.0.0.1:8000
#   }
sudo apt-get install -y caddy && sudo systemctl restart caddy
```

To update later: `git pull && docker build -t humiley-portal . && docker rm -f humiley_portal && docker run … ` (the named volume `humiley_data` keeps all data). Add `backup.sh` to cron.

---

### Verify after deploy
- [ ] Live URL shows the login (no demo data) and **demo=false** at `/api/config`.
- [ ] M365 sign‑in works for the admin and lands on the dashboard.
- [ ] **Redeploy once, then re‑check the data is still there** (proves persistence — do this before onboarding anyone).
- [ ] SharePoint folder/upload works (M365 Graph) on the live origin.
