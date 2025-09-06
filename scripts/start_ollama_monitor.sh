#!/bin/bash
#
# Quick Start Script for Ollama Monitor Bot
# This script starts everything you need for the AI dialogue system
#

echo "🤖 Starting Ollama LLM Monitor Bot"
echo "=================================="

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama not detected. Starting Ollama..."
    ollama serve &
    sleep 3
else
    echo "✅ Ollama is running"
fi

# Set up environment
export MCP_BEARER_MODE=1
# Use config file if specified, otherwise look for default
export MCP_CONFIG_PATH="${MCP_CONFIG_PATH:-configs/mcp_config.json}"
export PLUGIN_TYPE="ollama"
export OLLAMA_MODEL="gpt-oss"

# Check if config file exists
if [ ! -f "$MCP_CONFIG_PATH" ]; then
    echo "❌ Config file not found: $MCP_CONFIG_PATH"
    echo "   Copy configs/mcp_config.example.json to configs/mcp_config.json"
    echo "   and update with your settings"
    exit 1
fi

echo "✅ Config found: $MCP_CONFIG_PATH"

# Extract config values using Python
CONFIG_VALUES=$(uv run python -c "
import json
import sys
try:
    with open('$MCP_CONFIG_PATH') as f:
        cfg = json.load(f)
    server = list(cfg['mcpServers'].values())[0]
    args = server.get('args', [])
    
    # Find URLs and agent name
    server_url = None
    oauth_url = None
    agent_name = None
    
    for i, arg in enumerate(args):
        if not arg.startswith('-') and 'mcp' in arg:
            server_url = arg
        elif arg == '--oauth-server' and i+1 < len(args):
            oauth_url = args[i+1]
        elif arg.startswith('X-Agent-Name:'):
            agent_name = arg.split(':', 1)[1]
    
    token_dir = server['env']['MCP_REMOTE_CONFIG_DIR']
    print(f'{token_dir}|{server_url}|{oauth_url}|{agent_name}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

if [[ $CONFIG_VALUES == ERROR:* ]]; then
    echo "❌ Failed to parse config: ${CONFIG_VALUES#ERROR: }"
    exit 1
fi

# Parse the values
IFS='|' read -r TOKEN_DIR SERVER_URL OAUTH_URL AGENT_NAME <<< "$CONFIG_VALUES"

# Check if token directory exists and has tokens
TOKEN_FILE_PATTERN="$TOKEN_DIR/mcp-remote-*/4e91aa3e5d6e102a531e051834d6cbaa_tokens.json"
if ! ls $TOKEN_FILE_PATTERN >/dev/null 2>&1; then
    echo ""
    echo "🔐 First run detected - need to authenticate"
    echo "   Agent: $AGENT_NAME"
    echo "   Server: $SERVER_URL"
    echo ""
    echo "📋 Starting OAuth flow (browser will open)..."
    
    # Set environment for prime_tokens
    export MCP_SERVER_URL="$SERVER_URL"
    export MCP_OAUTH_SERVER_URL="$OAUTH_URL"
    export MCP_REMOTE_CONFIG_DIR="$TOKEN_DIR"
    export MCP_AGENT_NAME="$AGENT_NAME"
    
    # Run prime_tokens to get OAuth tokens
    if uv run python src/ax_mcp_wait_client/prime_tokens.py; then
        echo "✅ Authentication successful!"
    else
        echo "❌ Authentication failed. Please try again."
        exit 1
    fi
fi

echo ""
echo "Configuration:"
echo "  Config: $MCP_CONFIG_PATH"
echo "  Agent: $AGENT_NAME"
echo "  Model: $OLLAMA_MODEL"
echo ""
echo "📡 Starting monitor bot in loop mode..."
echo "   The bot will respond to @${AGENT_NAME} mentions"
echo "   Press Ctrl+C to stop"
echo ""

# Start the bot
uv run python src/ax_monitor_bot.py --loop