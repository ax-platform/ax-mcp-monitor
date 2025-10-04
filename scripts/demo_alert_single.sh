#!/usr/bin/env bash
#
# One-button fraud alert demo: starts a single monitor with streaming output
# and injects the staged alert once the monitor is ready.
#
# Usage (defaults assume local Docker agents):
#   ./scripts/demo_alert_single.sh
#
# Override defaults if needed:
#   MONITOR_CONFIG=configs/mcp_config_halo_script.json \
#   ALERT_CONFIG=configs/mcp_config_alerts.json \
#   PRIMARY_HANDLE=@HaloScript \
#   ./scripts/demo_alert_single.sh

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

MONITOR_CONFIG=${MONITOR_CONFIG:-configs/mcp_config_cbms_local.json}
ALERT_CONFIG=${ALERT_CONFIG:-configs/mcp_config_alerts.json}
PRIMARY_HANDLE=${PRIMARY_HANDLE:-@cbms}
SUPPORT_HANDLE=${SUPPORT_HANDLE:-@alerts_demo}
READY_DELAY=${READY_DELAY:-8}
PROMPT_PATH=${PROMPT_PATH:-$PROJECT_ROOT/prompts/fraud_demo_system_prompt.txt}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --monitor|--monitor-config)
      shift || { echo "Missing value for --monitor-config" >&2; exit 1; }
      MONITOR_CONFIG=$1
      ;;
    --alert|--alert-config)
      shift || { echo "Missing value for --alert-config" >&2; exit 1; }
      ALERT_CONFIG=$1
      ;;
    --primary)
      shift || { echo "Missing value for --primary" >&2; exit 1; }
      PRIMARY_HANDLE=$1
      ;;
    --support)
      shift || { echo "Missing value for --support" >&2; exit 1; }
      SUPPORT_HANDLE=$1
      ;;
    --prompt)
      shift || { echo "Missing value for --prompt" >&2; exit 1; }
      PROMPT_PATH=$1
      ;;
    --ready-delay)
      shift || { echo "Missing value for --ready-delay" >&2; exit 1; }
      READY_DELAY=$1
      ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/demo_alert_single.sh [options]
  --monitor-config <path>   Monitor MCP config (default configs/mcp_config_cbms_local.json)
  --alert-config <path>     Alert sender MCP config (default configs/mcp_config_alerts.json)
  --primary <@handle>       Agent handle to ping (default @cbms)
  --support <@handle>       Support handle mentioned in alert (default @alerts_demo)
  --prompt <path>           Prompt file (default prompts/fraud_demo_system_prompt.txt)
  --ready-delay <seconds>   Seconds to wait before firing alert (default 8)
Environment variables MONITOR_CONFIG/ALERT_CONFIG/etc. also work.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
  shift
done

if [[ ! -f "$MONITOR_CONFIG" ]]; then
  echo "❌ Monitor config not found: $MONITOR_CONFIG" >&2
  exit 1
fi

if [[ ! -f "$ALERT_CONFIG" ]]; then
  echo "❌ Alert config not found: $ALERT_CONFIG" >&2
  exit 1
fi

if [[ ! -f "$PROMPT_PATH" ]]; then
  echo "❌ Prompt file not found: $PROMPT_PATH" >&2
  exit 1
fi

mkdir -p "$PROJECT_ROOT/data/demo"

echo "🚀 Starting monitor $PRIMARY_HANDLE using $MONITOR_CONFIG"

MESSAGE_DB_PATH=$(mktemp "$PROJECT_ROOT/data/demo/${PRIMARY_HANDLE#@}_single_demo_XXXXXX.db")

cleanup() {
  if [[ -n "${MONITOR_PID:-}" ]]; then
    kill "$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
  fi
  rm -f "$MESSAGE_DB_PATH"
}

trap cleanup INT TERM EXIT

env MESSAGE_DB_PATH="$MESSAGE_DB_PATH" \
    LANGGRAPH_SYSTEM_PROMPT_FILE="$PROMPT_PATH" \
    LANGGRAPH_BACKEND="${LANGGRAPH_BACKEND:-openrouter}" \
    MCP_BEARER_MODE=1 \
    PYTHONUNBUFFERED=1 \
    "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/mcp_use_heartbeat_monitor.py" \
      --config "$MONITOR_CONFIG" \
      --plugin langgraph \
      --wait-timeout 25 \
      --stall-threshold 180 &

MONITOR_PID=$!

echo "⌛ Waiting ${READY_DELAY}s for the monitor to finish initialization..."
sleep "$READY_DELAY"

echo "📨 Sending staged alert to $PRIMARY_HANDLE"
"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/send_demo_fraud_alert.py" \
  --config "$ALERT_CONFIG" \
  --primary "$PRIMARY_HANDLE" \
  --support "$SUPPORT_HANDLE"

echo "\n🎬 Demo running. Monitor output is streaming above; press Ctrl+C to stop."

wait "$MONITOR_PID"
