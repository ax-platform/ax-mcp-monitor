#!/bin/bash
#
# Test script for the new conversation initiator feature
# This demonstrates the new environment variables and startup action logic
#

echo "🧪 Testing Conversation Initiator Feature"
echo "=========================================="

# Test case 1: Listen Only mode (default)
echo ""
echo "Test 1: Listen Only Mode"
echo "------------------------"
export STARTUP_ACTION="listen_only"
export CONVERSATION_TARGET=""
echo "STARTUP_ACTION: $STARTUP_ACTION"
echo "CONVERSATION_TARGET: $CONVERSATION_TARGET"
echo "✅ Expected behavior: Monitor starts in traditional listening mode"

# Test case 2: Initiate Conversation mode
echo ""
echo "Test 2: Initiate Conversation Mode"
echo "-----------------------------------"
export STARTUP_ACTION="initiate_conversation"
export CONVERSATION_TARGET="@backend_dev"
echo "STARTUP_ACTION: $STARTUP_ACTION"
echo "CONVERSATION_TARGET: $CONVERSATION_TARGET"
echo "✅ Expected behavior: Monitor sends startup message to @backend_dev, then listens"

# Test case 3: Invalid configuration
echo ""
echo "Test 3: Invalid Configuration"
echo "------------------------------"
export STARTUP_ACTION="initiate_conversation"
export CONVERSATION_TARGET=""
echo "STARTUP_ACTION: $STARTUP_ACTION"
echo "CONVERSATION_TARGET: $CONVERSATION_TARGET"
echo "⚠️  Expected behavior: Warning about missing target, fallback to listen mode"

# Test case 4: Environment variable defaults
echo ""
echo "Test 4: Default Values"
echo "----------------------"
unset STARTUP_ACTION
unset CONVERSATION_TARGET
STARTUP_ACTION_DEFAULT="${STARTUP_ACTION:-listen_only}"
CONVERSATION_TARGET_DEFAULT="${CONVERSATION_TARGET:-}"
echo "STARTUP_ACTION (default): $STARTUP_ACTION_DEFAULT"
echo "CONVERSATION_TARGET (default): $CONVERSATION_TARGET_DEFAULT"
echo "✅ Expected behavior: Defaults to listen_only mode"

echo ""
echo "🎯 Feature Summary:"
echo "- Environment variables control startup behavior"
echo "- STARTUP_ACTION: 'listen_only' | 'initiate_conversation'"
echo "- CONVERSATION_TARGET: target agent handle (e.g., '@backend_dev')"
echo "- Seamless integration with existing monitor workflow"
echo "- Enables automated agent-to-agent conversations"

echo ""
echo "🚀 To test manually:"
echo "1. Run: ./scripts/start_universal_monitor.sh"
echo "2. Select your agent configuration"
echo "3. Choose Ollama plugin and model"
echo "4. Select system prompt"
echo "5. NEW: Choose startup action (Listen Only vs Initiate Conversation)"
echo "6. If initiating, enter target agent handle"
echo "7. Monitor starts and optionally sends startup message"