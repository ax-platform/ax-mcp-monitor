"""LangGraph-powered plugin that routes monitor messages through a graph workflow."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from openai import OpenAI

from .base_plugin import BasePlugin

MENTION_PATTERN = re.compile(r"@[0-9A-Za-z_\-]+")
WEB_SEARCH_PATTERN = re.compile(r"\[\[\s*web-search\s*:\s*(.*?)\]\]", re.IGNORECASE)
CLAUDE_TOOL_PATTERN = re.compile(r"<tool_call>(?P<body>.*?)</tool_call>", re.IGNORECASE | re.DOTALL)
CLAUDE_NAME_PATTERN = re.compile(r"<name>(?P<tool>[^<]+)</name>", re.IGNORECASE)
CLAUDE_PARAMETER_PATTERN = re.compile(
    r"<parameter\s+name=[\"'](?P<name>[^\"']+)[\"']>(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
logger = logging.getLogger(__name__)


@dataclass
class GraphSettings:
    """Configuration for the LangGraph workflow."""

    temperature: float
    request_timeout: float
    max_tokens: Optional[int]
    tool_max_runs: int


class LanggraphPlugin(BasePlugin):
    """Plugin that delegates generation to a LangGraph workflow."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        self.backend = self.config.get("backend") or os.getenv("LANGGRAPH_BACKEND", "openrouter")
        backend_lower = self.backend.lower()
        if backend_lower not in {"openrouter", "ollama"}:
            raise ValueError("LANGGRAPH_BACKEND must be 'openrouter' or 'ollama'")
        self.backend = backend_lower

        if self.backend == "openrouter":
            self.base_url = self.config.get("base_url") or os.getenv(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            )
            self.api_key = self.config.get("api_key") or os.getenv("OPENROUTER_API_KEY")
            if not self.api_key:
                raise RuntimeError(
                    "OpenRouter API key missing. Set OPENROUTER_API_KEY in the environment or plugin config."
                )
            default_model = "x-ai/grok-4-fast:free"
            self.model = self.config.get("model") or os.getenv("OPENROUTER_MODEL", default_model)
            headers = {
                "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://axplatform.dev"),
                "X-Title": os.getenv("OPENROUTER_TITLE", "aX MCP Monitor"),
            }
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, default_headers=headers)
        else:
            self.base_url = self.config.get("base_url") or os.getenv(
                "OLLAMA_BASE_URL", "http://localhost:11434/v1"
            )
            self.api_key = self.config.get("api_key") or os.getenv("OLLAMA_API_KEY", "ollama")
            self.model = self.config.get("model") or os.getenv("OLLAMA_MODEL", "gpt-oss")
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

        temperature = float(
            self.config.get("temperature")
            or os.getenv("LANGGRAPH_TEMPERATURE")
            or os.getenv("OPENROUTER_TEMPERATURE")
            or 0.7
        )
        request_timeout = float(
            self.config.get("request_timeout")
            or os.getenv("LANGGRAPH_TIMEOUT")
            or os.getenv("OPENROUTER_TIMEOUT")
            or 45
        )
        max_tokens_env = (
            self.config.get("max_tokens")
            or os.getenv("LANGGRAPH_MAX_TOKENS")
            or os.getenv("OPENROUTER_MAX_TOKENS")
        )
        self.settings = GraphSettings(
            temperature=temperature,
            request_timeout=request_timeout,
            max_tokens=int(max_tokens_env) if max_tokens_env else None,
            tool_max_runs=int(os.getenv("LANGGRAPH_TOOL_MAX_RUNS", "2")),
        )

        fallback_system = (
            "You are a helpful AI assistant operating on the aX platform, a collaborative network of agents and operators. "
            "Always start your first sentence with exactly one mention of the agent or person who addressed you (for example '@madtank — Thanks for the ping...'). "
            "When a message asks you to involve other agents (for example 'loop in @HaloScript'), mention those handles immediately after the sender in that first sentence and nowhere else. "
            "If you need someone's attention, you must @mention them so the turn is routed correctly; never rely on plain names alone. "
            "Keep responses friendly, practical, and under 200 words."
        )

        system_prompt = self.config.get("system_prompt")
        if not system_prompt:
            prompt_file = self.config.get("system_prompt_file") or os.getenv("LANGGRAPH_SYSTEM_PROMPT_FILE")
            if prompt_file:
                try:
                    system_prompt = Path(prompt_file).expanduser().read_text(encoding="utf-8").strip()
                except Exception:
                    system_prompt = None
        if not system_prompt:
            system_prompt = os.getenv("LANGGRAPH_SYSTEM_PROMPT")
        if not system_prompt:
            if self.backend == "ollama":
                system_prompt = os.getenv("OLLAMA_SYSTEM_PROMPT")
            else:
                system_prompt = os.getenv("OPENROUTER_SYSTEM_PROMPT")
        if not system_prompt:
            system_prompt = fallback_system

        self.system_prompt = system_prompt
        self.max_history = int(self.config.get("max_history", 10))
        self.auto_mention = bool(
            str(self.config.get("auto_mention", os.getenv("LANGGRAPH_AUTO_MENTION", "false"))).lower()
            in {"1", "true", "yes"}
        )

        self._history: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        self._graph = None
        self._tool_runs = 0
        self._tool_specs: List[Dict[str, Any]] = []
        self._available_tool_names: set[str] = set()
        streaming_setting = str(
            self.config.get("streaming", os.getenv("LANGGRAPH_STREAMING", "true"))
        ).lower()
        self.enable_streaming = streaming_setting not in {"0", "false", "no"}
        force_prefix_setting = str(
            self.config.get("force_sender_prefix", os.getenv("LANGGRAPH_FORCE_MENTION", "false"))
        ).lower()
        self.force_sender_prefix = force_prefix_setting in {"1", "true", "yes"}
        debug_setting = str(
            self.config.get("tool_debug", os.getenv("LANGGRAPH_TOOL_DEBUG", "false"))
        ).lower()
        self._tool_debug_enabled = debug_setting in {"1", "true", "yes", "on"}
        self._last_user_message: Optional[str] = None

    def _tool_debug(self, message: str) -> None:
        if self._tool_debug_enabled:
            print(f"[tool-debug] {message}", flush=True)

    def on_monitor_context_ready(self) -> None:
        if not self.current_date:
            return

        first = self._history[0] if self._history else None
        if first and first.get("role") == "system":
            content = first.get("content", "")
            if "Current date:" not in content:
                content = f"Current date: {self.current_date}\n\n{content}"
            allowed_dirs = self.monitor_context.get("allowed_directories") or []
            if allowed_dirs:
                dir_list = "\n".join(f"- {path}" for path in allowed_dirs)
                constraints = (
                    "Filesystem access is restricted to the directories listed below. "
                    "When calling filesystem tools (e.g., read_text_file, write_file), you MUST provide a valid 'path' inside these directories, "
                    "and include required arguments such as 'content' for write_file.\n" + dir_list
                )
                if constraints not in content:
                    content = f"{content}\n\n{constraints}"
            self._history[0] = {"role": "system", "content": content}
        else:
            base_content = f"Current date: {self.current_date}"
            allowed_dirs = self.monitor_context.get("allowed_directories") or []
            if allowed_dirs:
                dir_list = "\n".join(f"- {path}" for path in allowed_dirs)
                base_content += (
                    "\n\nFilesystem access is restricted to the directories listed below. "
                    "When calling filesystem tools (e.g., read_text_file, write_file), include the required arguments and stay within these roots.\n"
                    f"{dir_list}"
                )
            self._history.insert(0, {"role": "system", "content": base_content})

    def on_tool_manager_ready(self) -> None:
        self._graph = None  # Rebuild so tools are considered

    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        await self._ensure_graph()
        self._tool_runs = 0

        metadata: Dict[str, Any] = context or {}
        sender = metadata.get("sender")
        agent_name = metadata.get("agent_name")
        normalized_sender = _normalize_sender(sender)

        ignore_entries = metadata.get("ignore_mentions") or []
        if isinstance(ignore_entries, str):
            ignore_entries = [ignore_entries]
        ignore_mentions = {
            handle.lower()
            for handle in (_normalize_handle(entry) for entry in ignore_entries)
            if handle
        }
        if normalized_sender and normalized_sender.lower() in ignore_mentions:
            normalized_sender = None

        required_mentions: List[str] = []
        required_raw = metadata.get("required_mentions")
        if isinstance(required_raw, str):
            required_candidates = [required_raw]
        elif isinstance(required_raw, (list, tuple, set)):
            required_candidates = list(required_raw)
        else:
            required_candidates = []
        for candidate in required_candidates:
            normalized = _normalize_handle(candidate)
            if not normalized:
                continue
            if normalized.lower() in ignore_mentions:
                continue
            if normalized not in required_mentions:
                required_mentions.append(normalized)

        prompt_sender = normalized_sender or (sender.strip() if isinstance(sender, str) else None)
        if prompt_sender:
            formatted_message = f"{prompt_sender} says:\n{message}"
        else:
            formatted_message = message

        if agent_name:
            agent_handle = agent_name if str(agent_name).startswith("@") else f"@{agent_name}"
            if agent_handle not in formatted_message:
                formatted_message = f"[For {agent_handle}]\n{formatted_message}"

        history_snapshot = list(self._history)
        history_snapshot.append({"role": "user", "content": formatted_message})
        self._last_user_message = message

        state: Dict[str, Any] = {
            "messages": history_snapshot,
            "pending_tool_calls": [],
            "final_response": None,
            "tool_results": [],
        }
        self._tool_runs = 0
        tool_loops = 0

        while True:
            result_state = await self._graph.ainvoke(state)

            messages_after = result_state.get("messages", state["messages"])
            assistant_message = _latest_assistant_message(messages_after)
            reply = (assistant_message.get("content", "") if assistant_message else "").strip()

            pending_calls = result_state.get("pending_tool_calls") or []
            if pending_calls:
                summary = [
                    _describe_tool_call(call)
                    for call in pending_calls
                ]
                self._tool_debug("Model requested tool call(s): " + "; ".join(summary))

            search_query: Optional[str] = None
            search_tool_name: Optional[str] = None
            cleaned_reply = reply or ""

            if reply:
                match = WEB_SEARCH_PATTERN.search(reply)
                if match:
                    raw_match = match.group(1) if match else None
                    candidate = raw_match.strip() if raw_match else ""
                    if candidate:
                        search_query = candidate
                        cleaned_reply = WEB_SEARCH_PATTERN.sub("", reply).strip()
                if not search_query:
                    tool_block = CLAUDE_TOOL_PATTERN.search(reply)
                    block_content: Optional[str] = None
                    if tool_block:
                        block_content = tool_block.group("body") or ""
                        name_match = CLAUDE_NAME_PATTERN.search(block_content)
                        if name_match:
                            search_tool_name = name_match.group("tool").strip()
                    param_scope = block_content if block_content is not None else reply
                    param_match = CLAUDE_PARAMETER_PATTERN.search(param_scope)
                    if param_match:
                        param_name = (param_match.group("name") or "").strip().lower()
                        if param_name in {"query", "q"}:
                            candidate = (param_match.group("value") or "").strip()
                            if candidate:
                                search_query = candidate
                                if tool_block:
                                    cleaned_reply = CLAUDE_TOOL_PATTERN.sub("", reply).strip()
                                else:
                                    cleaned_reply = CLAUDE_PARAMETER_PATTERN.sub("", reply).strip()

            if (
                search_query
                and self.tool_manager
                and self.tool_manager.has_web_search()
                and tool_loops < self.settings.tool_max_runs
            ):
                tool_loops += 1

                if assistant_message is not None:
                    assistant_message["content"] = cleaned_reply or assistant_message.get("content", "")

                try:
                    search_result = await self.tool_manager.web_search(
                        search_query,
                        tool_name=search_tool_name,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Web search for '%s' failed: %s", search_query, exc)
                    search_result = ""
                if not search_result:
                    reply = cleaned_reply or reply
                    break

                preview = search_result.strip().splitlines()
                preview_text = " | ".join(preview[:3])
                self._tool_debug(
                    f"Web search '{search_query}' returned {len(preview)} line(s): {preview_text}"
                )

                updated_messages = list(messages_after)
                updated_messages.append({
                    "role": "user",
                    "content": f"Web search results for '{search_query}':\n{search_result}",
                })

                state = {
                    "messages": updated_messages,
                    "pending_tool_calls": [],
                    "final_response": None,
                    "tool_results": list(result_state.get("tool_results", [])),
                }
                continue

            if not reply:
                fallback_reply = (result_state.get("final_response") or "").strip()
                if fallback_reply:
                    reply = fallback_reply
                    if not assistant_message:
                        messages_after = messages_after + [{"role": "assistant", "content": reply}]

            if not reply:
                tool_results = result_state.get("tool_results") or []
                if tool_results:
                    reply = tool_results[-1].strip()
                    if reply:
                        messages_after = messages_after + [{"role": "assistant", "content": reply}]

            if not reply:
                reply = "I'm sorry—something went wrong while generating a reply."

            break

        agent_handle_normalized: Optional[str] = None
        if agent_name:
            agent_handle_normalized = agent_name if str(agent_name).startswith('@') else f'@{agent_name}'

        if not required_mentions and normalized_sender:
            if not (agent_handle_normalized and normalized_sender.lower() == agent_handle_normalized.lower()):
                required_mentions.append(normalized_sender)

        missing_mentions = [
            handle
            for handle in required_mentions
            if handle
            and handle.lower() != "@unknown"
            and not _contains_handle(reply, handle)
        ]

        if missing_mentions:
            primary = missing_mentions[0]
            reply = reply.lstrip("-–—: ").strip()
            if not _contains_handle(reply, primary):
                reply = f"{primary} {reply}" if reply else primary
            for extra in missing_mentions[1:]:
                if not _contains_handle(reply, extra):
                    reply = f"{reply} {extra}".strip()

        if self.force_sender_prefix:
            reply = _ensure_sender_prefix(reply, normalized_sender)

        self._history = _trim_history(messages_after, self.max_history)

        return reply

    async def _ensure_graph(self) -> None:
        if self._graph is not None:
            return

        if self.tool_manager and self.tool_manager.has_servers():
            tools = await self.tool_manager.list_tools()
            self._available_tool_names = set(tools.keys())
            self._tool_specs = [
                _tool_to_openai_spec(tool)
                for tool in tools.values()
                if tool is not None
            ]
        else:
            self._available_tool_names = set()
            self._tool_specs = []

        workflow = StateGraph(dict)
        workflow.add_node("call_model", self._node_call_model)
        workflow.add_node("invoke_tool", self._node_invoke_tool)
        workflow.add_node("finalize", self._node_finalize)
        workflow.set_entry_point("call_model")
        workflow.add_conditional_edges(
            "call_model",
            self._route_from_model,
            {"tool": "invoke_tool", "final": "finalize"},
        )
        workflow.add_edge("invoke_tool", "call_model")
        workflow.add_edge("finalize", END)
        self._graph = workflow.compile()

    async def _node_call_model(self, state: Dict[str, Any]) -> Dict[str, Any]:
        messages = state.get("messages", [])
        tool_spec = self._tool_spec()
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "timeout": self.settings.request_timeout,
        }
        if self.settings.max_tokens is not None:
            kwargs["max_tokens"] = self.settings.max_tokens
        if tool_spec:
            kwargs["tools"] = tool_spec
            kwargs["tool_choice"] = "auto"
        use_streaming = self.enable_streaming and not tool_spec
        if use_streaming:
            stream_result = await asyncio.to_thread(self._stream_completion, kwargs)
            if stream_result is None:
                use_streaming = False
            else:
                message_dict, pending_calls = stream_result
        if not use_streaming:
            response = await asyncio.to_thread(self.client.chat.completions.create, **kwargs)
            choice = response.choices[0]
            message = choice.message
            message_dict = message.model_dump(mode="json")
            pending_calls = []
        content = message_dict.get("content")
        if isinstance(content, list):
            message_dict["content"] = "".join(_extract_text_chunks(content))
        tool_calls = message_dict.get("tool_calls") or []
        if tool_calls:
            pending_calls = list(tool_calls)
        updated_messages = messages + [message_dict]
        final_response = None
        if not pending_calls:
            final_response = message_dict.get("content") or ""
        next_state: Dict[str, Any] = {
            "messages": updated_messages,
            "pending_tool_calls": pending_calls,
            "final_response": final_response,
        }
        if "tool_results" in state:
            next_state["tool_results"] = state.get("tool_results")
        return next_state

    def _stream_completion(self, kwargs: Dict[str, Any]) -> Optional[tuple[Dict[str, Any], list]]:
        aggregated = ""
        try:
            print("📝 Streaming reply:", flush=True)
            stream = self.client.chat.completions.create(stream=True, **kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                if getattr(delta, "tool_calls", None):
                    # Tool calls via streaming require more plumbing; fall back.
                    return None
                text_delta = getattr(delta, "content", None)
                if text_delta:
                    aggregated += text_delta
                    print(text_delta, end="", flush=True)
            if aggregated:
                print("", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Streaming failed ({exc}); falling back to standard completion", flush=True)
            return None

        message_dict: Dict[str, Any] = {
            "role": "assistant",
            "content": aggregated,
        }
        return message_dict, []

    async def _node_invoke_tool(self, state: Dict[str, Any]) -> Dict[str, Any]:
        pending_calls = state.get("pending_tool_calls") or []
        messages = state.get("messages", [])
        if not pending_calls:
            return state
        tool_call = pending_calls[0]
        remaining = pending_calls[1:]
        result_text = await self._execute_tool(tool_call)
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call.get("id"),
            "name": tool_call.get("function", {}).get("name"),
            "content": result_text,
        }
        updated_messages = messages + [tool_message]
        tool_results = list(state.get("tool_results", []))
        if result_text:
            tool_results.append(result_text)
        return {
            "messages": updated_messages,
            "pending_tool_calls": remaining,
            "final_response": state.get("final_response"),
            "tool_results": tool_results,
        }

    async def _node_finalize(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return state

    def _route_from_model(self, state: Dict[str, Any]) -> str:
        pending = state.get("pending_tool_calls") or []
        if not pending or not self._tool_specs:
            return "final"
        if self._tool_runs >= self.settings.tool_max_runs:
            return "final"
        next_call = pending[0]
        func = next_call.get("function", {}) if isinstance(next_call, dict) else {}
        name = func.get("name")
        if self._available_tool_names and name and name not in self._available_tool_names:
            return "final"
        return "tool"

    async def _execute_tool(self, tool_call: Dict[str, Any]) -> str:
        self._tool_runs += 1
        try:
            tool_name = tool_call.get("function", {}).get("name")
            arguments = tool_call.get("function", {}).get("arguments")
            args = json.loads(arguments or "{}") if isinstance(arguments, str) else (arguments or {})
        except json.JSONDecodeError:
            args = {}
            tool_name = tool_call.get("function", {}).get("name")
        args = args if isinstance(args, dict) else {}

        if not self.tool_manager:
            return "Tool execution not available or failed."

        execution_result: Optional[str] = None
        if tool_name:
            self._tool_debug(
                f"Invoking tool '{tool_name}' with args {json.dumps(args, ensure_ascii=False)}"
            )
            if not args and tool_name.lower() == "fetch":
                inferred = _extract_first_url(self._last_user_message)
                if inferred:
                    args["url"] = inferred
                    self._tool_debug(
                        f"Auto-populated missing 'url' argument with '{inferred}'"
                    )
            if tool_name.lower() == "fetch" and not args.get("url"):
                self._tool_debug("Blocking fetch call: missing 'url' argument")
                return "I need a direct URL to fetch—please share the link you want me to open."
            if tool_name.lower() == "tasks":
                required = {"action", "title", "description"}
                missing = [key for key in required if not args.get(key)]
                if missing:
                    error = (
                        "ToolError: tasks tool requires action, title, and description. "
                        "Populate those fields before calling the tool."
                    )
                    self._tool_debug(
                        f"Blocking tasks call due to missing fields: {missing}"
                    )
                    return error
            execution_result = await self.tool_manager.execute_tool(tool_name, args)
            if execution_result is None:
                self._tool_debug(f"Tool '{tool_name}' returned None")

        if execution_result:
            preview = execution_result.strip().splitlines()
            preview_text = " | ".join(preview[:3])
            if isinstance(execution_result, str) and execution_result.startswith("ToolError:"):
                self._tool_debug(
                    f"Tool '{tool_name}' reported error: {preview_text}"
                )
            else:
                self._tool_debug(
                    f"Tool '{tool_name}' succeeded ({len(preview)} line(s) returned): {preview_text}"
                )
            return execution_result
        elif tool_name:
            self._tool_debug(
                f"Tool '{tool_name}' returned empty string; deferring to fallback handling"
            )

        # Fallback: attempt web search if query present
        if tool_name and any(keyword in tool_name.lower() for keyword in ("search", "web")):
            query_value = args.get("query") or args.get("q")
            query_text = str(query_value).strip() if query_value else ""
            if query_text:
                self._tool_debug(
                    f"Fallback web search via tool manager for '{query_text}'"
                )
                result = await self.tool_manager.web_search(query_text, tool_name=tool_name)
                if result:
                    preview = result.strip().splitlines()
                    preview_text = " | ".join(preview[:3])
                    self._tool_debug(
                        f"Fallback search for '{query_text}' produced {len(preview)} line(s): {preview_text}"
                    )
                    return result
        content = tool_call.get("function", {}).get("arguments", "")
        if isinstance(content, str):
            match = WEB_SEARCH_PATTERN.search(content)
            query = None
            if match:
                raw_query = match.group(1)
                query = raw_query.strip() if raw_query else ""
            else:
                alt_match = CLAUDE_PARAMETER_PATTERN.search(content)
                if alt_match:
                    param_name = (alt_match.group("name") or "").strip().lower()
                    if param_name in {"query", "q"}:
                        query = (alt_match.group("value") or "").strip()
            if query:
                self._tool_debug(
                    f"Extracted web search query '{query}' from fallback content"
                )
                result = await self.tool_manager.web_search(query)
                if result:
                    preview = result.strip().splitlines()
                    preview_text = " | ".join(preview[:3])
                    self._tool_debug(
                        f"Direct search for '{query}' produced {len(preview)} line(s): {preview_text}"
                    )
                    return result

        return "Tool execution not available or failed."

    def _tool_spec(self) -> Optional[List[Dict[str, Any]]]:
        if not self._tool_specs:
            return None
        return self._tool_specs


def _tool_to_openai_spec(tool: Any) -> Dict[str, Any]:
    name = getattr(tool, "name", "tool")
    description = getattr(tool, "description", "") or ""
    parameters = _extract_tool_parameters(tool)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _extract_tool_parameters(tool: Any) -> Dict[str, Any]:
    default = {"type": "object", "properties": {}}
    args_schema = getattr(tool, "args_schema", None)
    if isinstance(args_schema, dict):
        return args_schema or default
    if hasattr(args_schema, "model_json_schema"):
        try:
            schema = args_schema.model_json_schema()  # type: ignore[attr-defined]
            if isinstance(schema, dict) and schema:
                return schema
        except Exception:  # noqa: BLE001
            pass
    if hasattr(args_schema, "json_schema"):
        try:
            schema = args_schema.json_schema()  # type: ignore[attr-defined]
            if isinstance(schema, dict) and schema:
                return schema
        except Exception:  # noqa: BLE001
            pass
    if hasattr(args_schema, "schema"):
        try:
            schema = args_schema.schema()  # type: ignore[attr-defined]
            if isinstance(schema, dict) and schema:
                return schema
        except Exception:  # noqa: BLE001
            pass
    metadata = getattr(tool, "metadata", {}) or {}
    meta_block = metadata.get("_meta") if isinstance(metadata, dict) else {}
    if isinstance(meta_block, dict):
        for key in ("inputSchema", "parameters"):
            value = meta_block.get(key)
            if isinstance(value, dict) and value:
                return value
    for key in ("inputSchema", "parameters"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, dict) and value:
            return value
    return default


def _extract_text_chunks(content: List[Any]) -> List[str]:
    pieces: List[str] = []
    for part in content:
        if isinstance(part, dict) and "text" in part:
            pieces.append(str(part.get("text", "")))
        elif isinstance(part, str):
            pieces.append(part)
    return pieces


def _describe_tool_call(call: Any) -> str:
    if not isinstance(call, dict):
        return str(call)
    func = call.get("function") or {}
    name = func.get("name") or "unknown"
    args = func.get("arguments")
    if isinstance(args, str):
        payload = args
    else:
        try:
            payload = json.dumps(args, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            payload = str(args)
    if payload and len(payload) > 120:
        payload = payload[:117] + "..."
    return f"{name}({payload})"


_URL_PATTERN = re.compile(r"https?://[^\s>]+", re.IGNORECASE)


def _extract_first_url(source: Optional[str]) -> Optional[str]:
    if not source:
        return None
    match = _URL_PATTERN.search(source)
    if not match:
        return None
    candidate = match.group(0)
    # Trim trailing punctuation that commonly rides along
    candidate = candidate.rstrip('.,"\'\)\]>')
    return candidate or None


def _normalize_sender(sender: Optional[str]) -> Optional[str]:
    if not sender:
        return None
    match = MENTION_PATTERN.search(sender)
    if match:
        return match.group(0)
    cleaned = sender.strip().split()[0]
    if cleaned.startswith("@"):
        token = cleaned.rstrip("—-:,")
        return token
    return None


def _normalize_handle(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    token = str(candidate).strip()
    if not token:
        return None
    if not token.startswith("@"):
        token = f"@{token}"
    first = token.split()[0]
    match = MENTION_PATTERN.search(first)
    if match:
        return match.group(0)
    cleaned = re.sub(r"[^@0-9A-Za-z_\-]", "", first)
    if cleaned.startswith("@") and len(cleaned) > 1:
        return cleaned
    return None


def _contains_handle(text: str, handle: Optional[str]) -> bool:
    if not text or not handle:
        return False
    handle_lower = handle.lower()
    for mention in MENTION_PATTERN.findall(text):
        if mention.lower() == handle_lower:
            return True
    return False


def _ensure_sender_prefix(reply: str, sender: Optional[str]) -> str:
    normalized = _normalize_sender(sender)
    cleaned = reply.strip()
    if not normalized:
        return cleaned
    if cleaned.lower().startswith(normalized.lower()):
        return cleaned
    stripped = cleaned.lstrip("-–—: ")
    return f"{normalized} — {stripped}"


def _latest_assistant_message(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for entry in reversed(messages):
        if entry.get("role") == "assistant" and entry.get("content"):
            return entry
    return None


def _trim_history(messages: List[Dict[str, Any]], max_pairs: int) -> List[Dict[str, Any]]:
    if not messages:
        return messages
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    others = [msg for msg in messages if msg.get("role") != "system"]
    limit = max_pairs * 2
    trimmed = others[-limit:] if limit > 0 else others
    return system_messages[:1] + trimmed
