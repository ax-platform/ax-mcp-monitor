#!/usr/bin/env python3
"""Client Demo - Simple & Working.

Flow:
1. @director posts question to @open_router_grok4_fast
2. @grok does web search and responds
3. Terminal shows progress
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient


async def send_message(config_path: str, content: str):
    """Send a message via MCP."""
    print(f"📤 Sending from {config_path}...")

    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()

    server_name = list(client.config.get("mcpServers", {}).keys())[0]
    session = client.get_session(server_name)

    await session.call_tool("messages", arguments={
        "action": "send",
        "content": content,
    })

    await client.close_all_sessions()
    print("✅ Sent!")


async def main():
    print("="*60)
    print("🏦 Client - AI Prediction Market Demo")
    print("="*60)
    print()

    # Step 1: Director kicks off
    print("Step 1: @director initiates market question...")

    message = """@open_router_grok4_fast

🎯 **Prediction Market Question**

Will S&P 500 close above 6000 today?

Please use your web search to check current S&P 500 price and trends, then make your prediction.

Format: [YES/NO] [Confidence %] [Brief reasoning with data]

#prediction-market #demo
"""

    await send_message("configs/mcp_config_director.json", message)

    print()
    print("✅ Market posted!")
    print("📡 @open_router_grok4_fast will now search the web and respond")
    print()
    print("Check aX to see the response!")
    print()
    print("💡 This demonstrates:")
    print("  - Distributed AI agents")
    print("  - Web search capability")
    print("  - Autonomous decision making")
    print("  - No human intervention needed")


if __name__ == "__main__":
    asyncio.run(main())