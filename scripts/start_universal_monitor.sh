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

# Interactive cursor menu helper
cursor_menu() {
    local title="$1"
    local instructions="$2"
    local default_index="$3"
    shift 3
    local options=("$@")

    local values=()
    local labels=()
    local details=()
    for option in "${options[@]}"; do
        local value="${option%%::*}"           # Everything before first ::
        local remainder="${option#*::}"        # Everything after first ::
        local label="${remainder%%::*}"        # Everything before next ::
        local detail="${remainder#*::}"        # Everything after next ::
        values+=("$value")
        labels+=("$label")
        details+=("$detail")
    done

    local total=${#values[@]}
    if [[ $total -eq 0 ]]; then
        echo ""
        return 1
    fi

    local selected=$((default_index - 1))
    if (( selected < 0 || selected >= total )); then
        selected=0
    fi

    local rendered=0
    local lines_to_redraw=$((total * 2 + 4))

    printf '\033[?25l' >&2
    trap 'printf "\033[?25h" >&2; exit 1' INT TERM

    while true; do
        if (( rendered )); then
            printf "\033[%dA" "$lines_to_redraw" >&2
            printf "\033[J" >&2
        else
            rendered=1
        fi

        echo -e "$title" >&2
        echo -e "$instructions" >&2
        echo >&2
        for i in "${!labels[@]}"; do
            local pointer_icon="  "
            local label_text="${labels[$i]}"
            local detail="${details[$i]}"

            if [[ $i -eq $selected ]]; then
                pointer_icon="${YELLOW}▶▶${NC}"
                label_text="${GREEN}${label_text}${NC}"
            fi

            printf "  %b %b\n" "$pointer_icon" "$label_text" >&2

            if [[ -n "$detail" ]]; then
                printf "    %s\n" "$detail" >&2
            else
                printf "\n" >&2
            fi
        done
        printf "\n" >&2

        IFS= read -rsn1 key
        case "$key" in
            $'\x1b')
                read -rsn2 key
                case "$key" in
                    '[A')
                        ((selected--))
                        if (( selected < 0 )); then
                            selected=$((total - 1))
                        fi
                        ;;
                    '[B')
                        ((selected++))
                        if (( selected >= total )); then
                            selected=0
                        fi
                        ;;
                esac
                ;;
            'k'|'K')
                ((selected--))
                if (( selected < 0 )); then
                    selected=$((total - 1))
                fi
                ;;
            'j'|'J')
                ((selected++))
                if (( selected >= total )); then
                    selected=0
                fi
                ;;
            '')
                printf '\033[?25h' >&2
                trap - INT TERM
                printf "\033[J" >&2
                echo "${values[$selected]}"
                return 0
                ;;
            'q'|'Q')
                printf '\033[?25h' >&2
                trap - INT TERM
                printf "\033[J" >&2
                return 1
                ;;
        esac
    done
}

exit_with_goodbye() {
    echo
    echo -e "${YELLOW}👋 Exiting...${NC}"
    exit 0
}

exit_if_quit() {
    local input="$1"
    if [[ "$input" == "q" || "$input" == "Q" ]]; then
        exit_with_goodbye
    fi
}

get_agent_name_from_config() {
    local config_path="$1"
    jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$config_path" 2>/dev/null || echo "unknown"
}

set_mcp_token_env() {
    local config_path="$1"
    local token_dir
    token_dir=$(jq -r '.mcpServers | to_entries[0].value.env.MCP_REMOTE_CONFIG_DIR' "$config_path" 2>/dev/null)
    if [[ -n "$token_dir" && "$token_dir" != "null" ]]; then
        export MCP_REMOTE_CONFIG_DIR="$token_dir"
    else
        unset MCP_REMOTE_CONFIG_DIR
    fi
}

ensure_oauth_tokens() {
    local config_path="$1"
    local agent_label="$2"

    if [[ -z "$config_path" ]]; then
        echo -e "${RED}❌ No config path provided for token check${NC}"
        exit 1
    fi

    if [[ ! -f "$config_path" ]]; then
        echo -e "${RED}❌ Config file not found: $config_path${NC}"
        exit 1
    fi

    local display_name="$agent_label"
    if [[ -z "$display_name" ]]; then
        display_name=$(get_agent_name_from_config "$config_path")
    fi
    if [[ -z "$display_name" ]]; then
        display_name="unknown"
    fi
    if [[ "${display_name:0:1}" != "@" ]]; then
        display_name="@$display_name"
    fi

    set_mcp_token_env "$config_path"
    local token_dir="${MCP_REMOTE_CONFIG_DIR:-}"

    if [[ -z "$token_dir" || "$token_dir" == "null" ]]; then
        token_dir=$(jq -r '.mcpServers | to_entries[0].value.env.MCP_REMOTE_CONFIG_DIR' "$config_path" 2>/dev/null)
        if [[ "$token_dir" == "null" ]]; then
            token_dir=""
        fi
        if [[ -n "$token_dir" ]]; then
            export MCP_REMOTE_CONFIG_DIR="$token_dir"
        fi
    fi

    if [[ -z "$token_dir" ]]; then
        echo -e "${RED}❌ No MCP_REMOTE_CONFIG_DIR defined for $display_name in $config_path${NC}"
        exit 1
    fi

    if [[ ! -d "$token_dir" ]]; then
        echo -e "${YELLOW}🔐 First run detected for $display_name - OAuth setup required${NC}"
        mkdir -p "$token_dir"

        local config_values
        config_values=$(CONFIG_PATH="$config_path" uv run python - <<'PY'
import json
import os

config_path = os.environ["CONFIG_PATH"]
with open(config_path) as f:
    cfg = json.load(f)
server = list(cfg["mcpServers"].values())[0]
args = server.get("args", [])
server_url = None
oauth_url = None
agent_name = None
for i, arg in enumerate(args):
    if not arg.startswith("-") and "mcp" in arg:
        server_url = arg
    elif arg == "--oauth-server" and i + 1 < len(args):
        oauth_url = args[i + 1]
    elif arg.startswith("X-Agent-Name:"):
        agent_name = arg.split(":", 1)[1]
print(f"{server_url}|{oauth_url}|{agent_name}")
PY
)

        IFS='|' read -r SERVER_URL OAUTH_URL EXTRACTED_AGENT_NAME <<< "$config_values"

        export MCP_SERVER_URL="$SERVER_URL"
        export MCP_OAUTH_SERVER_URL="$OAUTH_URL"
        export MCP_REMOTE_CONFIG_DIR="$token_dir"
        export MCP_AGENT_NAME="$EXTRACTED_AGENT_NAME"

        echo
        echo "📋 Starting OAuth flow for $display_name (browser will open)..."
        if uv run python src/ax_mcp_wait_client/prime_tokens.py; then
            echo -e "${GREEN}✅ Authentication successful for $display_name!${NC}"
        else
            echo -e "${RED}❌ Authentication failed for $display_name.${NC}"
            exit 1
        fi
    fi

    local token_files
    token_files=$(find "$token_dir" -name "*_tokens.json" 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$token_files" -eq 0 ]]; then
        echo -e "${RED}❌ No OAuth tokens found in $token_dir for $display_name${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ $display_name tokens ready (${token_files} file(s))${NC}"

    set_mcp_token_env "$config_path"
    unset MCP_SERVER_URL MCP_OAUTH_SERVER_URL MCP_AGENT_NAME
}

prepare_ollama() {
    local model="$1"
    if [[ -z "$model" ]]; then
        model="gpt-oss"
    fi

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

    if ! ollama list | awk 'NR>1 {print $1}' | cut -d: -f1 | grep -q "^${model}$"; then
        echo -e "${YELLOW}⚠️  Model $model not found. Pulling...${NC}"
        ollama pull "$model"
    fi

    echo -e "${GREEN}✅ Ollama ready with $model model${NC}"
}

get_available_agents() {
    local agents=()
    while IFS= read -r config; do
        if [[ "$config" == *"example"* ]]; then
            continue
        fi
        local agent_name
        agent_name=$(get_agent_name_from_config "$config")
        if [[ "$agent_name" != "unknown" && "$agent_name" != "null" ]]; then
            agents+=("$agent_name:$config")
        fi
    done < <(find configs -name "mcp_config*.json" | sort)
    echo "${agents[@]}"
}

select_battle_agent() {
    local player_num="$1"
    local exclude_agent="$2"

    local agents=($(get_available_agents))
    local options=()
    for entry in "${agents[@]}"; do
        local agent_name="${entry%%:*}"
        local config_path="${entry##*:}"
        if [[ "$agent_name" == "$exclude_agent" ]]; then
            continue
        fi
        local role_detail
        if [[ $player_num -eq 1 ]]; then
            role_detail="👑 Will initiate the battle"
        else
            role_detail="🛡️  Will respond to Player 1"
        fi
        options+=("${agent_name}:${config_path}::@${agent_name}::${role_detail}")
    done

    if [[ ${#options[@]} -eq 0 ]]; then
        echo -e "${RED}❌ No available agents found for selection${NC}"
        exit 1
    fi

    local selection
    selection=$(cursor_menu "${CYAN}🤖 Select Player ${player_num}:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    local agent_choice="${selection%%:*}"
    local temp="${selection#*:}"
    local config_choice="${temp%%::*}"

    echo -e "${GREEN}✅ Selected: @${agent_choice}${NC}" >&2
    printf "%s:%s\n" "$agent_choice" "$config_choice"
}

select_battle_template() {
    local options=(
        "tic_tac_toe::🎯 Tic-Tac-Toe Battle::Strategic gaming with competitive trash talk"
        "debate_absurd::🤔 Philosophical Debate::Passionate arguments about absurd topics"
        "roast_battle::🔥 Roast Battle::Tech-themed comedy showdown"
    )

    local selection
    selection=$(cursor_menu "${CYAN}⚔️  Select Battle Template:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    case "$selection" in
        tic_tac_toe)
            echo -e "${GREEN}✅ Tic-Tac-Toe Battle selected!${NC}"
            ;;
        debate_absurd)
            echo -e "${GREEN}✅ Philosophical Debate selected!${NC}"
            ;;
        roast_battle)
            echo -e "${GREEN}✅ Roast Battle selected!${NC}"
            ;;
    esac

    echo "$selection"
}

run_ai_battle_mode() {
    echo
    echo "🎮 Let's set up your AI battle!"
    echo

    local player1_result
    player1_result=$(select_battle_agent 1)
    local player1_name="${player1_result%%:*}"
    local temp1="${player1_result#*:}"
    local player1_config="${temp1%%::*}"

    echo
    local player2_result
    player2_result=$(select_battle_agent 2 "$player1_name")
    local player2_name="${player2_result%%:*}"
    local temp2="${player2_result#*:}"
    local player2_config="${temp2%%::*}"

    echo
    local battle_mode
    battle_mode=$(select_battle_template)

    echo
    echo -e "${GREEN}🎊 Battle Setup Complete!${NC}"
    echo "=================================="
    echo "   Player 1 (Initiator): @${player1_name}"
    echo "   Player 2 (Defender):   @${player2_name}"
    echo "   Battle Mode: ${battle_mode}"
    echo

    local player1_handle="@${player1_name}"
    local player2_handle="@${player2_name}"

    ensure_oauth_tokens "$player2_config" "$player2_handle"
    ensure_oauth_tokens "$player1_config" "$player1_handle"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ UV not found. Please install UV first:${NC}"
        echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    echo "🚀 Starting AI Battle..."
    echo

    echo -e "${CYAN}Starting Player 2 (@${player2_name}) in listener mode...${NC}"

    export MCP_CONFIG_PATH="$player2_config"
    set_mcp_token_env "$MCP_CONFIG_PATH"
    export PLUGIN_TYPE="ollama"
    export OLLAMA_MODEL="gpt-oss"
    export STARTUP_ACTION="listen_only"
    export MCP_BEARER_MODE=1

    case "$battle_mode" in
        "tic_tac_toe")
            export OLLAMA_SYSTEM_PROMPT_FILE="$(pwd)/prompts/tic_tac_toe_system_prompt.txt"
            ;;
        "debate_absurd")
            export OLLAMA_SYSTEM_PROMPT_FILE="$(pwd)/prompts/debate_absurd_system_prompt.txt"
            ;;
        "roast_battle")
            export OLLAMA_SYSTEM_PROMPT_FILE="$(pwd)/prompts/roast_battle_system_prompt.txt"
            ;;
    esac

    prepare_ollama "$OLLAMA_MODEL"

    echo "   Config: ${player2_config}"
    echo "   Mode: Listener"
    echo "   System Prompt: ${OLLAMA_SYSTEM_PROMPT_FILE}"
    echo

    echo "📡 Player 2 starting up..."
    uv run python simple_working_monitor.py --loop &
    local player2_pid=$!

    sleep 5

    echo
    echo -e "${CYAN}Starting Player 1 (@${player1_name}) in battle mode...${NC}"

    export MCP_CONFIG_PATH="$player1_config"
    set_mcp_token_env "$MCP_CONFIG_PATH"
    export PLUGIN_TYPE="ollama"
    export OLLAMA_MODEL="gpt-oss"
    export STARTUP_ACTION="initiate_conversation"
    export CONVERSATION_TARGET="@${player2_name}"
    export CONVERSATION_TEMPLATE="$battle_mode"
    export MCP_BEARER_MODE=1

    echo "   Config: ${player1_config}"
    echo "   Mode: Battle Initiator"
    echo "   Target: @${player2_name}"
    echo "   Template: ${battle_mode}"
    echo

    cleanup() {
        echo
        echo -e "${YELLOW}🛑 Stopping AI Battle...${NC}"
        
        # Kill quit handler background process
        if [[ -n "$quit_handler_pid" ]]; then
            kill "$quit_handler_pid" 2>/dev/null || true
        fi
        
        # Kill Player 2 background process
        if [[ -n "$player2_pid" ]]; then
            echo "   Stopping Player 2 (@${player2_name})..."
            kill "$player2_pid" 2>/dev/null || true
            wait "$player2_pid" 2>/dev/null || true
        fi
        
        # Kill any remaining monitor processes
        echo "   Cleaning up any remaining monitor processes..."
        pkill -f "simple_working_monitor.py" 2>/dev/null || true
        pkill -f "python.*simple_working_monitor" 2>/dev/null || true
        
        # Kill any orphaned uv processes
        pkill -f "uv run python simple_working_monitor" 2>/dev/null || true
        
        echo -e "${GREEN}✅ All processes stopped cleanly${NC}"
        echo "👋 Battle ended!"
        exit 0
    }

    # Function to handle quit input
    handle_quit_input() {
        while true; do
            read -rsn1 key
            if [[ "$key" == "q" || "$key" == "Q" ]]; then
                echo
                echo -e "${YELLOW}❓ Are you sure you want to quit the battle? (y/N)${NC}"
                read -rsn1 confirm
                if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
                    cleanup
                else
                    echo -e "${CYAN}💪 Battle continues! Press Q again to quit.${NC}"
                fi
            fi
        done
    }

    trap cleanup SIGINT SIGTERM

    echo "🎬 Starting the battle!"
    echo "   💡 Press Q at any time to quit (with confirmation)"
    echo "   💡 Or use Ctrl+C for immediate stop"
    echo
    echo -e "${BLUE}🔥 LET THE AI BATTLE BEGIN! 🔥${NC}"
    echo
    
    # Start quit handler in background
    handle_quit_input &
    local quit_handler_pid=$!

    uv run python simple_working_monitor.py --loop

    # Kill quit handler when main process ends
    kill "$quit_handler_pid" 2>/dev/null || true
    cleanup
}

# Function to select mode
select_mode() {
    echo "This script helps you start MCP monitors with different agents and plugins."
    echo ""

    if (( DEFAULT_MODE )); then
        echo "   👉 Auto-selecting single agent mode for default"
        echo -e "${GREEN}✅ Single Agent Mode selected${NC}"
        MODE_SELECTION="single"
        return 0
    fi

    local options=(
        "single::👤 Single Agent Mode::Set up one AI agent to listen for mentions"
        "battle::🔥 AI Battle Mode::Pit two AI agents against each other"
    )

    local choice
    choice=$(cursor_menu "${CYAN}🎮 Select Mode:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    case "$choice" in
        single)
            echo -e "${GREEN}✅ Single Agent Mode selected${NC}"
            MODE_SELECTION="single"
            ;;
        battle)
            echo -e "${GREEN}✅ AI Battle Mode selected!${NC}"
            echo
            run_ai_battle_mode
            exit 0
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            exit 1
            ;;
    esac
}

# Function to select config file
select_config() {
    echo -e "${CYAN}📋 Available Configurations:${NC}"

    local discovered_configs=()
    while IFS= read -r config; do
        discovered_configs+=("$config")
    done < <(find configs -name "mcp_config*.json" | sort)

    if [[ ${#discovered_configs[@]} -eq 0 ]]; then
        echo -e "${RED}❌ No config files found in configs/ directory${NC}"
        exit 1
    fi

    local default_config="configs/mcp_config.json"
    local options=()
    local default_index=1

    for i in "${!discovered_configs[@]}"; do
        local entry="${discovered_configs[$i]}"
        local agent_name
        agent_name=$(jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$entry" 2>/dev/null || echo "unknown")
        local detail="$entry"
        local label="@${agent_name}"
        if [[ "$entry" == "$default_config" ]]; then
            default_index=$((i + 1))
            detail+=" (default)"
        fi
        options+=("${entry}::${label}::${detail}")
    done

    options+=("NEW_AGENT::🆕 Create new agent configuration::Spin up a fresh monitor config")

    if (( DEFAULT_MODE )); then
        local auto_choice="$default_config"
        if [[ ! -f "$auto_choice" ]]; then
            auto_choice="${discovered_configs[0]}"
        fi
        export MCP_CONFIG_PATH="$auto_choice"
        set_mcp_token_env "$MCP_CONFIG_PATH"
        local auto_agent
        auto_agent=$(get_agent_name_from_config "$MCP_CONFIG_PATH")
        echo "   👉 Auto-selecting configuration for @$auto_agent"
        echo -e "${GREEN}✅ Selected config: $MCP_CONFIG_PATH${NC}"
        return
    fi

    local selection
    selection=$(cursor_menu "${CYAN}Choose Your Agent Config:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    if [[ "$selection" == "NEW_AGENT" ]]; then
        create_new_agent_config
        return
    fi

    export MCP_CONFIG_PATH="$selection"
    set_mcp_token_env "$MCP_CONFIG_PATH"
    local chosen_agent
    chosen_agent=$(get_agent_name_from_config "$MCP_CONFIG_PATH")
    echo -e "${GREEN}✅ Selected config: $MCP_CONFIG_PATH${NC}"
    echo -e "${GREEN}🤝 Agent handle: @${chosen_agent}${NC}"
}

# Function to create new agent config
create_new_agent_config() {
    echo ""
    echo -e "${CYAN}🆕 Creating New Agent Configuration${NC}"
    echo "=================================="
    
    read -p "Enter agent name (e.g., backend_dev, frontend_dev): " agent_name
    exit_if_quit "$agent_name"
    
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
    set_mcp_token_env "$MCP_CONFIG_PATH"
}

# Function to select plugin
select_plugin() {
    echo ""
    echo -e "${CYAN}🔌 Plugin Selection:${NC}"

    local default_plugin="${PLUGIN_TYPE:-ollama}"
    local default_index=2
    if [[ "$default_plugin" == "echo" ]]; then
        default_index=1
    fi

    if (( DEFAULT_MODE )); then
        export PLUGIN_TYPE="$default_plugin"
        echo "   👉 Auto-selecting ${PLUGIN_TYPE} plugin"
        if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
            echo -e "${GREEN}✅ Selected: Ollama Plugin${NC}"
            select_ollama_model
            select_system_prompt
        else
            echo -e "${GREEN}✅ Selected: Echo Plugin${NC}"
        fi
        STARTUP_ACTION="listen_only"
        return
    fi

    local options=(
        "echo::📢 Echo Plugin::Great for quick wiring checks"
        "ollama::🧠 Ollama Plugin::Bring a local LLM into the loop"
    )

    local selection
    selection=$(cursor_menu "${CYAN}Pick Your Plugin:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    case "$selection" in
        echo)
            export PLUGIN_TYPE="echo"
            echo -e "${GREEN}✅ Selected: Echo Plugin${NC}"
            STARTUP_ACTION="listen_only"
            ;;
        ollama)
            export PLUGIN_TYPE="ollama"
            echo -e "${GREEN}✅ Selected: Ollama Plugin${NC}"
            select_ollama_model
            select_system_prompt
            STARTUP_ACTION="listen_only"
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

    local available_models=()
    if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Ollama not running. Will start automatically.${NC}"
        available_models=("gpt-oss" "llama3.2" "qwen2.5")
    else
        while IFS= read -r model_name; do
            [[ -n "$model_name" ]] && available_models+=("$model_name")
        done < <(ollama list | awk 'NR>1 {print $1}' | cut -d: -f1)
    fi
    available_models+=("custom")

    local preferred_model="${OLLAMA_MODEL:-gpt-oss}"
    local options=()
    local default_index=1

    for i in "${!available_models[@]}"; do
        local model_name="${available_models[$i]}"
        local label="$model_name"
        local detail="Installed model"
        if [[ "$model_name" == "custom" ]]; then
            detail="Type a custom model name"
            if [[ "$preferred_model" == "custom" ]]; then
                default_index=$((i + 1))
            fi
        else
            if [[ "$model_name" == "$preferred_model" ]]; then
                default_index=$((i + 1))
                detail+=" (default)"
            fi
        fi
        options+=("${model_name}::${label}::${detail}")
    done

    if (( DEFAULT_MODE )); then
        local auto_model="${available_models[$((default_index - 1))]}"
        if [[ "$auto_model" == "custom" ]]; then
            auto_model="$preferred_model"
        fi
        export OLLAMA_MODEL="$auto_model"
        echo -e "${GREEN}✅ Selected: $OLLAMA_MODEL${NC}"
        return
    fi

    local selection
    selection=$(cursor_menu "${CYAN}Choose Your Ollama Model:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    if [[ "$selection" == "custom" ]]; then
        local custom_model
        read -p "Enter custom model name: " custom_model
        exit_if_quit "$custom_model"
        if [[ -z "$custom_model" ]]; then
            echo -e "${RED}❌ Custom model name cannot be empty${NC}"
            exit 1
        fi
        export OLLAMA_MODEL="$custom_model"
    else
        export OLLAMA_MODEL="$selection"
    fi

    echo -e "${GREEN}✅ Selected: $OLLAMA_MODEL${NC}"
}

select_system_prompt() {
    echo ""
    echo -e "${CYAN}🧾 System Prompt Selection:${NC}"

    local prompt_dir="prompts"
    local default_prompt="${prompt_dir}/ollama_monitor_system_prompt.txt"

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

    local options=()
    local default_index=1
    for i in "${!prompt_files[@]}"; do
        local prompt_path="${prompt_files[$i]}"
        local prompt_name
        prompt_name=$(basename "$prompt_path")
        local detail="$prompt_path"
        if [[ "$prompt_path" == "$default_prompt" ]]; then
            default_index=$((i + 1))
            detail+=" (default)"
        fi
        options+=("${prompt_path}::📄 ${prompt_name}::${detail}")
    done

    options+=("custom::🔧 Enter custom prompt path::Provide a full path to a prompt file")
    options+=("fallback::🚫 Use plugin fallback prompt::Skip custom prompt and rely on plugin defaults")

    if (( DEFAULT_MODE )); then
        local auto_prompt="${prompt_files[$((default_index - 1))]}"
        if [[ "$auto_prompt" != /* ]]; then
            auto_prompt="$(pwd)/$auto_prompt"
        fi
        export OLLAMA_SYSTEM_PROMPT_FILE="$auto_prompt"
        echo -e "${GREEN}✅ Using system prompt: $OLLAMA_SYSTEM_PROMPT_FILE${NC}"
        return
    fi

    local selection
    selection=$(cursor_menu "${CYAN}Pick a System Prompt:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    local selected_prompt=""
    case "$selection" in
        custom)
            local custom_prompt=""
            read -p "Enter full path to prompt file: " custom_prompt
            exit_if_quit "$custom_prompt"
            if [[ -z "$custom_prompt" ]]; then
                echo -e "${RED}❌ Prompt path cannot be empty${NC}"
                exit 1
            fi
            if [[ ! -f "$custom_prompt" ]]; then
                echo -e "${RED}❌ Prompt file not found: $custom_prompt${NC}"
                exit 1
            fi
            selected_prompt="$custom_prompt"
            ;;
        fallback)
            echo -e "${YELLOW}ℹ️  Using plugin fallback system prompt.${NC}"
            return
            ;;
        *)
            selected_prompt="$selection"
            ;;
    esac

    if [[ "$selected_prompt" != /* ]]; then
        selected_prompt="$(pwd)/$selected_prompt"
    fi

    export OLLAMA_SYSTEM_PROMPT_FILE="$selected_prompt"
    echo -e "${GREEN}✅ Using system prompt: $OLLAMA_SYSTEM_PROMPT_FILE${NC}"
}

# Function to select startup action
select_startup_action() {
    echo ""
    echo -e "${CYAN}🚀 Startup Action Selection:${NC}"
    
    local default_action="${STARTUP_ACTION:-listen_only}"
    local default_index=1
    if [[ "$default_action" == "initiate_conversation" ]]; then
        default_index=2
    fi

    if (( DEFAULT_MODE )); then
        export STARTUP_ACTION="$default_action"
        echo "   👉 Auto-selecting startup action: $STARTUP_ACTION"
        if [[ "$STARTUP_ACTION" == "initiate_conversation" ]]; then
            echo -e "${GREEN}✅ Selected: Initiate Conversation${NC}"
            select_conversation_target
        else
            echo -e "${GREEN}✅ Selected: Listen Only${NC}"
        fi
        return
    fi

    local options=(
        "listen_only::👂 Listen Only::Wait patiently for mentions"
        "initiate_conversation::💬 Initiate Conversation::Send a templated opener, then listen"
    )

    local selection
    selection=$(cursor_menu "${CYAN}Choose Startup Behavior:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    case "$selection" in
        listen_only)
            export STARTUP_ACTION="listen_only"
            echo -e "${GREEN}✅ Selected: Listen Only${NC}"
            ;;
        initiate_conversation)
            export STARTUP_ACTION="initiate_conversation"
            echo -e "${GREEN}✅ Selected: Initiate Conversation${NC}"
            select_conversation_target
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            exit 1
            ;;
    esac
}

# Function to select conversation target for initiate mode
select_conversation_target() {
    echo ""
    echo -e "${CYAN}🎯 Conversation Target Selection:${NC}"
    echo "   Enter the agent you want to initiate a conversation with:"
    echo ""
    
    read -p "Target agent (e.g., @backend_dev, @frontend_dev): " target_agent
    exit_if_quit "$target_agent"
    
    if [[ -z "$target_agent" ]]; then
        echo -e "${RED}❌ Target agent cannot be empty${NC}"
        exit 1
    fi
    
    # Ensure it starts with @
    if [[ ! "$target_agent" =~ ^@ ]]; then
        target_agent="@$target_agent"
    fi
    
    export CONVERSATION_TARGET="$target_agent"
    echo -e "${GREEN}✅ Will initiate conversation with: $CONVERSATION_TARGET${NC}"
    
    # Now select conversation template
    select_conversation_template
}

# Function to select conversation template
select_conversation_template() {
    echo ""
    echo -e "${CYAN}📝 Conversation Template Selection:${NC}"
    
    local templates_file="configs/conversation_templates.json"
    
    if [[ ! -f "$templates_file" ]]; then
        echo -e "${YELLOW}⚠️  Templates file not found. Using basic startup message.${NC}"
        export CONVERSATION_TEMPLATE="basic"
        return
    fi
    
    # Read template options
    local template_keys=($(jq -r '.templates | keys[]' "$templates_file"))
    
    if [[ ${#template_keys[@]} -eq 0 ]]; then
        echo -e "${YELLOW}⚠️  No conversation templates defined. Using basic startup message.${NC}"
        export CONVERSATION_TEMPLATE="basic"
        return
    fi
    
    local default_template="${CONVERSATION_TEMPLATE:-tic_tac_toe}"
    local options=()
    local default_index=1
    
    for i in "${!template_keys[@]}"; do
        local key="${template_keys[$i]}"
        local name=$(jq -r ".templates.\"$key\".name" "$templates_file")
        local description=$(jq -r ".templates.\"$key\".description" "$templates_file")
        local icon="📋"
        case $key in
            "tic_tac_toe") icon="🎯" ;;
            "debate_absurd") icon="🤔" ;;
            "roast_battle") icon="🔥" ;;
            "custom") icon="✏️" ;;
        esac
        local detail="$description"
        if [[ "$key" == "$default_template" ]]; then
            default_index=$((i + 1))
            detail+=" (default)"
        fi
        options+=("${key}::${icon} ${name}::${detail}")
    done
    
    local selection_key=""
    if (( DEFAULT_MODE )); then
        selection_key="${template_keys[$((default_index - 1))]}"
        echo "   👉 Auto-selecting template: $selection_key"
    else
        local selection
        selection=$(cursor_menu "${CYAN}Pick a Conversation Template:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye
        selection_key="$selection"
    fi
    
    export CONVERSATION_TEMPLATE="$selection_key"
    local selected_name=$(jq -r ".templates.\"$selection_key\".name" "$templates_file")
    echo -e "${GREEN}✅ Selected: $selected_name${NC}"
    
    # Handle custom message input
    if [[ "$selection_key" == "custom" ]]; then
        echo ""
        echo -e "${CYAN}✏️  Custom Message Input:${NC}"
        echo "   Enter your custom startup message:"
        echo ""
        local custom_message=""
        read -p "Message: " custom_message
        exit_if_quit "$custom_message"
        
        if [[ -z "$custom_message" ]]; then
            echo -e "${RED}❌ Custom message cannot be empty${NC}"
            exit 1
        fi
        
        export CUSTOM_STARTUP_MESSAGE="$custom_message"
        echo -e "${GREEN}✅ Custom message set${NC}"
    else
        unset CUSTOM_STARTUP_MESSAGE
    fi
}

# Main execution
echo "This script helps you start MCP monitors with different agents and plugins."
echo ""

# Step 1: Select mode (will handle battle mode automatically)
select_mode

# Step 2: Select configuration
select_config

# Step 2: Select plugin
select_plugin

# Extract agent name from config
AGENT_NAME=$(get_agent_name_from_config "$MCP_CONFIG_PATH")

# Step 3: Set up environment
export MCP_BEARER_MODE=1

ensure_oauth_tokens "$MCP_CONFIG_PATH" "$AGENT_NAME"
set_mcp_token_env "$MCP_CONFIG_PATH"

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
if [[ "$STARTUP_ACTION" == "initiate_conversation" ]]; then
    echo "   Startup action: Initiate conversation with $CONVERSATION_TARGET"
    if [[ -n "$CONVERSATION_TEMPLATE" && "$CONVERSATION_TEMPLATE" != "basic" ]]; then
        template_name=$(jq -r ".templates.\"$CONVERSATION_TEMPLATE\".name" "configs/conversation_templates.json" 2>/dev/null || echo "$CONVERSATION_TEMPLATE")
        echo "   Template: $template_name"
    fi
else
    echo "   Startup action: Listen only"
fi
echo ""

# ensure_oauth_tokens already verified config and tokens

# Setup Ollama if needed
if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
    prepare_ollama "$OLLAMA_MODEL"
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