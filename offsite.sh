#!/usr/bin/env bash
# Humiley — copy the encrypted backups OFF this server.
#
# A backup on the same disk as the data is not a backup: it survives a bad deploy or a dropped table,
# and nothing else. This uploads the encrypted snapshots to an rclone remote (OneDrive, S3, Backblaze,
# a second box) so a lost or wiped VPS is still recoverable.
#
# ONE-TIME SETUP (needs your browser — sign-in cannot be scripted):
#     apt-get install -y rclone          # or: curl https://rclone.org/install.sh | bash
#     rclone config                      # create a remote, e.g. named "humiley-onedrive"
#     rclone lsd humiley-onedrive:       # confirm it can see your drive
#     echo 'OFFSITE_REMOTE=humiley-onedrive:Backups/Portal' >> /opt/humiley-timekeeping/.env
#
# Then it runs automatically at the end of every backup.sh, or by hand:
#     ./offsite.sh                # upload + verify + prune the remote
#     ./offsite.sh --dry-run      # show exactly what WOULD move, change nothing
#     ./offsite.sh --status       # what is on the remote right now, and how old
#
# Env:
#   OFFSITE_REMOTE     rclone destination, e.g. humiley-onedrive:Backups/Portal   (REQUIRED)
#   BACKUP_DIR         local snapshots        (default: /root/humiley-backups)
#   OFFSITE_RETAIN     delete remote copies older than N days (default: 90; 0 = keep forever)
#   OFFSITE_PING_URL   healthchecks.io-style URL pinged ONLY on full success (optional)
#   RCLONE_FLAGS       extra rclone flags, e.g. "--bwlimit 2M" to not saturate the office line
set -euo pipefail
cd "$(dirname "$0")"

# .env holds OFFSITE_REMOTE. Read it without executing it — a backup script must never source a file
# that could contain arbitrary shell.
if [ -f .env ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      OFFSITE_REMOTE|OFFSITE_RETAIN|OFFSITE_PING_URL|RCLONE_FLAGS)
        [ -z "${!k:-}" ] && export "$k=$(printf '%s' "$v" | sed 's/^["'\'']//; s/["'\'']$//')" ;;
    esac
  done < <(grep -E '^(OFFSITE_REMOTE|OFFSITE_RETAIN|OFFSITE_PING_URL|RCLONE_FLAGS)=' .env || true)
fi

BACKUP_DIR="${BACKUP_DIR:-/root/humiley-backups}"
OFFSITE_RETAIN="${OFFSITE_RETAIN:-90}"
MODE="${1:-}"

red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
say()   { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

if ! command -v rclone >/dev/null 2>&1; then
  red "✖ rclone is not installed."
  echo "    apt-get install -y rclone     # then: rclone config"
  exit 1
fi
if [ -z "${OFFSITE_REMOTE:-}" ]; then
  red "✖ OFFSITE_REMOTE is not set — nothing to copy to."
  echo "    Set it once:  echo 'OFFSITE_REMOTE=humiley-onedrive:Backups/Portal' >> $(pwd)/.env"
  echo "    (see the setup block at the top of this file)"
  exit 1
fi

RCONF="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"

# An ENCRYPTED rclone config prompts for a password on every single call. Interactively that is a
# mild nuisance; from cron there is no terminal, so the nightly copy blocks or fails forever with
# nobody watching. Catch it here with an explanation rather than at 02:00 in silence.
if [ -f "$RCONF" ] && grep -q 'RCLONE_ENCRYPT_V0' "$RCONF" 2>/dev/null && [ -z "${RCLONE_CONFIG_PASS:-}" ]; then
  red "✖ Your rclone config is password-encrypted and no RCLONE_CONFIG_PASS is set."
  echo "    Every rclone call will stop and ask for that password — which cron cannot answer, so the"
  echo "    nightly off-box copy would hang or fail every night unnoticed."
  echo
  echo "    Recommended — remove the config password (the file is root-only on a root-only box, and"
  echo "    file permissions are the protection that actually works unattended):"
  echo "        rclone config   ->   s) Set configuration password   ->   u) Unencrypt configuration"
  echo "        chmod 600 $RCONF"
  echo
  echo "    Or, if you want to keep it encrypted, put the password in .env (it then sits in plaintext"
  echo "    on the same box, which is why the above is recommended):"
  echo "        echo 'RCLONE_CONFIG_PASS=your-password' >> $(pwd)/.env"
  exit 1
fi

# A remote that does not exist fails with rclone's own cryptic "didn't find section in config file".
# Name the problem instead: setting a config password is NOT the same as creating a remote, and it is
# an easy pair to conflate because both live behind `rclone config`.
REMOTE_NAME="${OFFSITE_REMOTE%%:*}"
if ! rclone listremotes 2>/dev/null | grep -qx "$REMOTE_NAME:"; then
  red "✖ rclone has no remote called '$REMOTE_NAME'."
  FOUND="$(rclone listremotes 2>/dev/null | tr '\n' ' ')"
  echo "    Remotes that DO exist: ${FOUND:-（none）}"
  echo
  echo "    Create it — this is the 'n) New remote' path, not 's) Set configuration password':"
  echo "        rclone config"
  echo "          n) New remote"
  echo "          name> $REMOTE_NAME"
  echo "          Storage> onedrive          (type the number for Microsoft OneDrive)"
  echo "          client_id / client_secret> just press Enter for both"
  echo "          Edit advanced config> n    Use auto config> y   -> sign in in the browser"
  echo "          Choose 'OneDrive Personal or Business' -> pick your drive -> y) Yes this is OK"
  echo "          q) Quit config"
  echo "    Then check it:  rclone lsd $REMOTE_NAME:"
  exit 1
fi

# ── THE SAFETY RULE ──────────────────────────────────────────────────────────────────────────────
# Only ever upload ENCRYPTED artefacts, and never the key. Shipping .backup-key to the same cloud as
# the ciphertext would make the encryption purely decorative — one compromised account would hand over
# payroll, national IDs, bank details and GPS history in the clear. Equally, a plaintext .gz or .db
# would be exactly the unencrypted PII dump that backup.sh fail-closes to prevent, so we refuse to
# carry one off-box even if somebody produced it with BACKUP_ALLOW_PLAINTEXT=1.
# --filter, NOT --include + --exclude. rclone itself warns that mixing the two parses in an
# INDETERMINATE order ("Using --filter is recommended instead of both --include and --exclude") — which
# for this script means the deny rules protecting the key might or might not win. Filter rules are
# evaluated top-to-bottom, FIRST MATCH WINS, so ordering the denies first makes the guarantee real
# instead of hopeful.
FILTER=( --filter '- .backup-key'      # the key must NEVER travel with the ciphertext
         --filter '- *.key'
         --filter '- .env*'
         --filter '- *.db'             # plaintext forms: exactly the PII dump backup.sh fail-closes on
         --filter '- *.db.gz'
         --filter '- *.sql.gz'
         --filter '- *.tgz'
         --filter '+ timekeeping-*.db.gz.enc'
         --filter '+ procurement-*.sql.gz.enc'
         --filter '+ proc-storage-*.tgz.enc'
         --filter '- *' )              # deny-by-default: anything not named above stays put

if [ "$MODE" = "--status" ]; then
  say "Remote: $OFFSITE_REMOTE"
  rclone lsl "$OFFSITE_REMOTE" 2>/dev/null | sort -k2 | tail -20 || { red "✖ cannot read the remote."; exit 1; }
  echo
  N="$(rclone lsf "$OFFSITE_REMOTE" 2>/dev/null | wc -l | tr -d ' ')"
  NEWEST="$(rclone lsl "$OFFSITE_REMOTE" 2>/dev/null | awk '{print $2" "$3}' | sort | tail -1)"
  echo "    $N file(s) off-box; newest: ${NEWEST:-none}"
  if [ -n "$NEWEST" ]; then
    AGE_H=$(( ( $(date +%s) - $(date -d "$NEWEST" +%s 2>/dev/null || echo "$(date +%s)") ) / 3600 ))
    [ "$AGE_H" -le 26 ] && green "    ✓ newest off-box copy is ${AGE_H}h old" \
                        || red   "    ⚠ newest off-box copy is ${AGE_H}h old — the nightly copy may be failing"
  fi
  exit 0
fi

# A scalar, not an array: expanding an EMPTY array under `set -u` is an "unbound variable" error on
# bash 3.2, so the array form would work on the VPS and blow up anywhere older. Caught in testing.
DRY=0
[ "$MODE" = "--dry-run" ] && DRY=1

# Nothing to do is worth saying out loud rather than exiting 0 in silence — an empty backup dir means
# backup.sh never ran, which is the failure you least want to discover during a restore.
LOCAL_N="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.enc' 2>/dev/null | wc -l | tr -d ' ')"
if [ "$LOCAL_N" -eq 0 ]; then
  red "✖ no encrypted snapshots in $BACKUP_DIR — has backup.sh run yet?"
  exit 1
fi

say "Copying $LOCAL_N encrypted snapshot(s) -> $OFFSITE_REMOTE"
# `copy`, never `sync`: sync mirrors DELETIONS, so local pruning at 14 days would silently destroy the
# off-box history too — and a bug or a wrong BACKUP_DIR could empty the remote entirely. Remote
# retention is handled separately and explicitly below.
# shellcheck disable=SC2086
if [ "$DRY" -eq 1 ]; then
  rclone copy "$BACKUP_DIR" "$OFFSITE_REMOTE" "${FILTER[@]}" --dry-run \
    --transfers 2 --checkers 4 --retries 3 --stats-one-line --stats 30s ${RCLONE_FLAGS:-}
  say "--dry-run: nothing was uploaded."
  exit 0
fi
rclone copy "$BACKUP_DIR" "$OFFSITE_REMOTE" "${FILTER[@]}" \
  --transfers 2 --checkers 4 --retries 3 --stats-one-line --stats 30s ${RCLONE_FLAGS:-}

# A copy that reports success but did not land is the whole failure mode of off-box backups. Verify
# by hash, not by exit code.
say "Verifying the newest snapshot actually landed…"
NEWEST_LOCAL="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.enc' -print0 | xargs -0 ls -1t | head -1)"
BASE="$(basename "$NEWEST_LOCAL")"
if rclone check "$BACKUP_DIR" "$OFFSITE_REMOTE" --include "$BASE" --one-way 2>&1 | grep -q '0 differences found'; then
  green "  ✓ $BASE verified on the remote (hash match)"
else
  red "  ✖ $BASE did NOT verify on the remote."
  exit 1
fi

# Remote retention. Scoped by --include to our own filenames so a wrong remote path can never delete
# somebody else's files, and skipped entirely when OFFSITE_RETAIN=0.
if [ "$OFFSITE_RETAIN" -gt 0 ]; then
  say "Pruning off-box copies older than ${OFFSITE_RETAIN}d…"
  rclone delete "$OFFSITE_REMOTE" "${FILTER[@]}" --min-age "${OFFSITE_RETAIN}d" --rmdirs 2>/dev/null || true
fi

REMOTE_N="$(rclone lsf "$OFFSITE_REMOTE" 2>/dev/null | wc -l | tr -d ' ')"
green "✓ off-box copy complete — $REMOTE_N file(s) now on $OFFSITE_REMOTE"

# Dead-man's switch: only pinged on FULL success, so a silent failure shows up as a missed check-in
# rather than as nothing at all. Create a check at healthchecks.io and put its URL in .env.
if [ -n "${OFFSITE_PING_URL:-}" ]; then
  curl -fsS -m 10 --retry 3 "$OFFSITE_PING_URL" >/dev/null 2>&1 \
    && echo "    (pinged the backup dead-man's switch)" \
    || echo "    (⚠ could not ping $OFFSITE_PING_URL)" >&2
fi
