#!/usr/bin/env python3
"""Simple two-agent ping-pong orchestrator for the fraud alert demo."""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_use import MCPClient  # type: ignore


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


async def wait_for_reply(
    session,
    agent_handle: str,
    seen_ids: set[str],
    wait: int,
    overall_timeout: int,
    required_tag: Optional[str] = None,
) -> Optional[str]:
    deadline = time.monotonic() + overall_timeout
    normalized = agent_handle.lower().lstrip("@")

    while time.monotonic() < deadline:
        try:
            result = await session.call_tool(
                "messages",
                arguments={
                    "action": "check",
                    "wait": True,
                    "wait_mode": "mentions",
                    "timeout": wait,
                    "limit": 10,
                },
            )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ messages.check failed ({exc}); retrying in 3s")
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
        author, sender_handle = _extract_sender(raw, agent_handle)

        # Check if this is from the agent we're waiting for
        sender_normalized = sender_handle.lower().lstrip("@")
        if sender_normalized != normalized:
            continue

        # Check required tag if specified
        if required_tag and required_tag.lower() not in raw.lower():
            continue

        seen_ids.add(mid)
        print(f"✅ {agent_handle} replied")
        preview = textwrap.shorten(raw.replace("\n", " "), width=140)
        print(f"   {preview}")
        return raw

    print(f"⏱️ Timeout: no reply from {agent_handle} within {overall_timeout}s")
    return None


async def _UNUSED_wait_for_reply_OLD(
    session,
    agent_handle: str,
    seen_ids: set[str],
    wait: int,
    overall_timeout: int,
    required_tag: Optional[str] = None,
) -> Optional[str]:
    """OLD VERSION - kept for reference"""
    deadline = time.monotonic() + overall_timeout
    normalized = agent_handle.lower()

    while time.monotonic() < deadline:
        try:
            result = await session.call_tool(
                "messages",
                arguments={
                    "action": "check",
                    "wait": True,
                    "wait_mode": "mentions",
                    "timeout": wait,
                    "limit": 10,
                },
            )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ messages.check failed ({exc}); retrying in 3s")
            await asyncio.sleep(3)
            continue

        # As a fallback, perform a quick non-waiting poll in case the mention mode missed it
        try:
            result_latest = await session.call_tool(
                "messages",
                arguments={
                    "action": "check",
                    "mode": "latest",
                    "limit": 10,
                    "mark_read": False,
                },
            )
            for message in _extract_messages(result_latest):
                msg_id = message.get("id") or f"auto-latest-{hash(tuple(message.items()))}"
                author = (message.get("author") or "").lower()
                text = message.get("text") or ""
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
                if author in {normalized, normalized.lstrip("@")}:
                    if required_tag and required_tag.lower() not in text.lower():
                        continue
                    print(f"✅ {agent_handle} replied")
                    preview = textwrap.shorten(text.replace("\n", " "), width=140)
                    print(f"   {preview}")
                    return text
        except Exception:
            pass

    print(f"⏱️ Timeout waiting for {agent_handle}")
    return None


def build_first_message(agent_a: str, agent_b: str, tag: str) -> str:
    teammate = agent_b.lstrip("@")
    return textwrap.dedent(
        f"""{agent_a}

🚨 **Demo Fraud Escalation** — Scenario FAL-DEMO-001

Primary responder: {agent_a}
Wing teammate: {teammate}

**CRITICAL: Start your reply with @{teammate} NOT @alerts**

Checklist for your reply:
- Triage Priya Menon's $4,870 LIS contactless charge (SkyTrail concierge).
- Decide whether it smells like legit travel or fraud noise; cite at least one data point.
- Hand off by starting your reply with the literal handle @{teammate} (spell it exactly so they get paged).
- Do NOT mention @alerts in your reply. Only message @{teammate}.
- Keep it under 150 words.

Client Snapshot:
- Card: Platinum Horizon ****7331
- Location: Lisbon International Airport (LIS)
- Channel: Tap-to-pay (contactless)

{tag}
"""
    ).strip()


def build_second_message(agent_b: str, agent_a: str, tag: str, recap: str, final_round: bool) -> str:
    snippet = textwrap.shorten(recap.replace("\n", " "), width=180)
    teammate = agent_a.lstrip("@")
    if final_round:
        guidance_lines = [
            "This is the final round. Start your reply with @alerts to close the drill.",
            f"Do NOT mention {teammate} again—let the loop stop cleanly.",
        ]
    else:
        guidance_lines = [
            f"**CRITICAL: Start your reply with @{teammate} NOT @alerts**",
            f"Message ONLY @{teammate} to continue the handoff.",
        ]
    guidance = "\n".join(f"- {line}" for line in guidance_lines)
    return textwrap.dedent(
        f"""{agent_b}

Recap from {agent_a}: {snippet}

Guidelines for your reply:
- Call the play: keep watch-mode or escalate. Reference at least one stat from their analysis.
{guidance}
- Keep it demo-tight (<150 words) so observers follow the flow.

{tag}
"""
    ).strip()


async def orchestrate(args: argparse.Namespace) -> None:
    client = MCPClient.from_config_file(args.config)
    await client.create_all_sessions()
    server_name = list(client.config.get("mcpServers", {}).keys())[0]
    session = client.get_session(server_name)

    seen_ids: set[str] = set()

    print(f"📤 Sending alert to {args.agent_a}")
    await session.call_tool(
        "messages",
        arguments={
            "action": "send",
            "content": build_first_message(args.agent_a, args.agent_b, args.tag),
            "idempotency_key": f"pingpong-a-{int(time.time()*1000)}",
        },
    )

    reply_a = await wait_for_reply(
        session,
        args.agent_a,
        seen_ids,
        wait=args.wait_timeout,
        overall_timeout=args.max_wait,
        required_tag=None,
    )

    if not reply_a:
        await client.close_all_sessions()
        return

    print(f"\n📤 Handing off to {args.agent_b}")
    await session.call_tool(
        "messages",
        arguments={
            "action": "send",
            "content": build_second_message(args.agent_b, args.agent_a, args.tag, reply_a),
            "idempotency_key": f"pingpong-b-{int(time.time()*1000)}",
        },
    )

    await wait_for_reply(
        session,
        args.agent_b,
        seen_ids,
        wait=args.wait_timeout,
        overall_timeout=args.max_wait,
        required_tag="@alerts",
    )

    await client.close_all_sessions()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-agent fraud alert ping-pong orchestrator")
    parser.add_argument("--config", default="configs/mcp_config_alerts.json")
    parser.add_argument("--agent-a", default="@open_router_grok4_fast")
    parser.add_argument("--agent-b", default="@HaloScript")
    parser.add_argument("--tag", default="#client-fraud-demo")
    parser.add_argument("--wait-timeout", type=int, default=25)
    parser.add_argument("--max-wait", type=int, default=300)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(orchestrate(args))
