"""
Ollama LLM plugin for aX MCP monitor bot.

Provides AI responses using Ollama's local LLM models.
"""

import os
from typing import Dict, Any, Optional
from openai import OpenAI
from .base_plugin import BasePlugin


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
        """
        super().__init__(config)
        
        # Get configuration with defaults
        self.base_url = self.config.get('base_url', os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1'))
        self.model = self.config.get('model', os.getenv('OLLAMA_MODEL', 'gpt-oss'))
        self.max_history = self.config.get('max_history', 10)
        
        # Initialize OpenAI client for Ollama
        self.client = OpenAI(base_url=self.base_url, api_key="ollama")
        
        # Initialize conversation history
        default_system = (
            "You are a helpful AI assistant on the aX platform. "
            "Keep responses concise (<=200 words). Use plain text only. "
            "This is a multi-agent environment: when the user's message specifies a recipient (e.g., '@codex' or 'reply to @codex'), "
            "start your FIRST line with exactly one mention of that recipient, like '@codex — <reply>'. "
            "If no recipient is specified, do not add a mention or routing header. "
            "Never duplicate mentions or include multiple headers."
        )
        system_prompt = self.config.get('system_prompt', default_system)
        self.messages_history = [
            {"role": "system", "content": system_prompt}
        ]
    
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process a message using Ollama LLM.
        
        Args:
            message: The incoming message
            context: Optional context (not used currently)
            
        Returns:
            The LLM response
        """
        # Add the new user message to history
        self.messages_history.append({"role": "user", "content": message})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages_history,
                timeout=30
            )
            
            # Get the response and add it to history
            reply = response.choices[0].message.content
            self.messages_history.append({"role": "assistant", "content": reply})
            
            # Keep conversation history manageable
            if len(self.messages_history) > (self.max_history * 2 + 1):  # system + N exchanges
                # Keep system message and last N exchanges
                self.messages_history[1:] = self.messages_history[-(self.max_history * 2):]
            
            return reply
            
        except Exception as e:
            return f"Error calling Ollama: {e}"
    
    def reset_context(self):
        """Reset conversation history, keeping only system prompt."""
        if self.messages_history:
            self.messages_history = self.messages_history[:1]  # Keep system prompt
