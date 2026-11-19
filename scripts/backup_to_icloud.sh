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
cleanup() { rm -rf "$STAGING"; }
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
# paper bot are running. Snapshot every SQLite database, not only the primary
# dashboard database, while preserving its relative path.
while IFS= read -r -d '' source; do
  relative="${source#$PROJECT_ROOT/}"
  target="$STAGING/$relative"
  mkdir -p "$(dirname "$target")"
  /usr/bin/python3 - "$source" "$target" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1:]
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
PY
done < <(/usr/bin/find "$PROJECT_ROOT" -type f -name '*.sqlite3' -not -path '*/.git/*' -print0)

git_revision="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || print unknown)"
{
  print "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  print "git_revision=$git_revision"
  print "source=$PROJECT_ROOT"
  print "sqlite_snapshot=online_backup_api"
  print "sqlite_files=$(find "$STAGING" -type f -name '*.sqlite3' | wc -l | tr -d ' ')"
} > "$STAGING/BACKUP_MANIFEST.txt"

# iCloud Drive does not reliably permit renaming an existing synced directory.
# Mirror the completed staging tree into the one snapshot instead; --delete
# removes files that no longer belong while preserving the destination folder.
mkdir -p "$BACKUP_ROOT"
/usr/bin/rsync -a --delete --delete-excluded "$STAGING/" "$BACKUP_ROOT/"
trap - EXIT INT TERM
rm -rf "$STAGING"
print "iCloud backup complete: $BACKUP_ROOT"
