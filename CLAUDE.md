# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Setup and Dependencies
```bash
# Install dependencies using UV
uv sync

# Start the universal monitor with interactive setup
./scripts/start_universal_monitor.sh

# Start with default settings (skips interactive prompts)
./scripts/start_universal_monitor.sh -d
```

### Testing
```bash
# Run all tests with pytest
uv run pytest

# Run specific test file
uv run pytest tests/test_plugins.py

# Run tests with debug output
uv run pytest -v tests/
```

### Core Monitor Operations
```bash
# Start simple monitor directly (requires environment setup)
uv run python simple_working_monitor.py --loop

# Start AI battle mode between two agents
./scripts/start_universal_monitor.sh
# Then select "AI Battle Mode" from the interactive menu
```

## Architecture Overview

### Core Components

**Monitor Scripts:**
- `simple_working_monitor.py` - Main monitor that processes @mentions via MCP protocol
- `reliable_monitor.py` - Alternative monitor implementation with enhanced error handling
- `scripts/start_universal_monitor.sh` - Interactive setup script with menu-driven configuration

**Plugin System:**
- `plugins/base_plugin.py` - Abstract base class for all message processors
- `plugins/echo_plugin.py` - Simple echo implementation for testing connectivity
- `plugins/ollama_plugin.py` - AI responses using local Ollama LLM models

**MCP Client Infrastructure:**
- `src/ax_mcp_wait_client/` - Complete MCP client library for aX platform integration
- `src/ax_mcp_wait_client/wait_client.py` - Main client interface with real-time monitoring
- `src/ax_mcp_wait_client/universal_client.py` - Unified client with OAuth token management
- `src/ax_mcp_wait_client/bearer_refresh.py` - Automatic token refresh handling

### Custom MCP Client Features

Our MCP client extends the standard Model Context Protocol with production-grade capabilities:

**1. Real-Time Monitoring (wait_client.py:309-477)**
- Server-side blocking with `wait_mode` (mentions, urgent, assigned, direct, all)
- Long-polling up to 10 minutes per request
- Automatic reconnection with exponential backoff
- Duplicate message detection via processed ID tracking
- One-shot mode (`--once`) for single-message handlers

**2. Advanced OAuth (wait_client.py:48-149)**
- FileTokenStorage compatible with `mcp-remote` directory structure
- Automatic token refresh before expiry (proactive at line 299-305)
- Per-agent token isolation: `~/.mcp-auth/paxai/<agent>/`
- Atomic file writes with temp-and-replace pattern
- In-memory fallback storage for testing

**3. Agent Identity Headers (wait_client.py:330-333)**
- `X-Agent-Name`: Server-side routing and message filtering
- `X-Client-Instance`: UUID for connection tracking across reconnects
- Enables multi-agent coordination and follow-mode capabilities

**4. Universal Client (universal_client.py)**
- Dynamic tool discovery via `list_tools()`, `list_prompts()`, `list_resources()`
- Auto-generates pytest test files for any MCP server
- Interactive REPL mode for development (`--repl`)
- Supports OAuth, bearer token, or no auth
- Test generation includes sample args based on JSON schema

**5. Message Handler System**
- Pluggable processors: `echo`, `ollama`, or custom `pkg.module:Class`
- HandlerContext provides agent_name and server_url to handlers
- Handlers return True to mark message as processed
- Multiple handlers can be chained via `--handler` (repeated)

### Key Implementation Details

**OAuth Flow (wait_client.py:248-306)**
```python
# Callback server on localhost:3030
# Opens browser to authorization URL with agent_name param
# Waits up to 10 minutes for callback
# Stores tokens in FileTokenStorage
# Proactively refreshes on first request if tokens exist
```

**Message Extraction (wait_client.py:479-506)**
```python
# Handles multiple payload formats:
# - result.structuredContent (preferred)
# - result.content[].text (fallback)
# - Unwraps {"result": {"messages": [...]}}
# - Supports "events", "items", "data" keys
# - Normalizes message.id, message_id, messageId, short_id
```

**Token Refresh Strategy**
- FileTokenStorage finds latest `*_tokens.json` in `mcp-remote-*` dirs
- Sets `provider.context.token_expiry_time = 0` to force immediate refresh
- Prevents auth failures after laptop sleep or long idle periods

### Standard vs Custom MCP Client

| Feature | Standard MCP | Our Client |
|---------|--------------|------------|
| Tool Calling | ✅ Basic | ✅ Enhanced with retries |
| OAuth | ✅ Basic | ✅ Auto-refresh, multi-agent |
| Monitoring | ❌ Poll only | ✅ Server-side wait (10min) |
| Identity | ❌ None | ✅ Agent headers |
| Reconnection | ❌ Manual | ✅ Auto with backoff |
| Multi-Agent | ❌ No | ✅ Native via headers |
| Token Storage | ✅ Basic | ✅ mcp-remote compatible |
| Test Generation | ❌ No | ✅ Auto pytest files |

### Usage Examples

**Monitor with wait mode:**
```bash
uv run python -m ax_mcp_wait_client.wait_client \
  --server https://api.paxai.app/mcp \
  --oauth-server https://api.paxai.app \
  --agent-name my_agent \
  --wait-mode mentions \
  --handler echo
```

**Universal client REPL:**
```bash
uv run python -m ax_mcp_wait_client.universal_client \
  https://api.paxai.app/mcp \
  --auth oauth \
  --agent-name test_agent \
  --repl
```

**Generate tests:**
```bash
uv run python -m ax_mcp_wait_client.universal_client \
  https://api.paxai.app/mcp \
  --generate-tests tests/test_ax_tools.py
```

### Configuration System

**Agent Configs:**
- `configs/mcp_config*.json` - Per-agent MCP server configurations with OAuth tokens
- Each config maps to a unique agent handle (e.g., `@test_sentinel`, `@HaloScript`)
- Token directories are isolated per agent under `~/.mcp-auth/paxai/`

**Templates and Prompts:**
- `configs/conversation_templates.json` - Battle mode templates (tic-tac-toe, debates, etc.)
- `prompts/` - System prompt files for different AI personalities
- `prompts/ollama_monitor_system_prompt.txt` - Default AI behavior template

### Message Flow

1. **Monitor** listens for @mentions via MCP protocol to aX platform
2. **Plugin** processes the message content and generates response
3. **Client** posts the response back to the same aX space
4. **OAuth tokens** handle authentication automatically with refresh

### Key Environment Variables

- `MCP_CONFIG_PATH` - Path to agent's MCP configuration file
- `PLUGIN_TYPE` - Plugin to use (`echo` or `ollama`)
- `OLLAMA_MODEL` - Model name for Ollama plugin (`gpt-oss`, `qwen3`, etc.)
- `OLLAMA_SYSTEM_PROMPT_FILE` - Path to system prompt file
- `STARTUP_ACTION` - `listen_only` or `initiate_conversation`
- `CONVERSATION_TARGET` - Agent to initiate conversation with
- `CONVERSATION_TEMPLATE` - Template key from conversation_templates.json
- `MCP_BEARER_MODE=1` - Enable OAuth bearer token authentication

### Battle Mode Architecture

The AI Battle Mode creates automated agent-to-agent conversations:

1. **Player 2** starts in listener mode waiting for mentions
2. **Player 1** starts in battle mode and sends template-based opener to Player 2
3. Both agents then respond to each other's @mentions automatically
4. **Templates** define conversation types (tic-tac-toe, debates, roast battles)
5. **System prompts** shape each agent's personality and behavior

This enables fully autonomous AI-to-AI conversations for testing, demos, and entertainment.