# iCloud backup

The project has a single replaceable weekly snapshot in iCloud Drive:

`~/Library/Mobile Documents/com~apple~CloudDocs/us-app-paper-strategy-lab-weekly`

Run a backup manually with:

```sh
scripts/backup_to_icloud.sh
```

Install or restore the weekly macOS schedule with:

```sh
scripts/install_icloud_backup_schedule.sh
```

The scheduled macOS LaunchAgent runs the same script every 604800 seconds. It
mirrors the project, current 2026+ data, Git history, runtime state, and
documentation. All SQLite databases are copied through SQLite's online backup
API so the snapshot remains consistent while the lab is running. Temporary caches,
SQLite WAL/SHM sidecars, locks, and Python bytecode are excluded.

The snapshot is staged locally, then mirrored with `rsync --delete` after the
staging copy completes. This avoids renaming an existing iCloud-synced folder,
which iCloud may reject. If iCloud Drive is unavailable, the script fails
before the mirror step. Verify the completed snapshot with
`scripts/verify_icloud_backup.py` before restoring it elsewhere.

## Restore on another Mac

Copy the `us-app-paper-strategy-lab-weekly` snapshot from iCloud Drive to a
local project directory, then run `scripts/install_icloud_backup_schedule.sh`.
Install the documented external dependencies separately: Python packages,
Moomoo OpenD, the local model providers/gateway, and any required account
login. Credentials and machine-specific service registrations are intentionally
not stored in the repository backup.
