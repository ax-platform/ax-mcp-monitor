"""
Ollama LLM plugin for aX MCP monitor bot.

Provides AI responses using Ollama's local LLM models.
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional
from openai import OpenAI
from .base_plugin import BasePlugin


DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "ollama_monitor_system_prompt.txt"
MENTION_PATTERN = re.compile(r"@[0-9A-Za-z_\-]+")


def _read_prompt(path_like: Optional[str]) -> Optional[str]:
    """Load prompt text from a file path if provided."""
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
    """Extract the first @mention from the sender string."""
    if not sender:
        return None
    match = MENTION_PATTERN.search(sender)
    if match:
        return match.group(0)
    cleaned = re.sub(r"^✅\s*WAIT SUCCESS\s*—\s*", "", sender.strip(), flags=re.IGNORECASE)
    cleaned = cleaned.lstrip("-–—: ")
    if cleaned.startswith("@"):
        token = cleaned.split()[0].rstrip("—:,")
        return token
    return None


def _ensure_sender_prefix(reply: str, sender: Optional[str]) -> str:
    """Ensure the response starts with exactly one mention of the sender."""
    normalized = _normalize_sender(sender)
    cleaned = reply.strip()
    if not normalized:
        return cleaned
    if cleaned.lower().startswith(normalized.lower()):
        return cleaned
    stripped = cleaned.lstrip("-–—: ")
    return f"{normalized} — {stripped}"


class OllamaPlugin(BasePlugin):
    """Plugin that uses Ollama for LLM responses."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Ollama plugin.
        
        Config options:
            - base_url: Ollama API URL (default: http://localhost:11434/v1)
            - model: Model to use (default: gpt-oss)
            - max_history: Max conversation history to keep (default: 10 exchanges)
            - system_prompt: System prompt for the model
            - auto_mention: Whether to automatically prepend sender mentions (default: False)
            - thinking_tags: How to handle <think> tags ('show', 'hide', 'collapse', 'summary', default: 'show')
            - thinking_format: Format style for thinking tags ('block', 'inline', 'topic', default: 'block')
        """
        super().__init__(config)
        
        # Get configuration with defaults
        self.base_url = self.config.get('base_url', os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1'))
        self.model = self.config.get('model', os.getenv('OLLAMA_MODEL', 'gpt-oss'))
        self.max_history = self.config.get('max_history', 10)
        self.auto_mention = self.config.get('auto_mention', False)  # Default to natural responses
        
        # Thinking tag handling configuration
        self.thinking_tags = self.config.get('thinking_tags', 'show')  # 'show', 'hide', 'collapse', 'summary'
        self.thinking_format = self.config.get('thinking_format', 'block')  # 'block', 'inline', 'topic'
        
        # Initialize OpenAI client for Ollama
        self.client = OpenAI(base_url=self.base_url, api_key="ollama")
        
        # Initialize conversation history
        fallback_system = (
            "You are a helpful AI assistant operating on the aX platform, a collaborative network of agents and operators. "
            "Always start your first sentence with exactly one mention of the agent or person who addressed you (for example '@madtank — Thanks for the ping...'). "
            "When a message asks you to involve other agents (for example 'loop in @HaloScript'), mention those handles immediately after the sender in that first sentence and nowhere else. "
            "If you need someone's attention, you must @mention them so the turn is routed correctly; never rely on plain names alone. "
            "Keep responses friendly, practical, and under 200 words."
        )

        system_prompt = os.getenv('OLLAMA_SYSTEM_PROMPT')
        if not system_prompt:
            prompt_file = os.getenv('OLLAMA_SYSTEM_PROMPT_FILE') or self.config.get('system_prompt_file')
            system_prompt = _read_prompt(prompt_file)
        if not system_prompt:
            system_prompt = _read_prompt(str(DEFAULT_SYSTEM_PROMPT_PATH))
        if not system_prompt:
            system_prompt = self.config.get('system_prompt', fallback_system)

        self.messages_history = [
            {"role": "system", "content": system_prompt}
        ]
    
    def _extract_chunk_text(self, chunk: Any) -> str:
        """Extract text content from a streaming chunk."""
        try:
            choice = chunk.choices[0]
        except (AttributeError, IndexError):
            return ""

        delta = getattr(choice, "delta", None)
        if delta is not None:
            content = getattr(delta, "content", None)
            if content:
                if isinstance(content, list):
                    pieces = []
                    for part in content:
                        if isinstance(part, dict):
                            pieces.append(part.get("text", ""))
                        else:
                            pieces.append(str(part))
                    return "".join(pieces)
                return str(content)
            parts = getattr(delta, "parts", None)
            if isinstance(parts, list):
                pieces = []
                for part in parts:
                    if isinstance(part, dict):
                        pieces.append(part.get("text", ""))
                    else:
                        pieces.append(getattr(part, "text", "") or "")
                if pieces:
                    return "".join(pieces)
        message_obj = getattr(choice, "message", None)
        if message_obj is not None:
            content = getattr(message_obj, "content", None)
            if content:
                if isinstance(content, list):
                    return "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                return str(content)
        # Fallback attempt using model_dump if available
        try:
            data = chunk.model_dump(exclude_none=True)
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                text = delta.get("content")
                if text:
                    if isinstance(text, list):
                        return "".join(
                            part.get("text", "") if isinstance(part, dict) else str(part)
                            for part in text
                        )
                    return str(text)
        except AttributeError:
            pass
        return ""

    def _process_thinking_tags(self, reply: str) -> str:
        """
        Process thinking tags according to configuration.
        Handles both <think> tags and [Thinking]/[Answer] format.
        
        Args:
            reply: The raw AI response potentially containing thinking content
            
        Returns:
            Processed response based on thinking_tags and thinking_format settings
        """
        # Try to extract <think> tags first
        thinking_pattern = re.compile(r'<think>(.*?)</think>\s*', re.DOTALL)
        thinking_matches = thinking_pattern.findall(reply)
        main_response = thinking_pattern.sub('', reply).strip()
        
        # If no <think> tags, try [Thinking]/[Answer] format
        if not thinking_matches:
            # Look for [Thinking] ... [Answer] pattern
            bracket_pattern = re.compile(r'\[Thinking\](.*?)\[Answer\](.*)', re.DOTALL | re.IGNORECASE)
            bracket_match = bracket_pattern.search(reply)
            
            if bracket_match:
                thinking_content = bracket_match.group(1).strip()
                main_response = bracket_match.group(2).strip()
            else:
                # Look for standalone [Thinking] section at the start
                thinking_start_pattern = re.compile(r'^\[Thinking\](.*?)(?=@\w+|$)', re.DOTALL | re.IGNORECASE)
                thinking_start_match = thinking_start_pattern.search(reply)
                
                if thinking_start_match:
                    thinking_content = thinking_start_match.group(1).strip()
                    main_response = reply[thinking_start_match.end():].strip()
                else:
                    return reply  # No thinking content found
            
            thinking_matches = [thinking_content] if thinking_content else []
        
        if not thinking_matches:
            return reply  # No thinking content found
            
        thinking_content = '\n'.join(thinking_matches).strip()
        
        # Handle different thinking tag modes
        if self.thinking_tags == 'hide':
            return main_response
            
        elif self.thinking_tags == 'summary':
            # Extract key points from thinking (simple extraction)
            summary_lines = []
            for line in thinking_content.split('\n'):
                line = line.strip()
                if any(keyword in line.lower() for keyword in ['need to', 'should', 'will', 'plan to', 'going to']):
                    summary_lines.append(line)
            if summary_lines:
                summary = ' • '.join(summary_lines[:3])  # Limit to 3 key points
                formatted_thinking = f"💭 *AI Planning: {summary}*"
            else:
                formatted_thinking = "💭 *AI is thinking...*"
                
        elif self.thinking_tags == 'collapse':
            # Create collapsible format
            lines = len(thinking_content.split('\n'))
            formatted_thinking = f"💭 *[AI Reasoning - {lines} thoughts]* #AIthinking"
            
        else:  # 'show' (default)
            # Format thinking tags nicely based on format style
            if self.thinking_format == 'topic':
                formatted_thinking = f"#AIthinking 💭 **Reasoning Process:**\n{thinking_content}"
            elif self.thinking_format == 'inline':
                formatted_thinking = f"💭 *(Thinking: {thinking_content.replace(chr(10), ' ')})*"
            else:  # 'block' (default)
                formatted_thinking = f"💭 **AI Reasoning:**\n```\n{thinking_content}\n```"
        
        # Combine thinking and response
        if main_response:
            return f"{formatted_thinking}\n\n{main_response}"
        else:
            return formatted_thinking
    
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process a message using Ollama LLM.
        
        Args:
            message: The incoming message
            context: Optional context (sender, agent name, etc.)
            
        Returns:
            The LLM response
        """
        metadata: Dict[str, Any] = context or {}
        sender = metadata.get("sender")
        agent_name = metadata.get("agent_name")

        normalized_sender = _normalize_sender(sender)
        prompt_sender = normalized_sender or (sender.strip() if isinstance(sender, str) else None)

        # Blend sender info into the conversation history so the LLM knows who spoke.
        if prompt_sender:
            formatted_message = f"{prompt_sender} says:\n{message}"
        else:
            formatted_message = message

        if agent_name:
            agent_handle = agent_name if str(agent_name).startswith("@") else f"@{agent_name}"
            if agent_handle not in formatted_message:
                formatted_message = f"[For {agent_handle}]\n{formatted_message}"

        self.messages_history.append({"role": "user", "content": formatted_message})

        stream_handler = metadata.get("stream_handler")
        loop = asyncio.get_running_loop()

        def _invoke_model() -> str:
            try:
                if stream_handler:
                    accumulated: list[str] = []
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages_history,
                        stream=True,
                        timeout=45,
                    )
                    for chunk in response:
                        piece = self._extract_chunk_text(chunk)
                        if not piece:
                            continue
                        accumulated.append(piece)
                        try:
                            future = asyncio.run_coroutine_threadsafe(stream_handler(piece), loop)
                            future.result()
                        except Exception:
                            # Ignore streaming handler errors to avoid blocking reply generation
                            pass
                    return "".join(accumulated)
                else:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages_history,
                        timeout=45,
                    )
                    return response.choices[0].message.content
            except Exception as exc:
                raise exc

        try:
            raw_reply = await asyncio.to_thread(_invoke_model)
        except Exception as e:
            return f"Error calling Ollama: {e}"

        # Get the response and process thinking tags
        reply = raw_reply or ""

        # Fix curly brace mentions: @{username} -> @username
        reply = re.sub(r'@\{([^}]+)\}', r'@\1', reply)

        # Fix spaced mentions: @ username -> @username
        reply = re.sub(r'@\s+([A-Za-z0-9_]+)', r'@\1', reply)
        
        # Process thinking tags according to configuration
        reply = self._process_thinking_tags(reply)
        
        if self.auto_mention:
            reply = _ensure_sender_prefix(reply, normalized_sender)
        self.messages_history.append({"role": "assistant", "content": reply})
        
        # Keep conversation history manageable
        if len(self.messages_history) > (self.max_history * 2 + 1):  # system + N exchanges
            # Keep system message and last N exchanges
            self.messages_history[1:] = self.messages_history[-(self.max_history * 2):]
        
        return reply
    
    def reset_context(self):
        """Reset conversation history, keeping only system prompt."""
        if self.messages_history:
            self.messages_history = self.messages_history[:1]  # Keep system prompt
