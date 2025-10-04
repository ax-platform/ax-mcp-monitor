"""Gemini plugin for aX MCP monitor - Simple chatbot integration."""

from __future__ import annotations

import logging
import os
import requests
from typing import Any, Dict, Optional

from .base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class GeminiPlugin(BasePlugin):
    """Simple Gemini API plugin - no LangGraph complexity."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Get API key from config or environment
        self.api_key = self.config.get("api_key") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Gemini API key missing. Set GEMINI_API_KEY in environment or plugin config."
            )

        # Configuration
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.model = self.config.get("model") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.temperature = float(self.config.get("temperature", 0.7))
        self.max_tokens = self.config.get("max_tokens")

        logger.info(f"Initialized Gemini plugin: model={self.model}, temperature={self.temperature}")

    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process message through Gemini API.

        Args:
            message: The incoming message text
            context: Optional context (user info, conversation history, etc.)

        Returns:
            Gemini's response
        """
        try:
            # Build API request
            url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

            # Prepare payload
            payload = {
                "contents": [{
                    "parts": [{"text": message}]
                }],
                "generationConfig": {
                    "temperature": self.temperature,
                }
            }

            # Add max tokens if specified
            if self.max_tokens:
                payload["generationConfig"]["maxOutputTokens"] = self.max_tokens

            # Make request
            logger.info(f"Sending to Gemini: {message[:100]}...")
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            # Extract response
            result = response.json()
            if "candidates" in result and result["candidates"]:
                answer = result["candidates"][0]["content"]["parts"][0]["text"]
                logger.info(f"Gemini response: {answer[:100]}...")
                return answer
            else:
                logger.error(f"Unexpected Gemini response: {result}")
                return "I received an unexpected response format from Gemini."

        except requests.exceptions.Timeout:
            logger.error("Gemini API timeout")
            return "Sorry, the request timed out. Please try again."

        except requests.exceptions.RequestException as e:
            logger.error(f"Gemini API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return f"Sorry, I encountered an error: {str(e)}"

        except Exception as e:
            logger.error(f"Unexpected error in Gemini plugin: {e}")
            return f"Sorry, an unexpected error occurred: {str(e)}"
