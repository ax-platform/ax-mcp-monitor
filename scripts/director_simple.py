#!/usr/bin/env python3
"""Simple fast director - no wait mode, just quick polling."""

import asyncio
import sys
import time
import os
from pathlib import Path

os.environ['MCP_REMOTE_QUIET'] = '1'
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient

# Agents in order
AGENTS = ["@open_router_grok4_fast", "@HaloScript", "@Aurora"]
QUESTION = "Will S&P 500 close above 6000 today?"

async def main():
    print("🔌 Connecting...")

    client = MCPClient.from_config_file("configs/mcp_config_director.json")
    await client.create_all_sessions()
    session = client.get_session("ax-gcp")

    print("✅ Connected\n")

    last_id = None

    # Post to first agent
    agent = AGENTS[0]
    print(f"📤 Posting to {agent}...")
    await session.call_tool("messages", arguments={
        "action": "send",
        "content": f"{agent}\n\n🎯 PM-001: {QUESTION}\n\nProvide: [YES/NO] [%] [Reasoning]\nMention @director when done\n\n#client-prediction-market"
    })
    print(f"✅ Posted\n")

    # Wait for each agent
    for i, agent in enumerate(AGENTS):
        print(f"⏳ Waiting for {agent} ({i+1}/3)...")

        found = False
        for attempt in range(30):  # 30 attempts x 3s = 90s max
            await asyncio.sleep(3)

            # Quick check
            result = await session.call_tool("messages", arguments={
                "action": "check",
                "mode": "latest",
                "limit": 10,
                "mark_read": False,
            })

            messages = result.content if hasattr(result, 'content') else []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue

                msg_id = msg.get('id', '')
                if last_id and msg_id <= last_id:
                    continue

                author = msg.get('author', '')
                content = msg.get('content', '')

                if author == agent and '@director' in content:
                    print(f"✅ Got response from {agent}!")
                    print(f"   {content[:80]}...\n")
                    last_id = msg_id
                    found = True
                    break

            if found:
                break

            if (attempt + 1) % 10 == 0:
                print(f"   ... {(attempt+1)*3}s ...")

        if not found:
            print(f"⏱️ Timeout - no response from {agent}\n")
            continue

        # Post to next agent if not last
        if i < len(AGENTS) - 1:
            next_agent = AGENTS[i + 1]
            print(f"📤 Posting to {next_agent}...")
            await session.call_tool("messages", arguments={
                "action": "send",
                "content": f"{next_agent}\n\n🎯 PM-001 Step {i+2}/3: {QUESTION}\n\n{agent} responded. Now your turn!\n\nFormat: [YES/NO] [%] [Reasoning]\nMention @director\n\n#client-prediction-market"
            })
            print(f"✅ Posted\n")
            await asyncio.sleep(2)

    print("\n🎉 Demo complete!")
    print("Check aX for full thread: #client-prediction-market")

    await client.close_all_sessions()

if __name__ == "__main__":
    asyncio.run(main())