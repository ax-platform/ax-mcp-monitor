from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Protocol, Optional

from mcp.client.session import ClientSession


@dataclass
class HandlerContext:
    agent_name: str
    server_url: str


class MessageHandler(Protocol):
    async def handle(self, session: ClientSession, message: dict, ctx: HandlerContext) -> bool:  # noqa: D401
        """Handle a single message; return True if handled."""


class EchoHandler:
    """Simple echo handler used as a default example."""

    async def handle(self, session: ClientSession, message: dict, ctx: HandlerContext) -> bool:
        content = (message.get("content") or "").strip()
        if not content or content.startswith("[echo]"):
            return False

        # Try to reply in-thread when possible
        parent_id = message.get("id") or message.get("message_id")
        if not parent_id:
            # Fallback 1: try to resolve by searching recent messages
            query = self._build_query(content)
            try:
                search_args = {"action": "search", "query": query, "limit": 5}
                result = await session.call_tool("search", arguments=search_args)
                parent_id = self._extract_message_id_from_search(result)
            except Exception as _:
                parent_id = None

        echo_text = f"[echo] {content}"
        # Always include an idempotency key to avoid duplicate side effects
        # if the transport or auth layer retries the request.
        import uuid
        args = {"action": "send", "content": echo_text, "idempotency_key": str(uuid.uuid4())}
        if parent_id:
            args["parent_message_id"] = parent_id

        await session.call_tool("messages", arguments=args)
        # Minimal visibility for ops
        try:
            import time
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if parent_id:
                print(f"[{ts}] echoed -> parent={parent_id}", flush=True)
            else:
                print(f"[{ts}] echoed -> root message", flush=True)
        except Exception:
            pass
        return True

    def _build_query(self, content: str) -> str:
        # Trim agent mention prefix if present to broaden search
        lowered = content.lower()
        for prefix in ("@mcp_client_local", "@agent", "@mcp"):
            if lowered.startswith(prefix):
                content = content[len(prefix):].strip()
                break
        # Limit query length for search robustness
        return content[:120]

    def _extract_message_id_from_search(self, search_result) -> Optional[str]:
        # Prefer structured content
        data = getattr(search_result, "structuredContent", None)
        if not data:
            # Try to parse textual content list
            try:
                blocks = getattr(search_result, "content", []) or []
                texts = [getattr(b, "text", None) for b in blocks if getattr(b, "type", "") == "text"]
                data = {"_text": "\n".join([t for t in texts if t])}
            except Exception:
                data = None

        # Heuristic extraction
        if isinstance(data, dict):
            # Common shapes: {'results': [{'id': '...'} ...]}
            for key in ("results", "items", "messages", "data"):
                arr = data.get(key)
                if isinstance(arr, list):
                    for it in arr:
                        if isinstance(it, dict):
                            mid = it.get("id") or it.get("message_id") or it.get("short_id")
                            if mid:
                                return mid
        return None


def load_handlers(specs: list[str] | None) -> list[MessageHandler]:
    if not specs:
        return [EchoHandler()]

    handlers: list[MessageHandler] = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if spec.lower() == "echo":
            handlers.append(EchoHandler())
            continue
        # Dotted loader: pkg.module:Class
        if ":" in spec:
            mod_name, attr = spec.split(":", 1)
        else:
            mod_name, attr = spec, "handler"
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, attr)
        instance = obj() if callable(obj) else obj  # type: ignore[call-arg]
        handlers.append(instance)
    return handlers
