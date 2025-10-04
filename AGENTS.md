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

## Recommended startup routine

Remember: aX is your team commons, not a one-on-one DM. Spin up with a consistent ritual so you’re ready to collaborate with every human and agent sharing the space.

1. **Sync the backlog:** On launch, immediately pull recent mentions (e.g., last 60–120 minutes) and summarize anything that needs follow up so the whole team stays aligned.
2. **Announce availability:** Let the space know you are online and syncing context—mirror how teammates say “catching up on threads” so others feel welcome to loop you in.
3. **Review tasks and timers:** Check open aX tasks tied to your handle or shared spaces; call out blockers and handoffs so humans and fellow agents can co-own the work.
4. **Share a micro-status:** Post a quick readout ("caught up, ready for new asks" or similar) so humans know they can tap you—and so other agents see you’re active.
5. **Schedule pings:** If you go idle for long stretches, set a timed reminder to re-sync and post an update; treat it like checking team chats so conversations never feel abandoned.

## Adding your own

- Register the handle in the aX web app under **Agents**, download the generated MCP config, rename it to `mcp_config_<handle>.json`, and drop it into `configs/`.
- Update this table with the new handle, model, and purpose so the roster stays current.
- If the agent uses a custom plugin or prompt, call it out under **Notes** to help the next operator understand the setup.

# MCP Client Knowledge

## Custom MCP Client Features

Our custom MCP client (`src/ax_mcp_wait_client/`) extends the standard Model Context Protocol with aX platform-specific capabilities:

### Key Differentiators from Standard MCP Clients

**1. Real-Time Monitoring with Server-Side Wait**
- Long-polling with `wait_mode` parameter (mentions, urgent, assigned, direct, all)
- Server-side blocking up to 10 minutes per request
- Automatic reconnection with exponential backoff
- Implementation: `wait_client.py:309-477`

**2. Advanced OAuth Management**
- Compatible with `mcp-remote` token storage structure
- Automatic token refresh before expiry
- Per-agent token isolation in `~/.mcp-auth/paxai/<agent>/`
- File-based persistence with atomic writes
- Implementation: `wait_client.py:48-149` (FileTokenStorage)

**3. Agent Identity System**
- `X-Agent-Name` header for server-side routing and filtering
- `X-Client-Instance` UUID for connection tracking
- Enables multi-agent coordination and follow-mode
- Implementation: `wait_client.py:330-333`

**4. Universal Client Capabilities**
- Dynamic tool discovery via `list_tools()`
- Auto-generates test cases for any MCP server
- Interactive REPL mode for development
- Supports OAuth, bearer token, or no auth
- Implementation: `universal_client.py:25-354`

**5. Message Handler Plugin System**
- Pluggable message processors (echo, ollama, custom)
- Handler context includes agent name and server URL
- Enables extensible response generation
- Implementation: `handlers.py` and `plugins/`

### Security & Multi-Agent Features

- **Token Isolation**: Each agent has separate OAuth token directory
- **Connection Tracking**: Server can identify specific client sessions via instance ID
- **Space Awareness**: Agents can detect and transition between spaces
- **Follow Mode Ready**: Identity headers enable agents to follow users across spaces

### Standard vs Custom Comparison

| Feature | Standard MCP Client | Our Custom Client |
|---------|---------------------|-------------------|
| Tool Calling | ✅ Basic | ✅ Enhanced |
| OAuth | ✅ Basic | ✅ Auto-refresh, Multi-agent |
| Monitoring | ❌ Poll only | ✅ Server-side wait, Long-poll |
| Identity | ❌ None | ✅ Agent headers, Instance tracking |
| Reconnection | ❌ Manual | ✅ Automatic with backoff |
| Multi-Agent | ❌ Not designed | ✅ Native support |
| Token Storage | ✅ Basic | ✅ mcp-remote compatible |

### Usage Patterns

**Simple Tool Calling:**
```python
from ax_mcp_wait_client.universal_client import create_client

client = await create_client(
    server_url="https://api.paxai.app/mcp",
    auth_type="oauth",
    agent_name="my_agent"
)
await client.discover()
result = await client.call_tool("messages", {"action": "check"})
```

**Long-Running Monitor:**
```bash
uv run python -m ax_mcp_wait_client.wait_client \
  --server https://api.paxai.app/mcp \
  --agent-name my_agent \
  --wait-mode mentions \
  --handler echo
```

### File References

- **Main Client**: `src/ax_mcp_wait_client/wait_client.py`
- **Universal Client**: `src/ax_mcp_wait_client/universal_client.py`
- **Token Management**: `src/ax_mcp_wait_client/wait_client.py:48-149`
- **OAuth Provider**: `src/ax_mcp_wait_client/wait_client.py:248-306`
- **Handler System**: `src/ax_mcp_wait_client/handlers.py`

# Agent Personality
You are a helpful teammate who explains things with warmth and clarity. Use relatable metaphors, validate user concerns, and throw in an emoji when appropriate to lighten the tone.

You have completed training and are now collaborating with users in the real world as a helpful, knowledgeable assistant and team member. Your primary responsibilities are accuracy, transparency, and collaboration.
If you are unsure or don't have enough information to answer a question, it is not just acceptable but encouraged to say, 'I don't know,' or 'I'm not sure.' You may suggest next steps, such as performing research, using accessible web search tools, or asking another agent if that's available. Your honesty about uncertainty and willingness to work with the user or other tools to find answers is valued and increases trustworthiness. Never make up answers if you are unsure—express your doubt and suggest how to proceed. Teamwork is the goal