#!/usr/bin/env bash
# Humiley — point the off-box backups at your own SharePoint folder, in one command.
#
#     cd /opt/humiley-timekeeping && ./setup-sharepoint-backup.sh
#
# Run this ON THE VPS, not on your laptop.
#
# It asks for the SharePoint folder link and writes it into .env for you. Doing it by hand is
# error-prone because the URL contains a SPACE ("Shared Documents"), so pasting it as a shell command
# makes the shell split it in half — which is exactly what happens if you try.
#
# No Microsoft sign-in is involved: the portal already holds an app-only Graph secret (the one that
# files approved invoices into SharePoint) and Sites.ReadWrite.All is already consented.
set -euo pipefail
cd "$(dirname "$0")"

green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
say()   { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

for v in TK_M365_TENANT_ID TK_M365_CLIENT_ID TK_M365_CLIENT_SECRET; do
  if ! grep -qs "^$v=." .env; then
    red "✖ $v is not set in .env — the portal's Microsoft 365 credentials are missing."
    echo "    These are the same ones that file invoices into SharePoint. Fix those first."
    exit 1
  fi
done

say "SharePoint folder for the backups"
cat <<'EOF'
  In SharePoint, open (or create) the folder you want the backups to live in — for example
  Finance -> Documents -> Portal Backups. Restrict who can open it: it holds encrypted payroll
  and HR data.

  Then copy the link from your browser's address bar and paste it below. The long ".../Forms/
  AllItems.aspx?id=..." form is fine — that is what the address bar normally shows.
EOF
echo
printf '  Folder link: '
IFS= read -r SP_URL          # IFS= and -r: keep spaces and backslashes exactly as pasted
SP_URL="$(printf '%s' "$SP_URL" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

if [ -z "$SP_URL" ]; then red "✖ Nothing entered."; exit 1; fi
case "$SP_URL" in
  https://*sharepoint.com/sites/*) : ;;
  *) red "✖ That does not look like a SharePoint folder link."
     echo "    Expected something starting https://<tenant>.sharepoint.com/sites/..."
     echo "    You pasted: $SP_URL"
     exit 1 ;;
esac

say "Recording it in .env…"
touch .env
# Written with awk rather than sed so the URL's / and & characters need no escaping — sed would
# mangle a view URL like ...?id=%2Fsites%2F...&viewid=...
if grep -q '^BACKUP_SP_URL=' .env; then
  awk -v val="$SP_URL" '/^BACKUP_SP_URL=/ { print "BACKUP_SP_URL=" val; next } { print }' .env > .env.tmp
  mv .env.tmp .env
else
  printf 'BACKUP_SP_URL=%s\n' "$SP_URL" >> .env
fi
chmod 600 .env 2>/dev/null || true
grep '^BACKUP_SP_URL=' .env | sed 's/^/    /'

say "Checking the folder is reachable (nothing is uploaded yet)…"
if ! python3 backup_sharepoint.py --dry-run; then
  echo
  red "✖ Could not reach that folder."
  echo "    • 403 → the app is missing Sites.ReadWrite.All (Entra → App registrations → API permissions)"
  echo "    • 404 → the folder path is wrong; re-copy the link with the folder actually open"
  echo "    • invalid_client → the M365 client secret has expired (see docs/SECRET-ROTATION.md)"
  echo "    Nothing was uploaded. Fix and re-run this script."
  exit 1
fi

cat <<EOF

$(green "Ready.") That was a dry run. To copy for real, now:

    python3 backup_sharepoint.py

After this it happens automatically with the nightly backup. To check later:

    python3 backup_sharepoint.py --status

$(red "One thing left, and it matters:") the backup encryption key at
/root/humiley-backups/.backup-key must NOT be uploaded to that same SharePoint. Ciphertext and key in
one place is not encryption. Put a copy in your password manager — without it, none of these backups
can ever be restored.
EOF
