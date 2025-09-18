#!/bin/bash

# Reliable Monitor Startup Script
# This script starts the reliable monitor with 99.999% message delivery guarantee

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Default values
DEBUG=false
CONFIG_FILE=""
PLUGIN_TYPE="ollama"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--debug)
            DEBUG=true
            shift
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -p|--plugin)
            PLUGIN_TYPE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -d, --debug     Enable debug mode"
            echo "  -c, --config    Specify config file path"
            echo "  -p, --plugin    Specify plugin type (default: ollama)"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 -d                    # Start with debug mode"
            echo "  $0 -c config.json        # Start with specific config"
            echo "  $0 -p echo -d            # Start with echo plugin and debug"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Change to project directory
cd "$PROJECT_DIR"

echo "🔧 Starting Reliable Monitor..."
echo "📁 Project directory: $PROJECT_DIR"

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Please install uv first:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if configs directory exists
if [ ! -d "configs" ]; then
    echo "❌ configs/ directory not found"
    echo "   Please create configs/ directory and add your MCP config files"
    exit 1
fi

# Select config file if not specified
if [ -z "$CONFIG_FILE" ]; then
    echo ""
    echo "📋 Available configurations:"
    config_files=(configs/*.json)
    
    if [ ! -e "${config_files[0]}" ]; then
        echo "❌ No configuration files found in configs/"
        echo "   Please add your MCP config JSON files to the configs/ directory"
        exit 1
    fi
    
    for i in "${!config_files[@]}"; do
        basename="${config_files[$i]}"
        echo "  $((i+1)). ${basename#configs/}"
    done
    
    echo ""
    read -p "Select configuration (1-${#config_files[@]}): " choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#config_files[@]}" ]; then
        CONFIG_FILE="${config_files[$((choice-1))]}"
    else
        echo "❌ Invalid selection"
        exit 1
    fi
fi

# Verify config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Configuration file not found: $CONFIG_FILE"
    exit 1
fi

echo "✅ Using config: $CONFIG_FILE"

# Extract agent name from config for database naming
AGENT_NAME=$(python3 -c "
import json
import sys
try:
    with open('$CONFIG_FILE') as f:
        config = json.load(f)
    print(config.get('name', 'unknown'))
except Exception as e:
    print('unknown')
")

# Set environment variables
export MCP_CONFIG_PATH="$CONFIG_FILE"
export PLUGIN_TYPE="$PLUGIN_TYPE"
export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/src:$PYTHONPATH"

# Create database directory
mkdir -p data

# Set database path to be agent-specific
export RELIABLE_DB_PATH="data/messages_${AGENT_NAME}.db"

if [ "$DEBUG" = true ]; then
    echo "🐛 Debug mode enabled"
    echo "📄 Config file: $CONFIG_FILE"
    echo "🔌 Plugin type: $PLUGIN_TYPE"
    echo "👤 Agent name: $AGENT_NAME"
    echo "💾 Database: $RELIABLE_DB_PATH"
    echo ""
fi

# Check if Ollama is running (if using ollama plugin)
if [ "$PLUGIN_TYPE" = "ollama" ]; then
    if ! pgrep -f "ollama serve" > /dev/null; then
        echo "⚠️  Ollama is not running. Starting ollama serve..."
        echo "   You may need to run 'ollama serve' in another terminal if this fails"
        ollama serve &
        sleep 2
    else
        echo "✅ Ollama is running"
    fi
fi

echo ""
echo "🚀 Starting reliable monitor for agent: $AGENT_NAME"
echo "💡 Press Ctrl+C to stop"
echo ""
echo "🔍 Monitor features:"
echo "   • Message persistence with SQLite"
echo "   • Automatic retry with exponential backoff"
echo "   • Health monitoring and auto-reconnect"
echo "   • Dead letter queue for failed messages"
echo "   • Duplicate message detection"
echo "   • Graceful shutdown and recovery"
echo ""

# Run the reliable monitor
if [ "$DEBUG" = true ]; then
    uv run python reliable_monitor.py
else
    uv run python reliable_monitor.py 2>/dev/null
fi