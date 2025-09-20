#!/bin/bash
#
# Quick Demo of Conversation Templates
# 
# This script shows all templates in action for demo purposes
#

echo "🎪 CONVERSATION TEMPLATE SHOWCASE"
echo "================================="
echo ""
echo "Welcome to the new conversation template system!"
echo "These templates make it super easy to start engaging"
echo "AI-to-AI conversations with personality and fun."
echo ""

echo "🎯 TEMPLATE 1: TIC-TAC-TOE WITH ATTITUDE"
echo "--------------------------------------"
echo "Perfect for competitive gaming with trash talk!"
echo ""
python3 -c "
import json
with open('configs/conversation_templates.json') as f:
    templates = json.load(f)
template = templates['templates']['tic_tac_toe']
message = template['starter_message'].replace('{target}', '@demo_opponent')
print(message)
"
echo ""

echo "🤔 TEMPLATE 2: DEBATE THE ABSURD"
echo "--------------------------------"
echo "Great for philosophical arguments about silly topics!"
echo ""
python3 -c "
import json, random
with open('configs/conversation_templates.json') as f:
    templates = json.load(f)
template = templates['templates']['debate_absurd']
topic = random.choice(template['topics'])
message = template['starter_message'].replace('{target}', '@demo_opponent').replace('{topic}', topic)
print(f'Random topic: {topic}')
print('')
print(message)
"
echo ""

echo "🔥 TEMPLATE 3: AI ROAST BATTLE"
echo "------------------------------"
echo "Perfect for tech-themed comedy and AI humor!"
echo ""
python3 -c "
import json
with open('configs/conversation_templates.json') as f:
    templates = json.load(f)
template = templates['templates']['roast_battle']
message = template['starter_message'].replace('{target}', '@demo_opponent')
print(message)
"
echo ""

echo "🚀 HOW TO USE:"
echo "==============" 
echo "1. Run: ./scripts/start_universal_monitor.sh"
echo "2. Select 'Initiate Conversation' mode"
echo "3. Enter target agent (e.g., @backend_dev)"
echo "4. Choose your favorite template!"
echo "5. Watch the AI agents have entertaining conversations!"
echo ""

echo "💡 PERFECT FOR:"
echo "==============="
echo "• Live demos at conferences and meetups"
echo "• Testing AI personality and humor"
echo "• Breaking the ice between AI agents"
echo "• Showcasing interactive AI capabilities"
echo "• Having fun with AI-to-AI conversations!"
echo ""

echo "✨ Get ready for some seriously entertaining AI interactions! ✨"