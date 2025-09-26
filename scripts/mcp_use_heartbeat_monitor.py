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
import sqlite3
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from mcp_use import MCPClient

# Ensure project root is importable when running from scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ax_mcp_wait_client.config_loader import parse_all_mcp_servers
from mcp_tool_manager import MCPToolManager
from plugins.base_plugin import BasePlugin

# Components loaded

# Message storage classes (borrowed from reliable_monitor.py)
class MessageStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class StoredMessage:
    id: str
    raw_content: str
    parsed_author: Optional[str]
    parsed_mention: Optional[str]
    sender_handle: Optional[str]
    status: str
    created_at: str
    processed_at: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None

class MessageStore:
    """Simple SQLite-based message store for heartbeat monitor"""

    def __init__(self, db_path: str = "messages.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    raw_content TEXT NOT NULL,
                    parsed_author TEXT,
                    parsed_mention TEXT,
                    sender_handle TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON messages(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at)")
            conn.commit()
        finally:
            conn.close()

    def store_message(self, message: StoredMessage) -> bool:
        """Store message with basic guarantee"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO messages
                (id, raw_content, parsed_author, parsed_mention, sender_handle,
                 status, created_at, processed_at, retry_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.id, message.raw_content, message.parsed_author,
                message.parsed_mention, message.sender_handle, message.status,
                message.created_at, message.processed_at, message.retry_count,
                message.error_message
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"⚠️ Failed to store message: {e}")
            return False
        finally:
            conn.close()

    def update_message_status(self, message_id: str, status: MessageStatus, error_message: Optional[str] = None):
        """Update message status"""
        conn = sqlite3.connect(self.db_path)
        try:
            processed_at = datetime.now(timezone.utc).isoformat() if status in [MessageStatus.COMPLETED, MessageStatus.FAILED] else None
            conn.execute("""
                UPDATE messages
                SET status = ?, processed_at = ?, error_message = ?
                WHERE id = ?
            """, (status.value, processed_at, error_message, message_id))
            conn.commit()
        except Exception as e:
            print(f"⚠️ Failed to update message status: {e}")
        finally:
            conn.close()

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
for noisy_logger, level in (
    ('httpx', logging.WARNING),
    ('mcp', logging.CRITICAL),
    ('mcp.client', logging.CRITICAL),
    ('mcp.client.streamable_http', logging.CRITICAL),
    ('pydantic', logging.CRITICAL),
    ('pydantic_core', logging.CRITICAL),
    ('mcp_use', logging.ERROR),
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


def _env_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _schema_from_args(args_schema: Any) -> Optional[dict[str, Any]]:
    if not args_schema:
        return None
    if isinstance(args_schema, dict):
        return args_schema
    if hasattr(args_schema, "model_dump"):
        try:
            dumped = args_schema.model_dump()  # type: ignore[attr-defined]
            if isinstance(dumped, dict) and dumped:
                return dumped
        except Exception:  # noqa: BLE001
            pass
    for attr in ("model_json_schema", "json_schema", "schema", "dict"):
        fn = getattr(args_schema, attr, None)
        if not fn:
            continue
        try:
            schema = fn()
        except TypeError:
            try:
                schema = fn(ref_template="{model}")
            except Exception:  # noqa: BLE001
                continue
        except Exception:  # noqa: BLE001
            continue
        if isinstance(schema, dict) and schema:
            return schema
    return None


def _format_field_type(spec: dict[str, Any]) -> str:
    if "type" in spec:
        if isinstance(spec["type"], list):
            return " | ".join(spec["type"])
        return str(spec["type"])
    if "anyOf" in spec:
        return " | ".join(
            part.get("type") or part.get("$ref", "unknown") for part in spec["anyOf"]
        )
    if "$ref" in spec:
        return spec["$ref"]
    return "unknown"


async def _print_tool_catalog(manager: MCPToolManager) -> None:
    try:
        tools = await manager.list_tools()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Unable to retrieve MCP tools: {exc}")
        return

    if not tools:
        print("⚠️ No MCP tools discovered during startup.")
        return

    print("🧰 MCP tool catalog (visible to agent):")
    for name, tool in sorted(tools.items()):
        description = (getattr(tool, "description", "") or "").strip()
        print(f" • {name}: {description}")
        args_schema = getattr(tool, "args_schema", None)
        schema = _schema_from_args(args_schema)
        if not schema:
            metadata = getattr(tool, "metadata", {}) or {}
            meta_block = metadata.get("_meta") if isinstance(metadata, dict) else {}
            if isinstance(meta_block, dict):
                schema = meta_block.get("inputSchema") or meta_block.get("parameters")
            if not schema and isinstance(metadata, dict):
                schema = metadata.get("inputSchema") or metadata.get("parameters")
            if schema and isinstance(schema, tuple):
                schema = schema[0]
        if schema and not isinstance(schema, dict):
            try:
                schema = dict(schema)
            except Exception:  # noqa: BLE001
                schema = None
        if not schema:
            debug_bits = [f"args_schema={type(args_schema).__name__}"]
            for attr in ("model_json_schema", "json_schema", "schema"):
                debug_bits.append(f"has_{attr}={hasattr(args_schema, attr)}")
            metadata = getattr(tool, "metadata", {}) or {}
            if metadata:
                try:
                    meta_preview = json.dumps(metadata, indent=2, ensure_ascii=False)
                except Exception:  # noqa: BLE001
                    meta_preview = str(metadata)
                print(f"   {{ }} (no parameter schema provided; metadata fallback available)")
                print(textwrap.indent(meta_preview, "     "))
            else:
                print("   { } (no parameter schema provided)")
            print(textwrap.indent("; ".join(debug_bits), "     "))
            continue

        properties = schema.get("properties") or {}
        required_fields = set(schema.get("required") or [])
        if not properties:
            formatted = json.dumps(schema, indent=2, ensure_ascii=False)
            print(textwrap.indent(formatted, "   "))
            continue

        for field, spec in properties.items():
            field_type = _format_field_type(spec)
            required_note = " (required)" if field in required_fields else ""
            description = spec.get("description") or ""
            line = f"   • {field}: {field_type}{required_note}"
            if description:
                line += f" - {description.strip()}"
            print(line)

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

    # Initialize message store
    message_store = MessageStore()

    # Show connected status
    startup_time = datetime.now().strftime("%H:%M:%S")
    print(f"✅ Connected as {agent_name} (server: {server_name}) at {startup_time}")
    print("👂 Monitoring for mentions...")
    print("📂 Message storage initialized")

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

    show_catalog = _env_truthy(os.getenv("SHOW_TOOL_CATALOG")) or _env_truthy(
        os.getenv("LANGGRAPH_TOOL_DEBUG")
    )

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
            if show_catalog:
                await _print_tool_catalog(tool_manager)

    seen_ids: set[str] = set()

    last_activity = time.time()

    def console_print(*args, **kwargs) -> None:
        if "flush" not in kwargs:
            kwargs["flush"] = True
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

            console_print("\n📨 Incoming mention block:\n" + raw, flush=True)

            # Store message immediately for persistence
            stored_message = StoredMessage(
                id=mid,
                raw_content=raw,
                parsed_author=None,  # Will be set below
                parsed_mention=None,  # Will be set below
                sender_handle=None,   # Will be set below
                status=MessageStatus.PROCESSING.value,
                created_at=datetime.now(timezone.utc).isoformat()
            )

            # Process mention silently - no "Incoming mention block" message
            author, sender = _extract_sender(raw, agent_name)

            # Update stored message with parsed info
            stored_message.parsed_author = author
            stored_message.sender_handle = sender
            stored_message.parsed_mention = agent_name if agent_name in raw else None

            if message_store.store_message(stored_message):
                console_print(f"📥 Message stored: {mid[:8]}...")

            if sender.lower() == "@unknown":
                console_print("ℹ️ No valid mention detected; skipping response")
                message_store.update_message_status(mid, MessageStatus.COMPLETED, "No valid mention detected")
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
                    # Note: Don't mark as failed here since we'll still send an acknowledgment
                    response_text = None

            if not response_text:
                response_text = _build_ack(sender, mid[:8])
                console_print(f"💬 Acknowledging {sender} (author: {author}) with {mid[:8]}")
            else:
                console_print("📝 Streaming reply:")
                console_print(response_text)

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
                message_store.update_message_status(mid, MessageStatus.COMPLETED)
            else:
                console_print(f"❌ Response send failed for {mid[:8]}")
                message_store.update_message_status(mid, MessageStatus.FAILED, "Response send failed")
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
