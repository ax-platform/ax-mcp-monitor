#!/usr/bin/env bash
# Fast prediction market demo using the round-robin director and LangGraph monitors.

set -euo pipefail

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

mkdir -p data/demo logs

DEFAULT_AGENT_CONFIGS=(
  "configs/mcp_config_cbms_local.json:@cbms"
  "configs/mcp_config_jwt_local.json:@jwt"
  "configs/mcp_config_Aurora.json:@Aurora"
)

if [[ -n "${AGENT_CONFIGS:-}" ]]; then
  read -r -a AGENT_ENTRIES <<< "${AGENT_CONFIGS}"
else
  AGENT_ENTRIES=("${DEFAULT_AGENT_CONFIGS[@]}")
fi

if [[ ${#AGENT_ENTRIES[@]} -lt 2 ]]; then
  echo "Need at least two AGENT_CONFIGS entries (config:@handle)." >&2
  exit 1
fi

PROMPT_PATH="$(pwd)/prompts/prediction_market_system_prompt.txt"

echo -e "${BLUE}🚀 Spinning up ${#AGENT_ENTRIES[@]} monitors for the prediction market...${NC}"

PIDS=()
DBS=()
HANDLES=()

cleanup() {
  trap - INT TERM EXIT
  echo -e "\n${YELLOW}🛑 Stopping demo monitors...${NC}"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  for db in "${DBS[@]}"; do
    [[ -f "$db" ]] && rm -f "$db"
  done
  echo -e "${GREEN}✅ Demo shutdown complete${NC}"
}

trap cleanup INT TERM EXIT

start_monitor() {
  local pair="$1"
  local config="${pair%%:*}"
  local handle="${pair#*:}"

  if [[ ! -f "$config" ]]; then
    echo "❌ Config not found: $config" >&2
    exit 1
  fi

  local normalized=${handle#@}
  local db
  db=$(mktemp "./data/demo/${normalized}_pm_demo_XXXXXX.db")

  echo -e "  ${CYAN}• starting ${handle}${NC}"

  MESSAGE_DB_PATH="$db" \
  LANGGRAPH_SYSTEM_PROMPT_FILE="$PROMPT_PATH" \
  LANGGRAPH_BACKEND="${LANGGRAPH_BACKEND:-openrouter}" \
  MCP_BEARER_MODE=1 \
  PYTHONUNBUFFERED=1 \
  .venv/bin/python scripts/mcp_use_heartbeat_monitor.py \
    --config "$config" \
    --plugin langgraph \
    --wait-timeout 25 \
    --stall-threshold 180 \
    >"logs/${normalized}_pm_demo.log" 2>&1 &

  local pid=$!
  PIDS+=("$pid")
  DBS+=("$db")
  HANDLES+=("$handle")

  echo -e "    ${GREEN}✓ monitor PID ${pid}${NC}"
}

for entry in "${AGENT_ENTRIES[@]}"; do
  start_monitor "$entry"
done

echo ""
echo -e "${YELLOW}⏳ Waiting 5s for monitors to finish connecting...${NC}"
sleep 5

printf '\n%s\n' "${CYAN}🎯 Launching round-robin director...${NC}"

.venv/bin/python scripts/director_round_robin.py --agents "${HANDLES[@]}"

cleanup
