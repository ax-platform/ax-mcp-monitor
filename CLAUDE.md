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
- `src/ax_mcp_wait_client/wait_client.py` - Main client interface
- `src/ax_mcp_wait_client/universal_client.py` - Unified client with OAuth token management
- `src/ax_mcp_wait_client/bearer_refresh.py` - Automatic token refresh handling

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