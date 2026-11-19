# Antigravity code-audit handover

This document is the operating brief for Antigravity when auditing the entire
US.APP paper-strategy lab for faults. The objective is to find concrete defects,
repair safe defects where authorised, and leave an evidence-backed audit trail.

## Controller responsibility

Antigravity is the coordinator and supervisor for this audit. It must:

1. inspect the complete repository, not only the active mutation runner;
2. trace the live path from Moomoo candles through SQLite, research, promotion,
   hot-swap, paper execution, dashboard, and monitoring;
3. challenge assumptions and report contradictions between code, documentation,
   runtime state, and stored artifacts;
4. make bounded repairs when a defect is confirmed;
5. run the relevant checks after every repair; and
6. stop and report when a repair would require credentials, a live order, a
   destructive data operation, or an unverified model-generated code change.

The deterministic local evaluator remains the authority for candle validity,
trade chronology, returns, drawdown, trade counts, replay boundaries, and
promotion. Antigravity must never invent metrics or certify a candidate from
its own response.

## Hard project rules

The audit must treat these as non-negotiable invariants:

- US.APP only; no ASX, Australian-super, or unrelated-market code/data may be
  active in this repository.
- Only 2026 candles and later future data may remain in SQLite.
- Candles are deduplicated by `(symbol, interval_minutes, time_key)` and must
  have valid OHLCV relationships.
- The base comparison is always a freshly rerun 10-minute baseline.
- Research intervals are exactly 10, 20, 30, 40, 50, 60, and 70 minutes.
- Every candidate uses the same protocol: first 21 complete sessions for
  selection, then one continuous blind replay from session 22 through the
  latest candle. There are no rolling reselections, fixed validation slices,
  folds, chunks, or per-session test blocks.
- Signals use completed candles only; trades must be chronological, causal,
  non-overlapping, and limited to one open position.
- The evaluator, not a model, decides promotion.
- Paper execution is SIMULATE-only, signal-driven, and must not become live
  trading through configuration or hot-swap.
- Approved strategy parameters, interval changes, and code changes may be
  hot-swapped only at a completed-bar boundary and must be auditable.
- No arbitrary model-generated Python may be executed.
- API keys, OAuth tokens, account identifiers, private database files, and
  personal information must not be added to Git.

## Audit scope

Inspect every tracked Python file, shell script, workflow, configuration file,
and Markdown document. Pay particular attention to:

- `scripts/app_strategy_lab.py` — mutation loop, providers, promotion, status;
- `scripts/strategy_57pct.py` — indicators, entries, exits, aggregation,
  execution costs, and blind replay;
- `scripts/competition_bot.py` — candle freshness, session awareness, recovery,
  one-position enforcement, hot-swap, and SIMULATE protection;
- `scripts/quant_storage.py` — schema, uniqueness, retention, transactions;
- `scripts/research_console.py` — process liveness and truthful dashboard state;
- `scripts/session_monitor.py` — duplicate prevention, fault recovery, and
  US-session open/close behavior;
- `scripts/quant_api.py` and `scripts/quant_dashboard.py` — compatibility
  entry points that must use the same continuous replay protocol;
- `scripts/agent_workers.py`, `scripts/model_client.py`, and gateway adapters —
  provider routing, timeouts, malformed responses, rate limits, and fallback;
- `scripts/ml_strategy_engine.py` and `scripts/advanced_research_engine.py` —
  causal features, training-label timing, and unsupported research paths;
- all backup, launch, and data-import scripts; and
- all documentation links, commands, claims, and examples.

## Required checks

Run checks from the repository root and preserve the output in the audit
report. At minimum:

```sh
python3 -m compileall -q scripts
git diff --check
git status --short --branch
rg -n 'lookback_days|90.?day|ASX|australian|purged_walk_forward|slice\(|chunk|fold' scripts docs README.md
ps ax -o pid=,ppid=,state=,etime=,command=
curl -sS --max-time 5 http://127.0.0.1:8790/api/state
lsof -nP -iTCP:8790 -sTCP:LISTEN
lsof -nP -iTCP:11111 -sTCP:LISTEN
```

For every SQLite database found in the project, verify:

```sql
PRAGMA integrity_check;
```

Also verify candle counts versus distinct timestamps, pre-2026 retention,
malformed OHLCV rows, timestamp ordering, and the latest candle timestamp.

Run a deterministic smoke replay using the current root database and verify:

- 21 training sessions;
- continuous replay through the latest candle;
- no duplicate trades or overlapping positions;
- baseline metrics are reproducible; and
- the tester, API, and mutation lab report the same replay semantics.

If a formal test suite is absent, record that as an engineering gap and use
small deterministic smoke tests rather than treating compilation as sufficient.

## Fault classification

Classify every finding:

- **P0 safety:** any path to live orders, credential exposure, destructive
  database loss, or fabricated performance evidence;
- **P1 runtime:** worker crash, stale status, broken hot-swap, stale candles
  during an open session, duplicate worker, or failed recovery;
- **P2 correctness:** replay leakage, wrong boundary, malformed data accepted,
  inconsistent evaluator, invalid trade chronology, or undocumented behavior;
- **P3 maintenance:** documentation drift, missing tests, dead code, weak error
  messages, or reproducibility friction.

For each finding record the file and line, observed behavior, root cause,
impact, reproduction command, repair, and post-repair evidence.

## Repair protocol

Before changing code:

1. capture the current status, Git revision, process list, and relevant logs;
2. confirm the smallest safe scope;
3. preserve user data and quarantine rather than delete anything material;
4. never restart the Mac or Moomoo OpenD for a repository repair; and
5. do not alter paper positions or submit orders as part of an audit.

After changing code:

1. compile the affected Python files;
2. run focused smoke tests and the full available test suite;
3. re-check SQLite integrity and data invariants;
4. restart only the affected project worker when required to load new code;
5. verify the dashboard reports actual process liveness, not a stale status file;
6. confirm the paper bot remains SIMULATE-only; and
7. commit the repair with a focused message and include the commit in the
   handover report.

## Required handover output

Antigravity must return a concise report containing:

1. audit timestamp and Git revision;
2. processes and endpoints checked;
3. databases and data ranges checked;
4. findings grouped by P0–P3;
5. repairs made and commits created;
6. tests and smoke checks passed or failed;
7. unresolved risks and why they were not changed; and
8. final live state of the lab, console, supervisor, OpenD connection, and
   paper bot.

Do not report “healthy” when a check was skipped. Use `not checked`, `blocked`,
or `not applicable`, with the reason.
