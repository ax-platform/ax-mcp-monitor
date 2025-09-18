#!/bin/bash
#
# Universal MCP Monitor Startup Script
# 
# This script provides a user-friendly interface for starting MCP monitors
# with support for multiple agents, plugins, and models.
#

set -e

DEFAULT_MODE=0
FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--default)
            DEFAULT_MODE=1
            ;;
        --)
            shift
            FORWARD_ARGS+=("$@")
            break
            ;;
        *)
            FORWARD_ARGS+=("$1")
            ;;
    esac
    shift
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Clear screen for better UX
clear

echo -e "${BLUE}🤖 Universal MCP Monitor Startup${NC}"
echo -e "${BLUE}=================================${NC}"
echo ""

# Check UV installation
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ UV not found. Please install UV first:${NC}"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Function to select config file
select_config() {
    echo -e "${CYAN}📋 Available Configurations:${NC}"
    
    configs=($(find configs -name "mcp_config*.json" | sort))
    
    if [ ${#configs[@]} -eq 0 ]; then
        echo -e "${RED}❌ No config files found in configs/ directory${NC}"
        exit 1
    fi
    
    # Add option to create new config
    configs+=("configs/NEW_AGENT")
    
    echo ""

    local default_config="configs/mcp_config.json"
    local default_index=1

    for i in "${!configs[@]}"; do
        local entry="${configs[$i]}"
        if [[ "$entry" == "configs/NEW_AGENT" ]]; then
            echo "   $((i+1))) 🆕 Create new agent configuration"
            continue
        fi

        # Extract agent name from config
        AGENT_NAME=$(jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$entry" 2>/dev/null || echo "unknown")
        local label_suffix=""
        if [[ "$entry" == "$default_config" ]]; then
            default_index=$((i+1))
            label_suffix=" (default)"
        fi
        echo "   $((i+1))) ${entry} (Agent: $AGENT_NAME)${label_suffix}"
    done

    # Ensure the default points at a real config entry
    if [[ $default_index -gt ${#configs[@]} ]] || [[ "${configs[$((default_index-1))]}" == "configs/NEW_AGENT" ]]; then
        for idx in "${!configs[@]}"; do
            if [[ "${configs[$idx]}" != "configs/NEW_AGENT" ]]; then
                default_index=$((idx+1))
                break
            fi
        done
    fi

    echo ""
    if (( DEFAULT_MODE )); then
        choice=$default_index
        echo "   👉 Auto-selecting default configuration option ${choice}"
    else
        read -p "Select configuration (1-${#configs[@]}) [default: ${default_index}]: " choice
        if [[ -z "$choice" ]]; then
            choice=$default_index
            echo "   👉 Using default configuration option ${choice}"
        fi
    fi

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#configs[@]} ]; then
        echo -e "${RED}❌ Invalid choice${NC}"
        exit 1
    fi

    selected_config="${configs[$((choice-1))]}"
    
    if [[ "$selected_config" == "configs/NEW_AGENT" ]]; then
        create_new_agent_config
    else
        export MCP_CONFIG_PATH="$selected_config"
    fi
}

# Function to create new agent config
create_new_agent_config() {
    echo ""
    echo -e "${CYAN}🆕 Creating New Agent Configuration${NC}"
    echo "=================================="
    
    read -p "Enter agent name (e.g., backend_dev, frontend_dev): " agent_name
    
    if [[ -z "$agent_name" ]]; then
        echo -e "${RED}❌ Agent name cannot be empty${NC}"
        exit 1
    fi
    
    # Create config based on template
    new_config="configs/mcp_config_${agent_name}.json"
    
    cat > "$new_config" << EOF
{
  "mcpServers": {
    "ax-gcp": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@0.1.18",
        "https://api.paxai.app/mcp",
        "--transport",
        "http-only",
        "--allow-http",
        "--oauth-server",
        "https://api.paxai.app",
        "--header",
        "X-Agent-Name:${agent_name}"
      ],
      "env": {
        "MCP_REMOTE_CONFIG_DIR": "/Users/$(whoami)/.mcp-auth/paxai/83a87008/${agent_name}"
      }
    }
  }
}
EOF
    
    echo -e "${GREEN}✅ Created config: $new_config${NC}"
    echo -e "${YELLOW}⚠️  Note: OAuth authentication will be required on first run${NC}"
    
    export MCP_CONFIG_PATH="$new_config"
}

# Function to select plugin
select_plugin() {
    echo ""
    echo -e "${CYAN}🔌 Plugin Selection:${NC}"

    local default_plugin="${PLUGIN_TYPE:-ollama}"
    local default_choice=2

    echo "   1) 📢 Echo Plugin (for testing - echoes messages back)"
    echo "   2) 🧠 Ollama Plugin (intelligent AI responses)"
    if [[ "$default_plugin" == "echo" ]]; then
        default_choice=1
        echo "      (default -> option 1)"
    else
        echo "      (default -> option 2)"
    fi
    echo ""
    
    if (( DEFAULT_MODE )); then
        plugin_choice=$default_choice
        echo "   👉 Auto-selecting default plugin option ${plugin_choice}"
    else
        read -p "Select plugin (1-2) [default: ${default_choice}]: " plugin_choice
        if [[ -z "$plugin_choice" ]]; then
            plugin_choice=$default_choice
            echo "   👉 Using default plugin option ${plugin_choice}"
        fi
    fi
    
    case $plugin_choice in
        1)
            export PLUGIN_TYPE="echo"
            echo -e "${GREEN}✅ Selected: Echo Plugin${NC}"
            ;;
        2)
            export PLUGIN_TYPE="ollama"
            echo -e "${GREEN}✅ Selected: Ollama Plugin${NC}"
            select_ollama_model
            select_system_prompt
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            exit 1
            ;;
    esac
}

# Function to select Ollama model
select_ollama_model() {
    echo ""
    echo -e "${CYAN}🤖 Available Ollama Models:${NC}"
    
    # Check if Ollama is running
    if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Ollama not running. Will start automatically.${NC}"
        available_models=("gpt-oss" "llama3.2" "qwen2.5" "custom")
    else
        # Get installed models
        available_models=($(ollama list | awk 'NR>1 {print $1}' | cut -d: -f1))
        available_models+=("custom")
    fi
    
    echo ""
    local preferred_model="${OLLAMA_MODEL:-gpt-oss}"
    local default_index=1
    for i in "${!available_models[@]}"; do
        local label="${available_models[$i]}"
        if [[ "$label" == "custom" ]]; then
            if [[ "$preferred_model" == "custom" ]]; then
                default_index=$((i+1))
            fi
            echo "   $((i+1))) 🔧 Enter custom model name"
        else
            if [[ "$label" == "$preferred_model" ]]; then
                default_index=$((i+1))
                label+=" (default)"
            fi
            echo "   $((i+1))) ${label}"
        fi
    done
    echo ""
    
    if (( DEFAULT_MODE )); then
        model_choice=$default_index
        echo "   👉 Auto-selecting default model option ${model_choice}"
    else
        read -p "Select model (1-${#available_models[@]}) [default: ${default_index}]: " model_choice
        if [[ -z "$model_choice" ]]; then
            model_choice=$default_index
            echo "   👉 Using default model option ${model_choice}"
        fi
    fi
    
    if ! [[ "$model_choice" =~ ^[0-9]+$ ]] || [ "$model_choice" -lt 1 ] || [ "$model_choice" -gt ${#available_models[@]} ]; then
        echo -e "${RED}❌ Invalid choice${NC}"
        exit 1
    fi
    
    selected_model="${available_models[$((model_choice-1))]}"
    
    if [[ "$selected_model" == "custom" ]]; then
        read -p "Enter custom model name: " custom_model
        export OLLAMA_MODEL="$custom_model"
    else
        export OLLAMA_MODEL="$selected_model"
    fi
    
    echo -e "${GREEN}✅ Selected: $OLLAMA_MODEL${NC}"
}

select_system_prompt() {
    echo ""
    echo -e "${CYAN}🧾 System Prompt Selection:${NC}"

    local prompt_dir="prompts"
    local default_prompt="${prompt_dir}/ollama_monitor_system_prompt.txt"
    local selected_prompt=""

    if [[ -n "$OLLAMA_SYSTEM_PROMPT_FILE" ]]; then
        echo "   ⚙️  Using pre-set prompt from OLLAMA_SYSTEM_PROMPT_FILE"
        if [[ "$OLLAMA_SYSTEM_PROMPT_FILE" != /* ]]; then
            export OLLAMA_SYSTEM_PROMPT_FILE="$(pwd)/$OLLAMA_SYSTEM_PROMPT_FILE"
        fi
        return
    fi

    if [[ ! -d "$prompt_dir" ]]; then
        echo -e "${YELLOW}⚠️  Prompt directory not found. Using plugin default.${NC}"
        return
    fi

    local prompt_files=()
    while IFS= read -r prompt_path; do
        prompt_files+=("$prompt_path")
    done < <(find "$prompt_dir" -maxdepth 1 -type f -name "*.txt" | sort)

    if [[ -f "$default_prompt" ]]; then
        local has_default=0
        for prompt_path in "${prompt_files[@]}"; do
            if [[ "$prompt_path" == "$default_prompt" ]]; then
                has_default=1
                break
            fi
        done
        if [[ $has_default -eq 0 ]]; then
            prompt_files+=("$default_prompt")
        fi
    fi

    if [[ ${#prompt_files[@]} -eq 0 ]]; then
        echo -e "${YELLOW}⚠️  No prompt files found. Using plugin default.${NC}"
        return
    fi

    local default_index=-1
    echo ""
    for i in "${!prompt_files[@]}"; do
        local display_path="${prompt_files[$i]}"
        if [[ "$display_path" == "$default_prompt" ]]; then
            display_path+=" (default)"
            default_index=$((i+1))
        fi
        echo "   $((i+1))) ${display_path}"
    done

    if [[ $default_index -lt 1 ]]; then
        default_index=1
    fi

    local extra_offset=${#prompt_files[@]}
    echo "   $((extra_offset+1))) 🔧 Enter custom prompt path"
    echo "   $((extra_offset+2))) 🚫 Use plugin fallback prompt"
    echo ""

    local prompt_choice
    if (( DEFAULT_MODE )); then
        prompt_choice=$default_index
        echo "   👉 Auto-selecting default prompt option ${prompt_choice}"
    else
        read -p "Select prompt (1-$((extra_offset+2))) [default: ${default_index}]: " prompt_choice
        if [[ -z "$prompt_choice" ]]; then
            prompt_choice=$default_index
            echo "   👉 Using default prompt option ${prompt_choice}"
        fi
    fi

    if ! [[ "$prompt_choice" =~ ^[0-9]+$ ]] || [ "$prompt_choice" -lt 1 ] || [ "$prompt_choice" -gt $((extra_offset+2)) ]; then
        echo -e "${RED}❌ Invalid choice${NC}"
        exit 1
    fi

    if [ "$prompt_choice" -eq $((extra_offset+1)) ]; then
        local custom_prompt=""
        read -p "Enter full path to prompt file: " custom_prompt
        if [[ -z "$custom_prompt" ]]; then
            echo -e "${RED}❌ Prompt path cannot be empty${NC}"
            exit 1
        fi
        selected_prompt="$custom_prompt"
    elif [ "$prompt_choice" -eq $((extra_offset+2)) ]; then
        echo -e "${YELLOW}ℹ️  Using plugin fallback system prompt.${NC}"
        return
    else
        selected_prompt="${prompt_files[$((prompt_choice-1))]}"
    fi

    if [[ ! -f "$selected_prompt" ]]; then
        echo -e "${RED}❌ Prompt file not found: $selected_prompt${NC}"
        exit 1
    fi

    if [[ "$selected_prompt" != /* ]]; then
        selected_prompt="$(pwd)/$selected_prompt"
    fi

    export OLLAMA_SYSTEM_PROMPT_FILE="$selected_prompt"
    echo -e "${GREEN}✅ Using system prompt: $OLLAMA_SYSTEM_PROMPT_FILE${NC}"
}

# Main execution
echo "This script helps you start MCP monitors with different agents and plugins."
echo ""

# Step 1: Select configuration
select_config

# Step 2: Select plugin
select_plugin

# Extract agent name from config
AGENT_NAME=$(jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$MCP_CONFIG_PATH" 2>/dev/null || echo "unknown")

# Step 3: Set up environment
export MCP_BEARER_MODE=1

echo ""
echo -e "${GREEN}📋 Final Configuration:${NC}"
echo "   Config: $MCP_CONFIG_PATH"
echo "   Agent: @$AGENT_NAME"
echo "   Plugin: $PLUGIN_TYPE"
if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
    echo "   Model: $OLLAMA_MODEL"
    if [[ -n "$OLLAMA_SYSTEM_PROMPT_FILE" ]]; then
        echo "   System prompt: $OLLAMA_SYSTEM_PROMPT_FILE"
    else
        echo "   System prompt: (plugin fallback)"
    fi
fi
echo ""

# Check if config exists
if [[ ! -f "$MCP_CONFIG_PATH" ]]; then
    echo -e "${RED}❌ Config file not found: $MCP_CONFIG_PATH${NC}"
    exit 1
fi

# Check for existing tokens
TOKEN_DIR=$(jq -r '.mcpServers | to_entries[0].value.env.MCP_REMOTE_CONFIG_DIR' "$MCP_CONFIG_PATH")

if [[ ! -d "$TOKEN_DIR" ]]; then
    echo -e "${YELLOW}🔐 First run detected - OAuth setup required${NC}"
    echo "   Will authenticate with aX platform..."
    
    # Run OAuth setup using the original script logic
    CONFIG_VALUES=$(uv run python -c "
import json
with open('$MCP_CONFIG_PATH') as f:
    cfg = json.load(f)
server = list(cfg['mcpServers'].values())[0]
args = server.get('args', [])

server_url = None
oauth_url = None
agent_name = None

for i, arg in enumerate(args):
    if not arg.startswith('-') and 'mcp' in arg:
        server_url = arg
    elif arg == '--oauth-server' and i+1 < len(args):
        oauth_url = args[i+1]
    elif arg.startswith('X-Agent-Name:'):
        agent_name = arg.split(':', 1)[1]

print(f'{server_url}|{oauth_url}|{agent_name}')
")
    
    IFS='|' read -r SERVER_URL OAUTH_URL EXTRACTED_AGENT_NAME <<< "$CONFIG_VALUES"
    
    # Set environment for OAuth
    export MCP_SERVER_URL="$SERVER_URL"
    export MCP_OAUTH_SERVER_URL="$OAUTH_URL"
    export MCP_REMOTE_CONFIG_DIR="$TOKEN_DIR"
    export MCP_AGENT_NAME="$EXTRACTED_AGENT_NAME"
    
    echo ""
    echo "📋 Starting OAuth flow (browser will open)..."
    
    if uv run python src/ax_mcp_wait_client/prime_tokens.py; then
        echo -e "${GREEN}✅ Authentication successful!${NC}"
    else
        echo -e "${RED}❌ Authentication failed. Please try again.${NC}"
        exit 1
    fi
fi

TOKEN_FILES=$(find "$TOKEN_DIR" -name "*_tokens.json" 2>/dev/null | wc -l)
if [[ $TOKEN_FILES -eq 0 ]]; then
    echo -e "${RED}❌ No OAuth tokens found in $TOKEN_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Found $TOKEN_FILES OAuth token file(s)${NC}"

# Setup Ollama if needed
if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
    if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Ollama not running. Starting Ollama...${NC}"
        if command -v ollama &> /dev/null; then
            echo "   Running: ollama serve"
            ollama serve &
            sleep 3
        else
            echo -e "${RED}❌ Ollama not installed. Install with:${NC}"
            echo "   curl -fsSL https://ollama.ai/install.sh | sh"
            exit 1
        fi
    fi
    
    # Check if model is available
    if ! ollama list | grep -q "$OLLAMA_MODEL"; then
        echo -e "${YELLOW}⚠️  Model $OLLAMA_MODEL not found. Pulling...${NC}"
        ollama pull "$OLLAMA_MODEL"
    fi
    
    echo -e "${GREEN}✅ Ollama ready with $OLLAMA_MODEL model${NC}"
fi

# Final summary and start
echo ""
echo -e "${BLUE}🎯 Starting MCP Monitor...${NC}"
echo "   Listening for @$AGENT_NAME mentions"
echo "   Plugin: $PLUGIN_TYPE"
if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
    echo "   Model: $OLLAMA_MODEL"
    if [[ -n "$OLLAMA_SYSTEM_PROMPT_FILE" ]]; then
        echo "   System prompt: $OLLAMA_SYSTEM_PROMPT_FILE"
    else
        echo "   System prompt: (plugin fallback)"
    fi
fi
echo "   Press Ctrl+C to stop"
echo ""
echo -e "${CYAN}💡 Test by mentioning @$AGENT_NAME in the aX platform!${NC}"
echo ""

# Run the monitor
if (( ${#FORWARD_ARGS[@]} )); then
    uv run python simple_working_monitor.py --loop "${FORWARD_ARGS[@]}"
else
    uv run python simple_working_monitor.py --loop
fi