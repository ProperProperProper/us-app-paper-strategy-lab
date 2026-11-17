# Engineering concepts

This project applies production-oriented engineering patterns to local quantitative research.

## Deterministic authority

Models propose; deterministic Python code evaluates. This keeps scoring, fees, slippage, chronology, position limits, and promotion decisions reproducible.

## Structured orchestration

The runner delegates bounded proposal requests to configured providers and aggregates their structured parameter proposals. It does not currently implement a persistent reflection or long-term learning store.

## Guarded experimentation

Candidate strategies are represented as structured parameters, indicator specifications, or whitelisted formula trees. Arbitrary model-generated source is not executed during evaluation.

## Chronological blind replay

Data is kept chronological. The mutation loop selects using the first 21 complete training sessions, then scores every subsequent candle continuously through the data end. There are no rolling reselections, fixed validation partitions, or multi-session test blocks.

## Adversarial agent roles

Proposal workers are not treated as a voting pool. Explorer, critic, risk-reviewer, and coordinator roles are instructed to challenge the premise, benchmark fairness, leakage risk, regime dependence, causal implementability, and holdout evidence. Models may propose or reject hypotheses; only the deterministic evaluator can produce performance evidence.

## Run artifacts and auditability

Candidate results, provider responses, status, and promoted strategy parameters are written to local run JSON files. Long-term learned memory, supervisor state, and database-backed mutation history are not implemented in this repository. Generated artifacts are excluded from the public repository.

## Failure handling

Provider failures are caught at the proposal boundary and the deterministic baseline remains available. There is no in-repository supervisor or automatic restart loop in the current runner.

## Security boundaries

Credentials remain in local services or the macOS Keychain. The public repository contains no account identifiers, API keys, runtime databases, generated logs, or local machine paths. Paper execution is disabled in this build.
