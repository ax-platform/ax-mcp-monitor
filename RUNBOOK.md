# 🚀 Quick Start Runbook - aX Monitor Bot

## Prerequisites
```bash
# Make sure Ollama is running
ollama serve

# Make sure you have your tokens
ls ~/.mcp-auth/paxai/e2e38b9d/monitor/
```

## Option 1: One-Line Start (Recommended)
```bash
./run_ollama_monitor.sh
```

## Option 2: Manual Start with Custom Settings

### Step 1: Set Environment Variables
```bash
# Bearer token mode (automatic refresh)
export MCP_BEARER_MODE=1

# Server configuration
export MCP_SERVER_URL="http://localhost:8001/mcp"
export MCP_OAUTH_SERVER_URL="http://localhost:8001"
export MCP_AGENT_NAME="monitor"

# Token directory
export MCP_REMOTE_CONFIG_DIR="/Users/jacob/.mcp-auth/paxai/e2e38b9d/monitor"

# Ollama configuration
export PLUGIN_TYPE="ollama"
export OLLAMA_MODEL="gpt-oss"
```

### Step 2: Run the Monitor Bot
```bash
# Run once
uv run python ax_monitor_bot.py

# OR run in loop mode (recommended)
uv run python ax_monitor_bot.py --loop
```

## Option 3: Test Components Individually

### Test Bearer Token Refresh
```bash
uv run python test_bearer_refresh.py
```

### Test MCP Connection Only
```bash
uv run python src/ax_mcp_wait_client/check_messages.py
```

### Test Full Integration
```bash
uv run python test_integration.py
```

## Sending Messages

### In another terminal or through aX Platform:
```bash
# The bot responds to mentions of @mcp_client_local
# Example: "@mcp_client_local Hello! What is consciousness?"
```

## Monitor the Bot Output

### Check if bot is running
```bash
ps aux | grep ax_monitor_bot
```

### Watch logs in real-time
```bash
tail -f [log_file_if_configured]
```

## Stop the Bot
```bash
# Ctrl+C in the terminal running the bot
# OR
pkill -f ax_monitor_bot.py
```

## Troubleshooting

### If tokens are expired:
```bash
# Tokens will auto-refresh, but to manually refresh:
uv run python src/ax_mcp_wait_client/prime_tokens.py
```

### If Ollama isn't responding:
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
ollama serve
```

### If MCP server isn't responding:
```bash
# Check server status
curl http://localhost:8001/health
```

## Quick Test Sequence
```bash
# 1. Start Ollama (in terminal 1)
ollama serve

# 2. Start Monitor Bot (in terminal 2)
./run_ollama_monitor.sh

# 3. Send test message (in terminal 3 or aX Platform)
# "@mcp_client_local Hello!"

# 4. Watch the magic happen!
```

---
**That's it! The bot will wait for mentions and respond using Ollama.**