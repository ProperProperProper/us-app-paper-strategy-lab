# Model operations

The lab routes bounded research requests through local model services. Models propose; the deterministic local evaluator decides.

The gateway and MCP server are external dependencies. Their setup, credentials, model allowlists, and service lifecycle are documented in [External gateway and MCP setup](EXTERNAL_GATEWAY.md).

## Responsibilities

- The local gateway provider supplies local-model proposals when configured.
- NVIDIA workers provide bounded specialist proposals through the gateway.
- Antigravity is the required coordinator/controller invoked through its local CLI.
- The local evaluator performs all scoring and safety checks.
- Code-authority integrations are separate from proposal workers and must not bypass validation.

The lab does not call NVIDIA directly from strategy code. The local gateway handles the provider request boundary. Gateway rate limits and telemetry are external to this repository; this runner does not implement a hosted-request scheduler.

## Supported proposal surface

Workers may suggest parameter changes, indicator specifications, whitelisted formula trees, or structured strategy variants. They may not submit live orders or execute arbitrary generated code.

## Failure handling

Provider failures, malformed outputs, and timeouts from optional proposal
providers may be recorded and bypassed. Antigravity failures are fatal to the
lab round because it is the required coordinator/controller; the lab must be
restarted only after Antigravity authentication or availability is restored.
