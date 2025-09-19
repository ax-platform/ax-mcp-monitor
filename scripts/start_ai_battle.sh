#!/bin/bash
#
# AI Battle Mode - Simplified 2-Player AI Conversation Setup
# 
# This script makes it super easy to start entertaining AI-vs-AI battles
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Clear screen for better UX
clear

echo -e "${BLUE}🔥 AI BATTLE MODE 🔥${NC}"
echo -e "${BLUE}===================${NC}"
echo ""
echo "🎪 Welcome to AI Battle Mode - Where AIs duke it out with personality!"
echo ""
echo "How it works:"
echo "• Choose 2 AI agents (Player 1 and Player 2)"
echo "• Pick a battle mode (Tic-Tac-Toe, Debate, Roast Battle)"
echo "• Watch them battle it out in real-time!"
echo "• Player 1 always starts the conversation"
echo ""

# Function to get available agents
get_available_agents() {
    local agents=()
    local configs=($(find configs -name "mcp_config*.json" | sort))
    
    for config in "${configs[@]}"; do
        if [[ "$config" == *"example"* ]]; then
            continue  # Skip example configs
        fi
        local agent_name=$(jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$config" 2>/dev/null || echo "unknown")
        if [[ "$agent_name" != "unknown" && "$agent_name" != "null" ]]; then
            agents+=("$agent_name:$config")
        fi
    done
    
    echo "${agents[@]}"
}

# Function to select an agent with cursor navigation
select_agent_with_cursor() {
    local player_num=$1
    local exclude_agent=$2
    
    echo -e "${CYAN}🤖 Select Player $player_num:${NC}"
    echo -e "${YELLOW}Use ↑/↓ arrow keys (or j/k) to navigate, Enter to select${NC}"
    
    local agents=($(get_available_agents))
    local available_agents=()
    local agent_names=()
    local config_paths=()
    
    # Filter out excluded agent and build arrays
    for agent_config in "${agents[@]}"; do
        local agent_name="${agent_config%%:*}"
        local config_path="${agent_config##*:}"
        if [[ "$agent_name" != "$exclude_agent" ]]; then
            available_agents+=("$agent_config")
            agent_names+=("$agent_name")
            config_paths+=("$config_path")
        fi
    done
    
    if [[ ${#available_agents[@]} -eq 0 ]]; then
        echo -e "${RED}❌ No available agents found!${NC}"
        exit 1
    fi
    
    local selected_index=0
    local total_options=${#agent_names[@]}
    
    # Function to display the menu
    display_menu() {
        # Clear previous menu (move cursor up and clear lines)
        if [[ $1 == "update" ]]; then
            printf "\033[%dA" $((total_options + 2))
        fi
        
        echo ""
        for i in "${!agent_names[@]}"; do
            if [[ $i -eq $selected_index ]]; then
                echo -e "   ${GREEN}▶ @${agent_names[$i]}${NC}"
                if [[ $player_num -eq 1 ]]; then
                    echo -e "     ${GREEN}👑 (Will initiate the battle)${NC}"
                else
                    echo -e "     ${GREEN}🛡️  (Will respond to Player 1)${NC}"
                fi
            else
                echo -e "     @${agent_names[$i]}"
                if [[ $player_num -eq 1 ]]; then
                    echo "     👑 (Will initiate the battle)"
                else
                    echo "     🛡️  (Will respond to Player 1)"
                fi
            fi
        done
        echo ""
    }
    
    # Initial display
    display_menu "initial"
    
    # Read user input
    while true; do
        read -rsn1 key
        case "$key" in
            $'\x1b')  # ESC sequence
                read -rsn2 key
                case "$key" in
                    '[A'|'[k')  # Up arrow or k
                        ((selected_index--))
                        if [[ $selected_index -lt 0 ]]; then
                            selected_index=$((total_options - 1))
                        fi
                        display_menu "update"
                        ;;
                    '[B'|'[j')  # Down arrow or j
                        ((selected_index++))
                        if [[ $selected_index -ge $total_options ]]; then
                            selected_index=0
                        fi
                        display_menu "update"
                        ;;
                esac
                ;;
            'k'|'K')  # k key for up
                ((selected_index--))
                if [[ $selected_index -lt 0 ]]; then
                    selected_index=$((total_options - 1))
                fi
                display_menu "update"
                ;;
            'j'|'J')  # j key for down
                ((selected_index++))
                if [[ $selected_index -ge $total_options ]]; then
                    selected_index=0
                fi
                display_menu "update"
                ;;
            '')  # Enter key
                break
                ;;
            'q'|'Q')  # Quit
                echo ""
                echo -e "${YELLOW}👋 Exiting AI Battle Mode...${NC}"
                exit 0
                ;;
        esac
    done
    
    local selected_agent="${agent_names[$selected_index]}"
    local selected_config="${config_paths[$selected_index]}"
    
    echo -e "${GREEN}✅ Selected: @$selected_agent${NC}"
    echo "$selected_agent:$selected_config"
}

# Function to select battle mode
select_battle_mode() {
    echo ""
    echo -e "${CYAN}⚔️  Select Battle Mode:${NC}"
    echo ""
    echo "   1) 🎯 Tic-Tac-Toe Battle"
    echo "      Strategic gaming with competitive trash talk!"
    echo ""
    echo "   2) 🤔 Philosophical Debate"
    echo "      Passionate arguments about absurd topics!"
    echo ""
    echo "   3) 🔥 Roast Battle"
    echo "      Tech-themed comedy showdown!"
    echo ""
    
    local choice
    read -p "Select battle mode (1-3): " choice
    
    case $choice in
        1)
            echo -e "${GREEN}✅ Tic-Tac-Toe Battle selected!${NC}"
            echo "tic_tac_toe"
            ;;
        2)
            echo -e "${GREEN}✅ Philosophical Debate selected!${NC}"
            echo "debate_absurd"
            ;;
        3)
            echo -e "${GREEN}✅ Roast Battle selected!${NC}"
            echo "roast_battle"
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            exit 1
            ;;
    esac
}

# Main execution
echo "🎮 Let's set up your AI battle!"
echo ""

# Select Player 1 (initiator)
player1_result=$(select_agent 1)
player1_name="${player1_result%%:*}"
player1_config="${player1_result##*:}"

echo ""

# Select Player 2
player2_result=$(select_agent 2 "$player1_name")
player2_name="${player2_result%%:*}"
player2_config="${player2_result##*:}"

echo ""

# Select battle mode
battle_mode=$(select_battle_mode)

echo ""
echo -e "${GREEN}🎊 Battle Setup Complete!${NC}"
echo "=================================="
echo "   Player 1 (Initiator): @$player1_name"
echo "   Player 2 (Defender):   @$player2_name"
echo "   Battle Mode: $battle_mode"
echo ""

# Check UV installation
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ UV not found. Please install UV first:${NC}"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "🚀 Starting AI Battle..."
echo ""

# Start Player 2 (listener) first
echo -e "${CYAN}Starting Player 2 (@$player2_name) in listener mode...${NC}"

# Set up Player 2 environment
export MCP_CONFIG_PATH="$player2_config"
export PLUGIN_TYPE="ollama"
export OLLAMA_MODEL="gpt-oss"
export STARTUP_ACTION="listen_only"
export MCP_BEARER_MODE=1

# Determine system prompt for battle mode
case $battle_mode in
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

echo "   Config: $player2_config"
echo "   Mode: Listener"
echo "   System Prompt: $OLLAMA_SYSTEM_PROMPT_FILE"
echo ""

# Start Player 2 in background
echo "📡 Player 2 starting up..."
uv run python simple_working_monitor.py --loop &
PLAYER2_PID=$!

# Wait a moment for Player 2 to start
sleep 5

echo ""
echo -e "${CYAN}Starting Player 1 (@$player1_name) in battle mode...${NC}"

# Set up Player 1 environment
export MCP_CONFIG_PATH="$player1_config"
export PLUGIN_TYPE="ollama"
export OLLAMA_MODEL="gpt-oss"
export STARTUP_ACTION="initiate_conversation"
export CONVERSATION_TARGET="@$player2_name"
export CONVERSATION_TEMPLATE="$battle_mode"
export MCP_BEARER_MODE=1

echo "   Config: $player1_config"
echo "   Mode: Battle Initiator"
echo "   Target: @$player2_name"
echo "   Template: $battle_mode"
echo ""

# Clean up function
cleanup() {
    echo ""
    echo -e "${YELLOW}🛑 Stopping AI Battle...${NC}"
    if [[ -n "$PLAYER2_PID" ]]; then
        kill $PLAYER2_PID 2>/dev/null || true
    fi
    echo "👋 Battle ended!"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

echo "🎬 Starting the battle! Press Ctrl+C to stop both players."
echo ""
echo -e "${BLUE}🔥 LET THE AI BATTLE BEGIN! 🔥${NC}"
echo ""

# Start Player 1 (this will block)
uv run python simple_working_monitor.py --loop

# If we get here, Player 1 exited
cleanup