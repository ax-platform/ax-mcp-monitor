#!/bin/bash
#
# Prediction Market Demo - Single Script Launch
#
# Starts 3 agents with LangGraph for round-robin prediction market
# Shows real streaming output in terminal
#

set -e

# Load environment
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

clear
echo -e "${BLUE}🎯 Prediction Market Demo${NC}"
echo -e "${BLUE}=========================${NC}"
echo ""
echo "This will start 3 AI agents for a prediction market:"
echo "  🔍 @open_router_grok4_fast - Web search capability"
echo "  🧠 @HaloScript - Analysis"
echo "  💡 @Aurora - Insights"
echo ""
echo "They will respond in round-robin fashion with REAL streaming output."
echo ""

# Kill any existing monitors
echo -e "${YELLOW}Cleaning up old monitors...${NC}"
pkill -f "simple_working_monitor" 2>/dev/null || true
pkill -f "mcp_use_heartbeat_monitor" 2>/dev/null || true
sleep 2

# Check configs exist
AGENT1_CONFIG="configs/mcp_config_grok4.json"
AGENT2_CONFIG="configs/mcp_config_halo_script.json"
AGENT3_CONFIG="configs/mcp_config_Aurora.json"

for config in "$AGENT1_CONFIG" "$AGENT2_CONFIG" "$AGENT3_CONFIG"; do
    if [[ ! -f "$config" ]]; then
        echo -e "${RED}❌ Config not found: $config${NC}"
        exit 1
    fi
done

echo -e "${GREEN}✅ All configs found${NC}"
echo ""

mkdir -p "./data/demo"

# Function to start an agent monitor
start_agent() {
    local config=$1
    local agent_name=$2
    local plugin=$3

    echo -e "${CYAN}Starting $agent_name...${NC}"
    echo "    launching monitor (takes ~5s)..."

    local message_db
    message_db=$(mktemp "./data/demo/${agent_name#@}_prediction_market_XXXXXX.db")

    export MCP_CONFIG_PATH="$config"
    export PLUGIN_TYPE="$plugin"
    export LANGGRAPH_BACKEND="${LANGGRAPH_BACKEND:-openrouter}"
    export LANGGRAPH_SYSTEM_PROMPT_FILE="$(pwd)/prompts/prediction_market_system_prompt.txt"
    export MCP_BEARER_MODE=1
    export PYTHONUNBUFFERED=1
    export MESSAGE_DB_PATH="$message_db"
    export MCP_REMOTE_QUIET=1

    local python_cmd
    if [[ -x ".venv/bin/python" ]]; then
        python_cmd=(".venv/bin/python" "-u" "simple_working_monitor.py" "--loop")
    else
        python_cmd=("uv" "run" "python" "simple_working_monitor.py" "--loop")
    fi

    "${python_cmd[@]}" 2>/dev/null &
    local pid=$!

    echo -e "${GREEN}  ✅ $agent_name started (PID: $pid)${NC}"
    echo "$pid:$message_db"
}

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Stopping all agents...${NC}"
    pkill -9 -f "simple_working_monitor" 2>/dev/null || true
    pkill -9 -f "uv run python simple_working_monitor" 2>/dev/null || true
    jobs -p | xargs -r kill -9 2>/dev/null || true
    for db in "${MESSAGE_DBS[@]}"; do
        [[ -n "$db" && -f "$db" ]] && rm -f "$db"
    done
    echo "👋 Demo stopped!"
}

trap cleanup SIGINT SIGTERM EXIT

# Start all agents
echo "🚀 Starting agents (each spin-up takes ~5s)..."
echo ""

declare -a MESSAGE_DBS=()

AGENT1_INFO=$(start_agent "$AGENT1_CONFIG" "@open_router_grok4_fast" "langgraph")
AGENT1_PID=${AGENT1_INFO%%:*}
MESSAGE_DBS+=("${AGENT1_INFO##*:}")

AGENT2_INFO=$(start_agent "$AGENT2_CONFIG" "@HaloScript" "langgraph")
AGENT2_PID=${AGENT2_INFO%%:*}
MESSAGE_DBS+=("${AGENT2_INFO##*:}")

AGENT3_INFO=$(start_agent "$AGENT3_CONFIG" "@Aurora" "langgraph")
AGENT3_PID=${AGENT3_INFO%%:*}
MESSAGE_DBS+=("${AGENT3_INFO##*:}")

echo ""
echo -e "${CYAN}⏳ Waiting for agents to connect...${NC}"
sleep 5

echo ""
echo -e "${GREEN}✅ All agents running!${NC}"
echo ""
echo -e "${CYAN}Agents:${NC}"
echo "  • @open_router_grok4_fast (PID: $AGENT1_PID)"
echo "  • @HaloScript (PID: $AGENT2_PID)"
echo "  • @Aurora (PID: $AGENT3_PID)"
echo ""
echo -e "${YELLOW}📊 Next step:${NC}"
echo "   Open another terminal and run:  uv run ./scripts/director_demo.py"
echo ""
echo -e "${BLUE}💡 Streaming starts once the director posts the first question.${NC}"
echo "   This window just keeps the three agents alive—leave it open."
echo ""
echo "Press Ctrl+C here when you're ready to shut the demo down."
echo ""

# Keep script running
wait
