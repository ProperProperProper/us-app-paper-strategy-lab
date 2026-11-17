#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICLOUD_ROOT="${ICLOUD_DRIVE_ROOT:-$HOME/Library/Mobile Documents/com~apple~CloudDocs}"
BACKUP_ROOT="${ICLOUD_BACKUP_ROOT:-$ICLOUD_ROOT/us-app-paper-strategy-lab-weekly}"

if [[ ! -d "$ICLOUD_ROOT" ]]; then
  print -u2 "iCloud Drive is unavailable: $ICLOUD_ROOT"
  exit 1
fi

mkdir -p "$ICLOUD_ROOT"
STAGING="$(mktemp -d "$ICLOUD_ROOT/.us-app-paper-strategy-lab.XXXXXX")"
PREVIOUS="${BACKUP_ROOT}.previous"
cleanup() { rm -rf "$STAGING" "$PREVIOUS"; }
trap cleanup EXIT INT TERM

# Copy source, documentation, Git history, current data, and ignored runtime
# state. Temporary caches and SQLite sidecars are excluded and rebuilt below.
/usr/bin/rsync -a --delete \
  --exclude='.DS_Store' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.tmp' \
  --exclude='*.lock' \
  --exclude='*.sqlite3' \
  --exclude='*.sqlite3-shm' \
  --exclude='*.sqlite3-wal' \
  "$PROJECT_ROOT/" "$STAGING/"

# SQLite's online backup API produces a consistent snapshot while the lab and
# paper bot are running. Keep the original relative paths in the backup.
for relative in quant_dashboard.sqlite3 scripts/quant_dashboard.sqlite3; do
  source="$PROJECT_ROOT/$relative"
  target="$STAGING/$relative"
  if [[ -f "$source" ]]; then
    mkdir -p "$(dirname "$target")"
    /usr/bin/python3 - "$source" "$target" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1:]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
PY
  fi
done

git_revision="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || print unknown)"
{
  print "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  print "git_revision=$git_revision"
  print "source=$PROJECT_ROOT"
  print "sqlite_snapshot=online_backup_api"
} > "$STAGING/BACKUP_MANIFEST.txt"

# Atomically replace the one weekly snapshot. The previous snapshot is moved
# aside only long enough for the rename, then removed after the new snapshot is
# in place.
if [[ -e "$BACKUP_ROOT" ]]; then
  mv "$BACKUP_ROOT" "$PREVIOUS"
fi
mv "$STAGING" "$BACKUP_ROOT"
trap - EXIT INT TERM
rm -rf "$PREVIOUS"
print "iCloud backup complete: $BACKUP_ROOT"
