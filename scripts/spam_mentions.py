#!/usr/bin/env python3
"""Utility to blast a target handle with mentions for queue testing."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ax_mcp_wait_client.config_loader import get_default_config_path, parse_mcp_config
from ax_mcp_wait_client.mcp_client import MCPClient


async def main() -> int:
    config_path = os.getenv("MCP_CONFIG_PATH") or get_default_config_path()
    if not config_path:
        print("❌ No MCP config path found. Set MCP_CONFIG_PATH to a valid config JSON file.")
        return 1

    target = os.getenv("SPAM_TARGET", "@cbms")
    count = int(os.getenv("SPAM_COUNT", "5"))
    delay = float(os.getenv("SPAM_DELAY", "0.2"))

    cfg = parse_mcp_config(config_path)
    client = MCPClient(
        server_url=cfg.server_url,
        oauth_server=cfg.oauth_url,
        agent_name=cfg.agent_name,
        token_dir=cfg.token_dir,
    )

    await client.connect()
    try:
        for idx in range(1, count + 1):
            payload = f"{target} queue test #{idx} ({datetime.utcnow():%H:%M:%S})"
            if await client.send_message(payload):
                print(f"✅ Sent: {payload}")
            else:
                print(f"❌ Failed to send: {payload}")
            await asyncio.sleep(delay)
    finally:
        await client.disconnect()

    return 0


if __name__ == "__main__":
    try:
        exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n👋 Spam script interrupted")
        exit(130)
