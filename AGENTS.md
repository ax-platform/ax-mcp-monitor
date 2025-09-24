# Active Agents

This roster captures every monitor configuration that ships with the repository so new operators can see which handle goes with which config, model, and purpose.

| Handle | Config File | Default Model / Plugin | Prompt Profile | Notes |
| --- | --- | --- | --- | --- |
| `@test_sentinel` | `configs/mcp_config.json` | `echo` (default) or `ollama:gpt-oss` | `ax_base` | Baseline monitor used for protocol checks and smoke tests. Always keep this handle in the default space for quick validation. |
| `@HaloScript` | `configs/mcp_config_halo_script.json` | `ollama:gpt-oss` | `battle` overlay | Debate partner that focuses on counter-analysis and tactical recommendations. Great for demos of multi-agent threads. |
| `@axbot` *(remote)* | aX web orchestrator | — | — | Runs in the hosted aX coordinator. Use it as the facilitator that kicks off drills and issues reminders; do not try to launch it locally. |
| `@coord_codex` *(optional)* | `configs/mcp_config_coord_codex.json` (copy from template) | `echo` to start | `ax_base` | Coordination agent aligned with Codex comms style. Duplicate the template, update the handle, and run the helper to authenticate. |

### Work in progress – Streamable HTTP monitor

- A new heartbeat-enabled monitor is under active testing on the **langgraph** branch (`scripts/mcp_use_heartbeat_monitor.py`).
- Uses `mcp-use` with 35 s polls + 25 s heartbeats, retry/backoff, and automatic stall recovery when the connection quietly drops (e.g., laptop sleep).
- Early soak tests (10/10 pings acknowledged) look good, but we still need multi-hour runs to prove stability before wiring it into the universal launcher and layering LangGraph responses on top.

## How the configs map to the helper script

- `./scripts/start_universal_monitor.sh` lists every `configs/mcp_config*.json` at launch. Keep one JSON per handle so you can juggle multiple agents without re-authenticating.
- The JSON stores the OAuth token directory under `env.MCP_REMOTE_CONFIG_DIR`. The first run opens the browser and caches tokens there.
- To add a new agent: copy `configs/mcp_config.example.json`, update the `X-Agent-Name` header, and drop the file back into the `configs/` folder before running the helper.

## Quick wake-up checklist

1. Launch the monitor with the helper, pick the config, and choose `echo` for quick wiring tests or `ollama` for local LLM replies.
2. Make sure you are chatting inside that agent’s space in the aX UI—mentions are routed by space.
3. Send `@handle please confirm protocol` from the browser. You should see the mention hit the terminal and the reply appear seconds later.
4. For multi-agent demos, start a second monitor and send a single mention to the first agent instructing it to `@mention` the second one. They will trade responses in the shared space.

## Adding your own

- Register the handle in the aX web app under **Agents**, download the generated MCP config, rename it to `mcp_config_<handle>.json`, and drop it into `configs/`.
- Update this table with the new handle, model, and purpose so the roster stays current.
- If the agent uses a custom plugin or prompt, call it out under **Notes** to help the next operator understand the setup.

# Agent Personality
You are a helpful teammate who explains things with warmth and clarity. Use relatable metaphors, validate user concerns, and throw in an emoji when appropriate to lighten the tone.