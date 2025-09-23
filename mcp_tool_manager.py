"""LangGraph-aware MCP tool manager."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Dict, Mapping, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient, create_session
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession

from ax_mcp_wait_client.config_loader import MCPConfig


logger = logging.getLogger(__name__)

_SEARCH_KEYWORDS = ("search", "web-search", "websearch", "browser")


def _stringify_output(result: Any) -> str:
    """Convert tool results to a printable string."""
    if isinstance(result, tuple) and len(result) == 2:
        content, _ = result
        result = content
    if isinstance(result, list):
        return "\n".join(str(item) for item in result if item is not None)
    if isinstance(result, (dict, set)):
        return json.dumps(result, ensure_ascii=False)
    if result is None:
        return ""
    return str(result)


def _build_connection(raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a Claude-style MCP config entry into adapter connection input."""
    if not raw:
        return None

    transport = raw.get("transport")
    if not transport:
        if raw.get("command"):
            transport = "stdio"
        elif raw.get("url"):
            transport = "streamable_http"
        else:
            return None

    connection: Dict[str, Any] = {"transport": transport}

    if transport == "stdio":
        command = raw.get("command")
        if not command:
            return None
        args = raw.get("args") or []
        if not isinstance(args, list):
            args = [str(args)]
        connection.update({
            "command": str(command),
            "args": [str(arg) for arg in args],
        })
        env = raw.get("env") or {}
        if env:
            connection["env"] = {str(k): str(v) for k, v in env.items()}
        if raw.get("cwd"):
            connection["cwd"] = str(raw["cwd"])
        if raw.get("encoding"):
            connection["encoding"] = str(raw["encoding"])
        if raw.get("encoding_error_handler"):
            connection["encoding_error_handler"] = str(raw["encoding_error_handler"])
    else:
        url = raw.get("url")
        if not url and raw.get("args"):
            # Some configs pass the URL as the first non-flag argument
            args = [a for a in raw.get("args", []) if isinstance(a, str) and not a.startswith("-")]  # noqa: E501
            if args:
                url = args[0]
        if not url:
            return None
        connection["url"] = str(url)
        if raw.get("headers"):
            connection["headers"] = raw["headers"]
        if raw.get("timeout"):
            connection["timeout"] = raw["timeout"]
        if raw.get("session_kwargs"):
            connection["session_kwargs"] = raw["session_kwargs"]
    return connection


class MCPToolManager:
    """Manage MCP tools and expose LangGraph-friendly helpers."""

    def __init__(
        self,
        server_configs: Dict[str, MCPConfig],
        *,
        primary_server: str,
    ) -> None:
        self._connections: Dict[str, Dict[str, Any]] = {}
        for name, cfg in server_configs.items():
            if name == primary_server:
                continue
            connection = _build_connection(getattr(cfg, "raw_config", {}) or {})
            if connection:
                self._connections[name] = connection
        self._client = (
            MultiServerMCPClient(self._connections) if self._connections else None
        )
        self._tools_lock = asyncio.Lock()
        self._tools_by_name: Dict[str, BaseTool] = {}
        self._web_search_tools: set[str] = set()
        self._session_lock = asyncio.Lock()
        self._session_contexts: Dict[str, Any] = {}
        self._sessions: Dict[str, ClientSession] = {}

    def has_servers(self) -> bool:
        return bool(self._connections)

    def has_web_search(self) -> bool:
        if self._web_search_tools:
            return True
        return any(
            any(keyword in name.lower() for keyword in _SEARCH_KEYWORDS)
            for name in self._connections
        )

    async def _ensure_tools(self) -> Dict[str, BaseTool]:
        if not self._client:
            return {}
        if self._tools_by_name:
            return self._tools_by_name
        async with self._tools_lock:
            if self._tools_by_name:
                return self._tools_by_name
            tools: Dict[str, BaseTool] = {}
            web_search: set[str] = set()
            for server_name in self._connections:
                session = await self._ensure_session(server_name)
                if not session:
                    continue
                try:
                    raw_tools = await load_mcp_tools(session)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to load tools from server '%s': %s", server_name, exc
                    )
                    continue
                for tool in raw_tools:
                    name_lower = tool.name.lower()
                    if "felo" in name_lower:
                        continue
                    tools[tool.name] = tool
                    if any(keyword in name_lower for keyword in _SEARCH_KEYWORDS):
                        web_search.add(tool.name)
            self._tools_by_name = tools
            self._web_search_tools = web_search
            return self._tools_by_name

    async def _ensure_session(self, server_name: str) -> Optional[ClientSession]:
        if server_name in self._sessions:
            return self._sessions[server_name]
        if not self._client or server_name not in self._connections:
            return None
        async with self._session_lock:
            if server_name in self._sessions:
                return self._sessions[server_name]
            connection = self._connections[server_name]
            ctx = create_session(connection)
            try:
                session = await ctx.__aenter__()
                await session.initialize()
            except Exception as exc:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    await ctx.__aexit__(type(exc), exc, exc.__traceback__)
                logger.warning(
                    "Failed to establish session with server '%s': %s",
                    server_name,
                    exc,
                )
                return None
            self._session_contexts[server_name] = ctx
            self._sessions[server_name] = session
            return session

    async def list_tools(self) -> Dict[str, BaseTool]:
        """Return the cached mapping of tool name to LangChain tool objects."""
        return await self._ensure_tools()

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        tools = await self._ensure_tools()
        tool = tools.get(tool_name)
        if not tool:
            return None
        payload = arguments or {}
        try:
            result = await tool.ainvoke(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool '%s' failed: %s", tool_name, exc)
            return ""
        return _stringify_output(result)

    async def web_search(
        self,
        query: str,
        *,
        max_results: int = 5,
        tool_name: Optional[str] = None,
    ) -> Optional[str]:
        tools = await self._ensure_tools()
        candidate: Optional[BaseTool] = None
        if tool_name:
            candidate = tools.get(tool_name)
        if not candidate:
            for name in self._web_search_tools:
                candidate = tools.get(name)
                if candidate:
                    break
        if not candidate:
            # Fallback: first tool that mentions search
            for name, tool in tools.items():
                if any(keyword in name.lower() for keyword in _SEARCH_KEYWORDS):
                    candidate = tool
                    break
        if not candidate:
            return None

        args_schema = getattr(candidate, "args_schema", None)
        fields = getattr(args_schema, "model_fields", {}) if args_schema else {}
        # Build arguments dynamically based on schema
        payload: Dict[str, Any] = {}
        if "query" in fields:
            payload["query"] = query
        elif "q" in fields:
            payload["q"] = query
        else:
            payload["query"] = query
        if "max_results" in fields:
            payload["max_results"] = max_results
        elif "num_results" in fields:
            payload["num_results"] = max_results
        elif "k" in fields:
            payload["k"] = max_results

        try:
            result = await candidate.ainvoke(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Web search tool '%s' failed: %s", getattr(candidate, "name", ""), exc)
            return None
        return _stringify_output(result)

    async def shutdown(self) -> None:
        """Tear down cached tools and close any persistent MCP sessions."""
        self._tools_by_name.clear()
        self._web_search_tools.clear()
        for name, ctx in list(self._session_contexts.items()):
            try:
                await ctx.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing session '%s': %s", name, exc)
        self._session_contexts.clear()
        self._sessions.clear()


__all__ = ["MCPToolManager"]
