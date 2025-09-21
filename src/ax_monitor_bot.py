#!/usr/bin/env python3
"""
aX Monitor Bot - Modular MCP client with plugin support.

This bot monitors aX platform messages and processes them through configurable plugins.
"""

import os
import sys
import json
import time
import asyncio
import importlib
import logging
import warnings
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

# Suppress pydantic validation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")


class FilteredStderr:
    """Custom stderr that filters out specific error messages"""
    def __init__(self, original_stderr):
        self.original = original_stderr
        self.buffer = []
        self.suppress_patterns = [
            "Error parsing JSON response",
            "pydantic_core._pydantic_core.ValidationError",
            "JSONRPCMessage",
            "'id': None",
            "id: None",
            "Field required [type=missing",
            "Input should be a valid",
        ]
    
    def write(self, text):
        # Check if we should suppress this output
        for pattern in self.suppress_patterns:
            if pattern in text:
                return  # Suppress this output
        # Otherwise, write to original stderr
        self.original.write(text)
    
    def flush(self):
        self.original.flush()
    
    def __getattr__(self, attr):
        return getattr(self.original, attr)


# Replace stderr with our filtered version
sys.stderr = FilteredStderr(sys.stderr)

# Add parent directory to path for plugins
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our config loader and MCP client
sys.path.insert(0, 'src')
from ax_mcp_wait_client.config_loader import parse_mcp_config, get_default_config_path
from ax_mcp_wait_client.mcp_client import MCPClient


def load_plugin(plugin_type: str, config: Optional[Dict[str, Any]] = None):
    """
    Load a plugin by type.
    
    Args:
        plugin_type: Plugin name (e.g., 'ollama', 'echo')
        config: Optional plugin configuration
        
    Returns:
        Plugin instance
    """
    try:
        # Try to import the plugin module
        module_name = f"plugins.{plugin_type}_plugin"
        module = importlib.import_module(module_name)
        
        # Get the plugin class (assumes it follows naming convention)
        class_name = ''.join(word.capitalize() for word in plugin_type.split('_')) + 'Plugin'
        plugin_class = getattr(module, class_name)
        
        # Create and return plugin instance
        return plugin_class(config)
    except (ImportError, AttributeError) as e:
        print(f"❌ Failed to load plugin '{plugin_type}': {e}")
        print(f"   Available plugins: ollama, echo, openrouter")
        sys.exit(1)


async def show_progress(start_time: float):
    """Print a heartbeat every 30s; 10 per row = 5 minutes.

    Format:
    💭 Waiting: 💓💓... (10 hearts) [5m]\n
    💭 Waiting: 💓💓... (10 hearts) [10m]\n
    """
    hearts_in_row = 0
    # First row prefix
    print("💭 Waiting: ", end='', flush=True)
    while True:
        await asyncio.sleep(30)
        print("💓", end='', flush=True)
        hearts_in_row += 1
        if hearts_in_row >= 10:
            mins = int((time.time() - start_time) // 60)
            print(f" [{mins}m]")
            # Start next row
            print("💭 Waiting: ", end='', flush=True)
            hearts_in_row = 0


async def main():
    """Main bot loop"""

    # Load config from file if specified
    config_path = os.getenv('MCP_CONFIG_PATH') or get_default_config_path()

    # Configure logging to reduce noisy third-party stack traces on startup
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('mcp').setLevel(logging.CRITICAL)
    logging.getLogger('mcp.client').setLevel(logging.CRITICAL)
    logging.getLogger('mcp.client.streamable_http').setLevel(logging.CRITICAL)
    logging.getLogger('pydantic').setLevel(logging.CRITICAL)
    logging.getLogger('pydantic_core').setLevel(logging.CRITICAL)
    # Quiet our internal auth refresh noise
    logging.getLogger('ax_mcp_wait_client.bearer_refresh').setLevel(logging.WARNING)
    logging.getLogger('ax_mcp_wait_client.mcp_client').setLevel(logging.WARNING)

    async def _temporarily_quiet_mcp_logs(duration: int = 10):
        names = [
            'mcp',
            'mcp.client',
            'mcp.client.streamable_http',
        ]
        prev = {}
        for n in names:
            lg = logging.getLogger(n)
            prev[n] = lg.level
            lg.setLevel(logging.CRITICAL)
        try:
            await asyncio.sleep(duration)
        finally:
            # Restore to a quieter baseline after startup
            for n, lvl in prev.items():
                try:
                    # Keep them quiet-ish post-startup
                    base = logging.WARNING if n.startswith('mcp') else lvl
                    logging.getLogger(n).setLevel(base)
                except Exception:
                    pass
    
    # Create persistent MCP client
    try:
        # Load configuration
        if config_path and os.path.exists(config_path):
            cfg = parse_mcp_config(config_path)
            client = MCPClient(
                server_url=cfg.server_url,
                oauth_server=cfg.oauth_url,
                agent_name=cfg.agent_name,
                token_dir=cfg.token_dir,
            )
        else:
            client = MCPClient(
                server_url=os.getenv('MCP_SERVER_URL', 'http://localhost:8001/mcp'),
                oauth_server=os.getenv('MCP_OAUTH_SERVER_URL', 'http://localhost:8001'),
                agent_name=os.getenv('MCP_AGENT_NAME', 'mcp_client_local'),
                token_dir=os.getenv('MCP_REMOTE_CONFIG_DIR') or '',
            )
        # Suppress noisy MCP transport logs during initial connect window
        quiet_task = asyncio.create_task(_temporarily_quiet_mcp_logs(10))
        await client.connect()
    except Exception as e:
        print(f"❌ Failed to create MCP client: {e}")
        return 1
    
    # Get agent name for display
    agent_name = client.agent_name
    
    # Get plugin type from environment or default
    plugin_type = os.getenv('PLUGIN_TYPE', 'ollama')
    
    # Load plugin configuration if available
    plugin_config = {}
    plugin_config_file = os.getenv('PLUGIN_CONFIG')
    if plugin_config_file and os.path.exists(plugin_config_file):
        with open(plugin_config_file, 'r') as f:
            plugin_config = json.load(f)
    
    # Load the plugin
    print(f"🔌 Loading plugin: {plugin_type}")
    plugin = load_plugin(plugin_type, plugin_config)
    
    # Check if loop mode is enabled
    loop_mode = '--loop' in sys.argv
    
    print("=" * 60)
    print("🤖 aX Monitor Bot - Modular Message Processor")
    if config_path:
        print(f"📁 CONFIG: {config_path}")
    print(f"👤 AGENT: {agent_name}")
    print(f"🌐 SERVER: {client.server_url}")
    print(f"🔌 PLUGIN: {plugin.get_name()}")
    if loop_mode:
        print("🔄 MODE: Continuous monitoring with wait=true")
    else:
        print("⚡ MODE: Single check (no wait)")
    print("=" * 60)
    print("\n🚀 Starting bot...")
    
    # Track timing for heartbeat
    start_time = time.time()
    
    try:
        first_loop = True
        printed_listen = False
        progress_task = None
        status_block_printed = -1  # for periodic "no mentions" summary
        while True:
            # Step 1: Check messages (with wait in loop mode)
            if loop_mode:
                # Show we're entering wait mode
                if not printed_listen:
                    print(f"\n✅ Connected! Listening for @{agent_name} mentions...")
                    printed_listen = True
                # On very first loop, give the server a moment to finish initializing
                if first_loop:
                    await asyncio.sleep(2)
                # Start progress task if not already running
                if progress_task is None or progress_task.done():
                    progress_task = asyncio.create_task(show_progress(start_time))
                
            try:
                messages = await client.check_messages(wait=loop_mode, timeout=60, limit=5)
            except Exception as e:
                error_msg = str(e)
                if "504 Gateway Timeout" in error_msg or "Gateway Timeout" in error_msg:
                    print("\n⚠️  Server timeout (504) - will reconnect...")
                elif "401" in error_msg:
                    print("\n🔑 Authentication error - tokens may have expired")
                else:
                    print(f"\n❌ Error: {error_msg[:100]}")
                
                printed_listen = False  # force a reconnect banner next loop
                if not loop_mode:
                    return 1
                    
                # Wait before retrying
                await asyncio.sleep(10)
                continue
            finally:
                # Do not cancel progress task here; keep the heartbeat continuous
                pass
            
            if not messages:
                print("\n❌ Failed to check messages")
                printed_listen = False  # force a reconnect banner next loop
                if not loop_mode:
                    return 1
                await asyncio.sleep(30)
                continue
            
            # Only print message details if we got something
            if '✅ WAIT SUCCESS' in messages or not loop_mode:
                print("\n📨 Messages received:")
                print(messages[:500] + "..." if len(messages) > 500 else messages)
        
            # Look for mentions of our agent
            latest_mention = None
            latest_author = None
            
            # In wait mode, the format is simpler: "• user: message"
            if loop_mode and '✅ WAIT SUCCESS' in messages:
                lines = messages.split('\n')
                for i, line in enumerate(lines):
                    if '•' in line and f'@{agent_name}' in line:
                        # Extract message after the bullet and username
                        parts = line.split(': ', 1)
                        if len(parts) > 1:
                            # Capture the author (between the bullet and the colon)
                            try:
                                bullet, _ = line.split(': ', 1)
                                latest_author = bullet.replace('•', '').strip()
                            except Exception:
                                latest_author = None
                            # Start with the first line content
                            message_lines = [parts[1]]
                            # Collect continuation lines until we hit the end marker
                            j = i + 1
                            while j < len(lines):
                                next_line = lines[j]
                                # Stop if we hit the end of the message block
                                if next_line.strip() == '' and j + 1 < len(lines):
                                    # Check if next non-empty line is a marker
                                    k = j + 1
                                    while k < len(lines) and lines[k].strip() == '':
                                        k += 1
                                    if k < len(lines) and ('🎯' in lines[k] or '📨' in lines[k] or lines[k].startswith('•')):
                                        break
                                # Stop at obvious markers
                                if '🎯' in next_line or next_line.startswith('•'):
                                    break
                                # Add all content lines (even empty ones for formatting)
                                message_lines.append(next_line)
                                j += 1
                            # Join and clean up extra whitespace at the end
                            latest_mention = '\n'.join(message_lines).rstrip()
                            break
            else:
                # Non-wait mode: standard format with [id:...]
                for line in messages.split('\n'):
                    if f'@{agent_name}' in line and '[id:' in line:
                        # Skip our own messages (they start with our agent name)
                        if line.strip().startswith(f'@{agent_name}'):
                            continue
                        # Extract just the message content after the ID
                        parts = line.split(']: ')
                        if len(parts) > 1:
                            latest_mention = parts[1]
                            # Best-effort author capture from prefix before ']:' if formatted like "user [id:...]: msg"
                            try:
                                prefix = line.split(']:', 1)[0]
                                # e.g. "user [id:xyz" -> take the first token
                                latest_author = prefix.split()[0].lstrip('@')
                            except Exception:
                                latest_author = None
                            break  # Stop at first (most recent) mention
            
            if not latest_mention:
                # Print a concise status only every 10 minutes
                if not loop_mode:
                    return 0
                elapsed = int(time.time() - start_time)
                block = elapsed // 600
                if block > status_block_printed:
                    mins = block * 10 if block > 0 else 0
                    if mins > 0:
                        print(f"⏳ No mentions found. Bot has been running for {mins} minutes...")
                    else:
                        print("⏳ No mentions found, waiting…")
                    status_block_printed = block
                await asyncio.sleep(5)
                continue
            
            # Pause heartbeat while we print activity output
            if progress_task and not progress_task.done():
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
                progress_task = None
            print(f"\n🎯 Found mention: {latest_mention}")

            # Step 3: Process with plugin
            print(f"\n🤔 Processing with {plugin.get_name()}...")
            try:
                response = await plugin.process_message(latest_mention)
                print(f"Plugin response: {response[:200]}...")
            except Exception as e:
                print(f"❌ Plugin error: {e}")
                response = f"Sorry, I encountered an error: {e}"

            # Step 4: Send response using persistent client
            print(f"\n📤 Sending response...")
            # Rely on the model prompt to include mentions; do not inject headers here
            if await client.send_message(response):
                print("✅ Response sent successfully!")
            else:
                print("❌ Failed to send response")
                # Add delay on failure to prevent hammering
                if loop_mode:
                    print("⏳ Waiting 30 seconds before retrying due to send failure...")
                    await asyncio.sleep(30)
            
            # Exit if not in loop mode
            if not loop_mode:
                return 0
            
            # Add a small delay between loops to prevent rapid polling
            if loop_mode:
                await asyncio.sleep(2)  # 2 second minimum delay between checks
                # Resume heartbeat after handling the mention
                if progress_task is None:
                    progress_task = asyncio.create_task(show_progress(start_time))
            first_loop = False
                
    finally:
        # Clean up connection
        try:
            await client.disconnect()
        except Exception as e:
            # Ignore errors during cleanup
            pass


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user")
        sys.exit(130)
