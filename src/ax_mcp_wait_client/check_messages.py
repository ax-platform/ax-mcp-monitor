#!/usr/bin/env python3
"""
Minimal MCP client: connect → initialize → preflight (no side effects) → send once.

Goal: demonstrate single-insert (no duplicates) by ensuring the first RPC is
non-mutating (forces silent refresh if needed) and then performing send.

Run:
  MCP_REMOTE_CONFIG_DIR="$HOME/.mcp-auth/paxai/e2e38b9d/mcp_client_local" \
  uv run python examples/minimal_send_once.py
"""

import asyncio
import os
import sys
import uuid
from datetime import timedelta

# Patch MCP first
sys.path.insert(0, 'src')
# Patches removed - not needed for simple send

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402
from ax_mcp_wait_client.wait_client import build_oauth_provider  # noqa: E402
from ax_mcp_wait_client.bearer_refresh import BearerTokenStore, MCPBearerAuth  # noqa: E402

# Optional bearer loader (headless) to bypass OAuth flow entirely
import glob, json
from datetime import datetime, timezone, timedelta as _td

class _BearerLoader:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = os.path.expanduser(base_dir)

    def _find_latest(self, pattern: str) -> str | None:
        paths = sorted(
            glob.glob(os.path.join(self.base_dir, pattern)),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        return paths[0] if paths else None

    def load_access_token(self) -> str | None:
        # Only use mcp-remote versioned tokens like other clients
        cand = self._find_latest(os.path.join(self.base_dir, "mcp-remote-0.1.18", "*_tokens.json"))
        if not cand or not os.path.exists(cand):
            return None
        try:
            with open(cand, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("access_token")
        except Exception:
            return None


async def main() -> int:
    # Load config from file if specified, otherwise use env vars
    from ax_mcp_wait_client.config_loader import parse_mcp_config, get_default_config_path
    
    config_path = os.getenv('MCP_CONFIG_PATH') or get_default_config_path()
    
    if config_path and os.path.exists(config_path):
        # Load from config file
        try:
            config = parse_mcp_config(config_path)
            server_url = config.server_url
            oauth_url = config.oauth_url
            agent_name = config.agent_name
            token_dir = config.token_dir
        except Exception as e:
            print(f'Error loading config from {config_path}: {e}')
            return 2
    else:
        # Fall back to environment variables with defaults
        server_url = os.getenv('MCP_SERVER_URL', 'http://localhost:8001/mcp')
        oauth_url = os.getenv('MCP_OAUTH_SERVER_URL', 'http://localhost:8001')
        agent_name = os.getenv('MCP_AGENT_NAME', 'mcp_client_local')
        token_dir = os.getenv('MCP_REMOTE_CONFIG_DIR')

    if not token_dir:
        print('Missing MCP_REMOTE_CONFIG_DIR; cannot run headless.')
        return 2

    # Build OAuth provider (our helper proactively refreshes when refresh_token exists)
    bearer_mode = os.getenv('MCP_BEARER_MODE', '0') == '1'
    headers = {
        'X-Agent-Name': agent_name,
        'X-Client-Instance': str(uuid.uuid4()),
        'X-Idempotency-Key': str(uuid.uuid4()),
    }

    auth_obj = None
    if bearer_mode:
        store = BearerTokenStore(token_dir)
        if not store.token_file():
            print('No token file found for bearer mode.')
            return 2
        print(f'Using bearer token file: {store.token_file()}')
        auth_obj = MCPBearerAuth(store, oauth_url)
    else:
        auth_obj = await build_oauth_provider(oauth_url, token_dir=token_dir, interactive=False)

    async def _do_check():
        async with streamablehttp_client(
            url=server_url,
            headers=headers,  # headers must precede auth
            auth=auth_obj,
            timeout=timedelta(seconds=30),
        ) as (read, write, _get_sid):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Preflight
                await session.call_tool('messages', {
                    'action': 'check',
                    'wait': False,
                    'mode': 'latest',
                    'limit': 0,
                })
                import asyncio as _aio
                await _aio.sleep(0.2)

                wait_mode = os.getenv('MCP_WAIT', 'false').lower() == 'true'
                return await session.call_tool('messages', {
                    'action': 'check',
                    'wait': wait_mode,
                    'wait_mode': 'mentions' if wait_mode else None,
                    'timeout': 60 if wait_mode else None,
                    'mode': 'latest',
                    'limit': 5,
                })

    res = await _do_check()

    # Best-effort print
    text = None
    for c in getattr(res, 'content', []) or []:
        if getattr(c, 'type', '') == 'text' and hasattr(c, 'text'):
            text = c.text
            break
    print(text or str(getattr(res, '__dict__', res)))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
