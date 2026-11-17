# Model operations

The lab routes bounded research requests through local model services. Models propose; the deterministic local evaluator decides.

## Responsibilities

- MLX provides the local controller, persistent learning boundary, memory recall, reflection, and fallback behavior.
- NVIDIA workers provide bounded specialist proposals and research variations.
- The local evaluator performs all scoring and safety checks.
- Code-authority integrations are separate from proposal workers and must not bypass validation.

The lab does not call NVIDIA directly from strategy code. The local gateway handles routing, allowlists, rate limits, telemetry, and fallback boundaries.

## Supported proposal surface

Workers may suggest parameter changes, indicator specifications, whitelisted formula trees, or structured strategy variants. They may not submit live orders or execute arbitrary generated code.

## Failure handling

Provider failures, malformed outputs, timeouts, and rate limits are recorded as telemetry. The controller can fall back to local MLX behavior or deterministic evaluation, while the supervisor can restart stale child processes.
