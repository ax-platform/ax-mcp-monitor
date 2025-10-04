#!/usr/bin/env bash

# Lightweight LangGraph monitor launcher for the banking demo.
# - Uses a dedicated message DB per run and purges it on exit
# - Defaults to the fraud demo system prompt
# - Keeps the main heartbeat launcher untouched

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

CONFIG_PATH=""
PROMPT_PATH="${PROJECT_ROOT}/prompts/fraud_demo_system_prompt.txt"
WAIT_TIMEOUT=${WAIT_TIMEOUT:-25}
STALL_THRESHOLD=${STALL_THRESHOLD:-180}
QUIET_FLAG=0
EXTRA_ARGS=()

usage() {
    cat <<'EOF'
Usage: scripts/start_demo_langgraph_monitor.sh --config <path> [options]

Options:
  --config, -c <path>       MCP config JSON (required)
  --prompt, -p <path>       Override system prompt (default: prompts/fraud_demo_system_prompt.txt)
  --wait-timeout <secs>     messages.check timeout (default: 25)
  --stall-threshold <secs>  Reconnect threshold (default: 180)
  --quiet                   Suppress LangGraph telemetry banners
  --                        Forward remaining args to the Python monitor
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config|-c)
            shift || { echo "Missing value for --config" >&2; exit 1; }
            CONFIG_PATH=$1
            ;;
        --prompt|-p)
            shift || { echo "Missing value for --prompt" >&2; exit 1; }
            PROMPT_PATH=$1
            ;;
        --wait-timeout)
            shift || { echo "Missing value for --wait-timeout" >&2; exit 1; }
            WAIT_TIMEOUT=$1
            ;;
        --stall-threshold)
            shift || { echo "Missing value for --stall-threshold" >&2; exit 1; }
            STALL_THRESHOLD=$1
            ;;
        --quiet)
            QUIET_FLAG=1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_ARGS+=("$@")
            break
            ;;
        *)
            EXTRA_ARGS+=("$1")
            ;;
    esac
    shift || break
done

if [[ -z "$CONFIG_PATH" ]]; then
    echo "--config is required" >&2
    usage
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

# Try to load from .env if exists
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    source "$PROJECT_ROOT/.env"
fi

if [[ -z "${OPENROUTER_API_KEY:-}" && "${LANGGRAPH_BACKEND:-openrouter}" == "openrouter" ]]; then
    echo "OPENROUTER_API_KEY is not set. Export it or add to .env file." >&2
    exit 1
fi

CONFIG_BASENAME=$(basename "$CONFIG_PATH")
AGENT_STEM=${CONFIG_BASENAME%.json}

mkdir -p "$PROJECT_ROOT/data/demo"
MESSAGE_DB_PATH=$(mktemp "$PROJECT_ROOT/data/demo/${AGENT_STEM}_demo_messages_XXXXXX")

cleanup() {
    rm -f "$MESSAGE_DB_PATH"
}
trap cleanup EXIT INT TERM

if [[ $QUIET_FLAG -eq 1 ]]; then
    export QUIET=1
fi

export LANGGRAPH_SYSTEM_PROMPT_FILE="$PROMPT_PATH"
export LANGGRAPH_BACKEND="${LANGGRAPH_BACKEND:-openrouter}"
export MESSAGE_DB_PATH

echo "🚀 Demo monitor launching"
echo "   Config : $CONFIG_PATH"
echo "   Prompt : $PROMPT_PATH"
echo "   Msg DB : $MESSAGE_DB_PATH (ephemeral)"
echo "   Plugin : langgraph"
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    echo "   Extra  : ${EXTRA_ARGS[*]}"
fi
echo

env PYTHONUNBUFFERED=1 uv run scripts/mcp_use_heartbeat_monitor.py \
    --config "$CONFIG_PATH" \
    --plugin langgraph \
    --wait-timeout "$WAIT_TIMEOUT" \
    --stall-threshold "$STALL_THRESHOLD" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
