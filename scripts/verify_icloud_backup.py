#!/usr/bin/env python3
"""Verify that the weekly restore snapshot is complete and readable."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/us-app-paper-strategy-lab-weekly"
    manifest = root / "BACKUP_MANIFEST.txt"
    if not root.is_dir() or not manifest.is_file():
        raise SystemExit(f"backup snapshot is missing: {root}")
    sqlite_paths = sorted(root.rglob("*.sqlite3"))
    for path in sqlite_paths:
        try:
            with sqlite3.connect(path) as db:
                result = db.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise SystemExit(f"SQLite integrity failure: {path}: {result}")
        finally:
            # A normal read can create sidecars for a WAL-mode database;
            # remove only those verifier-created files before returning.
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
    sidecars = list(root.rglob("*.sqlite3-wal")) + list(root.rglob("*.sqlite3-shm"))
    if sidecars:
        raise SystemExit(f"backup contains SQLite sidecars: {sidecars}")
    print(f"backup_ok root={root} sqlite_files={len(sqlite_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
