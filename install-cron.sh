#!/usr/bin/env bash
# Humiley — install the two scheduled jobs this server needs, idempotently.
#
#   • auto-deploy poller  — every 2 min: `git push` on your laptop -> the VPS updates itself
#   • nightly backup      — 02:00: portal SQLite + Procurement Postgres + uploaded files
#
# Run it on the VPS:
#     cd /opt/humiley-timekeeping && ./install-cron.sh
#
# Safe to run as many times as you like: it REMOVES every existing Humiley line first and writes
# exactly one of each. (Duplicated entries are not harmless — two backup runs at the same minute
# race on the same temp file inside the container, and two deploys race on the git tree.)
#
# Flags:
#   --show     print the current crontab and what is missing, change nothing
#   --remove   take both jobs out again
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

DEPLOY_LINE="*/2 * * * * cd $HERE && ./autodeploy.sh"
BACKUP_LINE="0 2 * * * $HERE/backup.sh >> /var/log/humiley-backup.log 2>&1"
MARK='# humiley'

green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
say()   { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

current() { crontab -l 2>/dev/null || true; }
# The crontab MINUS every line we manage — matched by the script each line calls, so entries added
# by hand (or duplicated by an earlier paste) are cleaned up too, not just ones we wrote.
_filtered() { current | grep -v -e 'autodeploy\.sh' -e 'backup\.sh' -e "^$MARK" || true; }

case "${1:-}" in
  --show)
    say "Current crontab:"; current | sed 's/^/    /' || true
    echo
    current | grep -q 'autodeploy\.sh' && green "  ✓ auto-deploy poller installed" || red "  ✗ auto-deploy poller MISSING"
    current | grep -q 'backup\.sh'     && green "  ✓ nightly backup installed"     || red "  ✗ nightly backup MISSING"
    exit 0 ;;
  --remove)
    # Same read-then-write as the install path — piping _filtered straight into `crontab -` races
    # the reader against the writer and takes unrelated entries with it.
    KEEP="$(_filtered)"
    TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
    [ -n "$KEEP" ] && printf '%s\n' "$KEEP" > "$TMP" || : > "$TMP"
    crontab "$TMP"
    say "Removed. Crontab is now:"; current | sed 's/^/    /'
    exit 0 ;;
  "") ;;
  *) echo "unknown flag: $1  (use --show or --remove)" >&2; exit 2 ;;
esac

# The scripts have to exist and be runnable, or we would install a cron line that fails silently
# every two minutes forever.
for s in autodeploy.sh backup.sh; do
  if [ ! -f "$HERE/$s" ]; then red "✖ $HERE/$s not found — are you in the repo directory?"; exit 1; fi
  [ -x "$HERE/$s" ] || chmod +x "$HERE/$s"
done

say "Installing (removing any existing Humiley entries first)…"
# Read the existing crontab COMPLETELY before writing anything. Doing this as
#   { _filtered; echo …; } | crontab -
# reads and writes the crontab in the same pipeline: the reader and `crontab -` run concurrently, and
# an implementation that truncates the spool before stdin is drained silently eats every unrelated
# entry. Caught exactly that in testing — an @reboot line belonging to something else disappeared.
KEEP="$(_filtered)"
NEW="$(mktemp)"; trap 'rm -f "$NEW"' EXIT
{ [ -n "$KEEP" ] && printf '%s\n' "$KEEP"
  echo "$MARK — managed by install-cron.sh, do not edit by hand"
  echo "$DEPLOY_LINE"
  echo "$BACKUP_LINE"; } > "$NEW"
crontab "$NEW"

say "Crontab is now:"
current | sed 's/^/    /'

say "Checks"
current | grep -q 'autodeploy\.sh' && green "  ✓ auto-deploy poller — every 2 min" || { red "  ✗ poller failed to install"; exit 1; }
current | grep -q 'backup\.sh'     && green "  ✓ nightly backup — 02:00"            || { red "  ✗ backup failed to install"; exit 1; }
DUPES="$(current | grep -c 'autodeploy\.sh' || true)"
[ "$DUPES" -eq 1 ] && green "  ✓ exactly one poller entry (no duplicates)" || red "  ⚠ $DUPES poller entries — expected 1"

if [ ! -f "${BACKUP_DIR:-/root/humiley-backups}/.backup-key" ]; then
  echo
  red "  ⚠ No backup encryption key — backup.sh will ABORT rather than write plaintext HR data."
  echo "    Create it once, then copy it into your password manager (losing it loses every backup):"
  echo "      openssl rand -base64 48 > /root/humiley-backups/.backup-key"
  echo "      chmod 600 /root/humiley-backups/.backup-key"
fi

say "Running the poller once now so you can see it work…"
./autodeploy.sh || true
LOG="${AUTODEPLOY_STATE:-/root/humiley-backups}/autodeploy.log"
if [ -f "$LOG" ]; then
  green "  ✓ $LOG exists now:"; tail -5 "$LOG" | sed 's/^/    /'
else
  echo "    (no log yet — it only writes when it finds a change or an error; that is normal if you"
  echo "     just deployed by hand and the server is already on the newest commit)"
fi

say "Done. Test it: push a commit and watch"
echo "    tail -f $LOG"
