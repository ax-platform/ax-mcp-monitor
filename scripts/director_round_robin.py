#!/usr/bin/env python3
"""Round-robin prediction market director that waits for real agent replies.

Usage example:

    uv run scripts/director_round_robin.py \
        --agents @cbms @jwt @Aurora \
        --question "Will S&P 500 close above 6000 today?"

The director mentions each agent in order, waits for their `@director` reply,
and then cues the next agent. Responses are detected via `messages.check` with
`wait=true`, so the console updates as soon as the real message arrives.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_use import MCPClient  # type: ignore


DIRECTOR_HANDLE = "@director"
DEFAULT_CONFIG = "configs/mcp_config_director.json"
DEFAULT_TAG = "#client-prediction-market"


@dataclass
class AgentResponse:
    handle: str
    message_id: str
    text: str


def _to_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


def _normalize_handle(handle: Optional[str]) -> Optional[str]:
    if not handle:
        return None
    handle = handle.strip()
    if not handle:
        return None
    if not handle.startswith("@"):
        handle = f"@{handle}"
    return handle


def _extract_text(result: Any) -> str:
    """Extract raw text from MCP result - same as working monitors"""
    text_parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            text_parts.append(text)
    return "".join(text_parts)


def _extract_sender(raw: str, self_handle: str) -> tuple[str, str]:
    """Extract sender from raw message - same as working monitors"""
    lines = raw.replace("\\n", "\n").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("•") or line.startswith("-") or line.startswith("🤝"):
            if ":" not in line:
                continue
            author, body = line.split(":", 1)
            author = author.lstrip("•-🤝 \t")
            handles = [token for token in author.split() if token.startswith("@")]
            handles += [token for token in body.split() if token.startswith("@")]
            for handle in handles:
                if handle.lower() != self_handle.lower():
                    return author or "unknown", handle
            if author and not author.lower().startswith("✅"):
                base = author.split()[0].strip("@,:")
                if base and base.lower() != self_handle.lower():
                    return author, f"@{base}"
    return "unknown", "@unknown"


def _message_id(raw: str) -> str:
    """Generate message ID from raw content"""
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def wait_for_agent_reply(
    session,
    agent_handle: str,
    seen_ids: set[str],
    wait_timeout: int,
    overall_timeout: int,
) -> Optional[AgentResponse]:
    deadline = time.monotonic() + overall_timeout
    normalized_agent = agent_handle.lower().lstrip("@")

    print(f"🔍 Waiting for reply from {agent_handle}")

    while time.monotonic() < deadline:
        try:
            result = await session.call_tool(
                "messages",
                arguments={
                    "action": "check",
                    "wait": True,
                    "wait_mode": "mentions",
                    "timeout": wait_timeout,
                    "limit": 10,
                },
            )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  messages.check failed ({exc}); retrying in 3s")
            await asyncio.sleep(3)
            continue

        # Extract raw text exactly like working monitors
        raw = _extract_text(result)
        if not raw:
            continue

        if "WAIT TIMEOUT" in raw:
            continue

        # Generate message ID from content
        mid = _message_id(raw)
        if mid in seen_ids:
            continue

        # Extract sender handle
        author, sender_handle = _extract_sender(raw, DIRECTOR_HANDLE)

        # Check if this is from the agent we're waiting for
        sender_normalized = sender_handle.lower().lstrip("@")
        if sender_normalized != normalized_agent:
            continue

        # Check if message mentions @director
        if DIRECTOR_HANDLE.lower() not in raw.lower():
            continue

        seen_ids.add(mid)
        print(f"✅ Received {agent_handle}'s reply")
        preview = textwrap.shorten(raw.replace("\n", " "), width=120)
        print(f"   {preview}")
        return AgentResponse(handle=agent_handle, message_id=mid, text=raw)

    print(f"⏱️ Timeout: no reply from {agent_handle} within {overall_timeout}s")
    return None


def build_prompt(
    agent: str,
    index: int,
    total: int,
    question: str,
    tag: str,
    previous: Optional[AgentResponse],
) -> str:
    lines: List[str] = [agent.strip(), ""]
    lines.append(f"🎯 PM-001 Step {index + 1}/{total}: {question}")
    lines.append("")

    if previous:
        snippet = textwrap.shorten(previous.text.replace("\n", " "), width=140)
        lines.append(
            f"Recap: {previous.handle} replied → {snippet}"
        )
        lines.append("")

    lines.extend(
        [
            "Please respond in the format: [YES/NO] [Confidence %] [Reasoning]",
            "Make sure your first line starts with '@director [YES/NO] [Confidence %]'",
            "Do not mention other agents unless @director instructs you to.",
            "Keep it under 150 words and cite any data points.",
            "",
            tag,
        ]
    )

    return "\n".join(lines).strip() + "\n"


async def run_round_robin(args: argparse.Namespace) -> None:
    agents = [_normalize_handle(h) for h in args.agents]
    agents = [h for h in agents if h]
    if not agents:
        raise ValueError("No valid agent handles supplied")

    client = MCPClient.from_config_file(args.config)
    await client.create_all_sessions()

    server_name = list(client.config.get("mcpServers", {}).keys())[0]
    session = client.get_session(server_name)

    seen_ids: set[str] = set()
    responses: List[AgentResponse] = []

    print(f"🔌 Connected via {args.config}; orchestrating {len(agents)} agent(s)\n")

    for idx, handle in enumerate(agents):
        previous = responses[-1] if responses else None
        message = build_prompt(handle, idx, len(agents), args.question, args.tag, previous)

        print(f"📤 Prompting {handle} (step {idx + 1}/{len(agents)})...")
        await session.call_tool(
            "messages",
            arguments={
                "action": "send",
                "content": message,
                "idempotency_key": f"round-robin-{idx}-{int(time.time()*1000)}",
            },
        )

        reply = await wait_for_agent_reply(
            session,
            handle,
            seen_ids,
            wait_timeout=args.wait_timeout,
            overall_timeout=args.max_wait,
        )

        if reply:
            responses.append(reply)
        else:
            print(f"⚠️  Skipping {handle}; no reply captured\n")

    if responses:
        print("\n🧾 Summary of captured replies:")
        for resp in responses:
            preview = textwrap.shorten(resp.text.replace("\n", " "), width=160)
            print(f" - {resp.handle}: {preview}")
    else:
        print("\n⚠️  No agent replies were captured.")

    await client.close_all_sessions()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Round-robin prediction market director")
    parser.add_argument(
        "--agents",
        nargs="+",
        required=True,
        help="Agent handles in the order they should respond (e.g. @cbms @jwt @Aurora)",
    )
    parser.add_argument(
        "--question",
        default="Will S&P 500 close above 6000 today?",
        help="Prediction market question to post",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="Hashtag/topic to append to each director message",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="Director MCP config file (defaults to configs/mcp_config_director.json)",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=25,
        help="Seconds to wait per messages.check call",
    )
    parser.add_argument(
        "--max-wait",
        type=int,
        default=300,
        help="Maximum seconds to wait for each agent before moving on",
    )
    return parser.parse_args()


async def _amain() -> None:
    args = parse_args()
    await run_round_robin(args)


if __name__ == "__main__":
    asyncio.run(_amain())
