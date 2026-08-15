# Staging — look at it before thirty people do

Every change so far has gone straight to production and been verified there. That worked while the
changes were small and each was checked, but it is not a habit that scales, and it is how a device
ends up running old code in front of the whole company.

Staging is a **second copy of the portal, on a copy of the live database**, reachable only by you.

## First run

On the VPS:

```bash
cd /opt/humiley-timekeeping
./staging.sh                      # from whatever is checked out
./staging.sh fix/some-branch      # or from a branch, before it is merged
```

It copies the live SQLite database into a separate Docker volume, builds the portal, and starts it
on `127.0.0.1:8100`.

From your laptop:

```bash
ssh -L 8100:127.0.0.1:8100 root@portal.humiley.com
```

then open <http://127.0.0.1:8100>.

## What makes it safe

| | |
|---|---|
| Production's volume | mounted **`:ro`** — the copy runs one way and cannot write back |
| Compose project | `humiley_staging` — its own containers, network and volume |
| Mail / webhooks | **blank**, so staging can never email an employee or a supplier |
| Port | `127.0.0.1` only — never published to the internet |
| E-sign pepper | its own, so a staging copy cannot verify real signature PINs |

`./staging.sh --fresh` re-copies production. `./staging.sh --down` stops it and keeps the data.

## ⚠️ It holds real data

A staging database is a full copy of everybody's salary, bank details and personal records. Treat it
exactly like production: never publish the port, never point it at a real mailbox, and delete the
volume when you are finished with it:

```bash
docker volume rm humiley_staging_humiley_data
```

## Serving it on a subdomain instead

If tunnelling is inconvenient, add a block to the `Caddyfile` — but only behind authentication, and
only with a DNS record you control:

```
staging.humiley.com {
    basic_auth { you <bcrypt-hash> }        # caddy hash-password
    reverse_proxy humiley_portal_staging:8000
}
```

The tunnel is the safer default. Use the subdomain only if several people need to review at once.

## Restoring a backup into it

The nightly encrypted backup has never been restore-tested. Staging is where to do that — it
exercises the backup and gives you a realistic environment at the same time. Restore into the
STAGING volume, never production, and confirm the row counts look right before trusting it.
