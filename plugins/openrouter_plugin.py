"""OpenRouter LLM plugin for the aX MCP monitor bot."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from .base_plugin import BasePlugin


MENTION_PATTERN = re.compile(r"@[0-9A-Za-z_\-]+")


def _read_prompt(path_like: Optional[str]) -> Optional[str]:
    """Load prompt text from a file path if it exists."""
    if not path_like:
        return None
    try:
        return Path(path_like).expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"⚠️ System prompt file not found: {path_like}")
    except OSError as exc:
        print(f"⚠️ Failed to read system prompt file {path_like}: {exc}")
    return None


def _normalize_sender(sender: Optional[str]) -> Optional[str]:
    """Extract a normalized @mention from a sender string."""
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
    """Normalize arbitrary handle strings to @mentions."""
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


class OpenrouterPlugin(BasePlugin):
    """OpenRouter-backed completion plugin."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        self.base_url = self.config.get("base_url") or os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        )
        self.api_key = self.config.get("api_key") or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter API key missing. Set OPENROUTER_API_KEY in the environment or plugin config."
            )

        self.model = self.config.get("model") or os.getenv(
            "OPENROUTER_MODEL", "x-ai/grok-4-fast:free"
        )
        self.max_history = int(self.config.get("max_history", 10))
        self.auto_mention = bool(
            str(self.config.get("auto_mention", os.getenv("OPENROUTER_AUTO_MENTION", "false"))).lower()
            in {"1", "true", "yes"}
        )
        self.temperature = float(
            self.config.get("temperature", os.getenv("OPENROUTER_TEMPERATURE", "0.7"))
        )
        self.max_tokens = self.config.get("max_tokens")
        self.request_timeout = float(
            self.config.get("request_timeout", os.getenv("OPENROUTER_TIMEOUT", "45"))
        )

        headers = {
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://axplatform.dev"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "aX MCP Monitor"),
        }
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, default_headers=headers)

        fallback_system = (
            "You are a helpful AI assistant operating on the aX platform, a collaborative network of agents and operators. "
            "Always start your first sentence with exactly one mention of the agent or person who addressed you (for example '@madtank — Thanks for the ping...'). "
            "When a message asks you to involve other agents (for example 'loop in @HaloScript'), mention those handles immediately after the sender in that first sentence and nowhere else. "
            "If you need someone's attention, you must @mention them so the turn is routed correctly; never rely on plain names alone. "
            "Keep responses friendly, practical, and under 200 words."
        )

        system_prompt = os.getenv("OPENROUTER_SYSTEM_PROMPT")
        if not system_prompt:
            prompt_file = os.getenv("OPENROUTER_SYSTEM_PROMPT_FILE")
            system_prompt = _read_prompt(prompt_file)
        if not system_prompt:
            system_prompt = self.config.get("system_prompt", fallback_system)

        self.messages_history: list[dict[str, str]] = []
        if system_prompt:
            self.messages_history.append({"role": "system", "content": system_prompt})

    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
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

        required_mentions: list[str] = []
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

        if self.messages_history and self.messages_history[0].get("role") == "system":
            history = self.messages_history + [{"role": "user", "content": formatted_message}]
        else:
            history = self.messages_history + [{"role": "user", "content": formatted_message}]

        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": history,
            "temperature": self.temperature,
            "timeout": self.request_timeout,
        }
        if self.max_tokens is not None:
            request_kwargs["max_tokens"] = int(self.max_tokens)

        try:
            response = await asyncio.to_thread(self.client.chat.completions.create, **request_kwargs)
        except Exception as exc:
            return f"Error calling OpenRouter: {exc}"

        reply = response.choices[0].message.content if response.choices else ""
        reply = (reply or "").strip()

        agent_handle_normalized: Optional[str] = None
        if agent_name:
            agent_handle_normalized = agent_name if str(agent_name).startswith('@') else f'@{agent_name}'

        if not required_mentions and normalized_sender:
            if not (agent_handle_normalized and normalized_sender.lower() == agent_handle_normalized.lower()):
                required_mentions.append(normalized_sender)

        missing_mentions = [
            handle for handle in required_mentions if not _contains_handle(reply, handle)
        ]

        if missing_mentions:
            mention_prefix = " ".join(missing_mentions)
            reply = f"{mention_prefix} — {reply.lstrip('-–—: ')}"

        if self.auto_mention or normalized_sender:
            reply = _ensure_sender_prefix(reply, normalized_sender)

        self.messages_history.append({"role": "user", "content": formatted_message})
        self.messages_history.append({"role": "assistant", "content": reply})

        if len(self.messages_history) > (self.max_history * 2 + 1):
            self.messages_history[1:] = self.messages_history[-(self.max_history * 2):]

        return reply

    def reset_context(self) -> None:
        if self.messages_history:
            self.messages_history = self.messages_history[:1]
