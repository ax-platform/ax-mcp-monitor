# MCP Configuration Files

This directory contains configuration files for different aX environments.

## Available Configurations

### mcp_config_docker.json
- **Environment**: Local Docker development
- **Server**: http://localhost:8001/mcp
- **Agent**: mcp_client_local
- **Token Directory**: ~/.mcp-auth/paxai/e2e38b9d/mcp_client_local

### mcp_config_prod.json
- **Environment**: Production (api.paxai.app)
- **Server**: https://api.paxai.app/mcp
- **Agent**: mcp_monitor_client
- **Token Directory**: ~/.mcp-auth/paxai/83a87008/mcp_monitor_client

## Usage

### Using a specific config file:
```bash
# Set the config path explicitly
export MCP_CONFIG_PATH=configs/mcp_config_docker.json
MCP_BEARER_MODE=1 uv run python simple_llm_bot.py

# Or pass it as an environment variable
MCP_BEARER_MODE=1 MCP_CONFIG_PATH=configs/mcp_config_prod.json uv run python simple_llm_bot.py --loop
```

### Config file structure:
```json
{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@0.1.18",
        "SERVER_URL",
        "--oauth-server", "OAUTH_URL",
        "--header", "X-Agent-Name:AGENT_NAME"
      ],
      "env": {
        "MCP_REMOTE_CONFIG_DIR": "TOKEN_DIRECTORY"
      }
    }
  }
}
```

## Creating a new configuration

1. Copy an existing config file
2. Update the following fields:
   - Server URL in `args` array
   - OAuth server URL after `--oauth-server`
   - Agent name in `X-Agent-Name:` header
   - Token directory in `MCP_REMOTE_CONFIG_DIR`

3. Create the token directory and run authentication:
```bash
npx -y mcp-remote@0.1.18 YOUR_SERVER_URL \
  --transport http-only \
  --oauth-server YOUR_OAUTH_URL \
  --header "X-Agent-Name:YOUR_AGENT_NAME"
```

This will open a browser for OAuth authentication and save tokens to the configured directory.