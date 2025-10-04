"""
Simple echo plugin for testing.

Just echoes back the message with a prefix.
"""

import re
from typing import Dict, Any, Optional
from .base_plugin import BasePlugin


class EchoPlugin(BasePlugin):
    """Simple plugin that echoes messages back."""
    
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Echo the message back with a prefix.
        
        Args:
            message: The incoming message
            context: Optional context including agent_name to avoid self-mentions
            
        Returns:
            The echoed message with self-mentions removed
        """
        # Remove our own agent handle to avoid self-mention violations
        clean_message = message
        if context and context.get("agent_name"):
            agent_name = context["agent_name"]
            # Remove @agentname (case insensitive)
            clean_message = re.sub(
                rf'@{re.escape(agent_name)}\b',
                '',
                clean_message,
                flags=re.IGNORECASE
            ).strip()
        
        return f"[Echo] You said: {clean_message}"