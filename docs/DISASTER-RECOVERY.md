# Disaster Recovery — rebuilding the Humiley Portal from zero

The runbook for "the VPS is gone." Follow it top to bottom. It assumes you have **nothing** but this
repo (public on GitHub) and your off-box secret/backup escrow.

> **Rehearse this at least once.** A recovery path that has never been executed is a hypothesis, not a
> plan. The first real run is always slower than the steps suggest.

---

## Recovery objectives

| | Target | What it actually depends on |
|---|---|---|
| **RTO** (time to be back online) | **4 hours** | Mostly the Docker build (~25–30 min on a 2-core VPS) + DNS/TLS propagation. A practised run with secrets at hand is ~2 h; 4 h is the committed target with buffer. |
| **RPO** (acceptable data loss) | **24 hours** | The portal SQLite backup is **nightly**. Anything entered after the last successful snapshot is lost. Tighten by running `backup.sh` more often. |

⚠️ **Known gap — Procurement Postgres.** `backup.sh` snapshots only the portal SQLite. The `proc_db`
(all PO/GRN, approval matrix, Procurement's own e-signature chain) and `proc_storage` (uploaded
invoices) volumes are **not yet backed up** — see `OWNER-ACTIONS.md` P0-4. Until that is installed, a
full-host loss means **Procurement data is unrecoverable**. Fix that before relying on this runbook.

---

## What you must have OFF the server (verify quarterly)

If these are only on the VPS, this runbook cannot work.

1. **The encrypted DB snapshots** — off-box copy (rclone → OneDrive/S3). See `backup.sh`.
2. **The backup encryption key** — `/root/humiley-backups/.backup-key`. *Lose it and every encrypted
   snapshot is landfill.*
3. **The `.env` crown jewels** (password manager / sealed vault):
   - `TK_ESIGN_PEPPER` — lose it → every enrolled e-signature PIN stops verifying.
   - `TK_AUDIT_PEPPER` — lose it → the audit hash chain can no longer be verified.
   - `POSTGRES_PASSWORD` — lose it → the restored Procurement DB is locked.
   - `TK_SSO_SECRET`, `AUTH_SECRET`, `ESIGN_SIGNING_SECRET`, `TK_M365_CLIENT_SECRET`.
4. **Domain/DNS access** (Mat Bao) and **Entra (M365) admin** access.

---

## Rebuild procedure

### 1 · Provision the host (~15 min)
Ubuntu 22.04 LTS, ≥2 vCPU / 4 GB RAM / 40 GB disk, public IPv4.
Note the new IP. (If the first boot drops to `(initramfs)`, reboot from the provider panel.)

### 2 · Get the code (~5 min)
```bash
apt update && apt install -y git
git clone https://github.com/Humiley/humiley-timekeeping.git /opt/humiley-timekeeping
cd /opt/humiley-timekeeping
```

### 3 · Restore `.env` from escrow (~5 min) — **before** any build
Recreate `.env` with the escrowed values. **Do not let `update.sh` generate fresh secrets** — new
values would orphan every existing e-signature PIN, break audit-chain verification, and lock the
restored Procurement DB.
```bash
cat > .env <<'EOF'
PORTAL_DOMAIN=portal.humiley.com
TK_ADMIN_EMAIL=tony.nguyen@humiley.com
TK_ESIGN_PEPPER=<from escrow>
TK_AUDIT_PEPPER=<from escrow>
TK_SSO_SECRET=<from escrow>
AUTH_SECRET=<from escrow>
ESIGN_SIGNING_SECRET=<from escrow>
POSTGRES_PASSWORD=<from escrow>
TK_M365_CLIENT_SECRET=<from escrow — rotate if expired, see SECRET-ROTATION.md>
TK_ESIGN_REQUIRE_VERIFIED_TOKEN=1
EOF
chmod 600 .env
```

### 4 · Bring the stack up (~30 min — the long pole)
```bash
./update.sh --bootstrap      # installs Docker if needed, builds portal + procurement, migrates, seeds
```
This is the slow step (two image builds). Let it finish; don't interrupt.

### 5 · Restore the portal database (~5 min)
```bash
# fetch the newest encrypted snapshot from off-box storage first, then:
./restore.sh /root/humiley-backups/timekeeping-<STAMP>.db.gz.enc
docker compose restart app
```
`restore.sh` auto-decrypts `.enc` and decompresses `.gz`. It needs the backup key from escrow.

### 6 · Restore Procurement Postgres (~10 min) — *only once P0-4 backups exist*
```bash
gunzip -c proc_<DATE>.sql.gz.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/opt/humiley/.backup-key \
  | docker exec -i humiley_proc_db psql -U procurement -d humiley_procurement
docker restart humiley_proc_app
```

### 7 · Re-point DNS (~10 min + propagation)
Mat Bao DNS → `portal.humiley.com` **A record** → the new IP.
⚠️ **DNSSEC:** `humiley.com` previously had broken DNSSEC that made Let's Encrypt refuse to issue
(CAA lookup `SERVFAIL`). If the cert won't issue, check `dig humiley.com DS` — it should be empty.

### 8 · TLS
Caddy issues automatically once DNS resolves to the new box. Watch it:
```bash
docker logs -f humiley_caddy
```

### 9 · Re-consent M365 (if the secret was rotated)
See `docs/SECRET-ROTATION.md`. Also confirm the Entra app's SPA redirect URI is still
`https://portal.humiley.com` (no trailing slash).

---

## Verification — don't declare recovery until all pass

```bash
# 1. App healthy + DB attached
curl -s https://portal.humiley.com/api/health          # {"status":"ok","db":true,...}

# 2. Data actually restored (not an empty bootstrap DB)
docker exec humiley_portal python3 -c \
  "import sqlite3;print(sqlite3.connect('/data/timekeeping.db').execute('select count(*) from employees').fetchone())"

# 3. Audit chain still verifies under the restored pepper  (admin session required)
#    Portal → Audit Log → the badge must read "Chain verified", not "Reseal required".

# 4. Procurement reachable
curl -s -o /dev/null -w '%{http_code}\n' https://portal.humiley.com/procurement
```
Then, in the UI: sign in with M365, open Payroll, and confirm an e-signature still validates.

---

## Quarterly drill (30 min, no production impact)

Restore the newest snapshot into a throwaway path and prove it opens:
```bash
TK_DB_PATH=/tmp/drill.db ./restore.sh <newest.enc>
docker run --rm -v /tmp/drill.db:/data/timekeeping.db humiley_portal python3 -c \
  "import sqlite3; print(sqlite3.connect('/data/timekeeping.db').execute('select count(*) from employees').fetchone())"
```
Record the date you last did this. If it's been more than a quarter, your RTO above is fiction.
