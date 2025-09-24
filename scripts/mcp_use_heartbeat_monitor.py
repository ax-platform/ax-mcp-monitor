"""Heartbeat-based MCP monitor with optional LangGraph responses.

This script keeps a reliable long-poll connection alive using the ``mcp-use``
client (heartbeat pings, stall detection, automatic reconnection) and now
supports routing each mention through a LangGraph workflow powered by the
LangChain MCP adapter.  When the LangGraph plugin is enabled the monitor can
call remote MCP tools (e.g., filesystem, web search) while answering with
OpenRouter ``x-ai/grok-4-fast:free`` or other configured models.
"""

from __future__ import annotations

# Initializing AI Monitor (shell script shows ASCII art)

import argparse
import asyncio
import hashlib
import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from mcp_use import MCPClient

# Ensure project root is importable when running from scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ax_mcp_wait_client.config_loader import parse_all_mcp_servers
from mcp_tool_manager import MCPToolManager
from plugins.base_plugin import BasePlugin

# Components loaded

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
for noisy_logger, level in (
    ('httpx', logging.WARNING),
    ('mcp', logging.CRITICAL),
    ('mcp.client', logging.CRITICAL),
    ('mcp.client.streamable_http', logging.CRITICAL),
    ('pydantic', logging.CRITICAL),
    ('pydantic_core', logging.CRITICAL),
):
    logging.getLogger(noisy_logger).setLevel(level)

DEFAULT_WAIT_TIMEOUT = 35  # seconds — below the proxy timeout
# Heartbeat system removed - using welcome screen instead
MAX_BACKOFF_RETRIES = 3
STALL_THRESHOLD = 120  # seconds without mention or heartbeat => reconnect


def _load_server_name(client: MCPClient) -> str:
    servers = list(client.config.get("mcpServers", {}).keys())
    if not servers:
        raise RuntimeError("No servers defined in MCP configuration")
    return servers[0]


def _resolve_agent_handle(server_cfg: dict) -> Optional[str]:
    name = (server_cfg.get("agent") or {}).get("name")
    if name:
        return name
    env_block = server_cfg.get("env") or {}
    if "X-Agent-Name" in env_block:
        return env_block["X-Agent-Name"]
    args = server_cfg.get("args") or []
    for idx, arg in enumerate(args):
        if str(arg).lower() == "--header" and idx + 1 < len(args):
            header = str(args[idx + 1])
            if header.lower().startswith("x-agent-name:"):
                return header.split(":", 1)[1].strip()
    return None


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
            author = author.lstrip("•- \t")
            handles = [token for token in author.split() if token.startswith("@")]
            handles += [token for token in body.split() if token.startswith("@")]
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


def _load_plugin(plugin_type: str, plugin_config: Optional[dict]) -> BasePlugin:
    module_name = f"plugins.{plugin_type}_plugin"
    module = importlib.import_module(module_name)
    class_name = "".join(word.capitalize() for word in plugin_type.split("_")) + "Plugin"
    plugin_class = getattr(module, class_name)
    return plugin_class(plugin_config or {})


def _read_plugin_config(path: Optional[str]) -> dict:
    if not path:
        return {}
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"Plugin config not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _allowed_directories(server_configs) -> list[str]:
    roots: set[str] = set()
    for cfg in server_configs.values():
        raw = getattr(cfg, "raw_config", {}) or {}
        command = str(raw.get("command", ""))
        args = raw.get("args") or []
        if "server-filesystem" in command or any("server-filesystem" in str(arg) for arg in args):
            for arg in reversed(args):
                if isinstance(arg, str) and arg.startswith("/"):
                    roots.add(arg)
                    break
    return sorted(roots)


def _extract_message_text(raw: str) -> str:
    """Return the human-authored content from a mention block."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    cleaned = [line for line in lines if not line.startswith("✅ WAIT SUCCESS")]
    for line in cleaned:
        if line.startswith("•") or line.startswith("-"):
            body = line.lstrip("•- \t")
            if ":" in body:
                _, tail = body.split(":", 1)
                return tail.strip()
            return body.strip()
    return raw.strip()


async def _call_messages_with_retry(
    session,
    payload,
    retries: int = MAX_BACKOFF_RETRIES,
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

async def monitor_loop(
    config_path: str,
    stall_threshold: int,
    plugin_type: str,
    plugin_config_path: Optional[str] = None,
    wait_timeout: int = DEFAULT_WAIT_TIMEOUT,
) -> None:
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()
    server_name = _load_server_name(client)
    session = client.get_session(server_name)

    raw_server_cfg = client.config.get("mcpServers", {}).get(server_name, {})
    resolved = _resolve_agent_handle(raw_server_cfg) or "agent"
    if not resolved.startswith("@"):
        resolved = f"@{resolved}"
    agent_name = resolved

    # Show connected status
    startup_time = datetime.now().strftime("%H:%M:%S")
    print(f"✅ Connected as {agent_name} (server: {server_name}) at {startup_time}")
    print("👂 Monitoring for mentions...")

    # Load MCP configs for optional tool manager / LangGraph integration
    plugin: Optional[BasePlugin] = None
    tool_manager: Optional[MCPToolManager] = None
    allowed_dirs: list[str] = []

    try:
        server_configs = parse_all_mcp_servers(config_path)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Failed to parse MCP config for tool loading: {exc}")
        server_configs = {}

    if server_configs:
        primary_name = next(iter(server_configs.keys()))
        if len(server_configs) > 1:
            try:
                tool_manager = MCPToolManager(server_configs, primary_server=primary_name)
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Failed to initialize MCP tool manager: {exc}")
                tool_manager = None
        allowed_dirs = _allowed_directories(server_configs)

    plugin_enabled = plugin_type not in {"", "none", "ack", "Ack", "ACK"}
    if plugin_enabled:
        config_source = plugin_config_path or os.getenv("PLUGIN_CONFIG")
        plugin_config = {}
        if config_source:
            try:
                plugin_config = _read_plugin_config(config_source)
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ Failed to load plugin config '{config_source}': {exc}")
        try:
            plugin = _load_plugin(plugin_type, plugin_config)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Failed to load plugin '{plugin_type}': {exc}")
            plugin_enabled = False
            plugin = None

    if plugin:
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        plugin.attach_monitor_context(
            {
                "current_date": current_date,
                "allowed_directories": allowed_dirs,
            }
        )
        if tool_manager:
            plugin.set_tool_manager(tool_manager)

    seen_ids: set[str] = set()

    last_activity = time.time()

    def console_print(*args, **kwargs) -> None:
        print(*args, **kwargs)

    # Welcome screen already shown above

    # No heartbeat needed - just monitoring

    try:
        while True:
            if time.time() - last_activity > stall_threshold:
                console_print("⚠️ Detected stall; attempting reconnect")
                await client.close_all_sessions()
                await client.create_all_sessions()
                session = client.get_session(server_name)
                last_activity = time.time()
                continue

            payload = {
                "action": "check",
                "wait": True,
                "wait_mode": "mentions",
                "timeout": wait_timeout,
                "limit": 5,
            }
            result = await _call_messages_with_retry(
                session,
                payload,
                retries=1,
                allow_504=True,
                suppress_errors=True,
            )
            if result is None:
                continue
            raw = _extract_text(result)
            if not raw:
                continue
            if "WAIT TIMEOUT" in raw:
                continue
            mid = _message_id(raw)
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            last_activity = time.time()

            # Process mention silently - no "Incoming mention block" message
            author, sender = _extract_sender(raw, agent_name)
            if sender.lower() == "@unknown":
                console_print("ℹ️ No valid mention detected; skipping response")
                continue

            response_text: Optional[str] = None

            if plugin_enabled and plugin:
                message_text = _extract_message_text(raw)
                metadata = {
                    "sender": sender,
                    "agent_name": agent_name,
                    "ignore_mentions": [agent_name],
                }
                try:
                    response_text = await plugin.process_message(message_text, metadata)
                except Exception as exc:  # noqa: BLE001
                    console_print(f"⚠️ Plugin processing failed: {exc}")
                    response_text = None

            if not response_text:
                response_text = _build_ack(sender, mid[:8])
                console_print(f"💬 Acknowledging {sender} (author: {author}) with {mid[:8]}")
            else:
                console_print("📝 Streaming reply:")
                # Show first line of response if it's multiline
                first_line = response_text.split('\n')[0]
                if len(first_line) > 80:
                    first_line = first_line[:77] + "..."
                console_print(first_line)

            sent = await _call_messages_with_retry(
                session,
                {
                    "action": "send",
                    "content": response_text,
                    "idempotency_key": mid,
                },
                retries=1,
            )
            if sent is not None:
                console_print("✅ Response dispatched")
            else:
                console_print(f"❌ Response send failed for {mid[:8]}")
    except asyncio.CancelledError:
        pass
    finally:
        await client.close_all_sessions()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MCP-use heartbeat monitor")
    parser.add_argument("--config", required=True)
    parser.add_argument("--stall-threshold", type=int, default=STALL_THRESHOLD)
    parser.add_argument(
        "--plugin",
        default=os.getenv("PLUGIN_TYPE", "ack"),
        help="Optional plugin name (e.g., langgraph, echo). Use 'ack' to send simple acknowledgements.",
    )
    parser.add_argument(
        "--plugin-config",
        default=None,
        help="Path to plugin configuration JSON (overrides PLUGIN_CONFIG).",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=DEFAULT_WAIT_TIMEOUT,
        help="Timeout (seconds) for messages.check long polls",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(
            monitor_loop(
                args.config,
                args.stall_threshold,
                args.plugin,
                args.plugin_config,
                args.wait_timeout,
            )
        )
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
