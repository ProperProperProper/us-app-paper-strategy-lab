# External gateway and MCP setup

The public repository contains the US.APP lab and its local console. It does not contain the Multi-Model AI Gateway, its MCP server, model binaries, or provider credentials. Those are separate local services.

## Gateway service

The lab expects the gateway at `http://127.0.0.1:8788` when local or NVIDIA proposals are enabled. Build and start the gateway from its own repository using that repository's documented release command, then verify it:

```sh
curl http://127.0.0.1:8788/health
curl http://127.0.0.1:8788/api/status
```

The gateway repository documents its Apple Silicon, MLX, NVIDIA, Keychain, launchd, and security setup. Do not put an NVIDIA key or other credentials in this repository.

## MCP server discovery

The mutation runner automatically checks these locations for `ai/mcp_server.py`:

1. `MULTI_MODEL_MCP_SERVER`, when explicitly set.
2. A sibling `multi-model-ai-gateway/ai/mcp_server.py`.
3. `TradingSystem/multi-model-ai-gateway/ai/mcp_server.py` beside this repository.

For a different layout, set the path explicitly:

```sh
export MULTI_MODEL_MCP_SERVER=/absolute/path/to/multi-model-ai-gateway/ai/mcp_server.py
export MULTI_MODEL_GATEWAY_URL=http://127.0.0.1:8788
```

The MCP server is started as a local subprocess by the lab. It routes `local` and `nvidia` proposal requests to the gateway. If it cannot start, deterministic local mutations and the baseline remain available; provider proposals are not silently treated as performance evidence.

## Start the lab

```sh
python3 scripts/research_console.py
open http://127.0.0.1:8790
```

Or run the mutation worker directly:

```sh
python3 scripts/app_strategy_lab.py \
  --db quant_dashboard.sqlite3 \
  --agents 2 --candidates 100 \
  --providers local,nvidia,apple,antigravity --continuous
```

Apple private-cloud proposals are optional and bounded. The Apple bridge
receives only the research prompt; it has no tool, file, shell, account, order,
or promotion access. The gateway may refuse restricted trading-action language;
that is recorded as a provider failure and remains safe. Apple output is parsed
into the safe mutation vocabulary and then tested by the local evaluator.

Antigravity is required as the mutation coordinator/controller. Set `ANTIGRAVITY_BIN` and `ANTIGRAVITY_MODEL` if its executable or model differs from the local defaults. If Antigravity cannot authenticate or respond, the mutation lab stops rather than bypassing the controller. The deterministic evaluator remains authoritative for all metrics and promotion decisions.

The Python MCP client bounds each gateway response to 45 seconds by default
(`MCP_RESPONSE_TIMEOUT_SECONDS` can override this). A local or NVIDIA provider
timeout is recorded as a proposal failure and does not freeze the deterministic
lab or paper bot; the required Antigravity controller remains a separate
failure boundary.

## What this repository does not provide

- Gateway compilation or service installation.
- MLX model downloads.
- NVIDIA credentials or account configuration.
- A persistent launchd service for the lab itself.
- The optional `scripts/session_monitor.py` supervisor, which restarts the lab, console, or paper bot during the US session.
