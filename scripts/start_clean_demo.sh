#!/bin/bash
# Start clean demo monitors for Bank of America
# Only LangGraph plugin, no echo!

echo "🧹 Starting clean demo monitors..."
echo ""

# Kill any existing monitors
pkill -f "simple_working_monitor" 2>/dev/null
pkill -f "mcp_use_heartbeat_monitor" 2>/dev/null
sleep 2

echo "Starting agents with LangGraph (AI + web search)..."
echo ""

# Start @open_router_grok4_fast with LangGraph
echo "1️⃣  Starting @open_router_grok4_fast (web search enabled)..."
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_grok4.json &
sleep 3

# Start @HaloScript with LangGraph
if [ -f configs/mcp_config_halo_script.json ]; then
    echo "2️⃣  Starting @HaloScript..."
    ./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_halo_script.json &
    sleep 3
fi

# Start @Aurora with LangGraph
if [ -f configs/mcp_config_Aurora.json ]; then
    echo "3️⃣  Starting @Aurora..."
    ./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_Aurora.json &
    sleep 3
fi

echo ""
echo "✅ Clean demo monitors started!"
echo ""
echo "📊 Running agents:"
ps aux | grep -E "mcp_use_heartbeat_monitor|start_demo_langgraph" | grep -v grep | wc -l | xargs echo "   Active monitors:"
echo ""
echo "🎯 Ready for demo! Run:"
echo "   uv run ./scripts/director_demo.py"
echo ""
echo "⚠️  To stop all monitors:"
echo "   pkill -f mcp_use_heartbeat_monitor"