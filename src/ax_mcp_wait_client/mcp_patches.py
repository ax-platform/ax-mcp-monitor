"""Monkey patches for MCP library to handle non-compliant server responses."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from mcp.client.streamable_http import StreamableHTTPTransport
from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)

_original_validate_json: Callable[..., JSONRPCMessage] | None = None
_original_handle_sse_event: Callable[..., Awaitable[bool]] | None = None
_original_handle_post_request: Callable[..., Awaitable[None]] | None = None


def patch_mcp_library() -> None:
    """Apply monkey patches to MCP library to handle server quirks."""

    global _original_validate_json, _original_handle_sse_event, _original_handle_post_request

    if _original_validate_json is None:
        _original_validate_json = JSONRPCMessage.model_validate_json

        @classmethod
        def patched_model_validate_json(cls, json_data: str | bytes, **kwargs: Any) -> JSONRPCMessage:
            # Skip completely empty keep-alive payloads
            if isinstance(json_data, bytes):
                text = json_data.decode("utf-8", "ignore")
            else:
                text = str(json_data)

            if not text.strip():
                raise ValueError("Empty SSE payload")

            try:
                data = json.loads(text)
                if isinstance(data, dict) and "error" in data and data.get("id") is None:
                    data["id"] = "error-null-id-fixed"
                    logger.debug(
                        "Fixed null id in error response: %s",
                        data.get("error", {}).get("message", "unknown"),
                    )
                    text = json.dumps(data)
            except ValueError:
                # json.loads failed; fall through to original handler
                pass

            return _original_validate_json(text, **kwargs)  # type: ignore[arg-type]

        JSONRPCMessage.model_validate_json = patched_model_validate_json  # type: ignore[assignment]
        logger.info("Applied JSON validation patch for MCP stream handling")

    if _original_handle_sse_event is None:
        _original_handle_sse_event = StreamableHTTPTransport._handle_sse_event

        async def patched_handle_sse_event(
            self,
            sse,
            read_stream_writer,
            original_request_id=None,
            resumption_callback=None,
            is_initialization: bool = False,
        ) -> bool:
            data = getattr(sse, "data", "")
            if sse.event == "message" and (data is None or not str(data).strip()):
                logger.debug("Skipping empty SSE frame from streamable HTTP")
                return False

            try:
                return await _original_handle_sse_event(
                    self,
                    sse,
                    read_stream_writer,
                    original_request_id,
                    resumption_callback,
                    is_initialization,
                )
            except ValueError as exc:
                # Raised when our patched JSON validator encounters an empty payload
                logger.debug("Ignored SSE frame due to empty payload: %s", exc)
                return False

        StreamableHTTPTransport._handle_sse_event = patched_handle_sse_event  # type: ignore[assignment]
        logger.info("Applied SSE handler patch for MCP stream handling")

    if _original_handle_post_request is None:
        _original_handle_post_request = StreamableHTTPTransport._handle_post_request

        async def patched_handle_post_request(self, ctx):
            self._connection_start_ts = time.time()
            try:
                await _original_handle_post_request(self, ctx)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                if status == httpx.codes.GATEWAY_TIMEOUT:
                    elapsed = time.time() - getattr(self, "_connection_start_ts", time.time())
                    logger.info(
                        "StreamableHTTP long poll timed out after %.1fs (HTTP %s). Reissuing wait.",
                        elapsed,
                        status,
                    )
                    try:
                        await ctx.read_stream_writer.send(exc)
                    except Exception:
                        logger.debug("Failed to forward HTTP 504 to read stream")
                else:
                    logger.warning("StreamableHTTP POST failed with %s: %s", status, exc)
                    try:
                        await ctx.read_stream_writer.send(exc)
                    except Exception:
                        logger.debug("Failed to forward HTTP error to read stream")

        StreamableHTTPTransport._handle_post_request = patched_handle_post_request  # type: ignore[assignment]
        logger.info("Applied POST handler patch for MCP stream handling")


def unpatch_mcp_library() -> None:
    """Remove monkey patches from MCP library."""

    global _original_validate_json, _original_handle_sse_event

    if _original_validate_json is not None:
        JSONRPCMessage.model_validate_json = _original_validate_json  # type: ignore[assignment]
        _original_validate_json = None
        logger.info("Removed JSON validation patch")

    if _original_handle_sse_event is not None:
        StreamableHTTPTransport._handle_sse_event = _original_handle_sse_event  # type: ignore[assignment]
        _original_handle_sse_event = None
        logger.info("Removed SSE handler patch")

    global _original_handle_post_request
    if _original_handle_post_request is not None:
        StreamableHTTPTransport._handle_post_request = _original_handle_post_request  # type: ignore[assignment]
        _original_handle_post_request = None
        logger.info("Removed POST handler patch")


# Alias for backwards compatibility
apply_patches = patch_mcp_library
