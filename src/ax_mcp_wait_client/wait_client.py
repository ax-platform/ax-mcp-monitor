import argparse
import asyncio
import glob
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

# Apply patches before importing MCP modules
from .mcp_patches import patch_mcp_library
patch_mcp_library()

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from .handlers import load_handlers, HandlerContext


class InMemoryTokenStorage(TokenStorage):
    def __init__(self) -> None:
        self._tokens: Optional[OAuthToken] = None
        self._client_info: Optional[OAuthClientInformationFull] = None

    async def get_tokens(self) -> Optional[OAuthToken]:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


class FileTokenStorage(TokenStorage):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = os.path.expanduser(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        self._token_path: Optional[str] = None
        self._client_info_path: Optional[str] = None
        # Allow explicit mcp-remote token file override
        self._explicit_file: Optional[str] = os.environ.get("MCP_TOKEN_FILE")

    def _find_latest(self, pattern: str) -> Optional[str]:
        paths = sorted(
            glob.glob(os.path.join(self.base_dir, pattern)),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        return paths[0] if paths else None

    def _token_file(self) -> str:
        # If an explicit token file is provided, prefer it
        if self._explicit_file:
            path = os.path.expanduser(self._explicit_file)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._token_path = path
            return path
        # Use mcp-remote directory structure like other MCP clients
        import glob as _glob
        candidates = []
        for pattern in ["mcp-remote-*/*_tokens.json"]:
            candidates.extend(_glob.glob(os.path.join(self.base_dir, pattern)))
        if candidates:
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            self._token_path = candidates[0]
            return candidates[0]
        # If no existing file, create a new one in mcp-remote directory
        mcp_dir = os.path.join(self.base_dir, "mcp-remote-0.1.18")
        os.makedirs(mcp_dir, exist_ok=True)
        # Generate a stable filename based on base_dir
        import hashlib as _hashlib
        client_id = _hashlib.md5(self.base_dir.encode()).hexdigest()
        token_path = os.path.join(mcp_dir, f"{client_id}_tokens.json")
        self._token_path = token_path
        return token_path

    def _client_info_file(self) -> str:
        # If using explicit mcp-remote token file, colocate client_info next to it
        if self._explicit_file:
            base = os.path.expanduser(self._explicit_file)
            if base.endswith("_tokens.json"):
                cand = base.replace("_tokens.json", "_client_info.json")
            else:
                cand = os.path.join(os.path.dirname(base), "client_info.json")
            os.makedirs(os.path.dirname(cand), exist_ok=True)
            self._client_info_path = cand
            return cand
        # Default stable filename in the configured directory
        cand = os.path.join(self.base_dir, "client_info.json")
        self._client_info_path = cand
        return cand

    async def get_tokens(self) -> Optional[OAuthToken]:
        try:
            path = self._token_file()
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OAuthToken.model_validate(data)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        path = self._token_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tokens.model_dump(mode="json"), f)
            try:
                f.flush(); os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        try:
            path = self._client_info_file()
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return OAuthClientInformationFull.model_validate(data)
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        path = self._client_info_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(client_info.model_dump(mode="json"), f)
            try:
                f.flush(); os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)


class _CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server, state_store):
        self._state_store = state_store
        super().__init__(request, client_address, server)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            self._state_store["authorization_code"] = params["code"][0]
            self._state_store["state"] = params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"""
                <html>
                  <body>
                    <h1>Authorization Successful</h1>
                    <p>You can close this window.</p>
                    <script>setTimeout(() => window.close(), 1000);</script>
                  </body>
                </html>
                """
            )
        elif "error" in params:
            self._state_store["error"] = params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"""
                <html>
                  <body>
                    <h1>Authorization Failed</h1>
                    <p>Error: {params['error'][0]}</p>
                  </body>
                </html>
                """.encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A003
        pass


class CallbackServer:
    def __init__(self, port: int = 3030) -> None:
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._state: dict[str, Any] = {
            "authorization_code": None,
            "state": None,
            "error": None,
        }

    def _make_handler(self):
        state = self._state

        class Handler(_CallbackHandler):
            def __init__(self, request, client_address, server):
                super().__init__(request, client_address, server, state)

        return Handler

    def start(self) -> None:
        handler = self._make_handler()
        self._server = HTTPServer(("localhost", self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[oauth] Callback server at http://localhost:{self.port}/callback")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=1)

    def wait_for_code(self, timeout_sec: int = 300) -> tuple[str, Optional[str]]:
        started = time.time()
        while time.time() - started < timeout_sec:
            if self._state.get("authorization_code"):
                return self._state["authorization_code"], self._state.get("state")
            if self._state.get("error"):
                raise RuntimeError(f"OAuth error: {self._state['error']}")
            time.sleep(0.1)
        raise TimeoutError("Timed out waiting for OAuth callback")


async def build_oauth_provider(
    oauth_server_url: str,
    redirect_port: int = 3030,
    token_dir: Optional[str] = None,
    interactive: bool = True,
    agent_name: Optional[str] = None,
) -> OAuthClientProvider:
    storage: TokenStorage = FileTokenStorage(token_dir) if token_dir else InMemoryTokenStorage()
    cb_server = CallbackServer(port=redirect_port)

    async def redirect_handler(authorization_url: str) -> None:
        if not interactive:
            raise RuntimeError(
                "Interactive OAuth disabled (--no-browser). Provide valid tokens via MCP_REMOTE_CONFIG_DIR or enable browser."
            )
        # Add agent_name to authorization URL if provided
        if agent_name:
            separator = "&" if "?" in authorization_url else "?"
            authorization_url = f"{authorization_url}{separator}agent_name={agent_name}"
        print(f"[oauth] Opening browser: {authorization_url}")
        cb_server.start()
        webbrowser.open(authorization_url)

    async def callback_handler() -> tuple[str, Optional[str]]:
        if not interactive:
            raise RuntimeError(
                "Interactive OAuth disabled (--no-browser). No callback will be accepted."
            )
        try:
            print("[oauth] Waiting for authorization...")
            code, state = cb_server.wait_for_code(timeout_sec=600)
            return code, state
        finally:
            cb_server.stop()

    provider = OAuthClientProvider(
        server_url=oauth_server_url,
        client_metadata=OAuthClientMetadata(
            client_name="aX MCP Wait Client",
            redirect_uris=[f"http://localhost:{redirect_port}/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            # Use server-provided scopes (via discovery) by default.
            # This avoids requesting an overly narrow scope like "user".
            scope=None,
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    # Proactively force refresh on first authenticated request when tokens exist.
    try:
        existing = await storage.get_tokens()
        existing_info = await storage.get_client_info()
        if existing and getattr(existing, "refresh_token", None) and existing_info:
            provider.context.token_expiry_time = 0
    except Exception:
        pass
    return provider


async def monitor_messages(
    server_url: str,
    oauth_server_url: str,
    agent_name: str,
    wait_mode: str,
    timeout_seconds: int,
    limit: int,
    mode: str,
    json_output: bool,
    token_dir: Optional[str],
    handler_specs: list[str],
    debug: bool = False,
    interactive_oauth: bool = True,
    once: bool = False,
):
    client_instance_id = str(uuid.uuid4())

    oauth = await build_oauth_provider(oauth_server_url, token_dir=token_dir, interactive=interactive_oauth, agent_name=agent_name)

    conn_timeout = timedelta(seconds=max(timeout_seconds + 30, 120))

    extra_headers = {
        "X-Agent-Name": agent_name,
        "X-Client-Instance": client_instance_id,
    }

    async def open_transport():
        # Pass headers directly - the SDK supports this
        return streamablehttp_client(
            url=server_url,
            headers=extra_headers,  # Headers must come before auth
            auth=oauth,
            timeout=conn_timeout,
        )

    handlers = load_handlers(handler_specs)
    ctx = HandlerContext(agent_name=agent_name, server_url=server_url)

    while True:
        try:
            async with (await open_transport()) as (read_stream, write_stream, get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    sid = get_session_id() if get_session_id else None
                    print(
                        f"connected server={server_url} agent={agent_name} sid={sid or 'n/a'} instance={client_instance_id}",
                        flush=True
                    )

                    # Track processed message IDs to avoid duplicate echoes across iterations
                    processed_ids: set[str] = set()
                    first_output_printed = False

                    while True:
                        try:
                            args = {
                                "action": "check",
                                "wait": True,
                                "wait_mode": wait_mode,
                                "timeout": max(timeout_seconds, 600),
                                "poll_interval": 60,
                                "limit": limit,
                                "mode": mode,
                            }
                            result = await session.call_tool("messages", arguments=args)

                            payload: Any
                            if getattr(result, "structuredContent", None):
                                payload = result.structuredContent
                            else:
                                texts: list[str] = []
                                for c in getattr(result, "content", []) or []:
                                    if getattr(c, "type", "") == "text" and hasattr(c, "text"):
                                        texts.append(c.text)
                                payload = "\n".join(texts) if texts else getattr(result, "__dict__", "")

                            if debug:
                                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                try:
                                    dbg = payload if isinstance(payload, (dict, list)) else str(payload)
                                    print(f"[{ts}] debug: raw payload keys={list(dbg.keys()) if isinstance(dbg, dict) else 'n/a'}", flush=True)
                                except Exception:
                                    pass

                            if json_output:
                                try:
                                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                                except Exception:
                                    print(json.dumps({"event": str(payload)}, ensure_ascii=False), flush=True)
                            else:
                                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                print(f"[{ts}] event: {payload}", flush=True)

                            extracted = _extract_messages(payload)
                            if debug:
                                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                print(f"[{ts}] debug: extracted {len(extracted)} message(s)", flush=True)

                            

                            for msg in extracted:
                                # Normalize id and content
                                parent_id = (
                                    msg.get("id")
                                    or msg.get("message_id")
                                    or msg.get("messageId")
                                    or msg.get("short_id")
                                    or msg.get("shortId")
                                )
                                raw_content = msg.get("content")
                                if isinstance(raw_content, dict):
                                    content = (
                                        raw_content.get("text")
                                        or raw_content.get("body")
                                        or raw_content.get("message")
                                        or ""
                                    )
                                else:
                                    content = (raw_content or msg.get("text") or msg.get("body") or "").strip()

                                if debug:
                                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                    print(f"[{ts}] debug: msg id={parent_id} content_len={len(content)}", flush=True)

                                if not parent_id or not content:
                                    continue

                                if parent_id in processed_ids:
                                    continue

                                for handler in handlers:
                                    try:
                                        handled = await handler.handle(session, {"id": parent_id, "content": content, **msg}, ctx)
                                        if handled:
                                            processed_ids.add(parent_id)
                                            # One-shot output and exit if requested
                                            if handled and once and not first_output_printed:
                                                # Print a concise success line with the message id and a short preview, then exit.
                                                preview = (content[:120] + "…") if len(content) > 120 else content
                                                ts2 = time.strftime("%Y-%m-%d %H:%M:%S")
                                                if json_output:
                                                    try:
                                                        print(json.dumps({"received": True, "id": parent_id, "content": content, "timestamp": ts2}, ensure_ascii=False), flush=True)
                                                    except Exception:
                                                        print(json.dumps({"received": True, "id": parent_id, "timestamp": ts2}, ensure_ascii=False), flush=True)
                                                else:
                                                    print(f"[{ts2}] received: id={parent_id} content=\"{preview}\"", flush=True)
                                                first_output_printed = True
                                                return
                                            break
                                    except Exception as ee:
                                        ets = time.strftime("%Y-%m-%d %H:%M:%S")
                                        mid = parent_id or "?"
                                        print(f"[{ets}] warn: handler error for {mid}: {ee}", flush=True)
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            ts = time.strftime("%Y-%m-%d %H:%M:%S")
                            print(f"[{ts}] warn: wait loop error: {e}")
                            await asyncio.sleep(2)
                            break

        except asyncio.CancelledError:
            raise
        except Exception as e:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] error: connection dropped: {e}; reconnecting in 3s...")
            await asyncio.sleep(3)


def _extract_messages(payload: Any) -> list[dict]:
    try:
        if not payload:
            return []
        data = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except Exception:
                return []
        if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
            data = data["result"]
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return [m for m in data["messages"] if isinstance(m, dict)]
        for key in ("events", "items", "data"):
            if isinstance(data, dict) and isinstance(data.get(key), list):
                out: list[dict] = []
                for it in data[key]:
                    if isinstance(it, dict):
                        if "message" in it and isinstance(it["message"], dict):
                            out.append(it["message"])
                        elif "content" in it and "id" in it:
                            out.append(it)
                if out:
                    return out
        return []
    except Exception:
        return []


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="aX MCP wait client (messages)")
    p.add_argument(
        "--server",
        default=os.environ.get("MCP_SERVER_URL", "http://localhost:8001/mcp"),
        help="MCP server URL (default: http://localhost:8001/mcp)",
    )
    p.add_argument(
        "--oauth-server",
        default=os.environ.get("MCP_OAUTH_SERVER_URL", "http://localhost:8001"),
        help="OAuth server base URL (default: http://localhost:8001)",
    )
    p.add_argument(
        "--agent-name",
        default=os.environ.get("MCP_AGENT_NAME", "mcp_client_local"),
        help="Agent name to identify this client (X-Agent-Name)",
    )
    p.add_argument(
        "--wait-mode",
        default=os.environ.get("MCP_WAIT_MODE", "mentions"),
        choices=["mentions", "urgent", "assigned", "direct", "all"],
        help="Wait mode for server-side blocking (default: mentions)",
    )
    p.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("MCP_WAIT_TIMEOUT", "600")),
        help="Server-side wait timeout per request (seconds)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("MCP_WAIT_LIMIT", "50")),
        help="Number of items to fetch when events arrive",
    )
    p.add_argument(
        "--mode",
        default=os.environ.get("MCP_WAIT_LIST_MODE", "unread"),
        choices=["latest", "unread"],
        help="messages.check mode to use (default: unread)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit events as compact JSON (one object per line)",
    )
    p.add_argument(
        "--token-dir",
        default=os.environ.get("MCP_REMOTE_CONFIG_DIR"),
        help="Directory to read/write OAuth tokens (compatible with mcp-remote)",
    )
    p.add_argument(
        "--handler",
        action="append",
        default=["echo"],
        help="Message handler(s): 'echo' or 'pkg.module:Class'. Can be repeated.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging for payloads and extraction",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Disable interactive OAuth (do not open browser). Requires valid tokens in MCP_REMOTE_CONFIG_DIR.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Exit after the first handled message (one-shot monitor)."
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    print(
        f"starting mcp-wait: server={args.server} oauth={args.oauth_server} agent={args.agent_name} wait_mode={args.wait_mode}",
        flush=True
    )
    try:
        asyncio.run(
            monitor_messages(
                server_url=args.server,
                oauth_server_url=args.oauth_server,
                agent_name=args.agent_name,
                wait_mode=args.wait_mode,
                timeout_seconds=args.timeout_seconds,
                limit=args.limit,
                mode=args.mode,
                json_output=args.json,
                token_dir=args.token_dir,
                handler_specs=args.handler,
                debug=args.debug,
                interactive_oauth=not args.no_browser,
                once=args.once,
            )
        )
        return 0
    except KeyboardInterrupt:
        print("\nstop: interrupted by user")
        return 130
    except Exception as e:
        print(f"fatal: {e}")
        return 1


def cli() -> None:
    raise SystemExit(main(sys.argv[1:]))
