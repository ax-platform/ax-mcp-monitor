#!/usr/bin/env python3
"""Inject a staged fraud-alert message into aX using mcp-use.

This helper lets us pre-seed the banking demo with a realistic alert that
mentions the featured agents, highlights that the scenario is a drill, and
gives everyone clear objectives. Point it at whichever MCP config you need
(`dock` vs. `gcp`) and the message will land in the corresponding space.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from mcp_use import MCPClient


SUPPORT_PLAYBOOK = (
    "run network + velocity checks to decide if the pattern matches the "
    "customer's usual travel footprint.",
    "draft the customer-facing update that reassures them this drill caught the "
    "event early and outlines next steps.",
    "coordinate with compliance so the drill is logged and all sign-offs land in "
    "the control tower.",
)


def _pick_server_name(client: MCPClient) -> str:
    servers = list(client.config.get("mcpServers", {}).keys())
    if not servers:
        raise RuntimeError("Config does not define any MCP servers")
    return servers[0]


def _display_handle(handle: str, *, mention: bool) -> str:
    target = handle if handle.startswith("@") else f"@{handle}"
    return target if mention else target.lstrip("@")


def _format_support(handles: Sequence[str]) -> str:
    cleaned = [_display_handle(handle, mention=False) for handle in handles]
    return ", ".join(cleaned) if cleaned else "—"


def _build_objectives(primary: str, support: Sequence[str]) -> list[str]:
    objectives = [
        f"1. {primary} — orchestrate the response, confirm cardholder contact, and call the freeze vs. watch decision.",
    ]
    for idx, handle in enumerate(support, start=2):
        template_idx = (idx - 2) % len(SUPPORT_PLAYBOOK)
        detail = SUPPORT_PLAYBOOK[template_idx]
        display = _display_handle(handle, mention=False)
        objectives.append(f"{idx}. {display} — {detail}")

    objectives.append(
        f"{len(objectives) + 1}. Everyone — jot findings in `#fraud-demo` and reply with `demo-control: resolve` when the scenario wraps."
    )
    return objectives


def _build_message(
    primary: str,
    support: Sequence[str],
    *,
    alert_code: str,
    merchant: str,
    location: str,
    amount: str,
    channel: str,
    cardholder: str,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    support_line = _format_support(support)
    objective_lines = _build_objectives(primary, support)

    mention_line = primary

    lines = [
        mention_line,
        f"🚨 **Demo Fraud Escalation** — Scenario {alert_code}",
        "*Training drill for tomorrow's banking showcase. This is staged data; treat it like the real thing but keep customer comms in demo mode.*",
        "",
        f"Primary responder: {primary}",
        f"Wing team: {support_line}",
        "",
        "**Trigger Snapshot**",
        f"- Timestamp: {timestamp}",
        f"- Merchant: {merchant}",
        f"- Location: {location}",
        f"- Amount: ${amount}",
        f"- Channel: {channel}",
        f"- Customer: {cardholder}",
        "",
        "**Objectives**",
        *objective_lines,
        "",
        "✅ Demo reminder: mention the partners directly so the observers can watch the hand-off choreography.",
    ]

    # Unpack the objective lines into the main message list while keeping order.
    message_lines: list[str] = []
    for item in lines:
        if isinstance(item, list):
            message_lines.extend(item)
        else:
            message_lines.append(item)

    return "\n".join(message_lines).strip()


async def _send_demo_alert(
    config_path: str,
    message: str,
    *,
    dry_run: bool,
    idempotency_key: str,
) -> None:
    if dry_run:
        print("--- Dry run ---")
        print(message)
        return

    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = _pick_server_name(client)
    session = client.get_session(server_name)

    try:
        print(f"✅ Connected to {server_name}; sending demo alert")
        payload = {
            "action": "send",
            "content": message,
            "idempotency_key": idempotency_key,
        }
        await session.call_tool("messages", payload)
        print("🚀 Demo alert dispatched")
    finally:
        await client.close_all_sessions()


def _normalise_handles(handles: Iterable[str]) -> list[str]:
    seen = []
    for handle in handles:
        cleaned = handle.strip()
        if not cleaned:
            continue
        if not cleaned.startswith("@"):
            cleaned = f"@{cleaned}"
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the aX space with a demo fraud alert")
    parser.add_argument("--config", required=True, help="Path to the MCP config for the target space")
    parser.add_argument("--primary", default="@cbms", help="Lead agent handle for the alert")
    parser.add_argument(
        "--support",
        nargs="*",
        default=("@HaloScript", "@coord_codex"),
        help="Support agent handles to mention",
    )
    parser.add_argument("--merchant", default="SkyTrail Travel Concierge", help="Merchant to spotlight")
    parser.add_argument("--location", default="Lisbon International Airport (LIS)")
    parser.add_argument("--amount", default="4,870.00")
    parser.add_argument("--channel", default="Tap-to-pay (contactless)")
    parser.add_argument("--cardholder", default="Priya Menon — Platinum Horizon Card ****7331")
    parser.add_argument("--alert-code", default=None, help="Optional override for the scenario code")
    parser.add_argument("--dry-run", action="store_true", help="Print the message without sending")
    args = parser.parse_args(argv)

    primary = args.primary if args.primary.startswith("@") else f"@{args.primary}"
    support = _normalise_handles(args.support)

    alert_code = args.alert_code or f"FAL-{uuid.uuid4().hex[:4].upper()}"
    message = _build_message(
        primary,
        support,
        alert_code=alert_code,
        merchant=args.merchant,
        location=args.location,
        amount=args.amount,
        channel=args.channel,
        cardholder=args.cardholder,
    )

    idem_key = f"fraud-demo-{alert_code.lower()}"

    try:
        asyncio.run(
            _send_demo_alert(
                config_path=args.config,
                message=message,
                dry_run=args.dry_run,
                idempotency_key=idem_key,
            )
        )
    except KeyboardInterrupt:
        print("\n👋 Cancelled")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Failed to inject demo message: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
