#!/bin/bash

# Quick launcher for the heartbeat LangGraph monitor against the remote aX MCP.
# Usage: scripts/start_gcp_langgraph_monitor.sh [--quiet] [optional extra args]
# Example: scripts/start_gcp_langgraph_monitor.sh --quiet --plugin-config configs/langgraph_grok_prompt.json

set -euo pipefail

CONFIG_PATH=${CONFIG_PATH:-configs/mcp_config_grok4.json}
PROMPT_PATH=${LANGGRAPH_SYSTEM_PROMPT_FILE:-prompts/ax_base_system_prompt.txt}

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo "OPENROUTER_API_KEY is not set. Export it before running this script." >&2
    exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "Config not found: $CONFIG_PATH" >&2
    exit 1
fi

if [[ ! -f "$PROMPT_PATH" ]]; then
    echo "Prompt file not found: $PROMPT_PATH" >&2
    exit 1
fi

mkdir -p logs

export LANGGRAPH_SYSTEM_PROMPT_FILE="$PROMPT_PATH"
export LANGGRAPH_BACKEND=openrouter
export OPENROUTER_MODEL="${OPENROUTER_MODEL:-x-ai/grok-4-fast:free}"

echo "🚀 Starting LangGraph heartbeat monitor"
echo "   Config : $CONFIG_PATH"
echo "   Prompt : $PROMPT_PATH"
echo "   Model  : $OPENROUTER_MODEL"
echo "   Log    : logs/gcp_langgraph_monitor.log"
if [[ "${QUIET:-0}" == "1" ]]; then
    echo "   Mode   : quiet"
fi

# Build quiet passthrough without tripping nounset on empty arrays
QUIET_FLAGS=()
if [[ "${QUIET:-0}" == "1" ]]; then
    QUIET_FLAGS=(--quiet)
fi

echo "   ErrLog: logs/gcp_langgraph_transport.err"
echo
echo "    ╔═══════════════════════════════════╗"
echo "    ║         🤖 AI MONITOR 🤖         ║"
echo "    ║                                   ║"
echo "    ║  ███╗   ███╗ ██████╗ ███╗   ██╗  ║"
echo "    ║  ████╗ ████║██╔═══██╗████╗  ██║  ║"
echo "    ║  ██╔████╔██║██║   ██║██╔██╗ ██║  ║"
echo "    ║  ██║╚██╔╝██║██║   ██║██║╚██╗██║  ║"
echo "    ║  ██║ ╚═╝ ██║╚██████╔╝██║ ╚████║  ║"
echo "    ║  ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝  ║"
echo "    ║                                   ║"
echo "    ║      👁️  WATCHING MENTIONS  👁️   ║"
echo "    ║                                   ║"
echo "    ║  🔄 Loading components...         ║"
echo "    ║                                   ║"
echo "    ║      🚀 READY TO RESPOND! 🚀      ║"
echo "    ╚═══════════════════════════════════╝"
echo

# Check if virtual environment exists
if [[ ! -f ".venv/bin/python" ]]; then
    echo "❌ Virtual environment not found at .venv/bin/python"
    echo "   Run: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

.venv/bin/python scripts/mcp_use_heartbeat_monitor.py \
    --config "$CONFIG_PATH" \
    --plugin langgraph \
    --wait-timeout "${WAIT_TIMEOUT:-25}" \
    --stall-threshold "${STALL_THRESHOLD:-180}" \
    ${QUIET_FLAGS[@]+"${QUIET_FLAGS[@]}"} \
    "$@" \
    2>> logs/gcp_langgraph_transport.err | tee logs/gcp_langgraph_monitor.log
