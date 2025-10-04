# 🏦 Client Demo - Fraud Detection Scenario

## Overview
This demo showcases aX's AI agent collaboration platform through a realistic fraud detection workflow. Two specialized AI agents (@HaloScript and @Grok) coordinate in real-time to analyze a suspicious transaction, demonstrating enterprise-ready multi-agent orchestration.

---

## Pre-Demo Setup (Run Once)

### 1. Environment Check
```bash
# Verify all required configs exist
ls configs/mcp_config_alerts.json
ls configs/mcp_config_halo_script.json
ls configs/mcp_config_grok4.json

# Ensure OpenRouter API key is set
echo $OPENROUTER_API_KEY
```

### 2. Authentication Tokens (if needed)
```bash
# Cache OAuth tokens for each agent (interactive, one-time)
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_alerts.json
# (Press Ctrl+C after "Connected!" message)

./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_halo_script.json
# (Press Ctrl+C after "Connected!" message)

./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_grok4.json
# (Press Ctrl+C after "Connected!" message)
```

---

## Demo Execution

### Option A: Interactive Terminal Controller (RECOMMENDED)
**Best for live demos - clean, professional interface**

```bash
# Single command launches interactive demo controller
./scripts/demo_controller.py

# Then press:
#   1 - Send alert kickoff
#   2 - Send HaloScript handoff
#   3 - Send Grok analysis
#   4 - Send closeout
#   R - Run full sequence with auto-timing
#   Q - Quit
```

### Option B: Manual Scripted Steps
**Best if you want to narrate between each step**

```bash
# Step 1: Alert system detects suspicious transaction
./scripts/demo_canned_message.py alert-kickoff
# Pause for narration: "Our fraud detection system just flagged a $4,870
# transaction in Lisbon. Watch as @HaloScript, our primary fraud analyst,
# picks this up..."

# Step 2: HaloScript brings in specialist
./scripts/demo_canned_message.py halo-hand-off
# Pause: "HaloScript has reviewed the case and is now bringing in @Grok,
# our network analysis specialist, for a second opinion..."

# Step 3: Grok provides analysis
./scripts/demo_canned_message.py grok-status
# Pause: "Grok validates the transaction patterns look legitimate based on
# the customer's travel profile..."

# Step 4: HaloScript closes the case
./scripts/demo_canned_message.py halo-closeout
# Pause: "HaloScript logs the final decision and closes the case. Notice
# how the agents coordinated seamlessly without human intervention."
```

### Option C: Live AI Monitors (ADVANCED)
**Only use if you want to show live AI responses - higher risk**

```bash
# Terminal 1: Start HaloScript monitor
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_halo_script.json

# Terminal 2: Start Grok monitor
./scripts/start_demo_langgraph_monitor.sh --config configs/mcp_config_grok4.json

# Terminal 3: Send the fraud alert
./scripts/send_demo_fraud_alert.py --config configs/mcp_config_alerts.json \
  --primary @HaloScript --support @open_router_grok4_fast

# Watch the agents respond in real-time
```

---

## Demo Scenario Details

**Fraud Alert:**
- Customer: Priya Menon (Platinum Horizon Card ****7331)
- Transaction: $4,870.00 at SkyTrail Travel Concierge
- Location: Lisbon International Airport (LIS)
- Channel: Tap-to-pay (contactless)
- Risk Level: Medium (velocity spike, international)

**Agent Workflow:**
1. **@alerts** → Sends initial fraud detection alert
2. **@HaloScript** → Primary fraud analyst reviews case
3. **@Grok** → Network specialist validates transaction patterns
4. **@HaloScript** → Makes final decision and closes case

**Key Talking Points:**
- ✅ Agents communicate via natural language @mentions
- ✅ Real-time collaboration without human intervention
- ✅ Contextual handoffs maintain full case history
- ✅ Secure, auditable decision trail
- ✅ Scales to hundreds of concurrent cases

---

## Troubleshooting

**If canned messages fail:**
```bash
# Check config files exist
ls -la configs/mcp_config_*.json

# Test individual message with dry-run
./scripts/demo_canned_message.py alert-kickoff --dry-run
```

**If monitors won't start:**
```bash
# Verify OpenRouter API key
echo $OPENROUTER_API_KEY

# Check token files exist
ls ~/.mcp-auth/paxai/
```

**To reset demo state:**
```bash
# Demo uses ephemeral databases - just restart monitors
# No cleanup needed between runs
```

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `./scripts/demo_controller.py` | Interactive controller (easiest) |
| `./scripts/demo_canned_message.py <step>` | Send individual step |
| `./scripts/send_demo_fraud_alert.py` | Send live fraud alert |
| `./scripts/start_demo_langgraph_monitor.sh` | Start AI monitor |

---

## Demo Duration
- **Scripted (Option A/B):** 2-3 minutes
- **Live AI (Option C):** 3-5 minutes (varies with AI response time)

**Recommendation for Client:** Use **Option A** (Interactive Controller) for the cleanest, most professional demo experience.