#!/usr/bin/env python3
"""Minimal monitor powered by mcp-use.

Connects to the configured MCP server, waits for mentions via the
`messages` tool, logs each incoming block, and sends a simple
acknowledgement. Designed for reliability testing with
`scripts/mcp_use_tester.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from typing import Optional, Tuple

from mcp_use import MCPClient

WAIT_TIMEOUT_DEFAULT = 60


def _load_server_name(client: MCPClient) -> str:
    sessions = list(client.config.get("mcpServers", {}).keys())
    if not sessions:
        raise RuntimeError("No servers defined in MCP configuration")
    return sessions[0]


def _extract_sender(raw: str, self_handle: str) -> Tuple[str, str]:
    lines = raw.replace("\\n", "\n").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("•") or line.startswith("-"):
            if ":" not in line:
                continue
            author, body = line.split(":", 1)
            author = author.lstrip("•- ")
            handles = [h for h in author.split() if h.startswith("@")]
            handles += [h for h in body.split() if h.startswith("@")]
            for handle in handles:
                if handle.lower() != self_handle.lower():
                    return author or "unknown", handle
            if author and not author.lower().startswith("✅ wait success"):
                base = author.split()[0].strip("@,:")
                if base and base.lower() != self_handle.lower():
                    return author, f"@{base}"
    return "unknown", "@unknown"


def _message_id(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_ack(sender: str, ping_id: str) -> str:
    if not sender.startswith("@"):
        sender = f"@{sender}"
    return f"{sender} — Ack ({ping_id})"


def _extract_text(result) -> str:
    text_parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            text_parts.append(text)
    return "".join(text_parts)


async def _call_messages_with_retry(session, payload, retries: int = 3, base_delay: float = 1.0):
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
            last_error = exc
            break
    if last_error is not None:
        print(f"❌ messages call failed after {retries} attempts: {last_error}")
    return None


async def _heartbeat_loop(session, interval: int = 45, timeout: int = 10) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            payload = {
                "action": "check",
                "wait": False,
                "limit": 0,
            }
            result = await asyncio.wait_for(
                session.call_tool("messages", payload), timeout=timeout
            )
            if result is None:
                print("💔 Heartbeat returned no result")
            else:
                print("💓 Heartbeat ok")
        except asyncio.TimeoutError:
            print("💔 Heartbeat timed out")
        except Exception as exc:
            print(f"💔 Heartbeat error: {exc}")

async def monitor_loop(config_path: str, wait_timeout: int) -> None:
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = _load_server_name(client)
    session = client.get_session(server_name)
    self_handle = client.config["mcpServers"][server_name].get("agent", {}).get(
        "name",
        client.config["mcpServers"][server_name].get("env", {}).get("X-Agent-Name", "@agent"),
    )
    if not self_handle.startswith("@"):
        self_handle = f"@{self_handle}"

    seen_ids: set[str] = set()
    print(f"✅ Minimal monitor connected as {self_handle} (server: {server_name})")

    try:
        heartbeat = asyncio.create_task(
            _heartbeat_loop(session, interval=45, timeout=10)
        )
        while True:
            try:
                payload = {
                    "action": "check",
                    "wait": True,
                    "wait_mode": "mentions",
                    "timeout": wait_timeout,
                    "limit": 5,
                }
                result = await _call_messages_with_retry(session, payload)
                if result is None:
                    await asyncio.sleep(2)
                    continue
                raw = _extract_text(result)
                if not raw:
                    continue
                mid = _message_id(raw)
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)

                print("\n📨 Incoming mention block:\n" + raw)
                author, sender = _extract_sender(raw, self_handle)
                ack = _build_ack(sender, mid[:8])
                print(f"💬 Acknowledging {sender} (author: {author}) with {mid[:8]}")
                try:
                    sent = await _call_messages_with_retry(
                        session,
                        {
                            "action": "send",
                            "content": ack,
                            "idempotency_key": mid,
                        },
                    )
                    if sent is not None:
                        print("✅ Ack dispatched")
                    else:
                        print(f"❌ Ack dispatch ultimately failed for {mid[:8]}")
                except Exception as exc:
                    print(f"❌ Failed to dispatch ack for {mid[:8]}: {exc}")
            except asyncio.TimeoutError:
                print("⏳ Wait timed out; continuing")
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Monitor loop error: {exc}")
                await asyncio.sleep(2)
    finally:
        try:
            heartbeat.cancel()
        except Exception:
            pass
        await client.close_all_sessions()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Minimal MCP monitor using mcp-use")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to MCP config JSON",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=WAIT_TIMEOUT_DEFAULT,
        help="Wait timeout in seconds",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(monitor_loop(args.config, args.timeout))
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
