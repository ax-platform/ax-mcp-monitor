#!/bin/bash
#
# Quick launcher for the LangGraph plugin using OpenRouter Grok 4 Fast by default.
# Usage: scripts/run_langgraph_monitor.sh [config_path] [model]
# Example: scripts/run_langgraph_monitor.sh configs/mcp_config_grok4.json x-ai/grok-4-fast:free
# Remaining arguments after '--' are forwarded to simple_working_monitor.py.

set -euo pipefail

CONFIG_PATH="${1:-configs/mcp_config_grok4.json}"
MODEL="${2:-${OPENROUTER_MODEL:-x-ai/grok-4-fast:free}}"

# Shift positional args if provided so we can pass extras via '--'
if [[ $# -ge 1 ]]; then
    shift
fi
if [[ $# -ge 1 ]]; then
    shift
fi

PROMPT_PATH="${LANGGRAPH_SYSTEM_PROMPT_FILE:-$(pwd)/prompts/ax_base_system_prompt.txt}"

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "Config not found: $CONFIG_PATH" >&2
    exit 1
fi

if [[ ! -f "$PROMPT_PATH" ]]; then
    echo "Prompt file not found: $PROMPT_PATH" >&2
    exit 1
fi

# Source .env file if it exists to get OPENROUTER_API_KEY
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

export MCP_CONFIG_PATH="$CONFIG_PATH"
export PLUGIN_TYPE="langgraph"
export LANGGRAPH_BACKEND="openrouter"
export OPENROUTER_MODEL="$MODEL"
export OPENROUTER_SYSTEM_PROMPT_FILE="$PROMPT_PATH"
export LANGGRAPH_SYSTEM_PROMPT_FILE="$PROMPT_PATH"
export BASE_SYSTEM_PROMPT_PATH="$PROMPT_PATH"

# keep legacy envs so other plugins won't fail if referenced
export OPENROUTER_BASE_PROMPT_FILE="$PROMPT_PATH"
export LANGGRAPH_BASE_PROMPT_FILE="$PROMPT_PATH"

exec uv run reliable_monitor.py --loop "$@"
