#!/bin/bash
#
# Universal MCP Monitor Startup Script
# 
# This script provides a user-friendly interface for starting MCP monitors
# with support for multiple agents, plugins, and models.
#

set -e

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DEFAULT_MODE=0
FORWARD_ARGS=()
MODE_SELECTION=""
SINGLE_AGENT_BEHAVIOR="langgraph"
CONVERSATION_MODE=0
DEFAULT_BASE_PROMPT_PATH="$(pwd)/prompts/ax_base_system_prompt.txt"
BASE_SYSTEM_PROMPT_PATH="$DEFAULT_BASE_PROMPT_PATH"
ADDITIONAL_PROMPT_PATHS=()
CONVERSATION_SYSTEM_PROMPT_PATH=""
LAST_SYSTEM_PROMPT_SOURCE=""
LAST_SYSTEM_PROMPT_TEXT=""
LANGGRAPH_BACKEND=""

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

# Emoji selections for agent flair
AGENT_EMOJI_CHOICES=("🚀" "🌟" "⚡" "🛡️" "🧠" "🔥" "🪐" "🎮" "🦾" "🧬" "🛰️" "🪄" "🌈" "🎯")
SESSION_ADJECTIVES=("quantum" "luminous" "stellar" "ember" "cobalt" "aurora" "zenith" "crystal" "lunar" "solar" "nebula" "nova")
SESSION_NOUNS=("voyage" "vector" "signal" "mosaic" "flux" "horizon" "atlas" "glyph" "pulse" "circuit" "forge" "bloom")

generate_session_codename() {
    local adj=${SESSION_ADJECTIVES[$RANDOM % ${#SESSION_ADJECTIVES[@]}]}
    local noun=${SESSION_NOUNS[$RANDOM % ${#SESSION_NOUNS[@]}]}
    printf "#%s-%s" "$adj" "$noun"
}

lowercase() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

strings_equal_ci() {
    local left
    local right
    left=$(lowercase "$1")
    right=$(lowercase "$2")
    [[ "$left" == "$right" ]]
}

generate_tag_suggestion() {
    local suggestion
    suggestion=$(generate_session_codename)
    printf "%s" "$suggestion"
}

sanitize_tag_token() {
    local raw="${1:-}"
    # Trim whitespace
    raw="${raw#${raw%%[![:space:]]*}}"
    raw="${raw%${raw##*[![:space:]]}}"
    raw="${raw//#/}"
    if [[ -z "$raw" ]]; then
        return
    fi
    raw=$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')
    raw=${raw// /-}
    raw=${raw//[^a-z0-9_-]/-}
    while [[ "$raw" == *--* ]]; do
        raw=${raw//--/-}
    done
    raw="${raw#-}"
    raw="${raw%-}"
    if [[ -n "$raw" ]]; then
        printf "#%s" "$raw"
    fi
}

configure_session_tags() {
    unset SESSION_TAG_PRIMARY SESSION_TAGS SESSION_TAG_DISPLAY

    local suggested_tag
    suggested_tag=$(generate_tag_suggestion)

    echo ""
    echo -e "${CYAN}🏷️  Session Tag Setup:${NC}"
    echo "   Tags are optional, but they make filtering in aX easier."
    local tag_prompt="   Session tags (optional - press Enter to skip"
    if [[ -n "$suggested_tag" ]]; then
        tag_prompt+="; '.' to accept ${suggested_tag}"
    fi
    tag_prompt+="; custom tags separated by ';'): "

    local tag_input_raw
    read -p "$tag_prompt" tag_input_raw
    exit_if_quit "$tag_input_raw"

    if [[ -z "$tag_input_raw" ]]; then
        echo -e "${YELLOW}ℹ️  Skipping session tags for this run.${NC}"
        return
    fi

    local normalized_input="$tag_input_raw"
    if [[ "$tag_input_raw" == "." ]]; then
        normalized_input="$suggested_tag"
        echo "   Using suggested tag: ${suggested_tag}"
    fi

    normalized_input=${normalized_input//,/;}
    IFS=';' read -ra tag_tokens <<< "$normalized_input"

    local -a tags=()
    for token in "${tag_tokens[@]}"; do
        local trimmed_tag
        trimmed_tag=$(sanitize_tag_token "$token")
        if [[ -z "$trimmed_tag" ]]; then
            continue
        fi

        local duplicate=0
        for existing in "${tags[@]}"; do
            if strings_equal_ci "$existing" "$trimmed_tag"; then
                duplicate=1
                break
            fi
        done

        if (( ! duplicate )); then
            tags+=("$trimmed_tag")
        fi
    done

    if (( ${#tags[@]} == 0 )); then
        if [[ -n "$suggested_tag" ]]; then
            local sanitized_suggestion
            sanitized_suggestion=$(sanitize_tag_token "$suggested_tag")
            if [[ -n "$sanitized_suggestion" ]]; then
                tags+=("$sanitized_suggestion")
                echo "   No valid tags parsed, falling back to suggested tag."
            fi
        fi

        if (( ${#tags[@]} == 0 )); then
            echo -e "${YELLOW}ℹ️  No valid tags entered; skipping session tags.${NC}"
            return
        fi
    fi

    local joined_csv
    local joined_display
    joined_csv=$(IFS=','; echo "${tags[*]}")
    joined_display=$(IFS=' '; echo "${tags[*]}")

    export SESSION_TAG_PRIMARY="${tags[0]}"
    export SESSION_TAGS="$joined_csv"
    export SESSION_TAG_DISPLAY="$joined_display"

    echo -e "${GREEN}✅ Session tags ready:${NC} $SESSION_TAG_DISPLAY"
}

post_session_announcement() {
    local announcement_message="${1:-}"

    if [[ -z "$announcement_message" ]]; then
        return
    fi

    if [[ -z "$MCP_CONFIG_PATH" || ! -f "$MCP_CONFIG_PATH" ]]; then
        echo -e "${YELLOW}ℹ️  Skipping aX announcement (no MCP config path available).${NC}"
        return
    fi

    export SESSION_ANNOUNCEMENT="$announcement_message"

    if uv run python - <<'PY'
    then
import asyncio
import os
from ax_mcp_wait_client.config_loader import parse_mcp_config
from ax_mcp_wait_client.mcp_client import MCPClient

async def main() -> None:
    message = os.environ.get("SESSION_ANNOUNCEMENT")
    config_path = os.environ.get("MCP_CONFIG_PATH")
    if not message or not config_path:
        raise SystemExit(1)

    cfg = parse_mcp_config(config_path)
    client = MCPClient(
        server_url=cfg.server_url,
        oauth_server=cfg.oauth_url,
        agent_name=cfg.agent_name,
        token_dir=cfg.token_dir,
    )
    await client.connect()
    try:
        ok = await client.send_message(message)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    if not ok:
        raise SystemExit(1)

asyncio.run(main())
PY
    then
        echo -e "${GREEN}✅ Announcement posted to aX with session tags.${NC}"
    else
        echo -e "${YELLOW}⚠️  Failed to post the session announcement to aX.${NC}"
    fi

    unset SESSION_ANNOUNCEMENT
}

get_agent_emoji() {
    local name="${1:-}"
    local total=${#AGENT_EMOJI_CHOICES[@]}
    if (( total == 0 )); then
        echo "🤖"
        return
    fi
    local seed="${name#@}"
    if [[ -z "$seed" || "$seed" == "unknown" || "$seed" == "null" ]]; then
        echo "${AGENT_EMOJI_CHOICES[0]}"
        return
    fi
    local checksum
    checksum=$(printf "%s" "$seed" | LC_ALL=C cksum | awk '{print $1}')
    if [[ -z "$checksum" ]]; then
        echo "${AGENT_EMOJI_CHOICES[0]}"
        return
    fi
    local index=$(( checksum % total ))
    echo "${AGENT_EMOJI_CHOICES[$index]}"
}

format_agent_label() {
    local raw_name="${1:-}"
    local fallback="${2:-}"
    local clean="${raw_name#@}"
    if [[ -z "$clean" || "$clean" == "unknown" || "$clean" == "null" ]]; then
        clean="${fallback#@}"
    fi
    local emoji
    emoji=$(get_agent_emoji "$clean")
    if [[ -n "$clean" && "$clean" != "unknown" && "$clean" != "null" ]]; then
        echo "${emoji} @${clean}"
    elif [[ -n "$fallback" ]]; then
        echo "${emoji} ${fallback}"
    else
        echo "${emoji} @agent"
    fi
}

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

    local display_emoji
    display_emoji=$(get_agent_emoji "${display_name#@}")

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
        echo -e "${YELLOW}🔐 First run detected for ${display_emoji} $display_name - OAuth setup required${NC}"
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
            echo -e "${GREEN}✅ Authentication successful for ${display_emoji} $display_name!${NC}"
        else
            echo -e "${RED}❌ Authentication failed for ${display_emoji} $display_name.${NC}"
            exit 1
        fi
    fi

    local token_files
    token_files=$(find "$token_dir" -name "*_tokens.json" 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$token_files" -eq 0 ]]; then
        echo -e "${RED}❌ No OAuth tokens found in $token_dir for $display_name${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ ${display_emoji} $display_name tokens ready (${token_files} file(s))${NC}"

    set_mcp_token_env "$config_path"
    unset MCP_SERVER_URL MCP_OAUTH_SERVER_URL MCP_AGENT_NAME
}

is_ollama_running() {
    curl -s http://localhost:11434/api/tags >/dev/null 2>&1
}

prepare_ollama() {
    local model="$1"

    if ! is_ollama_running; then
        echo -e "${YELLOW}⚠️  Ollama service not detected.${NC}"
        echo "   Start Ollama in another terminal (e.g., 'ollama serve') and then reload the model list."
        return 1
    fi

    if [[ -n "$model" ]] && ! ollama list | awk 'NR>1 {print $1}' | cut -d: -f1 | grep -qx "$model"; then
        echo -e "${YELLOW}⚠️  Model '$model' is not installed.${NC}"
        echo "   Install it with 'ollama pull $model' and try again."
        return 1
    fi

    if [[ -n "$model" ]]; then
        echo -e "${GREEN}✅ Ollama ready with $model${NC}"
    else
        echo -e "${GREEN}✅ Ollama service detected${NC}"
    fi
    return 0
}

read_prompt_file() {
    local file_path="$1"
    if [[ -z "$file_path" ]]; then
        return 1
    fi
    if [[ ! -f "$file_path" ]]; then
        return 1
    fi
    cat "$file_path"
}

compose_system_prompt() {
    local base_path="$1"
    local scenario_content="$2"
    local scenario_path="$3"
    local scenario_text="$scenario_content"
    local combined=""

    if [[ -n "$base_path" && -f "$base_path" ]]; then
        local base_content
        base_content=$(read_prompt_file "$base_path")
        if [[ -n "$base_content" ]]; then
            combined="$base_content"
        fi
    fi

    for extra_path in "${ADDITIONAL_PROMPT_PATHS[@]}"; do
        if [[ -n "$extra_path" && -f "$extra_path" ]]; then
            local extra_content
            extra_content=$(read_prompt_file "$extra_path")
            if [[ -n "$extra_content" ]]; then
                if [[ -n "$combined" ]]; then
                    combined+=$'\n\n---\n\n'
                fi
                combined+="$extra_content"
            fi
        fi
    done

    if [[ -z "$scenario_text" && -n "$scenario_path" && -f "$scenario_path" ]]; then
        scenario_text=$(read_prompt_file "$scenario_path")
    fi

    if [[ -n "$scenario_text" ]]; then
        if [[ -n "$combined" ]]; then
            combined+=$'\n\n---\n\n'
        fi
        combined+="$scenario_text"
    fi

    printf "%s" "$combined"
}

apply_system_prompt_env() {
    local scenario_path="$1"
    local inline_scenario="$2"
    local combined
    local sources=()

    unset OLLAMA_SYSTEM_PROMPT
    unset OLLAMA_SYSTEM_PROMPT_FILE
    unset LANGGRAPH_SYSTEM_PROMPT
    unset LANGGRAPH_SYSTEM_PROMPT_FILE
    unset OPENROUTER_SYSTEM_PROMPT
    unset OPENROUTER_SYSTEM_PROMPT_FILE

    combined=$(compose_system_prompt "$BASE_SYSTEM_PROMPT_PATH" "$inline_scenario" "$scenario_path")

    if [[ -n "$SESSION_TAG_DISPLAY" ]]; then
        local tag_guidelines
        tag_guidelines=$'Session Tag Protocol:\n- Append these session tags to every message you send: '"$SESSION_TAG_DISPLAY"$'\n- Preserve these tags even when adding other hashtags or closing the exchange.'
        if [[ -n "$combined" ]]; then
            combined="$combined"$'\n\n---\n\n'$tag_guidelines
        else
            combined="$tag_guidelines"
        fi
    fi

    LAST_SYSTEM_PROMPT_SOURCE=""
    LAST_SYSTEM_PROMPT_TEXT=""

    if [[ -n "$BASE_SYSTEM_PROMPT_PATH" && -f "$BASE_SYSTEM_PROMPT_PATH" ]]; then
        sources+=("$BASE_SYSTEM_PROMPT_PATH")
    fi
    for extra_path in "${ADDITIONAL_PROMPT_PATHS[@]}"; do
        if [[ -n "$extra_path" && -f "$extra_path" ]]; then
            sources+=("$extra_path")
        fi
    done
    if [[ -n "$inline_scenario" ]]; then
        if [[ -n "$scenario_path" && -f "$scenario_path" ]]; then
            sources+=("$scenario_path (inline)")
        else
            sources+=("scenario instructions (inline)")
        fi
    elif [[ -n "$scenario_path" && -f "$scenario_path" ]]; then
        sources+=("$scenario_path")
    fi

    if [[ ${#sources[@]} -gt 0 ]]; then
        LAST_SYSTEM_PROMPT_SOURCE=$(IFS=' + ' ; echo "${sources[*]}")
    fi

    if [[ -n "$combined" ]]; then
        printf -v OLLAMA_SYSTEM_PROMPT "%s" "$combined"
        export OLLAMA_SYSTEM_PROMPT
        printf -v OPENROUTER_SYSTEM_PROMPT "%s" "$combined"
        export OPENROUTER_SYSTEM_PROMPT
        printf -v LANGGRAPH_SYSTEM_PROMPT "%s" "$combined"
        export LANGGRAPH_SYSTEM_PROMPT
        LAST_SYSTEM_PROMPT_TEXT="$combined"
    elif [[ -n "$BASE_SYSTEM_PROMPT_PATH" && -f "$BASE_SYSTEM_PROMPT_PATH" ]]; then
        export OLLAMA_SYSTEM_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export OPENROUTER_SYSTEM_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export LANGGRAPH_SYSTEM_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        LAST_SYSTEM_PROMPT_TEXT=$(read_prompt_file "$BASE_SYSTEM_PROMPT_PATH")
    elif [[ -n "$scenario_path" && -f "$scenario_path" ]]; then
        export OLLAMA_SYSTEM_PROMPT_FILE="$scenario_path"
        export OPENROUTER_SYSTEM_PROMPT_FILE="$scenario_path"
        export LANGGRAPH_SYSTEM_PROMPT_FILE="$scenario_path"
        LAST_SYSTEM_PROMPT_TEXT=$(read_prompt_file "$scenario_path")
    fi
}

print_system_prompt_details() {
    local indent="${1:-}"
    local label="${2:-}"
    local text="${3:-}"
    local body_indent="${indent}    "

    if [[ -n "$label" ]]; then
        echo "${indent}System prompt: ${label}"
    else
        echo "${indent}System prompt: (plugin fallback)"
    fi

    if [[ -n "$text" ]]; then
        echo "${indent}---"
        while IFS= read -r line; do
            echo "${body_indent}${line}"
        done <<< "${text%$'\r'}"
        echo "${indent}---"
    fi
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
        local clean_name="${agent_name#@}"
        local agent_icon
        agent_icon=$(get_agent_emoji "$clean_name")
        local handle="@${clean_name}"
        local role_detail
        if [[ $player_num -eq 1 ]]; then
            role_detail="${agent_icon} Will initiate the battle"
        else
            role_detail="${agent_icon} Will respond to Player 1"
        fi
        local label="${agent_icon} ${handle}"
        options+=("${agent_name}:${config_path}::${label}::${role_detail}")
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
    local templates_file="configs/conversation_templates.json"
    
    if [[ ! -f "$templates_file" ]]; then
        echo -e "${RED}❌ Templates file not found: $templates_file${NC}" >&2
        exit 1
    fi
    
    # Get all template keys except 'custom'
    local template_keys=($(jq -r '.templates | to_entries[] | select(.key != "custom") | .key' "$templates_file"))
    
    if [[ ${#template_keys[@]} -eq 0 ]]; then
        echo -e "${RED}❌ No battle templates found in $templates_file${NC}" >&2
        exit 1
    fi
    
    # Build options array dynamically
    local options=()
    for key in "${template_keys[@]}"; do
        local name=$(jq -r ".templates."$key".name" "$templates_file")
        local description=$(jq -r ".templates."$key".description" "$templates_file")
        
        # Add emoji based on template name for visual appeal
        local icon="⚔️"
        case $key in
            "tic_tac_toe") icon="🎯" ;;
            "debate_absurd") icon="🤔" ;;
            "roast_battle") icon="🔥" ;;
            "future_of_work") icon="🤖" ;;
            *) icon="💬" ;;
        esac
        
        options+=("${key}::${icon} ${name}::${description}")
    done

    local selection
    selection=$(cursor_menu "${CYAN}⚔️  Select Battle Template:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    # Get the selected template name for display
    local selected_name=$(jq -r ".templates."$selection".name" "$templates_file")
    echo -e "${GREEN}✅ ${selected_name} selected!${NC}" >&2

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

    local player1_emoji=$(get_agent_emoji "$player1_name")
    local player2_emoji=$(get_agent_emoji "$player2_name")

    echo
    local battle_mode
    battle_mode=$(select_battle_template)

    echo
    if ! select_ollama_model PLAYER1_MODEL "${CYAN}Choose Model for @${player1_name}:${NC}" "${CYAN}🤖 Player 1 Model Options:${NC}"; then
        echo -e "${YELLOW}↩️  Returning to main menu at your request.${NC}"
        return 1
    fi
    local player1_model="${PLAYER1_MODEL}"

    echo
    if ! select_ollama_model PLAYER2_MODEL "${CYAN}Choose Model for @${player2_name}:${NC}" "${CYAN}🤖 Player 2 Model Options:${NC}"; then
        echo -e "${YELLOW}↩️  Returning to main menu at your request.${NC}"
        return 1
    fi
    local player2_model="${PLAYER2_MODEL}"

    configure_session_tags

    echo
    echo -e "${GREEN}🎊 Battle Setup Complete!${NC}"
    echo "=================================="
    echo "   Player 1 (Initiator): ${player1_emoji} @${player1_name}"
    echo "   Player 1 Model: ${player1_model}"
    echo "   Player 2 (Defender):   ${player2_emoji} @${player2_name}"
    echo "   Player 2 Model: ${player2_model}"
    echo "   Battle Mode: ${battle_mode}"
    if [[ -n "$SESSION_TAG_DISPLAY" ]]; then
        echo "   Session tags: $SESSION_TAG_DISPLAY"
    fi
    echo

    local player1_handle="@${player1_name}"
    local player2_handle="@${player2_name}"
    local battle_stop_requested=0
    local battle_cleanup_ran=0

    ensure_oauth_tokens "$player2_config" "$player2_handle"
    ensure_oauth_tokens "$player1_config" "$player1_handle"

    export AGENT_EMOJI="$player2_emoji"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ UV not found. Please install UV first:${NC}"
        echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
        return 1
    fi

    echo "🚀 Starting AI Battle..."
    echo

    echo -e "${CYAN}Starting Player 2 (@${player2_name}) in listener mode...${NC}"

    export MCP_CONFIG_PATH="$player2_config"
    set_mcp_token_env "$MCP_CONFIG_PATH"
    export PLUGIN_TYPE="ollama"
    export OLLAMA_MODEL="$player2_model"
    export STARTUP_ACTION="listen_only"
    export MCP_BEARER_MODE=1

    # Set system prompt dynamically from templates file
    local templates_file="configs/conversation_templates.json"
    local prompt_file=$(jq -r ".templates.\"$battle_mode\".system_prompt_file" "$templates_file" 2>/dev/null)
    local prompt_path=""
    local inline_prompt=""

    unset OLLAMA_SYSTEM_PROMPT
    unset OLLAMA_SYSTEM_PROMPT_FILE

    if [[ -n "$prompt_file" && "$prompt_file" != "null" ]]; then
        prompt_path="$(pwd)/$prompt_file"
        if [[ -f "$prompt_path" ]]; then
            inline_prompt=$(<"$prompt_path")
            inline_prompt="${inline_prompt//\{initiator_handle\}/@$player1_name}"
            inline_prompt="${inline_prompt//\{initiator_name\}/$player1_name}"
            inline_prompt="${inline_prompt//\{responder_handle\}/@$player2_name}"
            inline_prompt="${inline_prompt//\{responder_name\}/$player2_name}"
            inline_prompt="${inline_prompt//\{player1_handle\}/@$player1_name}"
            inline_prompt="${inline_prompt//\{player1_name\}/$player1_name}"
            inline_prompt="${inline_prompt//\{player2_handle\}/@$player2_name}"
            inline_prompt="${inline_prompt//\{player2_name\}/$player2_name}"
        else
            echo -e "${YELLOW}⚠️  System prompt file $prompt_path not found; falling back to defaults${NC}" >&2
            prompt_path=""
        fi
    fi

    apply_system_prompt_env "$prompt_path" "$inline_prompt"
    local player2_prompt_label="$LAST_SYSTEM_PROMPT_SOURCE"
    local player2_prompt_text="$LAST_SYSTEM_PROMPT_TEXT"

    if [[ -n "$BASE_SYSTEM_PROMPT_PATH" && -f "$BASE_SYSTEM_PROMPT_PATH" ]]; then
        export OLLAMA_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export OPENROUTER_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export LANGGRAPH_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
    else
        unset OLLAMA_BASE_PROMPT_FILE
        unset OPENROUTER_BASE_PROMPT_FILE
        unset LANGGRAPH_BASE_PROMPT_FILE
    fi

    if ! prepare_ollama "$OLLAMA_MODEL"; then
        echo -e "${YELLOW}↩️  Returning to main menu so you can start Ollama or install the requested model.${NC}"
        return 1
    fi

    echo "   Config: ${player2_config}"
    echo "   Mode: Listener"
    echo "   Model: ${player2_model}"
    print_system_prompt_details "   " "$player2_prompt_label" "$player2_prompt_text"
    echo

    echo "📡 Player 2 starting up..."
    uv run reliable_monitor.py --loop &
    local player2_pid=$!

    sleep 5

    echo
    echo -e "${CYAN}Starting Player 1 (@${player1_name}) in battle mode...${NC}"

    export AGENT_EMOJI="$player1_emoji"
    export MCP_CONFIG_PATH="$player1_config"
    set_mcp_token_env "$MCP_CONFIG_PATH"
    export PLUGIN_TYPE="ollama"
    export OLLAMA_MODEL="$player1_model"
    export STARTUP_ACTION="listen_only"
    export CONVERSATION_TARGET="@${player2_name}"
    export CONVERSATION_TEMPLATE="$battle_mode"
    export MCP_BEARER_MODE=1

    apply_system_prompt_env "$prompt_path" "$inline_prompt"
    local player1_prompt_label="$LAST_SYSTEM_PROMPT_SOURCE"
    local player1_prompt_text="$LAST_SYSTEM_PROMPT_TEXT"

    echo "   Config: ${player1_config}"
    echo "   Mode: Battle Initiator"
    echo "   Model: ${player1_model}"
    echo "   Target: @${player2_name}"
    echo "   Template: ${battle_mode}"
    print_system_prompt_details "   " "$player1_prompt_label" "$player1_prompt_text"
    echo

    echo -e "${CYAN}💬 Sending moderator kickoff for @${player1_name}...${NC}"
    kickoff_args=("scripts/moderator_prompt_example.py" "@${player1_name}" "@${player2_name}" "--template" "$battle_mode" "--plugin" "ollama" "--send" "--config" "$player1_config")
    if [[ -n "$player1_model" ]]; then
        kickoff_args+=("--model" "$player1_model")
    fi
    if [[ -n "$BASE_SYSTEM_PROMPT_PATH" && -f "$BASE_SYSTEM_PROMPT_PATH" ]]; then
        kickoff_args+=("--base-prompt" "$BASE_SYSTEM_PROMPT_PATH")
    fi
    if [[ -n "$prompt_path" ]]; then
        kickoff_args+=("--scenario-prompt" "$prompt_path")
    fi
    if ! uv run python "${kickoff_args[@]}"; then
        echo -e "${YELLOW}⚠️  Kickoff delivery failed. Battle will continue without scripted opener.${NC}"
    else
        echo -e "${GREEN}✅ Moderator kickoff delivered!${NC}"
    fi
    echo

    if ! prepare_ollama "$OLLAMA_MODEL"; then
        echo -e "${YELLOW}↩️  Stopping the battle so you can restart once Ollama is ready.${NC}"
        cleanup
        return 1
    fi

    cleanup() {
        if (( battle_cleanup_ran )); then
            return 0
        fi
        battle_cleanup_ran=1
        battle_stop_requested=1

        echo
        echo -e "${YELLOW}🛑 Stopping AI Battle...${NC}"

        if [[ -n "$quit_handler_pid" ]]; then
            kill "$quit_handler_pid" 2>/dev/null || true
        fi

        if [[ -n "$player2_pid" ]]; then
            echo "   Stopping Player 2 (@${player2_name})..."
            kill "$player2_pid" 2>/dev/null || true
            wait "$player2_pid" 2>/dev/null || true
        fi

        echo "   Cleaning up any remaining monitor processes..."
        pkill -f "reliable_monitor.py" 2>/dev/null || true
        pkill -f "python.*reliable_monitor" 2>/dev/null || true
        pkill -f "uv run reliable_monitor" 2>/dev/null || true

        echo -e "${GREEN}✅ All processes stopped cleanly${NC}"
        echo "👋 Battle ended!"
    }

    handle_quit_input() {
        while true; do
            read -rsn1 key
            if [[ "$key" == "q" || "$key" == "Q" ]]; then
                echo
                echo -e "${YELLOW}🛑 Quit requested — wrapping up the battle...${NC}"
                cleanup
                break
            fi
        done
    }

    trap cleanup SIGINT SIGTERM

    echo "🎬 Starting the battle!"
    echo "   💡 Press Q at any time to quit"
    echo "   💡 Or use Ctrl+C for immediate stop"
    echo
    echo -e "${BLUE}🔥 LET THE AI BATTLE BEGIN! 🔥${NC}"
    echo

    handle_quit_input &
    local quit_handler_pid=$!

    set +e
    uv run reliable_monitor.py --loop
    local initiator_exit=$?
    set -e

    kill "$quit_handler_pid" 2>/dev/null || true
    cleanup

    if (( initiator_exit != 0 && initiator_exit != 130 && initiator_exit != 143 )); then
        return $initiator_exit
    fi
    return 0
}

select_evaluation_type() {
    local presets_file=${1:-configs/evaluation_presets.json}

    if [[ ! -f "$presets_file" ]]; then
        echo -e "${RED}❌ Evaluation presets file not found: $presets_file${NC}" >&2
        return 1
    fi

    local options=()
    while IFS=$'\t' read -r key name description icon; do
        [[ -z "$key" || "$key" == "null" ]] && continue
        [[ "$name" == "null" ]] && name="$key"
        [[ "$description" == "null" ]] && description=""
        [[ -z "$icon" || "$icon" == "null" ]] && icon="🎯"
        options+=("${key}::${icon} ${name}::${description}")
    done < <(jq -r '.types[] | [.key, .name, .description, (.icon // "")] | @tsv' "$presets_file")

    if (( ${#options[@]} == 0 )); then
        echo -e "${RED}❌ No evaluation types defined in $presets_file${NC}" >&2
        return 1
    fi

    local selection
    selection=$(cursor_menu "${CYAN}🎯 Select Evaluation Type:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    echo "$selection"
}

select_evaluation_config() {
    local presets_file=${1:-configs/evaluation_presets.json}
    local type_key=${2:-}

    if [[ -z "$type_key" ]]; then
        echo -e "${RED}❌ Internal error: evaluation type not provided${NC}" >&2
        return 1
    fi
    if [[ ! -f "$presets_file" ]]; then
        echo -e "${RED}❌ Evaluation presets file not found: $presets_file${NC}" >&2
        return 1
    fi

    local options=()
    while IFS=$'\t' read -r key name description icon; do
        [[ -z "$key" || "$key" == "null" ]] && continue
        [[ "$name" == "null" ]] && name="$key"
        [[ "$description" == "null" ]] && description=""
        [[ -z "$icon" || "$icon" == "null" ]] && icon="🧪"
        options+=("${key}::${icon} ${name}::${description}")
    done < <(jq -r --arg type "$type_key" '.types[] | select(.key == $type) | .configs[] | [.key, .name, .description, (.icon // "")] | @tsv' "$presets_file")

    if (( ${#options[@]} == 0 )); then
        echo -e "${RED}❌ No evaluation configs defined for type '$type_key'.${NC}" >&2
        return 1
    fi

    local selection
    selection=$(cursor_menu "${CYAN}🧪 Choose Evaluation Config:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    echo "$selection"
}

run_evaluation_mode() {
    echo
    echo -e "${CYAN}🎯 Evaluation Mode${NC}"

    local presets_file="configs/evaluation_presets.json"
    local eval_type
    eval_type=$(select_evaluation_type "$presets_file") || {
        echo -e "${YELLOW}↩️  Returning to main menu.${NC}"
        return 1
    }

    local eval_config
    eval_config=$(select_evaluation_config "$presets_file" "$eval_type") || {
        echo -e "${YELLOW}↩️  Returning to main menu.${NC}"
        return 1
    }

    local eval_type_name
    eval_type_name=$(jq -r --arg key "$eval_type" '.types[] | select(.key == $key) | (.name // $key)' "$presets_file")
    local eval_config_name
    eval_config_name=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.name // $cfg)' "$presets_file")
    local eval_config_desc
    eval_config_desc=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.description // "")' "$presets_file")

    local template_key
    template_key=$(jq -r --arg key "$eval_type" '.types[] | select(.key == $key) | (.template // "pairwise_basic")' "$presets_file")
    [[ -z "$template_key" || "$template_key" == "null" ]] && template_key="pairwise_basic"

    local dataset_default
    dataset_default=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.dataset // empty)' "$presets_file")
    [[ "$dataset_default" == "null" ]] && dataset_default=""

    local prompt_default
    prompt_default=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.default_prompt // empty)' "$presets_file")
    [[ "$prompt_default" == "null" ]] && prompt_default=""

    local prompt_required
    prompt_required=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.prompt_required // false)' "$presets_file")
    [[ -z "$prompt_required" || "$prompt_required" == "null" ]] && prompt_required="false"

    local max_samples_default
    max_samples_default=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.max_samples // 5)' "$presets_file")
    [[ -z "$max_samples_default" || "$max_samples_default" == "null" ]] && max_samples_default=5

    local confidence_threshold
    confidence_threshold=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.confidence_threshold // empty)' "$presets_file")
    [[ "$confidence_threshold" == "null" ]] && confidence_threshold=""

    local low_confidence_retry
    low_confidence_retry=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.low_confidence_retry // true)' "$presets_file")
    [[ -z "$low_confidence_retry" || "$low_confidence_retry" == "null" ]] && low_confidence_retry="true"

    local suggested_tags_raw
    suggested_tags_raw=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | (.tags // []) | join(" ")' "$presets_file")
    [[ "$suggested_tags_raw" == "null" ]] && suggested_tags_raw=""

    local default_candidate_a
    default_candidate_a=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | .default_models.candidate_a // empty' "$presets_file")
    local default_candidate_b
    default_candidate_b=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | .default_models.candidate_b // empty' "$presets_file")
    local default_judge_model
    default_judge_model=$(jq -r --arg type "$eval_type" --arg cfg "$eval_config" '.types[] | select(.key == $type) | .configs[] | select(.key == $cfg) | .default_models.judge // empty' "$presets_file")

    echo
    echo -e "${GREEN}✅ ${eval_type_name} selected${NC}"
    echo -e "   Config: ${eval_config_name}"
    if [[ -n "$eval_config_desc" ]]; then
        echo -e "   ${eval_config_desc}"
    fi

    echo
    if ! select_ollama_model CANDIDATE_A_MODEL "${CYAN}Choose Candidate A Model:${NC}" "${CYAN}🤖 Candidate A Options:${NC}" "$default_candidate_a"; then
        echo -e "${YELLOW}↩️  Returning to main menu at your request.${NC}"
        return 1
    fi
    local candidate_a="$CANDIDATE_A_MODEL"

    echo
    if ! select_ollama_model CANDIDATE_B_MODEL "${CYAN}Choose Candidate B Model:${NC}" "${CYAN}🤖 Candidate B Options:${NC}" "$default_candidate_b"; then
        echo -e "${YELLOW}↩️  Returning to main menu at your request.${NC}"
        return 1
    fi
    local candidate_b="$CANDIDATE_B_MODEL"

    echo
    if ! select_ollama_model JUDGE_MODEL "${CYAN}Choose Judge Model:${NC}" "${CYAN}⚖️  Judge Model Options:${NC}" "$default_judge_model"; then
        echo -e "${YELLOW}↩️  Returning to main menu at your request.${NC}"
        return 1
    fi
    local judge_model="$JUDGE_MODEL"

    local dataset_path=""
    if [[ -n "$dataset_default" ]]; then
        read -p "   Dataset path [$dataset_default]: " dataset_path
        exit_if_quit "$dataset_path"
        if [[ -z "$dataset_path" ]]; then
            dataset_path="$dataset_default"
        fi
    else
        read -p "   Dataset path (optional, jsonl/txt): " dataset_path
        exit_if_quit "$dataset_path"
    fi

    local prompt=""
    if [[ "$(lowercase "$prompt_required")" == "true" ]]; then
        while true; do
            local prompt_input=""
            if [[ -n "$prompt_default" ]]; then
                read -p "   Prompt [$prompt_default]: " prompt_input
            else
                read -p "   Prompt: " prompt_input
            fi
            exit_if_quit "$prompt_input"
            if [[ -z "$prompt_input" ]]; then
                if [[ -n "$prompt_default" ]]; then
                    prompt="$prompt_default"
                    break
                fi
                echo -e "${RED}❌ Prompt is required for this config${NC}"
                continue
            fi
            prompt="$prompt_input"
            break
        done
    else
        local prompt_input=""
        if [[ -n "$prompt_default" ]]; then
            read -p "   Single prompt (optional) [$prompt_default]: " prompt_input
            exit_if_quit "$prompt_input"
            prompt="${prompt_input:-$prompt_default}"
        else
            read -p "   Single prompt (optional): " prompt_input
            exit_if_quit "$prompt_input"
            prompt="$prompt_input"
        fi
    fi

    if [[ -n "$dataset_path" && ${dataset_path:0:1} == "~" ]]; then
        dataset_path="${dataset_path/#\~/$HOME}"
    fi

    if [[ -n "$dataset_path" && ! -f "$dataset_path" ]]; then
        echo -e "${RED}❌ Dataset file not found: $dataset_path${NC}"
        return 1
    fi

    if [[ -z "$prompt" && -z "$dataset_path" ]]; then
        echo -e "${RED}❌ Provide either a prompt or a dataset for this evaluation.${NC}"
        return 1
    fi

    local max_samples=""
    read -p "   Max samples [$max_samples_default]: " max_samples
    exit_if_quit "$max_samples"
    if [[ -z "$max_samples" ]]; then
        max_samples="$max_samples_default"
    fi

    if ! [[ "$max_samples" =~ ^[0-9]+$ && "$max_samples" -gt 0 ]]; then
        echo -e "${RED}❌ Max samples must be a positive integer${NC}"
        return 1
    fi

    local preset_tags=()
    if [[ -n "$suggested_tags_raw" ]]; then
        for raw_tag in $suggested_tags_raw; do
            local sanitized_tag
            sanitized_tag=$(sanitize_tag_token "$raw_tag")
            [[ -z "$sanitized_tag" ]] && continue
            preset_tags+=("$sanitized_tag")
        done
        if (( ${#preset_tags[@]} > 0 )); then
            local preset_display
            preset_display=$(IFS=' '; echo "${preset_tags[*]}")
            echo -e "${YELLOW}ℹ️  Preset tags will be applied: ${preset_display}${NC}"
        fi
    fi

    configure_session_tags

    local combined_tags=()
    for tag in "${preset_tags[@]}"; do
        local duplicate=0
        for existing in "${combined_tags[@]}"; do
            if strings_equal_ci "$existing" "$tag"; then
                duplicate=1
                break
            fi
        done
        (( duplicate )) || combined_tags+=("$tag")
    done

    if [[ -n "$SESSION_TAGS" ]]; then
        IFS=',' read -ra user_tags <<< "$SESSION_TAGS"
        for tag in "${user_tags[@]}"; do
            [[ -z "$tag" ]] && continue
            local duplicate=0
            for existing in "${combined_tags[@]}"; do
                if strings_equal_ci "$existing" "$tag"; then
                    duplicate=1
                    break
                fi
            done
            (( duplicate )) || combined_tags+=("$tag")
        done
    fi

    local tag_args=()
    for tag in "${combined_tags[@]}"; do
        tag_args+=("--tag" "$tag")
    done

    local combined_tag_display=""
    if (( ${#combined_tags[@]} > 0 )); then
        combined_tag_display=$(IFS=' '; echo "${combined_tags[*]}")
    fi

    local args=(
        "-m" "scripts.evaluation.pairwise_eval"
        "--candidate-a-model" "$candidate_a"
        "--candidate-b-model" "$candidate_b"
        "--judge-model" "$judge_model"
        "--template" "$template_key"
        "--max-samples" "$max_samples"
        "--output-dir" "logs/evaluations"
    )

    if [[ -n "$prompt" ]]; then
        args+=("--prompt" "$prompt")
    fi
    if [[ -n "$dataset_path" ]]; then
        args+=("--dataset" "$dataset_path")
    fi
    if [[ -n "$confidence_threshold" ]]; then
        args+=("--confidence-threshold" "$confidence_threshold")
    fi
    if [[ "$(lowercase "$low_confidence_retry")" == "false" || "$low_confidence_retry" == "0" ]]; then
        args+=("--no-low-confidence-retry")
    fi

    args+=("${tag_args[@]}")

    echo
    echo -e "${GREEN}🚀 Launching evaluation...${NC}"
    echo -e "   Type: ${eval_type_name}"
    echo -e "   Config: ${eval_config_name}"
    echo -e "   Candidate A: ${candidate_a}"
    echo -e "   Candidate B: ${candidate_b}"
    echo -e "   Judge: ${judge_model}"
    if [[ -n "$dataset_path" ]]; then
        echo -e "   Dataset: ${dataset_path}"
    fi
    if [[ -n "$prompt" ]]; then
        echo -e "   Prompt: ${prompt:0:60}"
    fi
    echo -e "   Template: ${template_key}"
    echo -e "   Max samples: ${max_samples}"
    if [[ -n "$confidence_threshold" ]]; then
        echo -e "   Confidence threshold: ${confidence_threshold}"
    fi
    if [[ "$(lowercase "$low_confidence_retry")" == "false" || "$low_confidence_retry" == "0" ]]; then
        echo -e "   Low-confidence retry: disabled"
    else
        echo -e "   Low-confidence retry: enabled"
    fi
    if [[ -n "$combined_tag_display" ]]; then
        echo -e "   Tags: ${combined_tag_display}"
    fi

    if ! uv run python "${args[@]}"; then
        echo -e "${RED}❌ Evaluation run failed.${NC}"
        return 1
    fi

    echo -e "${GREEN}✅ Evaluation completed.${NC}"
    return 0
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
        "echo::📢 Echo Mode::Run a simple echo monitor for quick checks"
        "single::👤 Single Agent Mode::Set up one AI agent to listen for mentions"
        "battle::🔥 AI Battle Mode::Pit two AI agents against each other"
        "eval::🎯 Evaluation Mode::Run pairwise model evaluations with a judge"
    )

    local choice
    choice=$(cursor_menu "${CYAN}🎮 Select Mode:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" 1 "${options[@]}") || exit_with_goodbye

    case "$choice" in
        echo)
            echo -e "${GREEN}✅ Echo Mode selected${NC}"
            MODE_SELECTION="echo"
            CONVERSATION_MODE=0
            PLUGIN_TYPE="echo"
            STARTUP_ACTION="listen_only"
            ;;
        single)
            echo -e "${GREEN}✅ Single Agent Mode selected${NC}"
            MODE_SELECTION="single"
            ;;
        battle)
            echo -e "${GREEN}✅ AI Battle Mode selected!${NC}"
            MODE_SELECTION="battle"
            ;;
        eval)
            echo -e "${GREEN}✅ Evaluation Mode selected${NC}"
            MODE_SELECTION="eval"
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

    local options=()
    local default_index=1

    for i in "${!discovered_configs[@]}"; do
        local entry="${discovered_configs[$i]}"
        local agent_name
        agent_name=$(jq -r '.mcpServers | to_entries[0].value.args[] | select(startswith("X-Agent-Name:")) | split(":")[1]' "$entry" 2>/dev/null || echo "unknown")
        local clean_name="${agent_name#@}"
        local detail="$entry"
        local display_handle
        if [[ -n "$clean_name" && "$clean_name" != "unknown" && "$clean_name" != "null" ]]; then
            display_handle="@${clean_name}"
        else
            display_handle="$(basename "$entry")"
        fi
        local decorated_label
        decorated_label=$(format_agent_label "$clean_name" "$display_handle")
        options+=("${entry}::${decorated_label}::${detail}")
    done

    options+=("NEW_AGENT::🆕 Create new agent configuration::Spin up a fresh monitor config")

    if (( DEFAULT_MODE )); then
        local auto_choice="${discovered_configs[0]}"
        export MCP_CONFIG_PATH="$auto_choice"
        set_mcp_token_env "$MCP_CONFIG_PATH"
        local auto_agent
        auto_agent=$(get_agent_name_from_config "$MCP_CONFIG_PATH")
        local auto_icon=$(get_agent_emoji "${auto_agent#@}")
        echo "   👉 Auto-selecting configuration for ${auto_icon} @$auto_agent"
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
    local chosen_icon=$(get_agent_emoji "${chosen_agent#@}")
    echo -e "${GREEN}✅ Selected config: $MCP_CONFIG_PATH${NC}"
    echo -e "${GREEN}🤝 Agent handle: ${chosen_icon} @${chosen_agent}${NC}"
}

# Function to create new agent config
create_new_agent_config() {
    echo ""
    echo -e "${CYAN}🆕 Creating New Agent Configuration${NC}"
    echo "=================================="

    read -p "Enter agent name (e.g., backend_dev, frontend_dev): " agent_name
    exit_if_quit "$agent_name"

    agent_name=${agent_name//@/}
    agent_name=${agent_name//[[:space:]]/}

    if [[ -z "$agent_name" ]]; then
        echo -e "${RED}❌ Agent name cannot be empty${NC}"
        exit 1
    fi

    if [[ "$agent_name" =~ [^A-Za-z0-9_-] ]]; then
        local cleaned
        cleaned=$(echo "$agent_name" | sed 's/[^A-Za-z0-9_-]//g')
        echo -e "${YELLOW}⚠️  Stripping unsupported characters. Using: ${cleaned}${NC}"
        agent_name="$cleaned"
    fi

    if [[ -z "$agent_name" ]]; then
        echo -e "${RED}❌ Agent name cannot be empty after sanitizing${NC}"
        exit 1
    fi

    local new_config="configs/mcp_config_${agent_name}.json"
    if [[ -e "$new_config" ]]; then
        echo -e "${RED}❌ Config already exists: $new_config${NC}"
        exit 1
    fi

    local template_config=""
    while IFS= read -r config; do
        if [[ "$config" == "$new_config" ]]; then
            continue
        fi
        if [[ "$config" == "configs/mcp_config.example.json" ]]; then
            continue
        fi
        template_config="$config"
        break
    done < <(find configs -name "mcp_config*.json" | sort)

    if [[ -z "$template_config" ]]; then
        template_config="configs/mcp_config.example.json"
    fi

    if [[ ! -f "$template_config" ]]; then
        echo -e "${RED}❌ Template config not found: $template_config${NC}"
        exit 1
    fi

    local generated_config
    generated_config=$(CONFIG_PATH="$template_config" NEW_AGENT="$agent_name" python - <<'PY'
import json
import os
from pathlib import Path

config_path = os.environ["CONFIG_PATH"]
agent_name = os.environ["NEW_AGENT"].strip()

with open(config_path, encoding="utf-8") as f:
    data = json.load(f)

servers = data.get("mcpServers")
if not servers:
    raise SystemExit("Template config missing mcpServers block")

server_key, server_cfg = next(iter(servers.items()))
args = list(server_cfg.get("args", []))

agent_flag_updated = False
for idx, arg in enumerate(args):
    if isinstance(arg, str) and arg.startswith("X-Agent-Name:"):
        args[idx] = f"X-Agent-Name:{agent_name}"
        agent_flag_updated = True

if not agent_flag_updated:
    args.append(f"X-Agent-Name:{agent_name}")

server_cfg["args"] = args

env = dict(server_cfg.get("env") or {})
existing_dir = env.get("MCP_REMOTE_CONFIG_DIR")

home = Path.home()
base_dir = None

if existing_dir:
    expanded = Path(os.path.expanduser(os.path.expandvars(existing_dir)))
    if expanded.name.lower() == agent_name.lower():
        expanded = expanded.parent
    base_dir = expanded.parent if expanded.name else expanded
else:
    base_dir = home / ".mcp-auth"

if not str(base_dir):
    base_dir = home / ".mcp-auth"

new_dir = (Path(base_dir) / agent_name).expanduser().resolve()

env["MCP_REMOTE_CONFIG_DIR"] = str(new_dir)
server_cfg["env"] = env
servers[server_key] = server_cfg

print(json.dumps(data, indent=2))
PY
) || {
        echo -e "${RED}❌ Failed to generate config from template${NC}"
        exit 1
    }

    printf '%s\n' "$generated_config" > "$new_config"

    echo -e "${GREEN}✅ Created config: $new_config${NC}"
    if [[ "$template_config" != "configs/mcp_config.example.json" ]]; then
        echo -e "${CYAN}ℹ️  Based on template: $template_config${NC}"
    else
        echo -e "${YELLOW}⚠️  Update server URLs in the new config before first run${NC}"
    fi
    echo -e "${YELLOW}⚠️  Note: OAuth authentication will be required on first run${NC}"

    if grep -q "YOUR-" "$new_config"; then
        echo -e "${YELLOW}⚠️  Detected placeholder values in $new_config. Please replace them before launching.${NC}"
    fi

    export MCP_CONFIG_PATH="$new_config"
    set_mcp_token_env "$MCP_CONFIG_PATH"
}

# Configure behavior for single-agent mode
select_single_agent_behavior() {
    echo ""
    echo -e "${CYAN}🔌 Plugin Selection:${NC}"

    local default_behavior="${SINGLE_AGENT_BEHAVIOR:-langgraph}"
    local default_index=1
    case "$default_behavior" in
        langgraph)
            default_index=1
            ;;
        monitor)
            default_index=2
            ;;
        kickoff)
            default_index=3
            ;;
        openrouter)
            default_index=4
            ;;
        *)
            default_index=2
            ;;
    esac

    if (( DEFAULT_MODE )); then
        SINGLE_AGENT_BEHAVIOR="langgraph"
        CONVERSATION_MODE=0
        export PLUGIN_TYPE="langgraph"
        echo "   👉 Auto-selecting LangGraph Monitor Mode"
        if ! select_langgraph_backend; then
            return 1
        fi
        select_system_prompt
        STARTUP_ACTION="listen_only"
        return 0
    fi

    local options=(
        "langgraph::🕸️ LangGraph Monitor Mode::Route replies through LangGraph with MCP tool support"
        "monitor::🧠 Ollama Monitor Mode::LLM monitors for a mention in aX"
        "kickoff::🗣️ Ollama Conversation Mode::Trigger a short conversation, then keep listening"
        "openrouter::🌐 OpenRouter Monitor Mode::Use OpenRouter-hosted completions (e.g., Grok 4 Fast)"
    )

    local selection
    selection=$(cursor_menu "${CYAN}Pick Your Plugin:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

    SINGLE_AGENT_BEHAVIOR="$selection"

    LANGGRAPH_BACKEND=""

    case "$selection" in
        monitor)
            SINGLE_AGENT_BEHAVIOR="monitor"
            CONVERSATION_MODE=0
            export PLUGIN_TYPE="ollama"
            echo -e "${GREEN}✅ Selected: Ollama Monitor Mode${NC}"
            if ! select_ollama_model; then
                return 1
            fi
            select_system_prompt
            STARTUP_ACTION="listen_only"
            ;;
        kickoff)
            SINGLE_AGENT_BEHAVIOR="kickoff"
            CONVERSATION_MODE=1
            export PLUGIN_TYPE="ollama"
            echo -e "${GREEN}✅ Selected: Ollama Conversation Mode${NC}"
            if ! select_ollama_model; then
                return 1
            fi
            select_system_prompt
            STARTUP_ACTION="listen_only"
            ;;
        openrouter)
            SINGLE_AGENT_BEHAVIOR="openrouter"
            CONVERSATION_MODE=0
            export PLUGIN_TYPE="openrouter"
            echo -e "${GREEN}✅ Selected: OpenRouter Monitor Mode${NC}"
            if ! select_openrouter_model; then
                return 1
            fi
            select_system_prompt
            STARTUP_ACTION="listen_only"
            ;;
        langgraph)
            SINGLE_AGENT_BEHAVIOR="langgraph"
            CONVERSATION_MODE=0
            export PLUGIN_TYPE="langgraph"
            echo -e "${GREEN}✅ Selected: LangGraph Monitor Mode${NC}"
            if ! select_langgraph_backend; then
                return 1
            fi
            select_system_prompt
            STARTUP_ACTION="listen_only"
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            exit 1
            ;;
    esac

    return 0
}

# Function to select Ollama model
select_ollama_model() {
    local target_var=${1:-OLLAMA_MODEL}
    local menu_title=${2:-}
    local heading_label=${3:-}
    local preferred_model=${4:-}

    if [[ -z "$menu_title" ]]; then
        menu_title="${CYAN}Choose Your Ollama Model:${NC}"
    fi
    if [[ -z "$heading_label" ]]; then
        heading_label="${CYAN}🤖 Available Ollama Models:${NC}"
    fi

    local chosen_value=""
    local available_models=()

    while true; do
        echo ""
        echo -e "$heading_label"

        if ! is_ollama_running; then
            echo -e "${YELLOW}⚠️  Ollama service is not running.${NC}"
            echo "   Start it in another terminal (for example: 'ollama serve')."
            echo "   Enter 'r' to retry after starting Ollama, or 'm' to return to the main menu."
            read -p "   Choice (r/m): " response
            exit_if_quit "$response"
            case "$(lowercase "$response")" in
                m)
                    return 1
                    ;;
                r|"")
                    continue
                    ;;
                *)
                    echo -e "${YELLOW}ℹ️  Type 'r' to retry or 'm' to go back.${NC}"
                    continue
                    ;;
            esac
        fi

        available_models=()
        while IFS= read -r model_name; do
            [[ -z "$model_name" ]] && continue
            local seen=0
            for existing in "${available_models[@]}"; do
                if [[ "$existing" == "$model_name" ]]; then
                    seen=1
                    break
                fi
            done
            if (( !seen )); then
                available_models+=("$model_name")
            fi
        done < <(ollama list | awk 'NR>1 {print $1}' | cut -d: -f1)

        if (( ${#available_models[@]} == 0 )); then
            echo -e "${YELLOW}⚠️  No Ollama models are installed.${NC}"
            echo "   Install one with 'ollama pull <model>' then choose 'r' to reload."
            read -p "   Choice (r/m): " response
            exit_if_quit "$response"
            case "$(lowercase "$response")" in
                m)
                    return 1
                    ;;
                r|"")
                    continue
                    ;;
                *)
                    echo -e "${YELLOW}ℹ️  Type 'r' to retry or 'm' to go back.${NC}"
                    continue
                    ;;
            esac
        fi

        if (( DEFAULT_MODE )); then
            chosen_value="${available_models[0]}"
            break
        fi

        local options=()
        local default_index=1
        local found_preferred=0
        for idx in "${!available_models[@]}"; do
            local model_name="${available_models[$idx]}"
            options+=("${model_name}::${model_name}::Installed model")
            if [[ -n "$preferred_model" && "$model_name" == "$preferred_model" ]]; then
                default_index=$((idx + 1))
                found_preferred=1
            fi
        done
        if [[ -n "$preferred_model" && $found_preferred -eq 0 ]]; then
            echo -e "${YELLOW}ℹ️  Suggested model '${preferred_model}' is not installed. Choose another or pick custom.${NC}"
        fi
        options+=("custom::✏️ Custom model::Type a custom model name")
        options+=("reload::🔄 Reload model list::Refresh after starting Ollama or installing models")
        options+=("back::↩️ Return to main menu::Go back without selecting a model")

        local selection
        selection=$(cursor_menu "$menu_title" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye

        case "$selection" in
            reload)
                echo -e "${CYAN}🔄 Reloading model list...${NC}"
                continue
                ;;
            back)
                return 1
                ;;
            custom)
                local custom_model
                read -p "Enter custom model name: " custom_model
                exit_if_quit "$custom_model"
                if [[ -z "$custom_model" ]]; then
                    echo -e "${RED}❌ Custom model name cannot be empty${NC}"
                    continue
                fi
                chosen_value="$custom_model"
                break
                ;;
            *)
                chosen_value="$selection"
                break
                ;;
        esac
    done

    printf -v "$target_var" "%s" "$chosen_value"
    local resolved_value="${!target_var}"
    export "$target_var=$resolved_value"
    echo -e "${GREEN}✅ Selected: $resolved_value${NC}"
    return 0
}

select_openrouter_model() {
    local target_var=${1:-OPENROUTER_MODEL}
    local menu_title=${2:-${CYAN}Choose Your OpenRouter Model:${NC}}
    local default_model=${3:-$(printf "%s" "${OPENROUTER_MODEL:-x-ai/grok-4-fast:free}")}

    if (( DEFAULT_MODE )); then
        printf -v "$target_var" "%s" "$default_model"
        local resolved="${!target_var}"
        export "$target_var=$resolved"
        echo -e "${GREEN}✅ Selected: $resolved${NC}"
        return 0
    fi

    echo ""
    echo -e "$menu_title"
    echo "   Press Enter to accept the default. Use ';' to chain multiple presses is not required."
    echo "   Popular choices:"
    echo "     • x-ai/grok-4-fast:free (fast Grok tier on OpenRouter)"
    echo "     • openrouter/auto (auto-select best route)"
    echo "     • anthropic/claude-3.5-sonnet (if enabled on your key)"

    local selection
    read -p "   OpenRouter model [${default_model}]: " selection
    exit_if_quit "$selection"
    if [[ -z "$selection" ]]; then
        selection="$default_model"
    fi

    printf -v "$target_var" "%s" "$selection"
    local resolved="${!target_var}"
    export "$target_var=$resolved"
    echo -e "${GREEN}✅ Selected: $resolved${NC}"
    return 0
}

select_langgraph_backend() {
    echo ""
    echo -e "${CYAN}🕸️ LangGraph Backend Selection:${NC}"

    local default_index=1
    if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
        default_index=2
    fi

    local options=(
        "openrouter::🌐 OpenRouter Backend::Use OpenRouter-hosted models with LangGraph workflow"
        "ollama::🤖 Ollama Backend::Use local Ollama models with LangGraph workflow"
    )

    local selection
    selection=$(cursor_menu "${CYAN}Choose LangGraph Backend:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || return 1

    case "$selection" in
        openrouter)
            export LANGGRAPH_BACKEND="openrouter"
            echo -e "${GREEN}✅ LangGraph backend set to OpenRouter${NC}"
            if ! select_openrouter_model; then
                return 1
            fi
            ;;
        ollama)
            export LANGGRAPH_BACKEND="ollama"
            echo -e "${GREEN}✅ LangGraph backend set to Ollama${NC}"
            if ! select_ollama_model; then
                return 1
            fi
            ;;
        *)
            echo -e "${RED}❌ Invalid LangGraph backend${NC}"
            return 1
            ;;
    esac

    return 0
}

select_system_prompt() {
    echo ""
    echo -e "${CYAN}🧾 System Prompt Selection:${NC}"

    local prompt_dir="prompts"
    local default_prompt="$DEFAULT_BASE_PROMPT_PATH"

    if [[ ! -d "$prompt_dir" ]]; then
        echo -e "${YELLOW}⚠️  Prompt directory not found. Using plugin fallback instructions.${NC}"
        BASE_SYSTEM_PROMPT_PATH=""
        return
    fi

    local prompt_files=()
    while IFS= read -r prompt_path; do
        if [[ "$prompt_path" != /* ]]; then
            prompt_path="$(pwd)/$prompt_path"
        fi
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
        echo -e "${YELLOW}⚠️  No prompt files found. Using plugin fallback instructions.${NC}"
        BASE_SYSTEM_PROMPT_PATH=""
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
        BASE_SYSTEM_PROMPT_PATH="$auto_prompt"
        echo -e "${GREEN}✅ Base system prompt set to: $BASE_SYSTEM_PROMPT_PATH${NC}"
        return
    fi

    default_index=1

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
            BASE_SYSTEM_PROMPT_PATH=""
            return
            ;;
        *)
            selected_prompt="$selection"
            ;;
    esac

    BASE_SYSTEM_PROMPT_PATH="$selected_prompt"
    echo -e "${GREEN}✅ Base system prompt set to: $BASE_SYSTEM_PROMPT_PATH${NC}"

    ADDITIONAL_PROMPT_PATHS=()
    return
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

    default_index=1

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
            if (( DEFAULT_MODE )); then
                default_index=$((i + 1))
            fi
            detail+=" (default)"
        fi
        options+=("${key}::${icon} ${name}::${detail}")
    done
    
    local selection_key=""
    if (( DEFAULT_MODE )); then
        selection_key="${template_keys[$((default_index - 1))]}"
        echo "   👉 Auto-selecting template: $selection_key"
    else
        default_index=1
        local selection
        selection=$(cursor_menu "${CYAN}Pick a Conversation Template:${NC}" "${YELLOW}Use ↑/↓ or j/k, Enter to select. Press q to quit.${NC}" "$default_index" "${options[@]}") || exit_with_goodbye
        selection_key="$selection"
    fi
    
    export CONVERSATION_TEMPLATE="$selection_key"
    local selected_name=$(jq -r ".templates.\"$selection_key\".name" "$templates_file")
    echo -e "${GREEN}✅ Selected: $selected_name${NC}"

    local template_prompt_file="$(jq -r ".templates.\"$selection_key\".system_prompt_file" "$templates_file")"
    if [[ -n "$template_prompt_file" && "$template_prompt_file" != "null" ]]; then
        if [[ "$template_prompt_file" != /* ]]; then
            template_prompt_file="$(pwd)/$template_prompt_file"
        fi
        CONVERSATION_SYSTEM_PROMPT_PATH="$template_prompt_file"
    else
        CONVERSATION_SYSTEM_PROMPT_PATH=""
    fi
    
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

print_banner() {
    echo -e "${BLUE}🤖 Universal MCP Monitor Startup${NC}"
    echo -e "${BLUE}=================================${NC}"
    echo ""
}

reset_session_state() {
    MODE_SELECTION=""
    SINGLE_AGENT_BEHAVIOR="langgraph"
    CONVERSATION_MODE=0
    STARTUP_ACTION="listen_only"
    PLUGIN_TYPE=""
    unset MCP_CONFIG_PATH AGENT_NAME AGENT_HANDLE AGENT_EMOJI
    unset OLLAMA_MODEL OLLAMA_SYSTEM_PROMPT OLLAMA_SYSTEM_PROMPT_FILE OLLAMA_BASE_PROMPT_FILE
    unset OPENROUTER_MODEL OPENROUTER_SYSTEM_PROMPT OPENROUTER_SYSTEM_PROMPT_FILE OPENROUTER_BASE_PROMPT_FILE
    unset LANGGRAPH_BACKEND LANGGRAPH_SYSTEM_PROMPT LANGGRAPH_SYSTEM_PROMPT_FILE LANGGRAPH_BASE_PROMPT_FILE
    unset CUSTOM_STARTUP_MESSAGE CONVERSATION_TARGET CONVERSATION_TEMPLATE
    unset SESSION_TAG_PRIMARY SESSION_TAGS SESSION_TAG_DISPLAY SESSION_ANNOUNCEMENT
    CONVERSATION_SYSTEM_PROMPT_PATH=""
    LANGGRAPH_BACKEND=""
    if [[ -n "$DEFAULT_BASE_PROMPT_PATH" && -f "$DEFAULT_BASE_PROMPT_PATH" ]]; then
        BASE_SYSTEM_PROMPT_PATH="$DEFAULT_BASE_PROMPT_PATH"
    else
        BASE_SYSTEM_PROMPT_PATH=""
    fi
    ADDITIONAL_PROMPT_PATHS=()
}

prompt_return_to_menu() {
    if (( DEFAULT_MODE )); then
        exit 0
    fi
    echo ""
    echo -e "${CYAN}↩️  Returning to the main menu...${NC}"
    clear
    print_banner
}

print_banner

echo "This script helps you start MCP monitors with different agents and plugins."
echo ""

while true; do
    reset_session_state

    select_mode

    if [[ "$MODE_SELECTION" == "battle" ]]; then
        if ! run_ai_battle_mode; then
            prompt_return_to_menu
            continue
        fi
        prompt_return_to_menu
        continue
    fi

    if [[ "$MODE_SELECTION" == "eval" ]]; then
        if ! run_evaluation_mode; then
            prompt_return_to_menu
            continue
        fi
        prompt_return_to_menu
        continue
    fi

    if [[ "$MODE_SELECTION" == "single" ]]; then
        if ! select_single_agent_behavior; then
            prompt_return_to_menu
            continue
        fi
    fi

    # Step 2: Select configuration
    select_config

    if [[ "$MODE_SELECTION" == "single" && "$CONVERSATION_MODE" -eq 1 ]]; then
        select_conversation_target
    fi

# Extract agent name from config
AGENT_NAME=$(get_agent_name_from_config "$MCP_CONFIG_PATH")
AGENT_HANDLE="@$AGENT_NAME"
AGENT_EMOJI=$(get_agent_emoji "$AGENT_NAME")
export AGENT_EMOJI

configure_session_tags

# Step 3: Set up environment
export MCP_BEARER_MODE=1

ensure_oauth_tokens "$MCP_CONFIG_PATH" "$AGENT_NAME"
set_mcp_token_env "$MCP_CONFIG_PATH"

if [[ "$MODE_SELECTION" == "single" ]]; then
    scenario_prompt_path=""
    inline_prompt=""
    if [[ "$CONVERSATION_MODE" -eq 1 && -n "$CONVERSATION_SYSTEM_PROMPT_PATH" ]]; then
        scenario_prompt_path="$CONVERSATION_SYSTEM_PROMPT_PATH"
    fi
    apply_system_prompt_env "$scenario_prompt_path" "$inline_prompt"
    unset scenario_prompt_path inline_prompt
fi

if [[ "$MODE_SELECTION" == "single" && "$CONVERSATION_MODE" -eq 1 ]]; then
    echo ""
    echo -e "${CYAN}💬 Sending kickoff message before starting monitor...${NC}"
    if [[ -n "$BASE_SYSTEM_PROMPT_PATH" && -f "$BASE_SYSTEM_PROMPT_PATH" ]]; then
        export OLLAMA_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export OPENROUTER_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
        export LANGGRAPH_BASE_PROMPT_FILE="$BASE_SYSTEM_PROMPT_PATH"
    else
        unset OLLAMA_BASE_PROMPT_FILE
        unset OPENROUTER_BASE_PROMPT_FILE
        unset LANGGRAPH_BASE_PROMPT_FILE
    fi
    kickoff_args=("scripts/moderator_prompt_example.py" "$AGENT_HANDLE" "$CONVERSATION_TARGET" "--template" "$CONVERSATION_TEMPLATE" "--plugin" "ollama" "--send" "--config" "$MCP_CONFIG_PATH")
    if [[ -n "$OLLAMA_MODEL" ]]; then
        kickoff_args+=("--model" "$OLLAMA_MODEL")
    fi
    if [[ -n "$CUSTOM_STARTUP_MESSAGE" ]]; then
        kickoff_args+=("--message" "$CUSTOM_STARTUP_MESSAGE")
    fi
    if ! uv run python "${kickoff_args[@]}"; then
        echo -e "${YELLOW}⚠️  Kickoff delivery failed. Monitor will still start in listen mode.${NC}"
    else
        echo -e "${GREEN}✅ Kickoff message delivered!${NC}"
    fi
fi

echo ""
echo -e "${GREEN}📋 Final Configuration:${NC}"
echo "   Config: $MCP_CONFIG_PATH"
echo "   Agent: ${AGENT_EMOJI} $AGENT_HANDLE"
if [[ "$MODE_SELECTION" == "echo" ]]; then
    echo "   Mode: Echo monitor"
else
    if [[ "$PLUGIN_TYPE" == "langgraph" ]]; then
        echo "   Mode: LangGraph monitor"
    else
        echo "   Mode: Single agent"
    fi
    if [[ "$SINGLE_AGENT_BEHAVIOR" == "kickoff" ]]; then
        echo "   Behavior: conversation kickoff"
    else
        echo "   Behavior: monitor"
    fi
    echo "   Plugin: $PLUGIN_TYPE"
    monitor_model=""
    if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
        monitor_model="$OLLAMA_MODEL"
    elif [[ "$PLUGIN_TYPE" == "openrouter" ]]; then
        monitor_model="$OPENROUTER_MODEL"
    elif [[ "$PLUGIN_TYPE" == "langgraph" ]]; then
        echo "   LangGraph backend: ${LANGGRAPH_BACKEND:-openrouter}"
        if [[ "$LANGGRAPH_BACKEND" == "ollama" ]]; then
            monitor_model="$OLLAMA_MODEL"
        else
            monitor_model="$OPENROUTER_MODEL"
        fi
    fi
    if [[ -n "$monitor_model" ]]; then
        echo "   Model: $monitor_model"
    fi
    print_system_prompt_details "   " "$LAST_SYSTEM_PROMPT_SOURCE" "$LAST_SYSTEM_PROMPT_TEXT"
    if [[ "$CONVERSATION_MODE" -eq 1 ]]; then
        echo "   Kickoff target: $CONVERSATION_TARGET"
        if [[ -n "$CONVERSATION_TEMPLATE" && "$CONVERSATION_TEMPLATE" != "basic" ]]; then
            template_name=$(jq -r ".templates.\"$CONVERSATION_TEMPLATE\".name" "configs/conversation_templates.json" 2>/dev/null || echo "$CONVERSATION_TEMPLATE")
            echo "   Template: $template_name"
        fi
    fi
fi
echo ""

# ensure_oauth_tokens already verified config and tokens

# Setup Ollama if needed
if [[ "$PLUGIN_TYPE" == "ollama" || ( "$PLUGIN_TYPE" == "langgraph" && "${LANGGRAPH_BACKEND:-}" == "ollama" ) ]]; then
    if ! prepare_ollama "$OLLAMA_MODEL"; then
        echo -e "${YELLOW}↩️  Returning to the main menu so you can start Ollama or install the requested model.${NC}"
        prompt_return_to_menu
        continue
    fi
fi

# Final summary and start
echo ""

# Run the monitor
monitor_exit=0
set +e
if [[ "$PLUGIN_TYPE" == "langgraph" ]]; then
    echo -e "${BLUE}🎯 Starting LangGraph Heartbeat Monitor...${NC}"
    echo "   Listening for ${AGENT_EMOJI} $AGENT_HANDLE mentions"
    echo "   LangGraph backend: ${LANGGRAPH_BACKEND:-openrouter}"
    if [[ "$LANGGRAPH_BACKEND" == "ollama" ]]; then
        echo "   Model: $OLLAMA_MODEL"
    else
        echo "   Model: $OPENROUTER_MODEL"
    fi
    print_system_prompt_details "   " "$LAST_SYSTEM_PROMPT_SOURCE" "$LAST_SYSTEM_PROMPT_TEXT"
    echo "   Press Ctrl+C to stop"
    echo ""
    echo -e "${CYAN}💡 Test by mentioning ${AGENT_EMOJI} $AGENT_HANDLE in the aX platform!${NC}"
    echo ""

    langgraph_wait_timeout="${WAIT_TIMEOUT:-35}"
    langgraph_stall_threshold="${STALL_THRESHOLD:-180}"
    heartbeat_cmd=(uv run python scripts/mcp_use_heartbeat_monitor.py --config "$MCP_CONFIG_PATH" --plugin langgraph --wait-timeout "$langgraph_wait_timeout" --stall-threshold "$langgraph_stall_threshold")

    if [[ ${SHOW_TOOL_CATALOG+x} ]]; then
        prev_show_tool_catalog="$SHOW_TOOL_CATALOG"
    else
        unset prev_show_tool_catalog
    fi
    if [[ ${LANGGRAPH_TOOL_DEBUG+x} ]]; then
        prev_langgraph_tool_debug="$LANGGRAPH_TOOL_DEBUG"
    else
        unset prev_langgraph_tool_debug
    fi

    export SHOW_TOOL_CATALOG=1
    unset LANGGRAPH_TOOL_DEBUG
    if [[ -z "${MCP_USE_LOG_LEVEL:-}" ]]; then
        export MCP_USE_LOG_LEVEL=error
    fi

    if (( ${#FORWARD_ARGS[@]} )); then
        for forwarded in "${FORWARD_ARGS[@]}"; do
            if [[ "$forwarded" == "--tool-debug" ]]; then
                export LANGGRAPH_TOOL_DEBUG=1
            else
                echo -e "${YELLOW}ℹ️  Forwarded argument '$forwarded' is not used in LangGraph mode.${NC}"
            fi
        done
    fi

    "${heartbeat_cmd[@]}"
    monitor_exit=$?

    if [[ ${prev_show_tool_catalog+x} ]]; then
        export SHOW_TOOL_CATALOG="$prev_show_tool_catalog"
    else
        unset SHOW_TOOL_CATALOG
    fi
    if [[ ${prev_langgraph_tool_debug+x} ]]; then
        export LANGGRAPH_TOOL_DEBUG="$prev_langgraph_tool_debug"
    else
        unset LANGGRAPH_TOOL_DEBUG
    fi
    unset prev_show_tool_catalog prev_langgraph_tool_debug
else
    echo -e "${BLUE}🎯 Starting MCP Monitor...${NC}"
    echo "   Listening for ${AGENT_EMOJI} $AGENT_HANDLE mentions"
    echo "   Mode: $MODE_SELECTION"
    echo "   Plugin: $PLUGIN_TYPE"
    if [[ "$PLUGIN_TYPE" == "ollama" ]]; then
        echo "   Model: $OLLAMA_MODEL"
    elif [[ "$PLUGIN_TYPE" == "openrouter" ]]; then
        echo "   Model: $OPENROUTER_MODEL"
    fi
    if [[ "$MODE_SELECTION" != "echo" ]]; then
        print_system_prompt_details "   " "$LAST_SYSTEM_PROMPT_SOURCE" "$LAST_SYSTEM_PROMPT_TEXT"
    fi
    echo "   Press Ctrl+C to stop"
    echo ""
    echo -e "${CYAN}💡 Test by mentioning ${AGENT_EMOJI} $AGENT_HANDLE in the aX platform!${NC}"
    echo ""

    if (( ${#FORWARD_ARGS[@]} )); then
        uv run reliable_monitor.py --loop "${FORWARD_ARGS[@]}"
        monitor_exit=$?
    else
        uv run reliable_monitor.py --loop
        monitor_exit=$?
    fi
fi
set -e

if (( monitor_exit != 0 )); then
    if (( monitor_exit == 130 || monitor_exit == 143 )); then
        echo -e "${YELLOW}ℹ️  Monitor exited on operator request (status ${monitor_exit}).${NC}"
    else
        echo -e "${YELLOW}⚠️  Monitor exited with status ${monitor_exit}.${NC}"
    fi
fi

prompt_return_to_menu
done
