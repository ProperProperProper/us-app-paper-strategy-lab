# Engineering concepts

This project applies production-oriented engineering patterns to local quantitative research.

## Deterministic authority

Models propose; deterministic Python code evaluates. This keeps scoring, fees, slippage, chronology, position limits, and promotion decisions reproducible.

## Structured orchestration

The runner delegates bounded proposal requests to configured providers and aggregates their structured parameter proposals. It does not currently implement a persistent reflection or long-term learning store.

## Guarded experimentation

Candidate strategies are represented as structured parameters, indicator specifications, or whitelisted formula trees. Arbitrary model-generated source is not executed during evaluation.

## Chronological holdout validation

Data is kept chronological. The current runner uses 60% training, 20% validation, and 20% final test data. It does not yet perform session-by-session strategy re-selection or full walk-forward replay in the mutation loop.

## Run artifacts and auditability

Candidate results, provider responses, status, and promoted strategy parameters are written to local run JSON files. Long-term learned memory, supervisor state, and database-backed mutation history are not implemented in this repository. Generated artifacts are excluded from the public repository.

## Failure handling

Provider failures are caught at the proposal boundary and the deterministic baseline remains available. There is no in-repository supervisor or automatic restart loop in the current runner.

## Security boundaries

Credentials remain in local services or the macOS Keychain. The public repository contains no account identifiers, API keys, runtime databases, generated logs, or local machine paths. Paper execution is disabled in this build.
