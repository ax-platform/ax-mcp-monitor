#!/bin/bash

# Quick launcher for the heartbeat LangGraph monitor against the remote aX MCP.
# Usage: scripts/start_gcp_langgraph_monitor.sh [--quiet] [optional extra args]
# Example: scripts/start_gcp_langgraph_monitor.sh --quiet --plugin-config configs/langgraph_grok_prompt.json

set -euo pipefail

CONFIG_PATH=${CONFIG_PATH:-configs/mcp_config_grok4.json}
PROMPT_PATH=${LANGGRAPH_SYSTEM_PROMPT_FILE:-prompts/ax_base_system_prompt.txt}

CHECK_TOOLS=0
TOOL_CHECK_ONLY=0
QUIET_FLAG=${QUIET:-0}
TOOL_DEBUG=0
FORWARDED_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quiet)
            QUIET_FLAG=1
            ;;
        --tool-check)
            CHECK_TOOLS=1
            ;;
        --tool-check-only)
            CHECK_TOOLS=1
            TOOL_CHECK_ONLY=1
            ;;
        --tool-debug)
            TOOL_DEBUG=1
            ;;
        --config|-c)
            shift || { echo "Missing value for --config" >&2; exit 1; }
            CONFIG_PATH="$1"
            ;;
        --prompt|-p)
            shift || { echo "Missing value for --prompt" >&2; exit 1; }
            PROMPT_PATH="$1"
            ;;
        --)
            shift
            FORWARDED_ARGS+=("$@")
            break
        ;;
        *)
            FORWARDED_ARGS+=("$1")
            ;;
    esac
    shift || break
done

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

QUIET="$QUIET_FLAG"
export QUIET
if [[ "$TOOL_DEBUG" == "1" ]]; then
    export LANGGRAPH_TOOL_DEBUG=1
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
if [[ "$QUIET_FLAG" == "1" ]]; then
    echo "   Mode   : quiet"
fi

# Build quiet passthrough without tripping nounset on empty arrays
QUIET_FLAGS=()
if [[ "$QUIET_FLAG" == "1" ]]; then
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

if [[ $CHECK_TOOLS -eq 1 ]]; then
    echo "🔍 Running MCP tool preflight..."
    if .venv/bin/python - "$CONFIG_PATH" <<'PY'
import asyncio
import sys

from ax_mcp_wait_client.config_loader import parse_all_mcp_servers
from mcp_tool_manager import MCPToolManager


async def main(cfg_path: str) -> None:
    servers = parse_all_mcp_servers(cfg_path)
    if not servers:
        raise RuntimeError("No MCP servers defined in config.")

    primary_name = next(iter(servers.keys()))
    manager = MCPToolManager(servers, primary_server=primary_name)
    try:
        tools = await manager.list_tools()
        if not tools:
            raise RuntimeError("No MCP tools discovered.")
        server_summary = ", ".join(servers.keys())
        web_ready = manager.has_web_search()
        tool_names = sorted(tools.keys())
        preview = ", ".join(tool_names[:5])
        print("✅ MCP tool preflight succeeded")
        print(f"   • Servers : {server_summary}")
        print(f"   • Tools   : {len(tool_names)} available")
        if preview:
            print(f"   • Sample  : {preview}")
        print(f"   • Web search ready: {'yes' if web_ready else 'no'}")
    finally:
        try:
            await manager.shutdown()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Tool manager cleanup warning: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        sys.exit(1)
PY
    then
        if [[ $TOOL_CHECK_ONLY -eq 1 ]]; then
            echo "✅ Tool check completed; exiting (--tool-check-only)."
            exit 0
        fi
    else
        echo "❌ MCP tool preflight failed. Re-run without --tool-check to bypass." >&2
        exit 1
    fi
fi

MONITOR_CMD_ARGS=()
if [[ ${#QUIET_FLAGS[@]} -gt 0 ]]; then
    MONITOR_CMD_ARGS+=("${QUIET_FLAGS[@]}")
fi
if [[ ${#FORWARDED_ARGS[@]} -gt 0 ]]; then
    MONITOR_CMD_ARGS+=("${FORWARDED_ARGS[@]}")
fi

.venv/bin/python scripts/mcp_use_heartbeat_monitor.py \
    --config "$CONFIG_PATH" \
    --plugin langgraph \
    --wait-timeout "${WAIT_TIMEOUT:-25}" \
    --stall-threshold "${STALL_THRESHOLD:-180}" \
    ${MONITOR_CMD_ARGS[@]+"${MONITOR_CMD_ARGS[@]}"} \
    2>> logs/gcp_langgraph_transport.err | tee logs/gcp_langgraph_monitor.log
