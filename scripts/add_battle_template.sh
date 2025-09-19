#!/bin/bash
#
# Add Battle Template Utility
# 
# This script helps you easily add new conversation templates
# for AI Battle Mode without editing any code.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛠️  Add New Battle Template${NC}"
echo "================================"
echo

# Get template details from user
read -p "Template key (e.g., philosophy_chat): " template_key
if [[ -z "$template_key" ]]; then
    echo -e "${RED}❌ Template key cannot be empty${NC}"
    exit 1
fi

read -p "Template name (e.g., Philosophy Chat): " template_name
if [[ -z "$template_name" ]]; then
    echo -e "${RED}❌ Template name cannot be empty${NC}"
    exit 1
fi

read -p "Description: " template_description
if [[ -z "$template_description" ]]; then
    echo -e "${RED}❌ Description cannot be empty${NC}"
    exit 1
fi

echo
echo "Enter the starter message (press Ctrl+D when done):"
echo "You can use {target} as a placeholder for the target agent name."
echo
starter_message=$(cat)

if [[ -z "$starter_message" ]]; then
    echo -e "${RED}❌ Starter message cannot be empty${NC}"
    exit 1
fi

read -p "System context (optional): " system_context
if [[ -z "$system_context" ]]; then
    system_context="Engage in thoughtful conversation with your conversation partner."
fi

read -p "System prompt filename (e.g., philosophy_chat_system_prompt.txt): " prompt_filename
if [[ -z "$prompt_filename" ]]; then
    prompt_filename="${template_key}_system_prompt.txt"
fi

# Escape the starter message for JSON
starter_message_escaped=$(echo "$starter_message" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')
system_context_escaped=$(echo "$system_context" | sed 's/"/\\"/g')

# Create the system prompt file
echo
echo -e "${CYAN}📝 Creating system prompt file...${NC}"
cat > "prompts/$prompt_filename" << EOF
You are an AI agent engaging in: $template_name

$system_context

## Discussion Guidelines:
- Be engaging and thoughtful in your responses
- Stay true to the conversation topic and template
- Build on your conversation partner's points
- Ask follow-up questions to keep the dialogue flowing
- Maintain a respectful but lively conversational tone

## Your Role:
Respond naturally to the conversation starter and continue the dialogue in the spirit of "$template_name". Keep responses substantive but not overly long.
EOF

echo -e "${GREEN}✅ Created: prompts/$prompt_filename${NC}"

# Update the conversation templates JSON file
echo -e "${CYAN}📋 Adding template to conversation_templates.json...${NC}"

# Create a temporary file with the new template
temp_file=$(mktemp)
jq --arg key "$template_key" \
   --arg name "$template_name" \
   --arg desc "$template_description" \
   --arg starter "$starter_message_escaped" \
   --arg context "$system_context_escaped" \
   --arg prompt_file "prompts/$prompt_filename" \
   '.templates[$key] = {
     "name": $name,
     "description": $desc,
     "starter_message": $starter,
     "system_context": $context,
     "system_prompt_file": $prompt_file
   }' configs/conversation_templates.json > "$temp_file"

# Replace the original file
mv "$temp_file" configs/conversation_templates.json

echo -e "${GREEN}✅ Added template '$template_key' to conversation_templates.json${NC}"
echo
echo -e "${BLUE}🎉 Template created successfully!${NC}"
echo "   Template key: $template_key"
echo "   Name: $template_name" 
echo "   System prompt: prompts/$prompt_filename"
echo
echo -e "${YELLOW}💡 You can now use this template in AI Battle Mode!${NC}"
