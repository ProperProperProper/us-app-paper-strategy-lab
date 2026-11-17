# Engineering concepts

This project applies production-oriented engineering patterns to local quantitative research.

## Deterministic authority

Models propose; deterministic Python code evaluates. This keeps scoring, fees, slippage, chronology, position limits, and promotion decisions reproducible.

## Structured orchestration

The controller decomposes work into bounded research tasks, delegates to specialist workers, aggregates results, validates outputs, records reflections, and persists memory for later cycles.

## Guarded experimentation

Candidate strategies are represented as structured parameters, indicator specifications, or whitelisted formula trees. Arbitrary model-generated source is not executed during evaluation.

## Walk-forward validation

Data is kept chronological. Training selects candidates, validation checks generalisation, and the final test remains unseen until selection is complete. Session replay models the sequence of decisions rather than treating all candles as independent observations.

## Persistent state and auditability

Run manifests, candidate results, provider telemetry, supervisor status, memory, and database events are persisted locally. Configuration and generated artifacts are excluded from the public repository.

## Resilience

The supervisor detects stale heartbeats, records failures, applies bounded restart backoff, and preserves the last completed summary. Provider errors and malformed responses are handled as explicit failure states with local fallback paths.

## Security boundaries

Credentials remain in local services or the macOS Keychain. The public repository contains no account identifiers, API keys, runtime databases, generated logs, or local machine paths. Paper execution is disabled in this build.
