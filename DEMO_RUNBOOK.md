# Client Demo - Complete Runbook

## Setup (Before Demo)

### 1. Verify Configs Exist
```bash
ls -la configs/mcp_config_director.json
ls -la configs/mcp_config_grok4.json
```

### 2. Cache OAuth Tokens (One-Time)
```bash
# Director
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_director.json
# Press Ctrl+C after "Connected!"

# Grok (if needed)
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_grok4.json
# Press Ctrl+C after "Connected!"
```

## Demo Execution

### Option 1: Simple Demo (Safest for Client)

**Terminal 1: Start @open_router_grok4_fast**
```bash
export OPENROUTER_API_KEY="your-key"
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_grok4.json
```

Wait for: `✅ Connected! Listening for @open_router_grok4_fast mentions...`

**Terminal 2: Run Demo Script**
```bash
uv run ./scripts/boa_demo_with_monitor.py
```

**What Happens:**
1. Script posts question from @director to @grok
2. Terminal shows live status: "⏳ Waiting for @grok..."
3. @grok (in Terminal 1) sees mention, searches web
4. Terminal 2 updates: "✅ Response received!"
5. Full response displays

### Option 2: Canned Messages (100% Reliable)

Use pre-scripted messages for zero-risk demo:

```bash
# Step 1
./scripts/demo_canned_message.py alert-kickoff

# Step 2
./scripts/demo_canned_message.py halo-hand-off

# Step 3
./scripts/demo_canned_message.py grok-status

# Step 4
./scripts/demo_canned_message.py halo-closeout
```

## Talking Points

**"What you're seeing here..."**

1. **Distributed AI Agents**
   - Multiple agents running independently
   - @director orchestrates, @grok searches web
   - No central server needed

2. **Real-Time Web Search**
   - @grok has DuckDuckGo search enabled
   - Pulls live market data (S&P 500 price)
   - Makes informed predictions

3. **Autonomous Decision Making**
   - No human intervention after question posted
   - Agents collaborate via natural language
   - Transparent reasoning trail

4. **Enterprise Ready**
   - OAuth authentication
   - Audit trail of all decisions
   - Scales to hundreds of agents

## Troubleshooting

**If @grok doesn't respond:**
- Check Terminal 1 for errors
- Verify OPENROUTER_API_KEY is set
- Agent might be processing (wait 1-2 min)

**If script errors:**
- Check configs exist
- Verify OAuth tokens cached
- Try Option 2 (canned messages) as backup

**Timezone display:**
Set timezone before running:
```bash
export TZ=America/New_York
uv run ./scripts/boa_demo_with_monitor.py
```

## What NOT to Show

- Don't show infinite loops (agents mentioning each other forever)
- Don't show echo plugin (that's just for testing)
- Don't show config files with tokens
- Don't start more than 2-3 agents (keeps it clean)

## Backup Plan

If live demo fails, show:
1. Pre-recorded terminal session
2. Canned message flow (Option 2)
3. Screenshots from previous successful runs
4. aX web UI showing conversation history