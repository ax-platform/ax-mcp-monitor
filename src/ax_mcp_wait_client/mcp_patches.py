"""Monkey patches for MCP library to handle non-compliant server responses."""

import json
import logging
from typing import Any, Optional
from mcp.types import JSONRPCMessage, JSONRPCError

logger = logging.getLogger(__name__)

# Store the original method
_original_validate_json = None

def patch_mcp_library():
    """Apply monkey patches to MCP library to handle server quirks."""
    global _original_validate_json
    
    # Only patch once
    if _original_validate_json is not None:
        return
    
    # Save the original method
    _original_validate_json = JSONRPCMessage.model_validate_json
    
    @classmethod
    def patched_model_validate_json(cls, json_data: str | bytes, **kwargs):
        """Patched version that fixes null IDs in error responses."""
        try:
            # Try to parse and fix the JSON
            data = json.loads(json_data)
            
            # Fix server bug: error responses with id:null
            if isinstance(data, dict) and "error" in data and data.get("id") is None:
                # Use a placeholder ID that won't match any real request
                data["id"] = "error-null-id-fixed"
                logger.debug(f"Fixed null id in error response: {data.get('error', {}).get('message', 'unknown')}")
                json_data = json.dumps(data)
            
            # Call the original method with the fixed data
            return _original_validate_json(json_data, **kwargs)
        except json.JSONDecodeError:
            # If it's not valid JSON, let the original method handle it
            return _original_validate_json(json_data, **kwargs)
        except Exception as e:
            # For any other error, try the original method
            logger.debug(f"Error in patched validation, falling back: {e}")
            return _original_validate_json(json_data, **kwargs)
    
    # Apply the monkey patch
    JSONRPCMessage.model_validate_json = patched_model_validate_json
    logger.info("Applied MCP library patches for server compatibility")

    # NOTE: We intentionally do NOT override OAuthClientProvider.async_auth_flow here
    # because the default implementation performs standards-compliant discovery.
    # Duplicates should be handled by server-side auth-before-side-effect or
    # idempotency, not by bypassing discovery.


def unpatch_mcp_library():
    """Remove monkey patches from MCP library."""
    global _original_validate_json
    
    if _original_validate_json is not None:
        JSONRPCMessage.model_validate_json = _original_validate_json
        _original_validate_json = None
        logger.info("Removed MCP library patches")

# Alias for compatibility
apply_patches = patch_mcp_library
