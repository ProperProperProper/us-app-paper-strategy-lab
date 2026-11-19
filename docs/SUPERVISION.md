# Supervisor-to-agent fault handoff

The session supervisor automatically restarts safe-to-restart services and
writes every detected fault to:

`strategy_lab_runs/supervisor_handoff.json`

Each event records the source, timestamp, message, automatic action, and a
`code_fix_candidate` flag. The flag is triage only; Codex or Antigravity must
inspect the evidence before changing code. The supervisor never applies model-
generated code or promotes a strategy.

The research console exposes the same queue at `/api/state` under
`supervisor_handoff`, so the dashboard and an agent can inspect it without
reading logs directly. A clean queue is represented as `status: CLEAR`.

This is a persistent handoff, not a push message into a chat session. A Codex
session must poll the console or read the handoff file to assess and repair a
fault. External notifications can be added separately without granting the
notification channel code or trading authority.
