# Engineering concepts

This project applies production-oriented engineering patterns to local quantitative research.

## Deterministic authority

Models propose; deterministic Python code evaluates. This keeps scoring, fees, slippage, chronology, position limits, and promotion decisions reproducible.

## Structured orchestration

The runner delegates bounded proposal requests to configured providers and
records structured handoffs in the persistent `agent_messages` SQLite ledger.
Each round records proposals, controller configuration, deterministic
evaluation, promotion, and the learning handoff to MLX. The evaluator remains
the only source of performance truth.

## Guarded experimentation

Candidate strategies are represented as structured parameters, indicator specifications, or whitelisted formula trees. Arbitrary model-generated source is not executed during evaluation.

## Chronological blind replay

Data is kept chronological. The mutation loop selects using the first 21 complete training sessions, then scores every subsequent candle continuously through the data end. There are no rolling reselections, fixed validation partitions, or multi-session test blocks.

## Adversarial agent roles

Proposal workers are not treated as a voting pool. Explorer, critic, risk-reviewer, and coordinator roles are instructed to challenge the premise, benchmark fairness, leakage risk, regime dependence, causal implementability, and holdout evidence. Models may propose or reject hypotheses; only the deterministic evaluator can produce performance evidence.

## Run artifacts and auditability

Candidate results, provider responses, status, promoted strategy parameters,
and agent-to-agent messages are written to local run JSON and SQLite artifacts.
Long-term model adapters remain external runtime state, while the research
conversation, structured evidence, and learning handoffs persist locally in
SQLite. Generated artifacts are excluded from the public repository.

## Failure handling

Provider failures are handled at the proposal boundary; Antigravity failure is fatal to the mutation round because it is the required controller, while the deterministic baseline remains the reference. `scripts/session_monitor.py` provides the session supervisor: it checks OpenD, console health, SQLite integrity, runtime faults, and code freshness, and restarts the lab, console, or SIMULATE paper bot when required during the session.

## Security boundaries

Credentials remain in local services or the macOS Keychain. The public repository contains no account identifiers, API keys, runtime databases, generated logs, or local machine paths. Paper execution is available only when explicitly enabled and is forced through Moomoo `TrdEnv.SIMULATE`; live trading is not supported in this build.
