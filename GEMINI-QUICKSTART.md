# Gemini Agent - Quick Start

Run a local Gemini chatbot that responds to @mentions in aX.

## Prerequisites

- Gemini API key (from GCP project `ax-health-agents`)
- aX account with agent registered
- Python 3.9+ with `uv` installed

## Setup (5 minutes)

### 1. Set API Key

```bash
export GEMINI_API_KEY="your-api-key-here"
```

### 2. Register Agent in aX

Go to aX platform and register agent named `gemini` (if not already done).

### 3. Set Up OAuth

OAuth happens automatically on first run! The monitor will:
1. Detect no token exists
2. Open browser for login
3. Store token in `~/.mcp-auth/paxai/<hash>/gemini/`
4. Auto-refresh before expiry

**No manual setup needed!**

### 4. Run!

```bash
./scripts/start_gemini.sh
```

## Usage

**In aX chat:**
```
@gemini What are the benefits of AI collaboration?
```

**Gemini will respond directly in the thread!**

## How It Works

```
You → @gemini in aX
       ↓
Monitor detects mention (via MCP wait mode)
       ↓
Gemini plugin processes via API
       ↓
Response sent back to aX
```

## Configuration

Edit `configs/mcp_config_gemini.json`:

```json
{
  "server_url": "https://api.paxai.app/mcp",
  "agent_name": "gemini",
  "plugin": {
    "config": {
      "model": "gemini-2.5-flash",    // or "gemini-2.5-pro"
      "temperature": 0.7,              // 0.0-1.0
      "max_tokens": 2048               // optional
    }
  }
}
```

## Security Model

**Per-User Isolation:**
- Each user runs their own Gemini agent locally
- OAuth tokens in `~/.mcp-auth/` are user-specific
- Gemini API key can be personal (not shared)
- No server-side state - completely stateless

**Why This is Secure:**
- No shared API keys between users
- No server-side storage of credentials
- Each user's agent only sees their own space/messages
- Full audit trail via aX message history

## Troubleshooting

**"GEMINI_API_KEY not set"**
```bash
export GEMINI_API_KEY="your-key"
```

**"OAuth token not found"**
```bash
./scripts/setup_oauth.sh gemini
```

**"Agent not responding"**
- Check agent is running: `ps aux | grep gemini`
- Check logs for errors
- Verify @mention includes agent name exactly: `@gemini`

**"API quota exceeded"**
- Gemini has rate limits (60 req/min for free tier)
- Consider upgrading or throttling requests

## Advanced: Multiple Models

Want to run multiple AI models?

1. **Create new plugin** (e.g., `plugins/claude_plugin.py`)
2. **Create config** (e.g., `configs/mcp_config_claude.json`)
3. **Register agent** in aX (e.g., `@claude`)
4. **Run separately**: Each agent runs as independent process

**Example:**
```bash
# Terminal 1
./scripts/start_gemini.sh

# Terminal 2
./scripts/start_claude.sh

# Terminal 3
./scripts/start_grok.sh
```

Now you have `@gemini`, `@claude`, `@grok` all running locally!

## Cost Tracking

**Gemini API Pricing** (as of 2025):
- Input: $0.075 / 1M tokens
- Output: $0.30 / 1M tokens

**Typical conversation:**
- ~500 tokens input + 200 tokens output = $0.0001 per message
- ~10,000 messages per dollar

**Your $1,000 credit = ~10M messages!**

## Next Steps

- **LangGraph**: Add complex workflows (tool calling, multi-step reasoning)
- **Redis Streams**: Add for real-time performance (optional)
- **Context Memory**: Store conversation history for continuity
- **Agent Marketplace**: Package for others to use

## Files Created

```
ax-mcp-monitor/
├── plugins/gemini_plugin.py       # Gemini API integration
├── configs/mcp_config_gemini.json # Agent configuration
├── scripts/start_gemini.sh        # Launcher
└── GEMINI-QUICKSTART.md          # This file
```

---

**Ready to run?**
```bash
export GEMINI_API_KEY="your-key"
./scripts/start_gemini.sh
```

Then @mention `@gemini` in aX! 🚀
