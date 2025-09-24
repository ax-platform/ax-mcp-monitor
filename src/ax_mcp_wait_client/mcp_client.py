#!/usr/bin/env python3
"""
Persistent MCP client with bearer refresh, expiry checks, and 401 backoff.
"""

import os
import json
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from ax_mcp_wait_client.bearer_refresh import BearerTokenStore, MCPBearerAuth

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages tokens on disk with proactive refresh and expiry checks."""

    def __init__(
        self,
        token_dir: str,
        oauth_server: str = "http://localhost:8001",
        refresh_interval_seconds: int = 600,
        skew_seconds: int = 60,
    ) -> None:
        self.token_dir = Path(token_dir)
        self.oauth_server = oauth_server
        self.refresh_interval = refresh_interval_seconds
        self.skew = skew_seconds
        self.last_refresh = 0.0
        self._token_cache: Optional[Dict[str, Any]] = None
        self._selected_path: Optional[Path] = None

    def _token_file(self) -> Optional[Path]:
        # Prefer mcp-remote versioned files like other MCP clients
        candidates: list[Path] = []
        for subdir in self.token_dir.glob("mcp-remote-*"):
            candidates.extend(subdir.glob("*_tokens.json"))
        if candidates:
            # Choose most recent by mtime
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        # No fallback to root tokens.json - only use mcp-remote directory
        return None

    def load_tokens(self) -> Optional[Dict[str, Any]]:
        path = self._token_file()
        if not path:
            logger.error(f"No token file found in {self.token_dir}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._token_cache = data
            self._selected_path = path
            return data
        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            return None

    def save_tokens(self, tokens: Dict[str, Any]) -> bool:
        # Write back only to the source file we loaded from mcp-remote directory
        # Never create a root tokens.json
        if not self._selected_path:
            logger.error("No token file selected - cannot save tokens")
            return False
        primary = self._selected_path
        try:
            primary.parent.mkdir(parents=True, exist_ok=True)
            with open(primary, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
            self._token_cache = tokens
            # Never mirror to root tokens.json
            return True
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
            return False

    def _parse_expires_at(self, tokens: Dict[str, Any]) -> Optional[float]:
        exp = tokens.get("expires_at")
        if exp is None:
            # Support expires_in + refreshed_at fallback
            expires_in = tokens.get("expires_in")
            refreshed_at = tokens.get("refreshed_at")
            if isinstance(expires_in, (int, float)) and isinstance(refreshed_at, (int, float)):
                return float(refreshed_at) + float(expires_in)
            return None
        if isinstance(exp, (int, float)):
            return float(exp)
        if isinstance(exp, str):
            try:
                # Try RFC3339
                dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return None
        return None

    def _should_refresh_now(self, tokens: Optional[Dict[str, Any]], now: float, force: bool) -> bool:
        if force:
            return True
        if not tokens:
            return True
        # If we refreshed very recently and have no expiry info, skip
        if (now - self.last_refresh) < self.refresh_interval and not tokens.get("expires_at"):
            return False
        exp_ts = self._parse_expires_at(tokens)
        if exp_ts is None:
            # No expiry info: rely on interval
            return (now - self.last_refresh) >= self.refresh_interval
        # Refresh when within skew window
        return now >= (exp_ts - self.skew)

    def refresh_token(self, force: bool = False) -> Optional[str]:
        now = time.time()
        always_reread = os.getenv("MCP_TOKEN_ALWAYS_REREAD", "0") == "1"
        if force or always_reread or self._token_cache is None:
            tokens = self.load_tokens()
        else:
            tokens = self._token_cache

        if not self._should_refresh_now(tokens, now, force):
            return tokens.get("access_token") if tokens else None

        if not tokens or not tokens.get("refresh_token"):
            logger.error("No refresh token available")
            return None

        url = f"{self.oauth_server}/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": "MCP CLI Proxy",
        }
        try:
            resp = httpx.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                new_tokens = resp.json()
                tokens.update(new_tokens)
                tokens["refreshed_at"] = int(now)
                if self.save_tokens(tokens):
                    self.last_refresh = now
                    logger.info("Token refreshed successfully")
                    return tokens.get("access_token")
            else:
                logger.error(f"Token refresh failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
        return None

    def get_access_token(self) -> Optional[str]:
        return self.refresh_token(force=False)


class MCPClient:
    """Persistent MCP client with single connection and backoff on 401."""

    def __init__(
        self,
        server_url: str = "http://localhost:8001/mcp",
        oauth_server: str = "http://localhost:8001",
        agent_name: str = "mcp_client_local",
        token_dir: Optional[str] = None,
        token_refresh_seconds: int = 600,
        heartbeat_interval: Optional[int] = None,
        heartbeat_timeout: Optional[int] = None,
    ) -> None:
        self.server_url = server_url
        self.agent_name = agent_name
        self._lock = asyncio.Lock()
        self._connected = False
        self._start_ts = time.time()
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._last_heartbeat = 0.0

        if not token_dir:
            token_dir = os.getenv("MCP_REMOTE_CONFIG_DIR")
            if not token_dir:
                raise ValueError("token_dir or MCP_REMOTE_CONFIG_DIR must be set")

        self.token_manager = TokenManager(
            token_dir=token_dir,
            oauth_server=oauth_server,
            refresh_interval_seconds=token_refresh_seconds,
        )
        self.oauth_server = oauth_server
        self.token_dir = token_dir

        # Connection state
        self._stream_ctx = None
        self.read = None
        self.write = None
        self.get_sid = None
        self.session: Optional[ClientSession] = None
        self.client_instance = None
        self.session_id = None
        
        # Serialize access to the messages tool so long polls and heartbeats
        # never collide on the same transport.
        self._request_lock = asyncio.Lock()
        self._current_request_label: Optional[str] = None
        self._current_request_started: float = 0.0
        self._last_request_completed: float = 0.0
        self._long_poll_active = False
        # Default long-poll guard to 20 minutes; override via MCP_LONG_POLL_TIMEOUT env.
        self.long_poll_timeout = int(os.getenv("MCP_LONG_POLL_TIMEOUT", "1200"))
        self._disconnected_since: Optional[float] = None

        # Heartbeat behaviour (env overrides win when explicit values are None)
        interval_env = os.getenv("MCP_HEARTBEAT_INTERVAL", "45")
        timeout_env = os.getenv("MCP_HEARTBEAT_TIMEOUT", "15")
        try:
            default_interval = int(interval_env)
        except ValueError:
            default_interval = 45
        try:
            default_timeout = int(timeout_env)
        except ValueError:
            default_timeout = 15

        self.heartbeat_interval = (
            heartbeat_interval if heartbeat_interval is not None else default_interval
        )
        self.heartbeat_timeout = (
            heartbeat_timeout if heartbeat_timeout is not None else default_timeout
        )

    async def connect(self) -> bool:
        async with self._lock:
            if self._connected and self.session:
                return True

            import uuid
            self.client_instance = str(uuid.uuid4())
            headers = {
                "X-Agent-Name": self.agent_name,
                "X-Client-Instance": self.client_instance,
            }
            if self.session_id:
                headers["mcp-session-id"] = self.session_id

            try:
                # Choose auth strategy: bearer via MCPBearerAuth when MCP_BEARER_MODE=1, else header with manual refresh
                auth_obj = None
                if os.getenv("MCP_BEARER_MODE", "0") == "1":
                    store = BearerTokenStore(self.token_dir)
                    if not store.token_file():
                        logger.error("No bearer token file found. Set MCP_TOKEN_FILE or ensure mcp-remote tokens exist.")
                        return False
                    auth_obj = MCPBearerAuth(store, self.oauth_server)
                else:
                    access_token = self.token_manager.get_access_token()
                    if not access_token:
                        logger.error("Failed to get access token")
                        return False
                    headers["Authorization"] = f"Bearer {access_token}"

                self._stream_ctx = streamablehttp_client(
                    url=self.server_url,
                    headers=headers,
                    auth=auth_obj,
                    timeout=timedelta(seconds=180),
                )
                self.read, self.write, self.get_sid = await self._stream_ctx.__aenter__()
                if self.get_sid:
                    sid = self.get_sid()
                    if sid and sid != self.session_id:
                        self.session_id = sid
                        logger.info(f"session id: {self.session_id}")

                self.session = ClientSession(self.read, self.write)
                await self.session.__aenter__()
                # Suppress transient transport parse errors during early startup
                _stream_logger = logging.getLogger('mcp.client.streamable_http')
                _prev_level = _stream_logger.level
                if (time.time() - getattr(self, '_start_ts', time.time())) < 10:
                    _stream_logger.setLevel(logging.CRITICAL)
                try:
                    await self.session.initialize()
                finally:
                    try:
                        _stream_logger.setLevel(_prev_level)
                    except Exception:
                        pass
                self._connected = True
                self._start_heartbeat()
                if self._disconnected_since:
                    downtime = max(0.0, time.time() - self._disconnected_since)
                    print(f"🔗 Reconnected to MCP server in {downtime*1000:.0f} ms")
                    self._disconnected_since = None
                return True
            except Exception as e:
                status = None
                if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                    status = e.response.status_code
                logger.error(f"Connection failed: {e}")
                if status == 401:
                    logger.warning("401 during connect; attempting token refresh")
                    self.token_manager.refresh_token(force=True)
                await self.disconnect()
                return False

    async def disconnect(self) -> None:
        async with self._lock:
            await self._stop_heartbeat()
            if self.session:
                try:
                    await self.session.__aexit__(None, None, None)
                except Exception:
                    pass
                self.session = None
            if self._stream_ctx:
                try:
                    await self._stream_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
                self._stream_ctx = None
            self.read = self.write = self.get_sid = None
            self._connected = False
            self._last_heartbeat = 0.0
            self._disconnected_since = time.time()

    @asynccontextmanager
    async def _request_guard(self, label: str, *, long_poll: bool = False):
        """Serialize message tool calls and capture request telemetry."""

        await self._request_lock.acquire()
        self._current_request_label = label
        self._current_request_started = time.time()
        if long_poll:
            self._long_poll_active = True
        try:
            yield
        finally:
            if long_poll:
                self._long_poll_active = False
            self._last_request_completed = time.time()
            self._current_request_label = None
            self._request_lock.release()

    def has_inflight_request(self) -> bool:
        """Return True when any messages call is currently active."""

        return self._request_lock.locked()

    def is_long_poll_active(self) -> bool:
        return self._long_poll_active

    def request_snapshot(self) -> Dict[str, Any]:
        now = time.time()
        label = self._current_request_label
        started = self._current_request_started if label else None
        elapsed = (now - started) if started else 0.0
        return {
            "inflight": self._request_lock.locked(),
            "label": label,
            "started_at": started,
            "elapsed": round(elapsed, 3),
            "last_completed": self._last_request_completed,
            "long_poll": self._long_poll_active,
            "session_id": self.session_id,
            "last_heartbeat": self._last_heartbeat,
        }

    def _start_heartbeat(self) -> None:
        if self.heartbeat_interval <= 0:
            return
        if self._heartbeat_task and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        task = self._heartbeat_task
        if not task:
            return
        self._heartbeat_task = None
        task.cancel()
        if asyncio.current_task() is task:
            # Avoid awaiting on ourselves; cancellation will unwind naturally.
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Heartbeat task closed with error: %s", exc)

    async def _heartbeat_loop(self) -> None:
        # Lightweight keep-alive that leverages MCP ping when available, otherwise
        # falls back to a zero-wait message check to touch the transport.
        try:
            while True:
                await asyncio.sleep(max(1, self.heartbeat_interval))

                if not self._connected or not self.session:
                    continue

                try:
                    start = time.time()
                    await asyncio.wait_for(
                        self._send_ping(), timeout=max(1, self.heartbeat_timeout)
                    )
                    latency_ms = (time.time() - start) * 1000
                    if latency_ms < 1:
                        latency_ms = 1
                    print(f"💓 Heartbeat ok ({latency_ms:.0f} ms)")
                    self._last_heartbeat = time.time()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Heartbeat ping failed: %s", exc)
                    print(f"💔 Heartbeat failed: {exc}")
                    print("💔 Heartbeat failed – closing stream for reconnect")
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 401:
                        logger.warning("401 during heartbeat; refreshing token")
                        self.token_manager.refresh_token(force=True)
                    # Proactively drop transport so the next operation reconnects.
                    await self.disconnect()
                    return
        except asyncio.CancelledError:
            pass

    async def _send_ping(self) -> None:
        if not self.session:
            return

        if self._request_lock.locked():
            logger.debug("Skipping heartbeat ping; another request is in flight")
            return

        async with self._request_guard("heartbeat.ping"):
            # Prefer the explicit ping method when the SDK provides it.
            ping_method = getattr(self.session, "ping", None)
            if callable(ping_method):
                await ping_method()
                return

            # Fallback: run a zero-wait message check to keep the stream warm.
            payload = {
                "action": "check",
                "wait": False,
                "mode": "latest",
                "limit": 0,
            }
            await self.session.call_tool("messages", payload)

    async def _preflight_locked(self) -> None:
        if not self.session:
            return
        try:
            _stream_logger = logging.getLogger('mcp.client.streamable_http')
            _prev_level = _stream_logger.level
            if (time.time() - self._start_ts) < 10:
                _stream_logger.setLevel(logging.CRITICAL)
            await self.session.call_tool(
                "messages",
                {"action": "check", "wait": False, "mode": "latest", "limit": 0},
            )
            await asyncio.sleep(0.2)
        except Exception:
            # ignore preflight errors; main call will handle
            pass
        finally:
            try:
                _stream_logger.setLevel(_prev_level)
            except Exception:
                pass

    async def check_messages(self, wait: bool = False, timeout: int = 60, limit: int = 5) -> Optional[str]:
        backoff = 1.0
        for attempt in range(5):
            if not await self.connect():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            try:
                res = None
                request_id = None
                async with self._request_guard("messages.check", long_poll=wait):
                    _stream_logger = logging.getLogger('mcp.client.streamable_http')
                    _prev_level = _stream_logger.level
                    if (time.time() - self._start_ts) < 10 and attempt == 0:
                        _stream_logger.setLevel(logging.CRITICAL)
                    try:
                        request_id = getattr(self.session, "_request_id", None)
                        call_started = time.time()
                        effective_timeout = timeout
                        if wait:
                            effective_timeout = min(timeout or self.long_poll_timeout, self.long_poll_timeout)
                        call_kwargs = {
                            "action": "check",
                            "wait": wait,
                            "wait_mode": "mentions" if wait else None,
                            "timeout": effective_timeout if wait else None,
                            "mode": "latest",
                            "limit": limit,
                        }

                        async def _do_call():
                            return await self.session.call_tool("messages", call_kwargs)

                        if wait:
                            guard_timeout = self.long_poll_timeout + 5
                            res = await asyncio.wait_for(
                                _do_call(),
                                timeout=guard_timeout,
                            )
                        else:
                            res = await _do_call()
                        call_duration = time.time() - call_started
                        if wait:
                            print(
                                f"📡 Long poll completed in {call_duration:.1f}s"
                            )
                    finally:
                        try:
                            _stream_logger.setLevel(_prev_level)
                        except Exception:
                            pass

                text = None
                if res is not None:
                    for c in getattr(res, "content", []) or []:
                        if getattr(c, "type", "") == "text" and hasattr(c, "text"):
                            text = c.text
                            break
                    if text:
                        return text
                    return str(getattr(res, "__dict__", res))
                return None
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                logger.warning(
                    "HTTP %s while checking messages: %s", status, exc
                )
                if status == 401:
                    logger.warning("401 while checking messages; refreshing token")
                    self.token_manager.refresh_token(force=True)
                    await asyncio.shield(self.disconnect())
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                if status is not None and status >= 500:
                    await asyncio.shield(self.disconnect())
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except asyncio.CancelledError as exc:
                logger.warning("Check messages cancelled (transport reset): %s", exc)
                await self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except asyncio.TimeoutError as exc:
                logger.warning("Check messages timed out awaiting response: %s", exc)
                elapsed = 0.0
                if 'call_started' in locals():
                    elapsed = time.time() - call_started
                print(
                    "⏳ Long poll guard tripped after "
                    f"{elapsed:.1f}s (limit {self.long_poll_timeout}s); reconnecting"
                )
                await self._cancel_request(request_id, "timeout")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except Exception as e:
                msg = str(e)
                if "401" in msg:
                    logger.warning("401 on check; refreshing token with backoff")
                    self.token_manager.refresh_token(force=True)
                    await asyncio.shield(self.disconnect())
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                if "ValidationError" in msg or "Error parsing JSON response" in msg:
                    logger.debug(f"Check messages early-startup noise: {e}")
                else:
                    logger.error(f"Check messages failed: {e}")
                await self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
        return None

    async def send_message(self, message: str) -> bool:
        import uuid
        idem_key = str(uuid.uuid4())
        backoff = 1.0
        for attempt in range(5):
            if not await self.connect():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            try:
                res = None
                request_id = None
                async with self._request_guard("messages.send"):
                    await self._preflight_locked()
                    _stream_logger = logging.getLogger('mcp.client.streamable_http')
                    _prev_level = _stream_logger.level
                    if (time.time() - self._start_ts) < 10 and attempt == 0:
                        _stream_logger.setLevel(logging.CRITICAL)
                    try:
                        request_id = getattr(self.session, "_request_id", None)
                        res = await self.session.call_tool(
                            "messages",
                            {"action": "send", "content": message, "idempotency_key": idem_key},
                        )
                    finally:
                        try:
                            _stream_logger.setLevel(_prev_level)
                        except Exception:
                            pass

                # Consider any response a success; server-side idempotency should dedupe
                text = None
                if res is not None:
                    for c in getattr(res, "content", []) or []:
                        if getattr(c, "type", "") == "text" and hasattr(c, "text"):
                            text = c.text
                            break
                logger.info(f"message sent (idem={idem_key}) -> {text or 'ok'}")
                return True
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                logger.warning(
                    "HTTP %s while sending message: %s", status, exc
                )
                if status == 401:
                    logger.warning("401 while sending message; refreshing token")
                    self.token_manager.refresh_token(force=True)
                    await asyncio.shield(self.disconnect())
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                if status is not None and status >= 500:
                    await asyncio.shield(self.disconnect())
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except asyncio.CancelledError as exc:
                logger.warning("Send message cancelled (transport reset): %s", exc)
                await self.disconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except asyncio.TimeoutError as exc:
                logger.warning("Send message timed out awaiting result: %s", exc)
                await self._cancel_request(request_id, "timeout")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
                continue
            except Exception as e:
                msg = str(e)
                if "401" in msg:
                    logger.warning("401 on send; refreshing token with backoff")
                    self.token_manager.refresh_token(force=True)
                    await asyncio.shield(self.disconnect())
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10)
                    continue
                logger.error(f"Send message failed: {e}")
                await asyncio.shield(self.disconnect())
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
            finally:
                try:
                    _stream_logger.setLevel(_prev_level)
                except Exception:
                    pass
        return False

    async def _cancel_request(self, request_id: Any, reason: str) -> None:
        """Issue a cancellation notification for an in-flight request."""
        if not self.session or request_id is None:
            return

        async def _send_cancel() -> None:
            try:
                from mcp import types

                cancel_id = request_id if isinstance(request_id, int) else request_id
                notification = types.CancelledNotification(
                    params=types.CancelledNotificationParams(requestId=cancel_id, reason=reason)
                )
                await self.session.send_notification(notification)
            except asyncio.CancelledError:
                logger.debug("Cancellation notification aborted: session closing")
            except Exception as exc:
                logger.debug("Failed to send cancellation notification: %s", exc)

        try:
            asyncio.create_task(_send_cancel())
        except RuntimeError:
            # Event loop may be shutting down; best-effort only
            pass


    async def simple_example() -> None:
        logging.basicConfig(level=logging.INFO)
        client = MCPClient(token_refresh_seconds=600)
        ok = await client.send_message("[MCPClient] Test message from persistent client")
        print(f"Result: {ok}")


if __name__ == "__main__":
    asyncio.run(simple_example())
