"""
Simple echo plugin for testing.

Just echoes back the message with a prefix.
"""

from typing import Dict, Any, Optional
from .base_plugin import BasePlugin


class EchoPlugin(BasePlugin):
    """Simple plugin that echoes messages back."""
    
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Echo the message back with a prefix.
        
        Args:
            message: The incoming message
            context: Optional context (not used)
            
        Returns:
            The echoed message
        """
        return f"[Echo] You said: {message}"