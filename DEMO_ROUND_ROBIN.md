# Round-Robin Prediction Market Demo

## Overview
Director script controls the flow, agents respond to @mentions in sequence.

## Quick Start

### 1. Start Agent Monitors (Terminal 1)
```bash
./scripts/start_prediction_market_demo.sh
```

Wait for all 3 agents to show "✅ Connected!"

### 2. Run Round-Robin Demo (Terminal 2)
```bash
uv run ./scripts/director_round_robin.py
```

## What Happens

1. **@director posts** question to @open_router_grok4_fast
2. **Script waits** for response (polls every 3s, 90s timeout)
3. **When response received**, script posts to @HaloScript
4. **Repeat** for @Aurora
5. **Done!** - All 3 predictions collected in sequence

## Key Features

✅ **Script maintains control** - No infinite loops
✅ **Real-time polling** - Detects responses automatically
✅ **Terminal feedback** - Shows status table, timing, progress
✅ **Timeout handling** - Continues if agent doesn't respond
✅ **State tracking** - Knows who responded, what's next

## Architecture

```
Director Script (Python)          aX Platform          Agent Monitors
     |                                  |                      |
     |--1. Post Q to @grok------------>|                      |
     |                                  |--@mention----------->|
     |                                  |<--Response---------- |
     |<-2. Poll & Detect Response------|                      |
     |--3. Post to @HaloScript-------->|                      |
     |                                  |--@mention----------->|
     |                                  |<--Response---------- |
     |<-4. Poll & Detect Response------|                      |
     |--5. Post to @Aurora------------>|                      |
     |                                  |--@mention----------->|
     |                                  |<--Response---------- |
     |<-6. Poll & Detect Response------|                      |
     |                                  |                      |
     [DONE - Display Results]
```

## Troubleshooting

**No responses detected?**
- Check agents are running: `ps aux | grep simple_working_monitor`
- Verify in aX that agents are online
- Check agent terminal for errors

**Timeout on first agent?**
- @grok may be slow (web search + LLM)
- Script will continue to next agent
- Check aX manually to see if response posted late

**Want faster demo?**
- Reduce timeout: Edit `director_round_robin.py` line with `timeout=90` → `timeout=60`

## Demo Tips

🎯 **For Client:**
- Show Terminal 1: Live agent monitoring
- Show Terminal 2: Orchestration + progress
- Show aX: Full conversation thread with predictions
- Emphasize: Agents work autonomously, no human intervention

⚡ **Backup Plan:**
If live demo issues, use canned messages:
```bash
uv run ./scripts/demo_canned_message.py
```