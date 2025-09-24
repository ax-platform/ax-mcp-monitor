#!/usr/bin/env bash
#
# Quick launcher for the Grok battle-mode monitor.
# Usage:
#   ./scripts/run_grok_monitor.sh [optional_config_path]
#
# If you provide a custom config path, it overrides the default
# `configs/mcp_config_grok4.json`. All additional arguments are
# forwarded to `uv run reliable_monitor.py` so you can pass flags like
# `--log-level DEBUG` in the future if the monitor grows CLI options.

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

DEFAULT_CONFIG="$PROJECT_ROOT/configs/mcp_config_grok4.json"
CONFIG_PATH="${1:-$DEFAULT_CONFIG}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "❌ MCP config not found: $CONFIG_PATH" >&2
  exit 1
fi

export MCP_CONFIG_PATH="$CONFIG_PATH"

# Sensible heartbeat defaults (override by exporting before running).
: "${MCP_HEARTBEAT_INTERVAL:=45}"
: "${MCP_HEARTBEAT_TIMEOUT:=15}"
export MCP_HEARTBEAT_INTERVAL MCP_HEARTBEAT_TIMEOUT

# Default plugin: prefer OpenRouter when an API key is available.
if [[ -n "${PLUGIN_TYPE:-}" ]]; then
  :
elif [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  PLUGIN_TYPE="openrouter"
else
  PLUGIN_TYPE="echo"
fi

if [[ "$PLUGIN_TYPE" == "openrouter" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "❌ OPENROUTER_API_KEY is required when PLUGIN_TYPE=openrouter" >&2
  exit 1
fi

export PLUGIN_TYPE

cd "$PROJECT_ROOT"

shift $(( $# > 0 ? 1 : 0 ))

exec uv run reliable_monitor.py "$@"
