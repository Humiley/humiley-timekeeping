#!/usr/bin/env bash
# Humiley — point the off-box backups at Backblaze B2, in one command.
#
#     cd /opt/humiley-timekeeping && ./setup-b2.sh
#
# Why B2 and not OneDrive: B2 authenticates with two values you paste, so there is no browser
# sign-in to complete on a headless server. That is the whole reason the OneDrive attempt stalled.
#
# BEFORE running this, create the bucket and key in the Backblaze web UI (5 minutes, one time):
#   1. Sign up / sign in at backblaze.com  ->  B2 Cloud Storage
#   2. Buckets -> Create a Bucket
#        name:  humiley-backups          (bucket names are GLOBALLY unique — add a suffix if taken)
#        files: PRIVATE                  <-- must be Private, never Public
#   3. Application Keys -> Add a New Application Key
#        name:            humiley-vps
#        allow access to: humiley-backups   (restrict it to that one bucket)
#        access:          Read and Write
#   4. Copy BOTH values it shows you — keyID and applicationKey. The applicationKey is displayed
#      ONCE and never again; if you lose it, delete the key and make a new one.
#
# This script asks for those two values, hides the key as you type it, sets up the rclone remote,
# proves it can reach the bucket, records it in .env and runs a dry run. It never echoes the key and
# never puts it on a command line (so it stays out of `ps` and your shell history).
set -euo pipefail
cd "$(dirname "$0")"

REMOTE_NAME="${B2_REMOTE_NAME:-humiley-b2}"
red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
say()   { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

if ! command -v rclone >/dev/null 2>&1; then
  red "✖ rclone is not installed."
  echo "    apt-get install -y rclone"
  exit 1
fi

# An encrypted rclone config prompts on every call, which cron cannot answer. Catch it here rather
# than at 02:00 in silence — same check offsite.sh makes.
RCONF="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
if [ -f "$RCONF" ] && grep -q 'RCLONE_ENCRYPT_V0' "$RCONF" 2>/dev/null && [ -z "${RCLONE_CONFIG_PASS:-}" ]; then
  red "✖ Your rclone config is password-encrypted, so unattended runs cannot read it."
  echo "    Remove the password first:  rclone config  ->  s) Set configuration password  ->  u) Unencrypt"
  echo "    Then re-run this script."
  exit 1
fi

say "Backblaze B2 credentials"
echo "  From Backblaze -> Application Keys. See the notes at the top of this file if you have not"
echo "  created the bucket and key yet."
echo
printf '  keyID           : '; read -r B2_ID
printf '  applicationKey  : '; read -rs B2_KEY; echo    # -s: not echoed to the screen
printf '  bucket name     : '; read -r B2_BUCKET
B2_BUCKET="${B2_BUCKET:-humiley-backups}"

if [ -z "$B2_ID" ] || [ -z "$B2_KEY" ]; then
  red "✖ Both the keyID and the applicationKey are required."; exit 1
fi

say "Creating the rclone remote '$REMOTE_NAME'…"
# Written straight into rclone.conf rather than via `rclone config create … key <secret>`. That
# command takes the key as a command-line ARGUMENT, and argv is world-readable in `ps` for as long as
# the process lives — a real (if brief) exposure of a credential that can read and delete every
# backup. rclone stores b2 account/key in plain text in this file anyway, so writing it ourselves is
# the same end state without the process-list window.
mkdir -p "$(dirname "$RCONF")"
if [ -f "$RCONF" ]; then cp -p "$RCONF" "$RCONF.bak-$(date +%Y%m%d%H%M%S)"; fi
TMPC="$(mktemp)"; chmod 600 "$TMPC"
trap 'rm -f "$TMPC"' EXIT
if [ -f "$RCONF" ]; then
  # Drop any existing [REMOTE_NAME] section (from its header to the next header or EOF) so re-running
  # this script updates rather than appending a duplicate rclone chokes on.
  awk -v name="[$REMOTE_NAME]" '
    $0 == name { skip = 1; next }
    /^\[/      { skip = 0 }
    !skip      { print }
  ' "$RCONF" > "$TMPC"
fi
{ printf '[%s]\ntype = b2\naccount = %s\nkey = %s\n\n' "$REMOTE_NAME" "$B2_ID" "$B2_KEY"; } >> "$TMPC"
cat "$TMPC" > "$RCONF"
chmod 600 "$RCONF"
unset B2_KEY

say "Checking the credentials actually work…"
if ! rclone lsd "$REMOTE_NAME:" >/dev/null 2>&1; then
  red "✖ rclone could not list your B2 account with those credentials."
  echo "    Common causes: the keyID and applicationKey were swapped; the key was restricted to a"
  echo "    different bucket; or the applicationKey was truncated when pasted (it is long)."
  echo "    Fix and re-run — nothing has been written to .env yet."
  exit 1
fi
green "  ✓ credentials accepted"

if ! rclone lsd "$REMOTE_NAME:" 2>/dev/null | awk '{print $NF}' | grep -qx "$B2_BUCKET"; then
  say "Bucket '$B2_BUCKET' not visible — creating it…"
  rclone mkdir "$REMOTE_NAME:$B2_BUCKET" 2>/dev/null || true
  if ! rclone lsd "$REMOTE_NAME:" 2>/dev/null | awk '{print $NF}' | grep -qx "$B2_BUCKET"; then
    red "✖ Could not see or create bucket '$B2_BUCKET'."
    echo "    If your application key is restricted to one bucket, the name must match EXACTLY."
    echo "    Check the spelling in the Backblaze UI and re-run."
    exit 1
  fi
fi
green "  ✓ bucket '$B2_BUCKET' reachable"

REMOTE_PATH="$REMOTE_NAME:$B2_BUCKET/portal"
say "Recording OFFSITE_REMOTE=$REMOTE_PATH in .env…"
touch .env
if grep -q '^OFFSITE_REMOTE=' .env; then
  sed -i.bak "s|^OFFSITE_REMOTE=.*|OFFSITE_REMOTE=$REMOTE_PATH|" .env && rm -f .env.bak
else
  printf 'OFFSITE_REMOTE=%s\n' "$REMOTE_PATH" >> .env
fi
grep '^OFFSITE_REMOTE=' .env | sed 's/^/    /'

say "Dry run — showing what WOULD be uploaded, changing nothing…"
./offsite.sh --dry-run || true

cat <<EOF

$(green "Set up.") The nightly backup will copy off-box from now on. To do it right now:

    ./offsite.sh

To check on it later:

    ./offsite.sh --status

$(red "One thing left, and it matters:") your backups are encrypted with the key at
/root/humiley-backups/.backup-key. That key must NOT live in Backblaze — ciphertext plus key in the
same account is not encryption. Put a copy in your password manager. Without it, none of these
backups can ever be restored.
EOF
