# NVIDIA hosted-model rate-limit policy

Updated 2026-11-16.

The lab uses three explicitly selected NVIDIA API Catalog model IDs:

- `nvidia/nemotron-3.5-bolt-e4b`
- `nvidia/nemotron-3.5-lightning-30b-a3b`
- `deepseek-ai/deepseek-v4.1-flash`

These are hosted NVIDIA endpoints, not local models. They must not be treated
as unlimited. NVIDIA's public documentation does not publish one universal
requests-per-minute or tokens-per-day quota for each API Catalog model. The
effective ceiling is account/endpoint dependent and may change with demand.
The lab therefore records observed per-model requests, successes, failures,
HTTP status, latency, and local fallbacks in `runtime_status.json` and the web
console.

Safety controls currently applied:

- one shared hosted request at a time;
- 30 seconds plus small jitter between hosted requests;
- global cooldown after an upstream failure;
- per-model exponential cooldown, up to 10 minutes;
- one hosted attempt per mutation job, with local MLX fallback;
- compact prompts and a 1,000-token response ceiling;
- no direct probing or retry storm while the continuous lab is running.

The MLX model is local to this Mac and has no NVIDIA vendor quota. It is only
limited by local compute, memory, and the lab's own concurrency controls.

NVIDIA's documentation confirms that hosted endpoints can return 429/503
during demand spikes and recommends reducing concurrency and adding delays.
It also states that no endpoint-specific limit is published for some NVIDIA
services, so an exact fixed per-model quota cannot responsibly be inferred
from the model name alone.
