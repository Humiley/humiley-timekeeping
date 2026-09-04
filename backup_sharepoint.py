#!/usr/bin/env python3
"""Copy the encrypted backups off this server into SharePoint (or a user's OneDrive) via Graph.

Why this instead of rclone: the portal already authenticates to Microsoft Graph with an APP-ONLY
secret (client credentials) — that is how approved invoices land in the Finance SharePoint folder.
App-only means there is no browser sign-in to complete, which is exactly where the rclone/OneDrive
attempt stalled on a headless VPS. Sites.ReadWrite.All is already consented for this app, so backing
up to a SharePoint document library needs no new permission at all.

Deliberately STANDALONE — stdlib only, and it does NOT import app.py. Backup tooling that depends on
the application being importable and healthy is tooling that fails exactly when you need it. It also
has to run on the HOST, because that is where backup.sh writes the snapshots.

  ./backup_sharepoint.py                 upload + verify + prune
  ./backup_sharepoint.py --dry-run       list what WOULD upload, change nothing
  ./backup_sharepoint.py --status        what is already off-box, and how old

Configure in /opt/humiley-timekeeping/.env:
  BACKUP_SP_URL=https://humiley.sharepoint.com/sites/<Site>/Shared Documents/Portal Backups
      A SharePoint folder link — paste it from the browser address bar. Uses Sites.ReadWrite.All,
      which this app already has.
  BACKUP_SP_USER=tony.nguyen@humiley.com          (alternative to BACKUP_SP_URL)
      Uploads to that user's OneDrive instead. NOTE: this needs Files.ReadWrite.All application
      consent, which is a BROADER grant than the SharePoint route — it reaches every user's OneDrive
      in the tenant, not one library. Prefer BACKUP_SP_URL unless you have a reason not to.
  BACKUP_SP_RETAIN=90                             delete off-box copies older than N days (0 = keep)

Needs only TK_M365_CLIENT_SECRET in .env — the tenant and client IDs fall back to the same values
app.py bakes in, so a correctly configured server needs nothing extra.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/root/humiley-backups")
GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK = 8 * 320 * 1024          # 2.5 MiB — Graph requires upload chunks to be a multiple of 320 KiB

# Only ENCRYPTED artefacts ever leave this box. The key and every plaintext form are excluded by
# construction rather than by a filter that could be loosened later: we match on these suffixes only.
WANTED = (".db.gz.enc", ".sql.gz.enc", ".tgz.enc")


def _env():
    """Read .env without executing it — a backup script must never source arbitrary shell."""
    out = dict(os.environ)
    path = os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
    return out


def die(msg, code=1):
    sys.stderr.write("\033[1;31m✖ %s\033[0m\n" % msg)
    sys.exit(code)


def say(msg):
    print("\n\033[1;34m==>\033[0m %s" % msg)


def ok(msg):
    print("\033[1;32m  ✓ %s\033[0m" % msg)


def _req(url, token=None, method="GET", data=None, ctype=None, extra=None, timeout=120):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if ctype:
        headers["Content-Type"] = ctype
    headers.update(extra or {})
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


def _err(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            j = json.loads(e.read().decode("utf-8", "replace"))
            return "%s %s" % (e.code, (j.get("error") or {}).get("message") or j)
        except Exception:
            return "HTTP %s" % e.code
    return str(e)


# app.py bakes the tenant and client IDs in as defaults (they are public SPA identifiers), so a real
# deployment only carries the SECRET in .env. Mirror that exactly — demanding all three in .env made
# this script refuse to run on a correctly configured server.
DEF_TENANT = "2a586c8f-fc2f-4c59-be46-938adfa3579c"
DEF_CLIENT = "8810a31e-788a-4f96-881c-c522fdc5b338"


def token(env):
    tid = env.get("TK_M365_TENANT_ID") or DEF_TENANT
    cid = env.get("TK_M365_CLIENT_ID") or DEF_CLIENT
    sec = env.get("TK_M365_CLIENT_SECRET", "")
    if not sec:
        die("TK_M365_CLIENT_SECRET is not set in .env.\n"
            "   That is the same secret the portal uses to send approval mail and file invoices into\n"
            "   SharePoint, so if those work it should already be there — check with:\n"
            "     grep -c TK_M365_CLIENT_SECRET /opt/humiley-timekeeping/.env")
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec,
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode()
    try:
        j = _req("https://login.microsoftonline.com/%s/oauth2/v2.0/token" % tid, method="POST",
                 data=body, ctype="application/x-www-form-urlencoded", timeout=30)
    except Exception as e:
        die("could not get a Microsoft Graph token: %s\n"
            "   If this says 'invalid_client', the client secret has EXPIRED — see docs/SECRET-ROTATION.md."
            % _err(e))
    if not j.get("access_token"):
        die("Graph returned no access_token")
    return j["access_token"]


def granted_roles(tok):
    """The application permissions this token actually carries.

    An app-only access token lists its granted roles in the `roles` claim. Reading them turns
    "403 Forbidden" — which tells you nothing about WHICH permission is missing — into a definite
    answer. Decoded locally without verification: we are reading our own token for diagnosis, not
    trusting it for authorisation."""
    try:
        import base64
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return sorted(json.loads(base64.urlsafe_b64decode(payload)).get("roles") or [])
    except Exception:
        return []


SITE_ROLES = ("Sites.ReadWrite.All", "Sites.Manage.All", "Sites.FullControl.All", "Sites.Selected")


def _permission_help(tok, kind="SharePoint"):
    roles = granted_roles(tok)
    need = SITE_ROLES if kind == "SharePoint" else ("Files.ReadWrite.All",)
    msg = ["", "  This app's granted application permissions are:",
           "      " + (", ".join(roles) if roles else "(none)")]
    if not any(r in roles for r in need):
        msg += ["",
                "  None of these is present: " + ", ".join(need),
                "  That is why Graph returns 403 — the permission simply is not granted.", ""]
        if kind == "SharePoint":
            msg += [
                "  Fix it in Entra → App registrations → (the portal app) → API permissions →",
                "  Add a permission → Microsoft Graph → APPLICATION permissions. Two options:",
                "",
                "    Sites.Selected      RECOMMENDED. Grants nothing by itself; an admin then",
                "                        authorises this app on ONE site only. Least privilege.",
                "    Sites.ReadWrite.All Simpler, but grants read/write to EVERY SharePoint site",
                "                        in the tenant. Only choose this if that is acceptable.",
                "",
                "  Then click 'Grant admin consent for <tenant>'. Consent is what actually applies it —",
                "  adding the permission without granting is the most common reason this stays 403.",
                "",
                "  If you pick Sites.Selected, an admin must also authorise this specific site once:",
                "    PATCH https://graph.microsoft.com/v1.0/sites/{siteId}/permissions",
                "  or via the SharePoint admin PowerShell (Grant-PnPAzureADAppSitePermission).",
            ]
    else:
        msg += ["", "  The needed permission IS granted, so a 403 here usually means either the consent",
                "  was added but never granted (check for the warning triangle in Entra), or the token",
                "  was minted before consent — this script gets a fresh token each run, so re-run it."]
    return "\n".join(msg)


def _parse_sp_folder(url):
    """SharePoint folder URL → (host, /sites/<Site>, folder-relative-path). Accepts the clean path
       and the browser's ?id=… view URL, which is what an admin usually copies."""
    pu = urllib.parse.urlparse(url)
    if not pu.netloc:
        raise ValueError("expected a full https://<tenant>.sharepoint.com/... link")
    qs = urllib.parse.parse_qs(pu.query or "")
    src = ""
    for key in ("id", "RootFolder", "rootfolder"):
        if qs.get(key):
            src = qs[key][0]
            break
    parts = [urllib.parse.unquote(p) for p in (src or pu.path).split("/") if p]
    while parts and (parts[-1].lower().endswith(".aspx") or parts[-1].lower() == "forms"):
        parts = parts[:-1]
    if len(parts) < 2 or parts[0].lower() != "sites":
        raise ValueError("expected .../sites/<Site>/Shared Documents/<Folder>")
    rest = parts[2:]
    if rest and rest[0].lower() in ("shared documents", "documents"):
        rest = rest[1:]
    return pu.netloc, "/sites/" + parts[1], "/".join(rest)


def target(env, tok):
    """Resolve where to upload → (drive_id, folder_rel, human_label)."""
    url = (env.get("BACKUP_SP_URL") or "").strip()
    user = (env.get("BACKUP_SP_USER") or "").strip()
    if url:
        host, site_path, rel = _parse_sp_folder(url)
        site = _req("%s/sites/%s:%s" % (GRAPH, host, site_path), tok)
        drive = _req("%s/sites/%s/drive" % (GRAPH, site["id"]), tok)
        return drive["id"], rel, "SharePoint %s/%s" % (site_path, rel)
    if user:
        drive = _req("%s/users/%s/drive" % (GRAPH, urllib.parse.quote(user)), tok)
        return drive["id"], "Portal Backups", "OneDrive of " + user
    die("Neither BACKUP_SP_URL nor BACKUP_SP_USER is set in .env — nothing to upload to.\n"
        "   Add one, e.g.:\n"
        "     BACKUP_SP_URL=https://humiley.sharepoint.com/sites/Finance/Shared Documents/Portal Backups")


def _enc_path(rel, name):
    p = ("%s/%s" % (rel, name)) if rel else name
    return urllib.parse.quote(p)


def upload(drive_id, rel, tok, path, name):
    """Upload one file. Small files go in a single PUT; anything larger uses a chunked upload session,
       which is required past ~4 MB and is the whole point for a multi-hundred-MB database snapshot."""
    size = os.path.getsize(path)
    dest = _enc_path(rel, name)
    if size <= 4 * 1024 * 1024:
        with open(path, "rb") as fh:
            return _req("%s/drives/%s/root:/%s:/content" % (GRAPH, drive_id, dest), tok,
                        method="PUT", data=fh.read(), ctype="application/octet-stream", timeout=300)
    sess = _req("%s/drives/%s/root:/%s:/createUploadSession" % (GRAPH, drive_id, dest), tok,
                method="POST", ctype="application/json",
                data=json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode())
    up = sess.get("uploadUrl")
    if not up:
        raise ValueError("Graph returned no uploadUrl")
    done = {}
    with open(path, "rb") as fh:
        sent = 0
        while sent < size:
            buf = fh.read(CHUNK)
            if not buf:
                break
            last = sent + len(buf) - 1
            # Transient 5xx / throttling mid-upload is normal on a long transfer; retry the CHUNK
            # rather than restarting a 200 MB file from zero.
            for attempt in range(4):
                try:
                    done = _req(up, method="PUT", data=buf, timeout=300, extra={
                        "Content-Length": str(len(buf)),
                        "Content-Range": "bytes %d-%d/%d" % (sent, last, size),
                    })
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (408, 429, 500, 502, 503, 504) and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    raise
            sent = last + 1
            pct = int(sent * 100 / size)
            sys.stdout.write("\r    %s  %d%%" % (name, pct))
            sys.stdout.flush()
    sys.stdout.write("\n")
    return done


def children(drive_id, rel, tok):
    url = ("%s/drives/%s/root:/%s:/children" % (GRAPH, drive_id, urllib.parse.quote(rel))) if rel \
        else ("%s/drives/%s/root/children" % (GRAPH, drive_id))
    out, nxt = [], url + "?$top=200"
    while nxt:
        j = _req(nxt, tok)
        out.extend(j.get("value") or [])
        nxt = j.get("@odata.nextLink")
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("", "--dry-run", "--status"):
        die("unknown flag %s (use --dry-run or --status)" % mode, 2)
    env = _env()
    tok = token(env)
    try:
        drive_id, rel, label = target(env, tok)
    except SystemExit:
        raise
    except Exception as e:
        # A raw Python traceback here tells the operator nothing. Say which permission is missing.
        kind = "OneDrive" if (env.get("BACKUP_SP_USER") and not env.get("BACKUP_SP_URL")) else "SharePoint"
        die("Could not reach that folder: %s\n%s" % (_err(e), _permission_help(tok, kind)))

    if mode == "--status":
        say("Off-box target: %s" % label)
        try:
            items = [c for c in children(drive_id, rel, tok) if c.get("name", "").endswith(WANTED)]
        except Exception as e:
            die("cannot read the folder: %s" % _err(e))
        if not items:
            die("NOTHING is backed up off-box yet.")
        items.sort(key=lambda c: c.get("createdDateTime", ""))
        for c in items[-15:]:
            print("    %-46s %10.1f MB  %s" % (c["name"], (c.get("size") or 0) / 1e6,
                                               (c.get("createdDateTime") or "")[:19]))
        newest = items[-1].get("createdDateTime", "")[:19]
        age_h = (time.time() - time.mktime(time.strptime(newest, "%Y-%m-%dT%H:%M:%S"))) / 3600 if newest else 1e9
        print()
        (ok if age_h <= 26 else lambda m: sys.stderr.write("\033[1;31m  ⚠ %s\033[0m\n" % m))(
            "%d file(s) off-box; newest is %.0fh old" % (len(items), age_h))
        return 0 if age_h <= 26 else 1

    local = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(WANTED)) \
        if os.path.isdir(BACKUP_DIR) else []
    if not local:
        die("no encrypted snapshots in %s — has backup.sh run yet?" % BACKUP_DIR)

    say("Uploading %d encrypted snapshot(s) → %s" % (len(local), label))
    try:
        have = {c["name"]: (c.get("size") or 0) for c in children(drive_id, rel, tok)}
    except Exception as e:
        die("cannot list the destination folder: %s\n"
            "   If this is a 403, the app is missing Sites.ReadWrite.All (or Files.ReadWrite.All for the\n"
            "   OneDrive route) — grant it in Entra → App registrations → API permissions." % _err(e))

    todo = [f for f in local if have.get(f) != os.path.getsize(os.path.join(BACKUP_DIR, f))]
    if mode == "--dry-run":
        for f in todo:
            print("    would upload  %s (%.1f MB)" % (f, os.path.getsize(os.path.join(BACKUP_DIR, f)) / 1e6))
        for f in local:
            if f not in todo:
                print("    already there %s" % f)
        say("--dry-run: nothing was uploaded.")
        return 0

    failed = []
    for f in todo:
        p = os.path.join(BACKUP_DIR, f)
        try:
            res = upload(drive_id, rel, tok, p, f)
            # Verify by SIZE, not by the absence of an exception. "Uploaded fine but isn't really
            # there" is the entire failure mode of off-box backups.
            if int(res.get("size") or 0) != os.path.getsize(p):
                raise ValueError("size mismatch: local %d, remote %s" % (os.path.getsize(p), res.get("size")))
            ok("%s (%.1f MB)" % (f, os.path.getsize(p) / 1e6))
        except Exception as e:
            sys.stderr.write("\033[1;31m  ✖ %s — %s\033[0m\n" % (f, _err(e)))
            failed.append(f)
    for f in local:
        if f not in todo:
            print("    unchanged  %s" % f)

    retain = int(env.get("BACKUP_SP_RETAIN", "90") or 0)
    if retain > 0:
        cutoff = time.time() - retain * 86400
        pruned = 0
        for c in children(drive_id, rel, tok):
            name, created = c.get("name", ""), (c.get("createdDateTime") or "")[:19]
            if not name.endswith(WANTED) or not created:
                continue            # never touch anything that is not one of ours
            try:
                if time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%S")) < cutoff:
                    _req("%s/drives/%s/items/%s" % (GRAPH, drive_id, c["id"]), tok, method="DELETE")
                    pruned += 1
            except Exception:
                pass
        if pruned:
            print("    pruned %d off-box copy(ies) older than %dd" % (pruned, retain))

    if failed:
        die("%d file(s) did NOT make it off-box: %s" % (len(failed), ", ".join(failed)))
    say("Off-box copy complete — %s" % label)
    print("\n\033[1;31mReminder:\033[0m the backup encryption key must NOT be stored in the same "
          "SharePoint/OneDrive\nas these files. Ciphertext plus key in one place is not encryption — "
          "keep it in a password manager.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
