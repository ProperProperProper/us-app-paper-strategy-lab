# Persistence and restore

The durable project state is stored locally and included in the weekly iCloud
snapshot:

- `quant_dashboard.sqlite3`: candles, agent-to-agent messages, proposals,
  controller configuration, evaluations, promotions, and learner records.
- `strategy_lab_runs/`: chronological profiles, replay evidence, decisions,
  and round reports.
- `paper_bot_live_strategy.json`: the latest approved SIMULATE runtime handoff,
  including the structural plugin descriptor when the plugin project is
  installed.
- `scripts/competition_bot_state.json` and `strategy_lab_runs/app_runtime_status.json`:
  restart and monitoring state.
- Git history, source, prompts, and documentation.

`scripts/backup_to_icloud.sh` uses SQLite's online backup API for every
`*.sqlite3` file in the project, preserving relative paths. It excludes WAL/SHM
sidecars because they are not portable restore state. Verify a snapshot with:

```sh
python3 scripts/verify_icloud_backup.py
```

The weekly LaunchAgent runs the backup every seven days. A restore requires
copying the snapshot to a new project directory, installing Python/runtime
dependencies, restoring local provider authentication separately, and running
the verification command before starting paper services.
