"""
Base plugin interface for aX MCP monitor bot.

All plugins should inherit from BasePlugin and implement process_message.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BasePlugin(ABC):
    """Base class for all message processing plugins."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the plugin with optional configuration.
        
        Args:
            config: Plugin-specific configuration dictionary
        """
        self.config = config or {}
        self.context = {}  # Plugin can maintain state here
    
    @abstractmethod
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process an incoming message and return a response.
        
        Args:
            message: The incoming message text
            context: Optional context (user info, conversation history, etc.)
            
        Returns:
            The response to send back
        """
        pass
    
    def get_name(self) -> str:
        """Return the plugin name."""
        return self.__class__.__name__
    
    def reset_context(self):
        """Reset any internal state/context."""
        self.context = {}