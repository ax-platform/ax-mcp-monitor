#!/usr/bin/env python3
"""Probe how long MCP long polls can stay open while heartbeats run.

This utility connects with :mod:`mcp_use`, runs a sequence of `messages.check`
calls with long `timeout` values, and logs how the server responds.  Optionally
it keeps a heartbeat going (zero-wait `messages.check`) so we can see whether
the underlying Streamable HTTP connection survives during very long waits.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from typing import Iterable, List, Optional

import httpx
from mcp_use import MCPClient


DEFAULT_TIMEOUTS = [60, 120, 180, 240, 300]
DEFAULT_HEARTBEAT_INTERVAL = 25
DEFAULT_HEARTBEAT_TIMEOUT = 10


def _extract_text(result) -> str:
    text_parts: List[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            text_parts.append(text)
    return "".join(text_parts)


def _parse_timeouts(raw: Optional[str]) -> List[int]:
    if not raw:
        return list(DEFAULT_TIMEOUTS)
    values: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError as exc:  # noqa: BLE001
            raise argparse.ArgumentTypeError(f"Invalid timeout value: {part}") from exc
    if not values:
        raise argparse.ArgumentTypeError("At least one timeout is required")
    return values


async def _heartbeat_loop(session, interval: int, timeout: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            payload = {"action": "check", "wait": False, "limit": 0}
            await asyncio.wait_for(session.call_tool("messages", payload), timeout=timeout)
            print("💓 Heartbeat ok")
        except asyncio.TimeoutError:
            print("💔 Heartbeat timed out")
        except Exception as exc:  # noqa: BLE001
            print(f"💔 Heartbeat error: {exc}")
            raise


async def _run_probe(
    config_path: str,
    timeouts: Iterable[int],
    heartbeat_interval: int,
    heartbeat_timeout: int,
) -> None:
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = next(iter(client.config.get("mcpServers", {})))
    session = client.get_session(server_name)

    print(f"✅ Probe connected (server: {server_name})")

    hb_task: Optional[asyncio.Task[None]] = None
    if heartbeat_interval > 0:
        hb_task = asyncio.create_task(
            _heartbeat_loop(session, heartbeat_interval, heartbeat_timeout)
        )

    try:
        for index, poll_timeout in enumerate(timeouts, start=1):
            payload = {
                "action": "check",
                "wait": True,
                "wait_mode": "mentions",
                "timeout": poll_timeout,
                "limit": 1,
            }
            print(
                f"\n⏱️ Probe #{index}: issuing long poll with timeout={poll_timeout}s"
            )
            start = time.time()
            try:
                result = await asyncio.wait_for(
                    session.call_tool("messages", payload),
                    timeout=poll_timeout + heartbeat_timeout + 5,
                )
                elapsed = time.time() - start
                text = _extract_text(result)
                if text:
                    print(f"✅ Poll returned in {elapsed:.1f}s with payload: {text}")
                else:
                    print(f"ℹ️ Poll returned in {elapsed:.1f}s with no text content")
            except asyncio.TimeoutError:
                elapsed = time.time() - start
                print(
                    "⏳ Local guard timed out after "
                    f"{elapsed:.1f}s (requested {poll_timeout}s); assuming stall"
                )
            except httpx.HTTPStatusError as exc:
                elapsed = time.time() - start
                status = exc.response.status_code if exc.response else "?"
                print(
                    f"⚠️ HTTP {status} after {elapsed:.1f}s while waiting: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = time.time() - start
                print(f"❌ Probe failed after {elapsed:.1f}s: {exc}")
                break
    finally:
        if hb_task:
            hb_task.cancel()
            with contextlib.suppress(Exception):
                await hb_task
        await client.close_all_sessions()
        print("\n🏁 Probe finished")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure how long MCP long polls can stay open"
    )
    parser.add_argument("--config", required=True, help="Path to MCP client config")
    parser.add_argument(
        "--timeouts",
        type=_parse_timeouts,
        default=None,
        help="Comma-separated list of poll timeouts in seconds (default: 60,120,180,240,300)",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=DEFAULT_HEARTBEAT_INTERVAL,
        help="Seconds between keep-alive checks (0 disables)",
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=int,
        default=DEFAULT_HEARTBEAT_TIMEOUT,
        help="Seconds to wait for a heartbeat response",
    )
    args = parser.parse_args(argv)

    timeouts = args.timeouts or DEFAULT_TIMEOUTS

    try:
        asyncio.run(
            _run_probe(
                args.config,
                timeouts,
                args.heartbeat_interval,
                args.heartbeat_timeout,
            )
        )
    except KeyboardInterrupt:
        print("\n👋 Probe interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
