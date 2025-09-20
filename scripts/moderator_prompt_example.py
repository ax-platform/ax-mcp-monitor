#!/usr/bin/env python3
"""Quick experiment to prototype moderator kickoffs for aX agents.

By default this runs completely locally:
  1. Loads a conversation template (e.g. debate_absurd, quantum_chat).
  2. Sets up the Ollama plugin with that template's system prompt.
  3. Sends a "moderator" instruction to the plugin asking it to craft the
     first message that the initiator agent should post.

Add --send (with an MCP config) to actually deliver the result to aX so you can
see the kickoff live in the platform.
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any

from ax_mcp_wait_client.config_loader import (
    get_default_config_path,
    parse_mcp_config,
)
from ax_mcp_wait_client.mcp_client import MCPClient

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "conversation_templates.json"

# Ensure we can import plugins.* modules relative to the repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.append(str(REPO_ROOT / "src"))


def load_templates() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Conversation templates file not found at {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("templates", {})


def resolve_prompt_path(candidate: str | None, *, label: str, required: bool = False) -> Path | None:
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()
    if path.exists():
        return path
    message = f"⚠️  {label} not found at {path}"
    if required:
        raise FileNotFoundError(message)
    print(message)
    return None


def read_prompt_text(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"⚠️  Failed to read prompt file {path}: {exc}")
        return None


def render_scenario_text(raw: str | None, initiator: str, responder: str) -> str | None:
    if raw is None:
        return None
    initiator_handle = initiator
    responder_handle = responder
    initiator_name = initiator_handle.lstrip("@")
    responder_name = responder_handle.lstrip("@")
    replacements = {
        "{initiator_handle}": initiator_handle,
        "{initiator_name}": initiator_name,
        "{responder_handle}": responder_handle,
        "{responder_name}": responder_name,
        "{player1_handle}": initiator_handle,
        "{player1_name}": initiator_name,
        "{player2_handle}": responder_handle,
        "{player2_name}": responder_name,
    }
    result = raw
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def compose_system_prompt_text(base_text: str | None, scenario_text: str | None) -> str | None:
    if base_text and scenario_text:
        return f"{base_text.rstrip()}\n\n---\n\n{scenario_text.lstrip()}"
    if base_text:
        return base_text
    if scenario_text:
        return scenario_text
    return None


def load_plugin(plugin_type: str, config: Dict[str, Any] | None = None):
    module = importlib.import_module(f"plugins.{plugin_type}_plugin")
    class_name = "".join(part.capitalize() for part in plugin_type.split("_")) + "Plugin"
    plugin_cls = getattr(module, class_name)
    return plugin_cls(config or {})


@contextmanager
def temporary_env(**updates: str | None):
    """Temporarily set environment variables."""
    previous: Dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_moderator_prompt(template: Dict[str, Any], initiator: str, responder: str) -> str:
    name = template.get("name", template.get("description", "Unnamed Scenario"))
    description = template.get("description", "")
    starter = template.get("starter_message", "").strip()

    pieces = [
        f"Moderator kickoff for {initiator}:",
        f"- You are about to chat with {responder} in the '{name}' scenario.",
        "- Mention the responder in your first sentence and keep the reply under 200 words.",
        "- Stay on-theme and sound natural—no reference to this moderator note.",
    ]

    if description:
        pieces.append(f"- Scenario context: {description}")

    if starter:
        pieces.append(
            "- Inspiration from the original template (rephrase in your own words):\n"
            + starter
        )

    pieces.append("Now craft the opening message you would post on aX.")

    return "\n".join(pieces)


async def generate_initial_message(
    plugin_name: str,
    template_key: str,
    initiator_handle: str,
    responder_handle: str,
    model: str | None,
    plugin_config: Dict[str, Any] | None,
    base_prompt_override: str | None,
    scenario_prompt_override: str | None,
) -> str:
    templates = load_templates()
    if template_key not in templates:
        raise KeyError(f"Template '{template_key}' not found. Available: {', '.join(sorted(templates.keys()))}")

    template = templates[template_key]

    base_candidate = base_prompt_override or os.getenv("OLLAMA_BASE_PROMPT_FILE")
    base_path = resolve_prompt_path(base_candidate, label="Base system prompt") if base_candidate else None

    prompt_file = template.get("system_prompt_file")
    prompt_path: Path | None = None
    if scenario_prompt_override:
        prompt_path = resolve_prompt_path(
            scenario_prompt_override,
            label=f"Scenario prompt override for {template_key}",
            required=True,
        )
    elif prompt_file:
        prompt_path = resolve_prompt_path(
            prompt_file,
            label=f"Template '{template_key}' system prompt",
            required=True,
        )

    base_text = read_prompt_text(base_path)
    scenario_text = read_prompt_text(prompt_path)
    if scenario_text is None:
        scenario_text = template.get("system_context")
    scenario_text = render_scenario_text(scenario_text, initiator_handle, responder_handle)

    combined_prompt = compose_system_prompt_text(base_text, scenario_text)

    env_updates: Dict[str, str | None] = {}
    env_updates["OLLAMA_BASE_PROMPT_FILE"] = str(base_path) if base_path else None
    if combined_prompt:
        env_updates["OLLAMA_SYSTEM_PROMPT"] = combined_prompt
        env_updates["OLLAMA_SYSTEM_PROMPT_FILE"] = None
    elif prompt_path:
        env_updates["OLLAMA_SYSTEM_PROMPT"] = None
        env_updates["OLLAMA_SYSTEM_PROMPT_FILE"] = str(prompt_path)
    elif base_path:
        env_updates["OLLAMA_SYSTEM_PROMPT"] = None
        env_updates["OLLAMA_SYSTEM_PROMPT_FILE"] = str(base_path)
    else:
        env_updates["OLLAMA_SYSTEM_PROMPT"] = None
        env_updates["OLLAMA_SYSTEM_PROMPT_FILE"] = None
    if model:
        env_updates["OLLAMA_MODEL"] = model

    async with EnvScope(**env_updates):
        plugin = load_plugin(plugin_name, plugin_config)
        moderator_prompt = build_moderator_prompt(template, initiator_handle, responder_handle)

        stream_started = False

        async def stream_handler(chunk: str) -> None:
            nonlocal stream_started
            if not chunk:
                return
            if not stream_started:
                stream_started = True
                print("\n🎙️ Streaming kickoff draft...\n")
            print(chunk, end="", flush=True)

        context = {
            "sender": "@moderator",  # imaginary helper sending the setup
            "agent_name": initiator_handle,
            "required_mentions": [responder_handle],
            "ignore_mentions": ["@moderator"],
            "stream_handler": stream_handler,
        }
        response = await plugin.process_message(moderator_prompt, context=context)
        if stream_started:
            print("\n", end="", flush=True)
        return response.strip()


def ensure_mention_present(message: str, handle: str) -> str:
    stripped = message.strip()
    normalized_handle = handle.strip()
    if not normalized_handle.startswith("@"):
        normalized_handle = f"@{normalized_handle}"

    if normalized_handle.lower() in stripped.lower():
        return stripped

    if stripped:
        separator = "" if stripped.endswith((" ", "\t", "\n")) else " "
        return f"{stripped}{separator}{normalized_handle}"

    return normalized_handle


def collect_session_tags() -> list[str]:
    raw = os.getenv("SESSION_TAGS")
    if not raw:
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        trimmed = token.strip()
        if not trimmed:
            continue
        if not trimmed.startswith("#"):
            trimmed = f"#{trimmed}"
        lowered = trimmed.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tags.append(trimmed)
    return tags


def apply_session_tags(message: str, tags: list[str]) -> tuple[str, bool]:
    if not tags:
        return message, False

    lower_text = message.lower()
    missing: list[str] = [tag for tag in tags if tag.lower() not in lower_text]
    if not missing:
        return message, False

    tag_block = " ".join(missing)
    separator = "\n\n" if not message.endswith("\n") else "\n"
    return f"{message}{separator}{tag_block}", True


async def send_to_ax(
    message: str,
    config_path: str | None,
    server_name: str | None,
) -> tuple[bool, str]:
    resolved_path = config_path or get_default_config_path()
    if not resolved_path:
        raise ValueError("No MCP config path provided and none discovered via get_default_config_path().")

    cfg = parse_mcp_config(resolved_path, server_name)
    client = MCPClient(
        server_url=cfg.server_url,
        oauth_server=cfg.oauth_url,
        agent_name=cfg.agent_name,
        token_dir=cfg.token_dir,
    )
    try:
        success = await client.send_message(message)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    agent_handle = cfg.agent_name if cfg.agent_name.startswith("@") else f"@{cfg.agent_name}"
    return success, agent_handle


class EnvScope:
    """Async-friendly wrapper around temporary_env for convenience."""

    def __init__(self, **updates: str | None):
        self._updates = updates
        self._cm = temporary_env(**updates)

    async def __aenter__(self):
        self._cm.__enter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._cm.__exit__(exc_type, exc, tb)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Moderator prompt prototype")
    parser.add_argument("initiator", help="Handle of the initiating agent (e.g. @Prism)")
    parser.add_argument("responder", help="Handle of the responder agent (e.g. @HaloScript)")
    parser.add_argument(
        "--template",
        default="quantum_chat",
        help="Conversation template key to use (default: quantum_chat)",
    )
    parser.add_argument(
        "--plugin",
        default="ollama",
        help="Plugin to invoke (ollama, echo, etc.)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL"),
        help="Override Ollama model name (optional)",
    )
    parser.add_argument(
        "--base-prompt",
        dest="base_prompt",
        help="Optional path to a base system prompt that should always be prepended",
    )
    parser.add_argument(
        "--scenario-prompt",
        dest="scenario_prompt",
        help="Override the scenario-specific system prompt file",
    )
    parser.add_argument(
        "--plugin-config",
        dest="plugin_config",
        help="Path to a JSON file with plugin configuration overrides",
    )
    parser.add_argument(
        "--message",
        dest="message",
        help="Bypass generation and send this exact kickoff message",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the generated kickoff message to aX using MCP credentials",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to MCP config JSON (defaults to MCP_CONFIG_PATH or common locations)",
    )
    parser.add_argument(
        "--server-name",
        dest="config_server",
        help="Specific server name inside the MCP config to use",
    )
    return parser.parse_args()


def normalize_handle(handle: str) -> str:
    handle = handle.strip()
    if not handle:
        raise ValueError("Handle cannot be blank")
    return handle if handle.startswith("@") else f"@{handle}"


def load_plugin_config(path: str | None) -> Dict[str, Any] | None:
    if not path:
        return None
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


async def main() -> int:
    args = parse_args()
    initiator = normalize_handle(args.initiator)
    responder = normalize_handle(args.responder)
    plugin_config = load_plugin_config(args.plugin_config)

    templates = load_templates()
    if args.template not in templates:
        print(f"❌ Template '{args.template}' not found. Available: {', '.join(sorted(templates.keys()))}")
        return 1
    template = templates[args.template]

    print("🔧 Running moderator prompt prototype...")
    print(f"   Plugin: {args.plugin}")
    print(f"   Template: {args.template}")
    if args.model:
        print(f"   Model override: {args.model}")
    if args.base_prompt:
        print(f"   Base prompt override: {args.base_prompt}")
    elif os.getenv("OLLAMA_BASE_PROMPT_FILE"):
        print(f"   Base prompt (env): {os.getenv('OLLAMA_BASE_PROMPT_FILE')}")
    if args.scenario_prompt:
        print(f"   Scenario prompt override: {args.scenario_prompt}")
    if plugin_config:
        print(f"   Plugin config: {args.plugin_config}")
    if args.send:
        config_hint = args.config_path or get_default_config_path()
        print(f"   Send to aX: enabled (config={config_hint or 'auto-discover'})")

    moderator_prompt = None
    if args.message:
        candidate_message = args.message.strip()
        if not candidate_message:
            print("❌ Provided message is empty after trimming.")
            return 1
        print("\n🗒️  Skipping generation – using provided kickoff message.\n")
    else:
        try:
            candidate_message = await generate_initial_message(
                plugin_name=args.plugin,
                template_key=args.template,
                initiator_handle=initiator,
                responder_handle=responder,
                model=args.model,
                plugin_config=plugin_config,
                base_prompt_override=args.base_prompt,
                scenario_prompt_override=args.scenario_prompt,
            )
        except Exception as exc:
            print(f"❌ Failed to generate kickoff message: {exc}")
            return 1

        moderator_prompt = build_moderator_prompt(template, initiator, responder)
        print("\n🗒️  Sample moderator instruction that was sent to the plugin:\n")
        print(moderator_prompt)

        print("\n💬 Plugin suggested opening message:\n")
        print(candidate_message)

    final_message_with_mention = ensure_mention_present(candidate_message, responder)
    mention_added = final_message_with_mention != candidate_message

    session_tags = collect_session_tags()
    final_message, tags_appended = apply_session_tags(final_message_with_mention, session_tags)

    print("\n📤 Final kickoff message:\n")
    print(final_message)
    if mention_added or tags_appended:
        print("\nAdjustments applied:")
        if mention_added:
            print(" - Added missing responder mention.")
        if tags_appended:
            print(" - Appended required session tags.")
    else:
        print("\nAll required mentions and tags were already present.")

    if not args.send:
        print("\n💡 Add --send to deliver this message to aX automatically.")
        return 0

    print("\n🚀 Sending kickoff to aX...")
    try:
        success, config_agent = await send_to_ax(final_message, args.config_path, args.config_server)
    except Exception as exc:
        print(f"❌ Failed to send message: {exc}")
        return 1

    if not success:
        print("❌ MCP client returned failure when sending the message.")
        return 1

    print(f"✅ Message sent via agent credentials for {config_agent}.")
    if config_agent.lower() != initiator.lower():
        print(
            "⚠️  Note: MCP config agent differs from the initiator handle provided. "
            "Make sure this is intentional."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
