#!/usr/bin/env python3
"""Refresh the access token using the refresh token."""

import json
import os
import httpx
import sys

def refresh_access_token(oauth_server: str, refresh_token: str):
    """Exchange refresh token for new access token."""
    
    url = f"{oauth_server}/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "MCP CLI Proxy"
    }
    
    response = httpx.post(url, data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to refresh token: {response.status_code}")
        print(response.text)
        return None

if __name__ == "__main__":
    token_dir = "/Users/jacob/.mcp-auth/paxai/e2e38b9d/mcp_client_local"
    oauth_server = "http://localhost:8001"
    
    # Load existing tokens
    token_file = os.path.join(token_dir, "tokens.json")
    if not os.path.exists(token_file):
        print(f"Token file not found: {token_file}")
        sys.exit(1)
    
    with open(token_file, "r") as f:
        tokens = json.load(f)
    
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("No refresh token found")
        sys.exit(1)
    
    print(f"Current access token: {tokens.get('access_token', 'NONE')[:30]}...")
    print(f"Refreshing with refresh token: {refresh_token[:30]}...")
    
    # Refresh the token
    new_tokens = refresh_access_token(oauth_server, refresh_token)
    
    if new_tokens:
        print(f"New access token: {new_tokens.get('access_token', 'NONE')[:30]}...")
        
        # Update the tokens file
        tokens.update(new_tokens)
        with open(token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        
        print(f"Updated tokens saved to {token_file}")
    else:
        print("Failed to refresh token")
        sys.exit(1)