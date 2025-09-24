#!/usr/bin/env python3
"""Minimal reliability tester using mcp-use.

Sends periodic pings to a target agent via the `messages` tool and waits for
acknowledgements that reference the ping ID. Designed to pair with
`scripts/mcp_use_monitor.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from typing import Optional

from mcp_use import MCPClient

WAIT_TIMEOUT_DEFAULT = 35


def _extract_text(result) -> str:
    text_parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            text_parts.append(text)
    return "".join(text_parts)


def _pick_server_name(client: MCPClient) -> str:
    servers = list(client.config.get("mcpServers", {}).keys())
    if not servers:
        raise RuntimeError("Tester config contains no servers")
    return servers[0]


async def _call_messages_with_retry(
    session,
    payload,
    retries: int = 3,
    base_delay: float = 1.0,
    allow_504: bool = False,
    suppress_errors: bool = False,
):
    last_error = None
    for attempt in range(retries):
        try:
            return await session.call_tool("messages", payload)
        except Exception as exc:
            message = str(exc)
            if ("504" in message or "timeout" in message.lower()) and attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"⚠️ messages call failed ({message}); retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
                last_error = exc
                continue
            if "504" in message and allow_504:
                print("⏳ messages wait timed out (HTTP 504)")
                return None
            last_error = exc
            break
    if last_error is not None and not suppress_errors:
        print(f"❌ messages call failed after {retries} attempts: {last_error}")
    return None


async def tester_loop(
    config_path: str,
    target_handle: str,
    iterations: int,
    interval: float,
    response_timeout: float,
) -> None:
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = _pick_server_name(client)
    session = client.get_session(server_name)

    print(f"✅ Tester connected (server: {server_name})")

    try:
        for i in range(1, iterations + 1):
            ping_id = uuid.uuid4().hex[:8]
            sent_at = time.time()
            message = (
                f"{target_handle} Minimal tester ping #{i} (ID: {ping_id}). "
                "Please acknowledge."
            )

            print(f"\n📤 Sending ping #{i} (ID: {ping_id}) -> {target_handle}")
            sent = await _call_messages_with_retry(
                session,
                {
                    "action": "send",
                    "content": message,
                    "idempotency_key": f"tester-{ping_id}",
                },
                retries=1,
                base_delay=1.0,
            )
            if sent is None:
                print(f"❌ Failed to send ping {ping_id}; moving on")
                continue

            acknowledged = False
            deadline = sent_at + response_timeout

            while time.time() < deadline:
                remaining = max(1, int(deadline - time.time()))
                try:
                    poll_timeout = min(remaining, WAIT_TIMEOUT_DEFAULT)
                    result = await _call_messages_with_retry(
                        session,
                        {
                            "action": "check",
                            "wait": True,
                            "wait_mode": "mentions",
                            "timeout": poll_timeout,
                            "limit": 5,
                        },
                        retries=1,
                        base_delay=1.0,
                        allow_504=True,
                        suppress_errors=True,
                    )
                except asyncio.TimeoutError:
                    continue
                if result is None:
                    print(f"⚠️ Check failed for {ping_id}; retrying")
                    await asyncio.sleep(2)
                    continue

                text = _extract_text(result)
                if ping_id in text:
                    latency = time.time() - sent_at
                    print(f"✅ Ack for {ping_id} in {latency:.2f}s")
                    acknowledged = True
                    break

            if not acknowledged:
                print(f"❌ No acknowledgement for {ping_id} within {response_timeout}s")

            if i < iterations and interval > 0:
                print(f"⏱️ Sleeping {interval:.1f}s")
                await asyncio.sleep(interval)
    finally:
        await client.close_all_sessions()
        print("\n🏁 Tester finished")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Minimal MCP tester using mcp-use")
    parser.add_argument("--config", required=True, help="Tester MCP config JSON")
    parser.add_argument("--target", required=True, help="Target agent handle")
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--interval", type=float, default=600.0)
    parser.add_argument("--response-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    try:
        asyncio.run(
            tester_loop(
                config_path=args.config,
                target_handle=args.target,
                iterations=args.iterations,
                interval=args.interval,
                response_timeout=args.response_timeout,
            )
        )
    except KeyboardInterrupt:
        print("\n👋 Tester interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
