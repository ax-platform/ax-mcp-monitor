#!/usr/bin/env bash
# Simple launcher for Gemini agent

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# Check for API key
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    echo "❌ GEMINI_API_KEY not set"
    echo "Set it with: export GEMINI_API_KEY='your-key-here'"
    exit 1
fi

# Check for config
CONFIG_PATH="${PROJECT_ROOT}/configs/mcp_config_gemini.json"
if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "❌ Config not found: $CONFIG_PATH"
    exit 1
fi

echo "🤖 Starting Gemini agent..."
echo "   Config: $CONFIG_PATH"
echo "   Model: gemini-2.5-flash"
echo "   Server: https://api.paxai.app"
echo ""

# Run the monitor with Gemini plugin
env PYTHONUNBUFFERED=1 uv run scripts/mcp_use_heartbeat_monitor.py \
    --config "$CONFIG_PATH" \
    --plugin gemini \
    --wait-timeout 25 \
    --stall-threshold 180
