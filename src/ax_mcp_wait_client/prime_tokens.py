#!/usr/bin/env python3
"""
Prime OAuth tokens to disk at the exact MCP_TOKEN_FILE path.

Opens the OAuth flow (interactive) and performs a non-mutating request to
force tokens to be saved via FileTokenStorage. This avoids the common pitfall
where build_oauth_provider() alone does not persist tokens until first use.
"""

import asyncio
import os
from datetime import timedelta

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from ax_mcp_wait_client.wait_client import build_oauth_provider


async def main() -> int:
    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")
    oauth_url = os.getenv("MCP_OAUTH_SERVER_URL", "http://localhost:8001")
    token_dir = os.getenv("MCP_REMOTE_CONFIG_DIR")
    if not token_dir:
        print("Missing MCP_REMOTE_CONFIG_DIR")
        return 2

    print("Starting interactive OAuth; will write to:")
    print(f"  TOKEN_FILE (if set): {os.getenv('MCP_TOKEN_FILE')}")
    print(f"  TOKEN_DIR: {token_dir}")

    agent_name = os.getenv("MCP_AGENT_NAME", "mcp_client_local")
    oauth = await build_oauth_provider(oauth_url, token_dir=token_dir, interactive=True, agent_name=agent_name)

    async with streamablehttp_client(
        url=server_url,
        headers={"X-Agent-Name": os.getenv("MCP_AGENT_NAME", "mcp_client_local")},
        auth=oauth,
        timeout=timedelta(seconds=30),
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Non-mutating call to force token persistence
            await session.call_tool("messages", {"action": "check", "wait": False, "mode": "latest", "limit": 0})
            print("✅ Tokens should now be saved to disk.")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

