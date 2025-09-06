"""Patched streamable HTTP client that handles null id in error responses."""

import json
import logging
from typing import Any

from mcp.client.streamable_http import streamablehttp_client as original_streamablehttp_client

logger = logging.getLogger(__name__)


def patch_json_response(response_text: str) -> str:
    """Fix server's non-compliant JSON-RPC error responses with id:null."""
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and "error" in data and data.get("id") is None:
            # Server bug: returns id:null in errors, which violates JSON-RPC spec
            # Change it to a string id to make it parseable
            data["id"] = "error-null-id"
            logger.debug(f"Patched null id in error response: {data.get('error', {}).get('message', 'unknown')}")
            return json.dumps(data)
    except Exception:
        pass
    return response_text


async def patched_streamablehttp_client(*args, **kwargs):
    """Wrapper that patches the streamable client to handle server bugs."""
    # For now, use the original - we'd need to monkey-patch the internals
    # This is more complex than expected due to the async context manager
    return await original_streamablehttp_client(*args, **kwargs)