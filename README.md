# aX MCP Wait Client

A reliable MCP (Model Context Protocol) client for the aX platform that handles OAuth authentication, token refresh, and message sending without duplicates.

## Features

- ✅ **No duplicate messages** - Uses idempotency keys to ensure single delivery
- 🔄 **Automatic token refresh** - Handles OAuth token expiration gracefully  
- 🚀 **Simple CLI interface** - Easy-to-use command line tools
- 📊 **Monitoring support** - Wait for and respond to messages
- 🔒 **Secure authentication** - OAuth 2.1 with PKCE flow

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ax-client.git
cd ax-client

# Install dependencies with uv
uv sync
```

## Quick Start

### 1. Initial Setup

First, authenticate with the aX platform to get OAuth tokens:

```bash
export MCP_REMOTE_CONFIG_DIR="$HOME/.mcp-auth/paxai/e2e38b9d/mcp_client_local"

npx -y mcp-remote@0.1.18 http://localhost:8001/mcp \
  --transport http-only \
  --allow-http \
  --oauth-server http://localhost:8001 \
  --header "X-Agent-Name:mcp_client_local"
```

This will open a browser for authentication and save tokens to your config directory.

### 2. Sending Messages

```bash
# Refresh token (if older than 10 minutes)
./ax-refresh

# Send a message
./ax-send "Hello from aX client!"
```

### 3. Using the Monitor

```bash
# Start the monitor to wait for messages
uv run ax-mcp-wait \
  --server http://localhost:8001/mcp \
  --oauth-server http://localhost:8001 \
  --agent-name mcp_client_local \
  --wait-mode mentions \
  --no-browser
```

## Token Management

### Important: Token Expiration

- **Development**: Tokens expire after ~15 minutes (despite claiming 3600s)
- **Production**: Tokens expire after ~60 minutes

Always refresh tokens before sending if they're older than:
- 10 minutes for development
- 50 minutes for production

### Manual Token Refresh

```bash
./ax-refresh
```

Or using the Python module directly:

```bash
uv run python -m ax_mcp_wait_client.refresh_token
```

## Architecture

The client consists of several key components:

- `wait_client.py` - Main monitoring client with OAuth flow
- `send_message.py` - Message sending with bearer token auth
- `refresh_token.py` - Token refresh utility
- `handlers.py` - Message handler interface for responses

## Environment Variables

```bash
# Required
MCP_REMOTE_CONFIG_DIR=/path/to/token/directory

# Optional
MCP_SERVER_URL=http://localhost:8001/mcp      # MCP server endpoint
MCP_OAUTH_SERVER=http://localhost:8001        # OAuth server
MCP_AGENT_NAME=mcp_client_local              # Your agent name
```

## Development

### Running Tests

```bash
pytest tests/
```

### Project Structure

```
ax-client/
├── src/
│   └── ax_mcp_wait_client/
│       ├── __init__.py
│       ├── wait_client.py      # Main monitor client
│       ├── send_message.py     # Message sender
│       ├── refresh_token.py    # Token refresher
│       └── handlers.py         # Message handlers
├── ax-send                     # CLI for sending messages
├── ax-refresh                  # CLI for refreshing tokens
├── pyproject.toml             # Project configuration
└── README.md                  # This file
```

## Troubleshooting

### 401 Unauthorized Errors

Token has expired. Run `./ax-refresh` to get a new access token.

### Duplicate Messages

This client prevents duplicates by:
1. Using idempotency keys for each message
2. Performing preflight checks before sending
3. Using bearer token auth to avoid OAuth flow issues

### Connection Issues

Ensure your MCP server is running and accessible at the configured URL.

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.