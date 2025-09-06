#!/usr/bin/env python3
"""
MCPRemoteWrapper - Leverages mcp-remote CLI for robust OAuth management.

This wrapper uses the proven mcp-remote implementation to handle OAuth flows
and token management, then provides simple bearer tokens for MCP communication.
"""

import os
import json
import subprocess
import hashlib
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class MCPRemoteWrapper:
    """Wrapper that uses mcp-remote CLI for OAuth, then connects via Python SDK."""
    
    def __init__(
        self,
        server_url: str,
        token_dir: str,
        agent_name: str = "mcp_client_local",
        oauth_server: Optional[str] = None,
    ):
        self.server_url = server_url
        self.token_dir = Path(token_dir)
        self.agent_name = agent_name
        self.oauth_server = oauth_server or server_url.replace("/mcp", "")
        self._token_cache: Optional[Dict[str, Any]] = None
        
    def _find_token_file(self) -> Optional[Path]:
        """Find the most recent token file in mcp-remote directory structure."""
        # Look for mcp-remote versioned directories
        candidates = []
        for subdir in self.token_dir.glob("mcp-remote-*"):
            candidates.extend(subdir.glob("*_tokens.json"))
        
        if candidates:
            # Return most recent by modification time
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]
        
        return None
    
    def _compute_server_hash(self) -> str:
        """Compute the hash that mcp-remote uses for token files."""
        # mcp-remote uses MD5 hash of the server URL for file naming
        return hashlib.md5(self.server_url.encode()).hexdigest()[:32]
    
    async def ensure_authenticated(self, interactive: bool = True) -> bool:
        """
        Use mcp-remote to ensure we have valid tokens.
        
        Args:
            interactive: If True, allow browser-based OAuth flow
            
        Returns:
            True if authentication successful
        """
        try:
            # First, check if we have existing tokens
            token_file = self._find_token_file()
            if token_file and token_file.exists():
                # Try a test connection to verify tokens are valid
                tokens = self.get_tokens()
                if tokens and tokens.get("access_token"):
                    logger.info(f"Found existing tokens at {token_file}")
                    # Could add a test API call here to verify token validity
                    return True
            
            if not interactive:
                logger.error("No valid tokens found and interactive mode disabled")
                return False
            
            # Need fresh auth - run mcp-remote interactive flow
            logger.info("🔐 Launching mcp-remote for OAuth authentication...")
            
            env = os.environ.copy()
            env["MCP_REMOTE_CONFIG_DIR"] = str(self.token_dir)
            
            # Build mcp-remote command
            cmd = [
                "npx", "-y", "mcp-remote@0.1.18",
                self.server_url,
                "--transport", "http-only",
                "--allow-http",
                "--oauth-server", self.oauth_server,
                "--header", f"X-Agent-Name:{self.agent_name}",
            ]
            
            # Run mcp-remote to handle OAuth flow
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=False,  # Allow interactive browser flow
                text=True,
                timeout=120  # 2 minute timeout for user interaction
            )
            
            if result.returncode == 0:
                logger.info("✅ OAuth authentication successful")
                # Reload tokens after successful auth
                self._token_cache = None
                return True
            else:
                logger.error(f"mcp-remote authentication failed with code {result.returncode}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ mcp-remote authentication timed out")
            return False
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """
        Test if current tokens work by making a simple MCP request.
        
        Returns:
            True if connection successful
        """
        try:
            import httpx
            
            tokens = self.get_tokens()
            if not tokens:
                return False
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.server_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-20",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "mcp-remote-wrapper",
                                "version": "1.0.0"
                            }
                        }
                    },
                    headers={
                        "Authorization": f"Bearer {tokens['access_token']}",
                        "Content-Type": "application/json",
                        "X-Agent-Name": self.agent_name,
                    },
                    timeout=10.0
                )
                
                return response.status_code == 200
                
        except Exception as e:
            logger.debug(f"Connection test failed: {e}")
            return False
    
    def get_tokens(self) -> Optional[Dict[str, Any]]:
        """
        Extract tokens from mcp-remote storage.
        
        Returns:
            Dictionary containing access_token, refresh_token, etc.
        """
        if self._token_cache:
            return self._token_cache
        
        token_file = self._find_token_file()
        if not token_file or not token_file.exists():
            logger.debug(f"No token file found in {self.token_dir}")
            return None
        
        try:
            with open(token_file, 'r') as f:
                self._token_cache = json.load(f)
                return self._token_cache
        except Exception as e:
            logger.error(f"Failed to load tokens from {token_file}: {e}")
            return None
    
    def get_access_token(self) -> Optional[str]:
        """
        Get the current access token.
        
        Returns:
            Access token string or None
        """
        tokens = self.get_tokens()
        return tokens.get("access_token") if tokens else None
    
    async def refresh_if_needed(self) -> bool:
        """
        Check token expiry and refresh if needed using mcp-remote.
        
        Returns:
            True if tokens are valid (either current or refreshed)
        """
        tokens = self.get_tokens()
        if not tokens:
            return False
        
        # Check if token is expired
        import time
        now = time.time()
        expires_at = tokens.get("expires_at")
        
        if expires_at and now >= (expires_at - 60):  # 60 second buffer
            logger.info("Token expired or expiring soon, refreshing...")
            # Clear cache to force reload
            self._token_cache = None
            # Use mcp-remote to refresh
            return await self.ensure_authenticated(interactive=False)
        
        return True
    
    async def create_bearer_auth(self):
        """
        Create an httpx Auth object for bearer token authentication.
        
        Returns:
            MCPBearerAuth instance or None
        """
        from ax_mcp_wait_client.bearer_refresh import BearerTokenStore, MCPBearerAuth
        
        if not await self.ensure_authenticated():
            return None
        
        store = BearerTokenStore(str(self.token_dir))
        return MCPBearerAuth(store, self.oauth_server)
    
    async def create_http_client(self, timeout: int = 30):
        """
        Create an httpx client with bearer token authentication.
        
        Args:
            timeout: Request timeout in seconds
            
        Returns:
            Configured httpx.AsyncClient
        """
        import httpx
        
        tokens = self.get_tokens()
        if not tokens:
            raise ValueError("No tokens available - call ensure_authenticated() first")
        
        return httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "X-Agent-Name": self.agent_name,
                "Content-Type": "application/json",
            },
            timeout=timeout
        )


# Example usage
async def main():
    """Example of using MCPRemoteWrapper."""
    wrapper = MCPRemoteWrapper(
        server_url="http://localhost:8001/mcp",
        token_dir="/Users/jacob/.mcp-auth/paxai/e2e38b9d/mcp_client_local",
        agent_name="mcp_client_local"
    )
    
    # Ensure we have valid tokens (may launch browser)
    if await wrapper.ensure_authenticated():
        print("✅ Authentication successful")
        
        # Get tokens for use with any HTTP client
        token = wrapper.get_access_token()
        print(f"Access token: {token[:50]}...")
        
        # Test the connection
        if await wrapper.test_connection():
            print("✅ Connection test successful")
        else:
            print("❌ Connection test failed")
    else:
        print("❌ Authentication failed")


if __name__ == "__main__":
    asyncio.run(main())