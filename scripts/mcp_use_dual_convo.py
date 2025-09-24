#!/usr/bin/env python3
"""Driver that nudges two MCP agents into a long-running collaboration.

The script alternates mentions between two agent handles (e.g., @jwt and
@cbms), feeding structured prompts that push them through planning and build
phases. Each prompt is sent with ``messages.send`` via the ``mcp-use`` client so
the agents can respond naturally through their monitors.

Usage example::

    uv run scripts/mcp_use_dual_convo.py \
        --config configs/mcp_config_jwt_local.json \
        --agent-a @jwt --agent-b @cbms \
        --planning-turns 50 --build-turns 100 \
        --fast-interval 5 --slow-interval 600 \
        --log conversation_log.md

The config only needs to contain one MCP server definition; requests are
routed through that connection regardless of which agent handle we mention.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import random
from pathlib import Path
from typing import Iterable, List, Optional

from mcp_use import MCPClient


async def _call_messages_with_retry(
    session,
    payload,
    *,
    retries: int = 3,
    base_delay: float = 1.0,
) -> bool:
    """Send a messages.* request with simple retry/backoff."""

    for attempt in range(retries):
        try:
            await session.call_tool("messages", payload)
            return True
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"❌ call failed after {retries} attempts: {exc}")
                return False
            delay = base_delay * (2 ** attempt)
            print(f"⚠️ call failed ({exc}); retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
    return False


def _build_prompts(
    planning_turns: int,
    build_turns: int,
    agent_a: str,
    agent_b: str,
) -> List[str]:
    """Generate structured prompts for planning and build phases."""

    planning_topics = [
        "collaboration charter",
        "language mission statement",
        "core design principles",
        "agent-to-agent messaging syntax",
        "type system goals",
        "concurrency model",
        "error-handling philosophy",
        "standard library footprint",
        "deployment storyboard",
        "testing strategy",
    ]

    build_topics = [
        "function declaration syntax",
        "module packaging",
        "capability negotiation",
        "async workflow example",
        "static vs dynamic typing trade-offs",
        "state persistence",
        "tool invocation DSL",
        "security sandboxing",
        "observability hooks",
        "migration from existing languages",
        "sample REPL transcript",
        "compiler pipeline sketch",
        "runtime scheduling diagram",
        "bytecode or IR concept",
        "ecosystem roadmap",
    ]

    planning_prompts: List[str] = []
    for i in range(planning_turns):
        topic = planning_topics[i % len(planning_topics)]
        template = (
            "Phase 1 Planning #{idx}: Chart the {topic}. Work with {peer} to "
            "capture assumptions, constraints, and success metrics; conclude "
            "with explicit next actions."
        )
        peer = agent_b if i % 2 == 0 else agent_a
        planning_prompts.append(template.format(idx=i + 1, topic=topic, peer=peer))

    build_prompts: List[str] = []
    for i in range(build_turns):
        topic = build_topics[i % len(build_topics)]
        template = (
            "Phase 2 Build #{idx}: Produce tangible artefacts for {topic}. "
            "Collaborate with {peer}; embed code snippets, #milestone tags, "
            "and clear review questions before handing off."
        )
        peer = agent_b if (planning_turns + i) % 2 == 0 else agent_a
        build_prompts.append(template.format(idx=i + 1, topic=topic, peer=peer))

    return planning_prompts + build_prompts


async def run_driver(args: argparse.Namespace) -> None:
    client = MCPClient.from_config_file(args.config)
    await client.create_all_sessions()
    server_name = next(iter(client.config.get("mcpServers", {})))
    session = client.get_session(server_name)

    print(f"✅ Conversation driver connected (server: {server_name})")

    prompts = _build_prompts(
        planning_turns=args.planning_turns,
        build_turns=args.build_turns,
        agent_a=args.agent_a,
        agent_b=args.agent_b,
    )

    handles = [args.agent_a, args.agent_b]
    log_path: Optional[Path] = Path(args.log).expanduser() if args.log else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# Dual-agent conversation prompts\n\n", encoding="utf-8")

    for idx, prompt in enumerate(prompts, start=1):
        handle = handles[(idx - 1) % 2]
        content = f"{handle} {prompt}"
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
        print(f"\n📤 Turn {idx}/{len(prompts)} → {handle}: {prompt}")

        if not await _call_messages_with_retry(
            session,
            {
                "action": "send",
                "content": content,
                "idempotency_key": f"dual-convo-{idx}-{random.randint(1000, 9999)}",
            },
        ):
            print("❌ Failed to dispatch prompt; aborting conversation driver")
            break

        if log_path:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"- {timestamp} :: {content}\n")

        interval = args.fast_interval if idx <= args.fast_turns else args.slow_interval
        if interval > 0 and idx < len(prompts):
            await asyncio.sleep(interval)

    await client.close_all_sessions()
    print("\n🏁 Conversation driver finished")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alternate prompts between two MCP agents")
    parser.add_argument("--config", required=True, help="Path to MCP config JSON")
    parser.add_argument("--agent-a", required=True, help="First agent handle (e.g., @jwt)")
    parser.add_argument("--agent-b", required=True, help="Second agent handle (e.g., @cbms)")
    parser.add_argument("--planning-turns", type=int, default=50)
    parser.add_argument("--build-turns", type=int, default=100)
    parser.add_argument("--fast-turns", type=int, default=20, help="# of turns to run at fast interval")
    parser.add_argument("--fast-interval", type=float, default=5.0, help="Seconds between early prompts")
    parser.add_argument("--slow-interval", type=float, default=600.0, help="Seconds between later prompts")
    parser.add_argument("--log", help="Optional path to append prompt log")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run_driver(args))
    except KeyboardInterrupt:
        print("\n👋 Conversation driver interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
