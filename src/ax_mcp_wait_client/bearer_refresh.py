from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class BearerTokenStore:
    """Load/save and refresh bearer tokens from mcp-remote token files.

    - Prefers explicit MCP_TOKEN_FILE if set
    - Else chooses most-recent file under <MCP_REMOTE_CONFIG_DIR>/mcp-remote-*/ *_tokens.json
    - No fallback to root tokens.json - only uses mcp-remote directory structure
    - Supports proactive token refresh based on expiry time
    """

    def __init__(self, base_dir: str, refresh_buffer_seconds: int = 60) -> None:
        self.base_dir = Path(os.path.expanduser(base_dir))
        self.explicit_file = os.getenv("MCP_TOKEN_FILE")
        self._selected: Optional[Path] = None
        self._token_cache: Optional[Dict[str, Any]] = None
        self._last_load_time: float = 0
        self.refresh_buffer = refresh_buffer_seconds  # Refresh tokens this many seconds before expiry

    def _find_latest(self) -> Optional[Path]:
        # Only look in mcp-remote versioned folders
        candidates = []
        for sub in self.base_dir.glob("mcp-remote-*"):
            candidates.extend(sub.glob("*_tokens.json"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        # No fallback to root tokens.json
        return None

    def token_file(self) -> Optional[Path]:
        if self.explicit_file:
            p = Path(os.path.expanduser(self.explicit_file))
            return p if p.exists() else None
        return self._find_latest()

    def load(self, force_reload: bool = False) -> Optional[dict]:
        """Load tokens from file, with optional caching.
        
        Args:
            force_reload: Force reload from disk even if cached
            
        Returns:
            Token dictionary or None
        """
        # Check cache validity (reload every 30 seconds or on force)
        now = time.time()
        if not force_reload and self._token_cache and (now - self._last_load_time) < 30:
            return self._token_cache
        
        path = self.token_file()
        if not path:
            logger.debug(f"No token file found in {self.base_dir}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._selected = path
            self._token_cache = data
            self._last_load_time = now
            return data
        except Exception as e:
            logger.error(f"Failed to load tokens from {path}: {e}")
            return None

    def save(self, tokens: dict) -> bool:
        """Save tokens to file atomically.
        
        Args:
            tokens: Token dictionary to save
            
        Returns:
            True if successful
        """
        path = self._selected or self.token_file()
        if not path:
            logger.error("No token file path available for saving")
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to temp then replace
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(path)
            # Update cache
            self._token_cache = tokens
            self._last_load_time = time.time()
            logger.debug(f"Saved tokens to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save tokens to {path}: {e}")
            return False

    def _find_client_info(self) -> Optional[Path]:
        # Look for a sibling *_client_info.json next to the selected token file
        if self._selected and self._selected.parent.exists():
            for f in self._selected.parent.glob("*_client_info.json"):
                return f
        # Or search in mcp-remote folders
        for sub in self.base_dir.glob("mcp-remote-*"):
            files = list(sub.glob("*_client_info.json"))
            if files:
                return files[0]
        # No fallback to root directory
        return None

    def _client_id(self) -> Optional[str]:
        p = self._find_client_info()
        if not p:
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("client_id") or data.get("client_name")
        except Exception:
            return None

    def is_expired(self, tokens: Optional[Dict[str, Any]] = None) -> bool:
        """Check if tokens are expired or about to expire.
        
        Args:
            tokens: Token dict to check, or None to load from file
            
        Returns:
            True if tokens are expired or will expire soon
        """
        if tokens is None:
            tokens = self.load()
        if not tokens:
            return True
        
        # Check expires_at field
        expires_at = tokens.get("expires_at")
        if expires_at:
            now = time.time()
            # Consider expired if within buffer window
            return now >= (expires_at - self.refresh_buffer)
        
        # Check refreshed_at + expires_in
        refreshed_at = tokens.get("refreshed_at") or tokens.get("issued_at")
        expires_in = tokens.get("expires_in")
        if refreshed_at and expires_in:
            expiry_time = refreshed_at + expires_in
            now = time.time()
            return now >= (expiry_time - self.refresh_buffer)
        
        # No expiry info - assume expired after 15 minutes
        if refreshed_at:
            return (time.time() - refreshed_at) > 900
        
        return True  # No way to determine, assume expired
    
    def refresh(self, oauth_server: str, force: bool = False) -> Tuple[bool, Optional[str]]:
        """Refresh access token using refresh_token from file.
        
        Args:
            oauth_server: OAuth server URL
            force: Force refresh even if not expired
            
        Returns:
            (success, new_access_token or None)
        """
        tokens = self.load()
        if not tokens:
            logger.error("No tokens available to refresh")
            return False, None
        
        # Check if refresh is needed
        if not force and not self.is_expired(tokens):
            logger.debug("Tokens not expired, skipping refresh")
            return True, tokens.get("access_token")
        
        rt = tokens.get("refresh_token")
        if not rt:
            logger.error("No refresh token available")
            return False, None

        url = f"{oauth_server.rstrip('/')}/oauth/token"
        client_id = self._client_id() or "MCP CLI Proxy"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": client_id,
        }
        
        logger.info(f"Refreshing token with {url}")
        try:
            resp = httpx.post(url, data=data, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Token refresh failed: {resp.status_code} - {resp.text}")
                return False, None
            new_tokens = resp.json()
            tokens.update(new_tokens)
            tokens["refreshed_at"] = int(time.time())
            if "expires_in" in new_tokens:
                tokens["expires_at"] = int(time.time() + new_tokens["expires_in"])
            if not self.save(tokens):
                return False, None
            logger.info("Token refreshed successfully")
            return True, tokens.get("access_token")
        except Exception as e:
            logger.error(f"Token refresh exception: {e}")
            return False, None


class MCPBearerAuth(httpx.Auth):
    """httpx.Auth that injects Bearer and refreshes transparently on 401."""

    requires_request_body = True
    requires_response_body = True

    def __init__(self, token_store: BearerTokenStore, oauth_url: str) -> None:
        self.store = token_store
        self.oauth_url = oauth_url

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        # Check for proactive refresh
        tokens = self.store.load()
        if self.store.is_expired(tokens):
            logger.debug("Token expired or expiring soon, refreshing proactively")
            ok, new_access = self.store.refresh(self.oauth_url)
            if ok and new_access:
                tokens = {"access_token": new_access}
            else:
                logger.warning("Proactive refresh failed, using existing token")
        
        # Attach current access token
        access = tokens.get("access_token") if tokens else None
        if access:
            request.headers["Authorization"] = f"Bearer {access}"

        # First attempt
        response = yield request

        # If unauthorized, refresh then retry once
        if response.status_code == 401:
            logger.info("Got 401, attempting token refresh")
            ok, new_access = self.store.refresh(self.oauth_url, force=True)
            if ok and new_access:
                request.headers["Authorization"] = f"Bearer {new_access}"
                yield request
            else:
                logger.error("Token refresh failed on 401")
