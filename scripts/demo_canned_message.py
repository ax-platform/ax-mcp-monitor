#!/usr/bin/env python3
"""Send short, pre-scripted banking demo messages via mcp-use.

Run this script with one of the registered steps to drop a specific turn in the
demo conversation. Each step is tied to a default MCP config (alerts, HaloScript,
or Grok) and mentions only the intended recipient so the flow stays orderly.

Examples
========

    # Kick off the scenario from @alerts to @HaloScript
    ./scripts/demo_canned_message.py alert-kickoff

    # HaloScript loops in Grok
    ./scripts/demo_canned_message.py halo-hand-off

    # Grok reports back to HaloScript
    ./scripts/demo_canned_message.py grok-status

    # HaloScript closes the loop with @alerts
    ./scripts/demo_canned_message.py halo-closeout

Use --dry-run to preview a message without sending it, or --config/--target to
override the defaults if needed.
"""

from __future__ import annotations

import argparse
import asyncio
import textwrap
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from mcp_use import MCPClient


def _pick_server_name(client: MCPClient) -> str:
    servers = list(client.config.get("mcpServers", {}).keys())
    if not servers:
        raise RuntimeError("Config does not define any MCP servers")
    return servers[0]


async def _send_message(config_path: str, content: str, *, idempotency_key: str) -> None:
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = _pick_server_name(client)
    session = client.get_session(server_name)
    try:
        payload = {
            "action": "send",
            "content": content,
            "idempotency_key": idempotency_key,
        }
        await session.call_tool("messages", payload)
    finally:
        await client.close_all_sessions()


def _normalise_handle(handle: str) -> str:
    return handle if handle.startswith("@") else f"@{handle}"


@dataclass(frozen=True)
class DemoStep:
    name: str
    description: str
    default_config: str
    default_target: str
    builder: Callable[[str], str]

    def render(self, target: str) -> str:
        return self.builder(_normalise_handle(target))


def _alert_kickoff_message(target: str) -> str:
    return textwrap.dedent(
        f"""
        {target} Heads-up: demo drill in progress. Horizon flagged a $4,870 Lisbon tap
        on Priya Menon's Platinum card. Treat it like a live case, keep comms in sim
        mode, and let me know when you're ready to pull in your wingmate for a second
        look.
        """
    ).strip()


def _halo_hand_off_message(target: str) -> str:
    return textwrap.dedent(
        f"""
        {target} I just reviewed the LIS tap from Priya's card. I'm leaning toward
        watch-mode—velocity spike but the concierge partner checks out. Can you run
        your network + geo sanity pass and confirm this still feels legit?
        """
    ).strip()


def _grok_status_message(target: str) -> str:
    return textwrap.dedent(
        f"""
        {target} Velocity + network look clean. Lisbon lines up with Priya's premium
        travel profile and concierge programs. Call is yours, but I'd stay in watch
        mode and log the drill for the observers.
        """
    ).strip()


def _halo_closeout_message(target: str) -> str:
    return textwrap.dedent(
        f"""
        {target} Grok validated the pattern, so I'm locking this sim as a green
        travel case. Logging the note in the demo channel and standing by for the
        next drill.
        """
    ).strip()


STEPS: Dict[str, DemoStep] = {
    "alert-kickoff": DemoStep(
        name="alert-kickoff",
        description="Send the initial fraud drill from @alerts to HaloScript",
        default_config="configs/mcp_config_alerts.json",
        default_target="@HaloScript",
        builder=_alert_kickoff_message,
    ),
    "halo-hand-off": DemoStep(
        name="halo-hand-off",
        description="Have HaloScript loop in the Grok agent",
        default_config="configs/mcp_config_halo_script.json",
        default_target="@open_router_grok4_fast",
        builder=_halo_hand_off_message,
    ),
    "grok-status": DemoStep(
        name="grok-status",
        description="Share Grok's verdict back to HaloScript",
        default_config="configs/mcp_config_grok4.json",
        default_target="@HaloScript",
        builder=_grok_status_message,
    ),
    "halo-closeout": DemoStep(
        name="halo-closeout",
        description="Let HaloScript close the loop with alerts",
        default_config="configs/mcp_config_halo_script.json",
        default_target="@alerts",
        builder=_halo_closeout_message,
    ),
}


def _list_steps() -> str:
    lines = ["Available steps:"]
    for step in STEPS.values():
        lines.append(f"  - {step.name}: {step.description}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a canned banking demo message",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_list_steps(),
    )
    parser.add_argument("step", choices=STEPS.keys(), help="Which canned turn to send")
    parser.add_argument("--config", dest="config", help="Override MCP config path for this step")
    parser.add_argument("--target", dest="target", help="Override mention handle for this step")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending it")
    args = parser.parse_args()

    step = STEPS[args.step]
    config_path = args.config or step.default_config
    target_handle = args.target or step.default_target

    try:
        message = step.render(target_handle)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Failed to build message: {exc}")
        return 1

    if args.dry_run:
        print("--- Dry run ---")
        print(f"Config : {config_path}")
        print(f"Target : {_normalise_handle(target_handle)}")
        print("Message:\n" + message)
        return 0

    idem_key = f"demo-canned-{step.name}-{uuid.uuid4().hex[:8]}"

    try:
        asyncio.run(
            _send_message(
                config_path=config_path,
                content=message,
                idempotency_key=idem_key,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Failed to send message: {exc}")
        return 1

    print(f"✅ Sent '{step.name}' as {_normalise_handle(target_handle)} target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

