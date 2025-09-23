#!/usr/bin/env python3
"""
MCP Configuration Loader

Parses MCP config files (like those used by Claude) and extracts server settings.
Supports multiple server definitions and environment variables.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class MCPConfig:
    """Represents configuration for an MCP server connection."""

    def __init__(
        self,
        server_url: str,
        oauth_url: str,
        agent_name: str,
        token_dir: str,
        *,
        raw_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.server_url = server_url
        self.oauth_url = oauth_url
        self.agent_name = agent_name
        self.token_dir = token_dir
        self.raw_config = raw_config or {}
    
    def __repr__(self):
        return f"MCPConfig(server={self.server_url}, agent={self.agent_name})"


def _extract_server_config(server_name: str, server_config: Dict[str, Any]) -> MCPConfig:
    args = server_config.get('args', [])
    server_url = None
    oauth_url = None
    agent_name = None

    i = 0
    while i < len(args):
        arg = args[i]

        if not arg.startswith('-') and arg not in ['-y', 'mcp-remote@0.1.18'] and not server_url:
            server_url = arg
        elif arg == '--oauth-server' and i + 1 < len(args):
            oauth_url = args[i + 1]
            i += 1
        elif arg == '--header' and i + 1 < len(args):
            header = args[i + 1]
            if header.startswith('X-Agent-Name:'):
                agent_name = header.split(':', 1)[1]
            i += 1

        i += 1

    env = server_config.get('env', {}) or {}
    token_dir = env.get('MCP_REMOTE_CONFIG_DIR')

    if not server_url:
        raise ValueError("Could not extract server URL from config")
    if not token_dir:
        token_dir = os.path.expanduser(os.path.join("~/.mcp-auth", server_name))

    if not oauth_url:
        from urllib.parse import urlparse
        parsed = urlparse(server_url)
        oauth_url = f"{parsed.scheme}://{parsed.netloc}"

    if not agent_name:
        agent_name = os.path.basename(token_dir)

    token_dir = os.path.expanduser(token_dir)

    return MCPConfig(
        server_url=server_url,
        oauth_url=oauth_url,
        agent_name=agent_name,
        token_dir=token_dir,
        raw_config=server_config,
    )


def parse_all_mcp_servers(config_path: str) -> Dict[str, MCPConfig]:
    """Parse every server entry in a MCP config file."""

    config_path = Path(config_path).expanduser()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r') as f:
        config = json.load(f)

    servers = config.get('mcpServers', {})
    if not servers:
        raise ValueError(f"No MCP servers defined in {config_path}")

    parsed: Dict[str, MCPConfig] = {}
    for name, server_config in servers.items():
        parsed[name] = _extract_server_config(name, server_config)
    return parsed


def parse_mcp_config(config_path: str, server_name: Optional[str] = None) -> MCPConfig:
    """
    Parse an MCP configuration file and extract server settings.
    
    Args:
        config_path: Path to the MCP config JSON file
        server_name: Name of the server to use (defaults to first server found)
    
    Returns:
        MCPConfig object with parsed settings
    """
    config_path = Path(config_path).expanduser()
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    parsed = parse_all_mcp_servers(config_path)

    if server_name:
        if server_name not in parsed:
            raise ValueError(f"Server '{server_name}' not found in config. Available: {list(parsed.keys())}")
        return parsed[server_name]

    return next(iter(parsed.values()))


def get_default_config_path() -> Optional[str]:
    """
    Get the default config path, checking common locations.
    
    Returns:
        Path to config file, or None if not found
    """
    # Check environment variable first
    if env_path := os.getenv('MCP_CONFIG_PATH'):
        return env_path
    
    # Check common locations
    possible_paths = [
        './mcp_config.json',
        './pax_mcp_config.json',
        '~/.config/mcp/config.json',
        '~/.mcp/config.json',
    ]
    
    for path in possible_paths:
        expanded = Path(path).expanduser()
        if expanded.exists():
            return str(expanded)
    
    return None


if __name__ == '__main__':
    # Test the config loader
    import sys
    
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = get_default_config_path()
        if not config_file:
            print("No config file found. Provide path as argument or set MCP_CONFIG_PATH")
            sys.exit(1)
    
    try:
        config = parse_mcp_config(config_file)
        print(f"Loaded config from: {config_file}")
        print(f"  Server URL: {config.server_url}")
        print(f"  OAuth URL: {config.oauth_url}")
        print(f"  Agent Name: {config.agent_name}")
        print(f"  Token Dir: {config.token_dir}")
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)
