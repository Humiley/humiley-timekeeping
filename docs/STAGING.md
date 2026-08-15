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

---

## Opening staging in a browser

`staging.sh` binds the container to `127.0.0.1:8100` on the server. That is reachable two ways, and
on this network only one of them works.

**An SSH tunnel needs outbound port 22.** The office network blocks it — which is exactly why
auto-deploy polls outward instead of accepting a connection. If you want to know whether your
current network allows it, run this **on your own computer** (not in the Vietnix console):

```
ssh -o ConnectTimeout=5 root@portal.humiley.com true && echo OK
```

`OK` means tunnelling works: `ssh -L 8100:127.0.0.1:8100 root@portal.humiley.com`, leave it open,
browse `http://127.0.0.1:8100`. A timeout means the port is blocked and no amount of retrying will
change it. Running either command in the browser console fails with `Address already in use`,
because there it is the server trying to forward a port to itself.

**The reliable path is HTTPS through the Caddy you already run.** Staging joins the same Docker
network as production, so Caddy can reach it by container name and serve it on a subdomain, on 443,
like the portal itself.

### One-time setup

1. **DNS** — add an `A` record for `staging.portal.humiley.com` pointing at the server's IP. Note
   the DNSSEC caveat in the production-deploy notes: if the zone's DNSSEC is broken, the name will
   not resolve and Let's Encrypt cannot validate it.

2. **The password gate.** Staging runs on a full copy of production: every salary, bank account and
   signed document. Generate a bcrypt hash on the server — the password is typed into a hidden
   prompt and is never stored:

   ```
   docker exec -it humiley_caddy caddy hash-password
   ```

   Keep the password in your password manager. The hash is not a usable credential; the password
   itself should never be sent to anyone, including me.

3. **The site file** — copy the template, fill in the domain and the hash:

   ```
   cp caddy.d/staging.caddy.example caddy.d/staging.caddy
   ```

   It is gitignored, so auto-deploy's `git pull` will not overwrite or remove it.

4. **Reload the edge:**

   ```
   docker exec humiley_caddy caddy reload --config /etc/caddy/Caddyfile
   ```

   `caddy reload` validates the new configuration *before* applying it. A syntax error is reported
   and the currently-running config keeps serving — a broken staging file cannot take
   portal.humiley.com down. Caddy requests the certificate on the first visit.

### Sign-in on staging

The portal itself still authenticates with Microsoft 365, and Entra only accepts redirects to URIs
registered on the app. If staging's sign-in fails, add `https://staging.portal.humiley.com` as a
redirect URI on the Entra app registration; without it the password gate opens and the portal login
then bounces.

### Taking it down

Delete `caddy.d/staging.caddy`, reload Caddy, then `./staging.sh --down`. When you are finished with
the data entirely, `docker volume rm humiley_staging_humiley_data` — it holds real personal data and
the disk is the smaller constraint of the two.
