#!/usr/bin/env python3
"""
Simple Working Monitor - Based on working ax_monitor_bot.py but simplified

This script monitors aX platform messages and processes them through plugins.
Envelope processing removed for simplicity.

Environment Variables / Feature Flags:
    VALIDATE_MENTIONS=true/false - Enable mention format validation
    WARN_MISSING_MENTIONS=true/false - Show warnings for missing mentions
    
Plugin-specific flags (see plugins/):
    auto_mention=true/false - Automatically prepend sender mention to responses
"""

import os
import sys
import json
import time
import asyncio
import importlib
import logging
import warnings
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Suppress pydantic validation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

try:
    from arena import arena_guard
except ImportError:  # pragma: no cover
    arena_guard = None  # type: ignore

MENTION_LINE_PATTERN = re.compile(r"^[•\-]\s*(?P<author>[^:]+):\s*(?P<body>.*)$")
MENTION_HANDLE_PATTERN = re.compile(r"@[0-9A-Za-z_\-]+")

class FilteredStderr:
    """Custom stderr that filters out specific error messages"""
    def __init__(self, original_stderr):
        self.original = original_stderr
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
from ax_mcp_wait_client.config_loader import (
    get_default_config_path,
    parse_all_mcp_servers,
)
from ax_mcp_wait_client.mcp_client import MCPClient
from mcp_tool_manager import MCPToolManager
from message_queue import MessageQueue, MessageJob

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
    """Print a heartbeat every 30s; 10 per row = 5 minutes."""
    hearts_in_row = 0
    print("💭 Waiting: ", end='', flush=True)
    while True:
        await asyncio.sleep(30)
        print("💓", end='', flush=True)
        hearts_in_row += 1
        if hearts_in_row >= 10:
            mins = int((time.time() - start_time) // 60)
            print(f" [{mins}m]")
            print("💭 Waiting: ", end='', flush=True)
            hearts_in_row = 0


async def plugin_wait_status(
    plugin_name: str,
    interval: float = 3.0,
    stop_event: Optional[asyncio.Event] = None,
):
    """Emit periodic status while waiting on a plugin response."""
    icons = ["🧠", "⏳", "⌛", "🤖"]
    cycle = 0
    print(f"🧠 {plugin_name} acknowledged payload; awaiting response...")
    try:
        while True:
            if stop_event and stop_event.is_set():
                return
            await asyncio.sleep(interval)
            if stop_event and stop_event.is_set():
                return
            icon = icons[cycle % len(icons)]
            print(f"{icon} {plugin_name} still processing...", flush=True)
            cycle += 1
    except asyncio.CancelledError:
        # Caller prints completion status; just stop quietly.
        raise


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
    logging.getLogger('ax_mcp_wait_client.bearer_refresh').setLevel(logging.WARNING)
    logging.getLogger('ax_mcp_wait_client.mcp_client').setLevel(logging.WARNING)

    async def _temporarily_quiet_mcp_logs(duration: int = 10):
        names = ['mcp', 'mcp.client', 'mcp.client.streamable_http']
        prev = {}
        for n in names:
            lg = logging.getLogger(n)
            prev[n] = lg.level
            lg.setLevel(logging.CRITICAL)
        try:
            await asyncio.sleep(duration)
        finally:
            for n, lvl in prev.items():
                try:
                    base = logging.WARNING if n.startswith('mcp') else lvl
                    logging.getLogger(n).setLevel(base)
                except Exception:
                    pass
    
    # Create persistent MCP client
    try:
        # Load configuration
        tool_manager: Optional[MCPToolManager] = None

        if config_path and os.path.exists(config_path):
            all_servers = parse_all_mcp_servers(config_path)
            primary_name = next(iter(all_servers.keys()))
            primary_cfg = all_servers[primary_name]
            client = MCPClient(
                server_url=primary_cfg.server_url,
                oauth_server=primary_cfg.oauth_url,
                agent_name=primary_cfg.agent_name,
                token_dir=primary_cfg.token_dir,
            )
            tool_manager = MCPToolManager(all_servers, primary_server=primary_name)
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
    agent_handle = agent_name if str(agent_name).startswith('@') else f'@{agent_name}'
    agent_handle_lower = agent_handle.lower()
    agent_display_name = agent_handle[1:] if agent_handle.startswith('@') else agent_handle
    agent_emoji = os.getenv('AGENT_EMOJI', '🤖')
    stream_prefix = f"\n{agent_emoji} {agent_display_name}: "
    
    # Get plugin type from environment or default
    plugin_type = os.getenv('PLUGIN_TYPE', 'echo')  # Default to echo
    
    arena_session_id = os.getenv('ARENA_SESSION_ID')
    arena_opponent = os.getenv('ARENA_OPPONENT')
    arena_cooldown_override: Optional[float] = None
    cooldown_env = os.getenv('ARENA_COOLDOWN_SEC')
    if cooldown_env:
        try:
            arena_cooldown_override = float(cooldown_env)
        except ValueError:
            arena_cooldown_override = None
    arena_enabled = bool(arena_guard and arena_session_id and arena_opponent)
    
    # Load plugin configuration if available
    plugin_config = {}
    plugin_config_file = os.getenv('PLUGIN_CONFIG')
    if plugin_config_file and os.path.exists(plugin_config_file):
        with open(plugin_config_file, 'r') as f:
            plugin_config = json.load(f)
    
    # Feature flags for validation and warnings
    validate_mentions = os.getenv('VALIDATE_MENTIONS', 'false').lower() == 'true'
    warn_missing_mentions = os.getenv('WARN_MISSING_MENTIONS', 'false').lower() == 'true'
    
    # Load the plugin
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"🔌 Loading plugin: {plugin_type}")
    plugin = load_plugin(plugin_type, plugin_config)
    plugin.attach_monitor_context({
        "current_date": current_date,
        "tool_manager": tool_manager,
    })
    if tool_manager:
        plugin.set_tool_manager(tool_manager)
    
    # Check if loop mode is enabled
    loop_mode = '--loop' in sys.argv or True  # Force loop mode for monitoring
    
    print("=" * 60)
    print("🤖 Simple Working Monitor - Message Processor")
    if config_path:
        print(f"📁 CONFIG: {config_path}")
    print(f"👤 AGENT: {agent_emoji} {agent_handle}")
    print(f"🌐 SERVER: {client.server_url}")
    print(f"🔌 PLUGIN: {plugin.get_name()}")
    print("🔄 MODE: Continuous monitoring with wait=true")
    print("⌨️  Commands: 'r' or 'resend' to replay the last reply, 'history' for a preview, 'q' to quit.")
    print("=" * 60)
    print("\\n🚀 Starting monitor...")
    
    # Track timing for heartbeat
    start_time = time.time()

    # Command handling state
    command_queue: asyncio.Queue[str] = asyncio.Queue()
    message_queue = MessageQueue()
    last_sent_payload: Optional[str] = None
    last_sent_preview: Optional[str] = None
    last_sent_timestamp: Optional[datetime] = None
    shutdown_requested = False
    active_response_task: Optional[asyncio.Task[str]] = None
    self_mention_violation_count = 0
    self_handle_pattern = re.compile(
        rf"(?<![0-9A-Za-z_\-]){re.escape(agent_handle_lower)}(?![0-9A-Za-z_\-])",
        re.IGNORECASE,
    )

    async def command_listener() -> None:
        while True:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except Exception:
                await asyncio.sleep(0.25)
                continue
            if not line:
                await asyncio.sleep(0.1)
                continue
            cleaned = line.strip()
            if not cleaned:
                continue
            await command_queue.put(cleaned.lower())

    command_listener_task = asyncio.create_task(command_listener())

    async def handle_operator_command(cmd: str, *, during_response: bool = False) -> None:
        nonlocal shutdown_requested, active_response_task, last_sent_payload, last_sent_preview, last_sent_timestamp

        normalized = cmd.strip().lower()
        if not normalized:
            return

        if normalized in {"q", "quit", "exit"}:
            if not shutdown_requested:
                message = "\n👋 Exit requested."
                if during_response:
                    message += " Cancelling the in-flight response and shutting down..."
                else:
                    message += " Finishing the current cycle and shutting down..."
                print(message)
            shutdown_requested = True
            if active_response_task and not active_response_task.done():
                active_response_task.cancel()
            return

        if during_response:
            if normalized in {"r", "resend", "history"}:
                print("⚠️ Command ignored while a reply is in progress; please wait for the current turn to finish.")
            else:
                print(f"ℹ️ Command '{normalized}' received—will process after the current reply.")
            return

        if normalized in {"r", "resend"}:
            if not last_sent_payload:
                print("⚠️ No message available to resend yet.")
                return
            print("🔁 Resending last reply...")
            if await client.send_message(last_sent_payload):
                print("✅ Resent successfully.")
                if last_sent_timestamp:
                    print(f"   Original send at {last_sent_timestamp:%H:%M:%S} UTC")
            else:
                print("❌ Resend failed; message remains available for another try.")
            return

        if normalized == "history":
            if last_sent_preview:
                print("🗒️ Last reply preview:")
                print(last_sent_preview)
            else:
                print("⚠️ No previous reply to preview.")
            return

        print(f"ℹ️ Unknown command '{normalized}'. Try 'resend', 'history', or 'q' to quit.")

    async def process_queue_job(job: MessageJob) -> None:
        nonlocal progress_task, active_response_task, last_sent_payload, last_sent_preview
        nonlocal last_sent_timestamp, shutdown_requested, self_mention_violation_count

        if shutdown_requested:
            return

        latest_mention: str = job.payload["mention"]
        latest_author = job.payload.get("author")

        print(
            f"\n🚚 Processing queued mention {job.id}"
            f" (queue depth: {message_queue.size()})"
        )

        mention_token = None
        if arena_enabled and arena_guard:
            signature = ""
            if latest_author and latest_mention:
                signature = f"{latest_author}\n{latest_mention}"
            if signature:
                mention_token = hashlib.blake2s(signature.encode("utf-8"), digest_size=16).hexdigest()
                can_respond = arena_guard.should_respond(
                    session_id=arena_session_id,
                    agent=agent_name,
                    mention_ids=[mention_token],
                    opponent=arena_opponent,
                )
                if not can_respond:
                    print("⛔ Arena guard: holding turn for opponent.")
                    if progress_task is None:
                        progress_task = asyncio.create_task(show_progress(start_time))
                    return
        
        print(f"\n🤔 Processing with {plugin.get_name()}...")
        sender_handle = "@unknown"
        if latest_author:
            author_text = str(latest_author).strip()
            print(f"🔍 Debug: Extracting sender from author_text: '{author_text}'")
            author_match = MENTION_HANDLE_PATTERN.search(author_text)
            if author_match:
                sender_handle = author_match.group(0)
                print(f"🔍 Debug: Found @mention in author: {sender_handle}")
            else:
                base = author_text.replace('•', '').replace('-', '').strip()
                base = base.split('[', 1)[0].split('(', 1)[0].strip()
                if base:
                    base = base.lstrip('@')
                    parts = base.split()
                    base = parts[0] if parts else ""
                    base = base.strip('@,:')
                    base = re.sub(r"[^0-9A-Za-z_\-]", "", base)
                    if base:
                        sender_handle = f"@{base}"
                        print(f"🔍 Debug: Constructed sender handle: {sender_handle}")
        else:
            print("🔍 Debug: latest_author is None or empty")

        print(f"✅ Final sender handle: {sender_handle}")

        stream_started = asyncio.Event()

        async def stream_handler(chunk: str) -> None:
            if not chunk:
                return
            if not stream_started.is_set():
                stream_started.set()
                print(stream_prefix, end='', flush=True)
            print(chunk, end='', flush=True)

        plugin_context = {
            "sender": sender_handle,
            "agent_name": agent_handle,
            "session_id": arena_session_id,
            "stream_handler": stream_handler,
        }

        enhanced_message = latest_mention
        if sender_handle and sender_handle != agent_handle:
            enhanced_message = (
                "aX Platform Message Received\n"
                f"- Your agent handle: {agent_handle}\n"
                f"- Mention originated from: {sender_handle}\n"
                "- The sender tagged you in a shared conversation.\n\n"
                "MESSAGE CONTENT:\n"
                f"{latest_mention}"
            )

        print("---- Payload to Plugin ----")
        preview = enhanced_message if len(enhanced_message) < 2000 else enhanced_message[:2000] + "..."
        print(preview)
        print("----------------------------------------")

        wait_task = asyncio.create_task(
            plugin_wait_status(plugin.get_name(), stop_event=stream_started)
        )
        response: Optional[str] = None
        active_response_task = asyncio.create_task(
            plugin.process_message(enhanced_message, context=plugin_context)
        )
        command_task: Optional[asyncio.Task[str]] = None
        try:
            while True:
                if shutdown_requested:
                    if not active_response_task.done():
                        active_response_task.cancel()
                    break

                if command_task is None:
                    command_task = asyncio.create_task(command_queue.get())

                done, _ = await asyncio.wait(
                    {active_response_task, command_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if active_response_task in done:
                    try:
                        response = active_response_task.result()
                    except asyncio.CancelledError:
                        response = None
                    break

                if command_task in done:
                    cmd_value = command_task.result()
                    command_task = None
                    await handle_operator_command(cmd_value, during_response=True)
                    if shutdown_requested and not active_response_task.done():
                        active_response_task.cancel()
                    continue

            if not shutdown_requested and response is not None:
                if stream_started.is_set():
                    print("", flush=True)
                print(f"Plugin response: {response[:200]}...")
        except asyncio.CancelledError:
            response = None
        except Exception as e:
            if not shutdown_requested:
                print(f"❌ Plugin error: {e}")
            response = f"Sorry, I encountered an error: {e}"
        finally:
            if command_task and not command_task.done():
                command_task.cancel()
                try:
                    await command_task
                except asyncio.CancelledError:
                    pass
            if not wait_task.done():
                wait_task.cancel()
                try:
                    await wait_task
                except asyncio.CancelledError:
                    pass
            active_response_task = None

        if shutdown_requested or response is None:
            return

        normalized_response = response.strip()
        normalized_response_lower = normalized_response.lower()
        response_starts_with_mention = False
        if validate_mentions and sender_handle and sender_handle != agent_handle:
            expected_mention = sender_handle
            expected_lower = expected_mention.lower()
            if normalized_response_lower.startswith(expected_lower):
                response_starts_with_mention = True
                print(f"✅ Response correctly starts with {expected_mention}")
            elif warn_missing_mentions:
                print(f"⚠️  WARNING: Response does not start with {expected_mention}")
                print(f"   This means {sender_handle} will NOT receive the response!")
                warning_prefix = (
                    "⚠️ PROTOCOL WARNING: This message doesn't start with "
                    f"{sender_handle} so they won't see it. "
                )
                response = warning_prefix + response
                normalized_response = response.strip()
                normalized_response_lower = normalized_response.lower()

        if self_handle_pattern.search(response.lower()):
            self_mention_violation_count += 1
            print(
                "⚠️  Protocol violation: self-mention detected in response "
                f"(count={self_mention_violation_count})."
            )
            sanitized_response = self_handle_pattern.sub("[self-mention-blocked]", response)
            penalty_note = (
                "⚠️ PROTOCOL PENALTY: Self-mentions are disallowed. "
                "This turn loses a point."
            )
            if self_mention_violation_count >= 3:
                penalty_note += " #protocol-violation"
            response = sanitized_response.rstrip() + "\n" + penalty_note

        print(f"\n📤 Sending response...")
        if await client.send_message(response):
            print("✅ Response sent successfully!")
            last_sent_payload = response
            last_sent_preview = response[:500] + ("..." if len(response) > 500 else "")
            last_sent_timestamp = datetime.now(timezone.utc)
            if arena_enabled and arena_guard:
                arena_guard.record_spoken(
                    session_id=arena_session_id,
                    agent=agent_name,
                    opponent=arena_opponent,
                    cooldown_sec=arena_cooldown_override,
                )
        else:
            print("❌ Failed to send response")
            print("⏳ Waiting 30 seconds before retrying due to send failure...")
            last_sent_payload = response
            last_sent_preview = response[:500] + ("..." if len(response) > 500 else "")
            last_sent_timestamp = datetime.now(timezone.utc)
            await asyncio.sleep(30)

        await asyncio.sleep(2)
        if progress_task is None or progress_task.done():
            progress_task = asyncio.create_task(show_progress(start_time))

    async def queue_worker() -> None:
        while True:
            try:
                job = await message_queue.get()
            except asyncio.CancelledError:
                break

            try:
                await process_queue_job(job)
            except asyncio.CancelledError:
                message_queue.task_done()
                break
            except Exception as exc:
                print(f"❌ Queue worker error for job {getattr(job, 'id', '?')}: {exc}")
            finally:
                message_queue.task_done()

    try:
        first_loop = True
        printed_listen = False
        progress_task = None
        status_block_printed = -1
        startup_message_sent = False
        worker_task = asyncio.create_task(queue_worker())
        
        while True:
            # Process pending operator commands before polling for new mentions
            while not command_queue.empty():
                cmd = command_queue.get_nowait()
                await handle_operator_command(cmd)
                if shutdown_requested:
                    break

            if shutdown_requested:
                if progress_task and not progress_task.done():
                    progress_task.cancel()
                    try:
                        await progress_task
                    except asyncio.CancelledError:
                        pass
                    progress_task = None
                print("\n👋 Monitor shutting down per operator request...")
                break

            # Step 1: Check messages (with wait in loop mode)
            if not printed_listen:
                print(f"\\n✅ Connected! Listening for {agent_emoji} {agent_handle} mentions...")
                printed_listen = True
            
            # On very first loop, give the server a moment to finish initializing
            if first_loop:
                await asyncio.sleep(2)
                
                # Handle startup action - send initial message if configured
                startup_action = os.getenv('STARTUP_ACTION', 'listen_only')
                if startup_action == 'initiate_conversation' and not startup_message_sent:
                    conversation_target = os.getenv('CONVERSATION_TARGET')
                    if conversation_target:
                        print(f"\\n🚀 Initiating conversation with {conversation_target}...")
                        
                        # Load conversation template
                        conversation_template = os.getenv('CONVERSATION_TEMPLATE', 'basic')
                        custom_startup_message = os.getenv('CUSTOM_STARTUP_MESSAGE')
                        
                        startup_message = None
                        
                        # Handle custom message
                        if conversation_template == 'custom' and custom_startup_message:
                            startup_message = custom_startup_message
                            print(f"🎯 Using custom startup message: {startup_message[:100]}...")
                        
                        # Handle template-based message
                        elif conversation_template != 'basic':
                            try:
                                import random
                                # Try both relative and absolute paths
                                templates_file = 'configs/conversation_templates.json'
                                if not os.path.exists(templates_file):
                                    # Try absolute path from script directory
                                    script_dir = os.path.dirname(os.path.abspath(__file__))
                                    templates_file = os.path.join(script_dir, 'configs', 'conversation_templates.json')
                                
                                print(f"🔍 Looking for templates at: {templates_file}")
                                print(f"📁 Current working directory: {os.getcwd()}")
                                print(f"🎯 Template requested: {conversation_template}")
                                
                                if os.path.exists(templates_file):
                                    print(f"✅ Templates file found, loading...")
                                    with open(templates_file, 'r') as f:
                                        templates = json.load(f)
                                    
                                    print(f"📋 Available templates: {list(templates['templates'].keys())}")
                                    
                                    if conversation_template in templates['templates']:
                                        template = templates['templates'][conversation_template]
                                        template_message = template['starter_message']
                                        
                                        # Replace placeholders
                                        template_message = template_message.replace('{target}', conversation_target)
                                        
                                        # Handle topic selection for debate template
                                        if conversation_template == 'debate_absurd' and 'topics' in template:
                                            topic = random.choice(template['topics'])
                                            template_message = template_message.replace('{topic}', topic)
                                            print(f"🎲 Random debate topic: {topic}")
                                        
                                        startup_message = template_message
                                        print(f"📝 Using template '{template['name']}': {startup_message[:100]}...")
                                    else:
                                        print(f"⚠️ Template '{conversation_template}' not found in available templates, using AI generation")
                                else:
                                    print(f"⚠️ Templates file not found at {templates_file}, using AI generation")
                            except Exception as e:
                                print(f"⚠️ Error loading template: {e}, using AI generation")
                        
                        # Fallback to AI generation if no template message was set
                        if not startup_message:
                            startup_prompt = f"You are starting a conversation with {conversation_target}. Send a brief, friendly greeting message to initiate the conversation. Be natural and conversational."
                            
                            startup_context = {
                                "sender": agent_handle,
                                "agent_name": agent_handle,
                                "session_id": os.getenv('ARENA_SESSION_ID'),
                                "required_mentions": [conversation_target],
                            }
                            
                            try:
                                startup_response = await plugin.process_message(startup_prompt, context=startup_context)
                                
                                if startup_response:
                                    print(f"🔍 AI generated response: {startup_response[:150]}...")
                                    
                                    # Check if the response already starts with the target mention
                                    if startup_response.strip().lower().startswith(conversation_target.lower()):
                                        # Response already includes the mention, use as-is
                                        startup_message = startup_response
                                        print(f"✅ Response already contains mention, using as-is")
                                    else:
                                        # Add the target mention to the beginning of the message
                                        startup_message = f"{conversation_target} {startup_response}"
                                        print(f"➕ Adding mention to response")
                                else:
                                    print("❌ Plugin failed to generate startup message")
                                    
                            except Exception as e:
                                print(f"❌ Error generating startup message: {str(e)}")
                        
                        # Send the startup message
                        if startup_message:
                            # Ensure the message is properly formatted with target mention
                            if not startup_message.strip().lower().startswith(conversation_target.lower()):
                                startup_message = f"{conversation_target} {startup_message}"
                            
                            print(f"📤 Sending startup message: {startup_message[:100]}...")
                            
                            if await client.send_message(startup_message):
                                print(f"✅ Startup message sent to {conversation_target}!")
                                startup_message_sent = True
                            else:
                                print("❌ Failed to send startup message")
                        else:
                            print("❌ No startup message to send")
                    else:
                        print("⚠️ No conversation target specified for initiate mode")
                
                first_loop = False
            
            # Start progress task if not already running
            if progress_task is None or progress_task.done():
                progress_task = asyncio.create_task(show_progress(start_time))
                
            try:
                messages = await client.check_messages(wait=True, timeout=25, limit=5)
            except Exception as e:
                error_msg = str(e)
                if "504 Gateway Timeout" in error_msg or "Gateway Timeout" in error_msg:
                    print("\\n⚠️  Server timeout (504) - will reconnect...")
                elif "401" in error_msg:
                    print("\\n🔑 Authentication error - tokens may have expired")
                else:
                    print(f"\\n❌ Error while waiting for messages: {error_msg[:100]}")

                printed_listen = False
                await asyncio.sleep(10)
                continue

            if not messages:
                print("\\n❌ Failed to check messages")
                printed_listen = False
                await asyncio.sleep(30)
                continue
            
            # Only print message details if we got something
            if '✅ WAIT SUCCESS' in messages:
                print("\\n📨 Messages received:")
                print(messages[:500] + "..." if len(messages) > 500 else messages)
        
            # Look for mentions of our agent
            latest_mention = None
            latest_author = None
            
            # In wait mode, the format is simpler: "• user: message"
            if '✅ WAIT SUCCESS' in messages:
                # Handle both actual newlines and escaped newlines
                lines = messages.replace('\\n', '\n').split('\n')
                print(f"🔍 Debug: Processing {len(lines)} lines from message")
                previous_nonempty = ''
                for idx, raw_line in enumerate(lines):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    print(f"🔍 Debug: Line {idx}: '{stripped}'")
                    
                    # Skip header lines
                    if stripped.startswith('✅') or stripped.startswith('📨') or stripped.startswith('🎯'):
                        print(f"🔍 Debug: Skipping header line")
                        continue
                        
                    print(f"🔍 Debug: Testing regex against: '{stripped}'")
                    match = MENTION_LINE_PATTERN.match(stripped)
                    if match:
                        print(f"🔍 Debug: REGEX MATCH! Author: '{match.group('author')}', Body: '{match.group('body')}'")
                        author_part = match.group('author').strip()
                        body_part = match.group('body')
                        message_lines: list[str] = []
                        if previous_nonempty:
                            message_lines.append(previous_nonempty)
                        message_lines.append(f"• {author_part}: {body_part.lstrip()}")
                        j = idx + 1
                        while j < len(lines):
                            follow_raw = lines[j]
                            follow = follow_raw.rstrip('\\n')
                            follow_stripped = follow.strip()
                            if not follow_stripped:
                                j += 1
                                continue
                            if (MENTION_LINE_PATTERN.match(follow_stripped)
                                    or follow_stripped.startswith('✅')
                                    or follow_stripped.startswith('📨')
                                    or follow_stripped.startswith('📬')
                                    or '🎯' in follow_stripped):
                                break
                            message_lines.append(follow_stripped)
                            j += 1
                        message_block = '\\n'.join(message_lines).strip()
                        mentions_in_block = {m.lower() for m in MENTION_HANDLE_PATTERN.findall(message_block)}
                        print(f"🔍 Debug: Found mentions in block: {mentions_in_block}")
                        print(f"🔍 Debug: Looking for agent: {agent_handle_lower}")
                        if agent_handle_lower not in mentions_in_block:
                            print(f"🔍 Debug: Agent handle not found in mentions, skipping")
                            continue
                        latest_author = author_part
                        latest_mention = message_block
                        print(f"🔍 Debug: SUCCESS! Set latest_author='{latest_author}', latest_mention='{latest_mention}'")
                        break
                    else:
                        print(f"🔍 Debug: No regex match for line: '{stripped}'")
                    if stripped:
                        previous_nonempty = stripped
            
            if not latest_mention and '✅ WAIT SUCCESS' in messages:
                print(f"\n⚠️  Wait success reported a mention for {agent_handle}, but the parser extracted none.")
                preview = messages[:800] + ("..." if len(messages) > 800 else "")
                if preview:
                    print("   Raw payload preview:")
                    print(preview)

            if not latest_mention:
                # Print a concise status only every 10 minutes
                elapsed = int(time.time() - start_time)
                block = elapsed // 600
                if block > status_block_printed:
                    mins = block * 10 if block > 0 else 0
                    if mins > 0:
                        print(f"⏳ No mentions found. Bot has been running for {mins} minutes...")
                    else:
                        print("⏳ No mentions found, waiting...")
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
            print(f"\\n🎯 Found mention: {latest_mention}")

            job = await message_queue.enqueue(
                {
                    "mention": latest_mention,
                    "author": latest_author,
                },
                metadata={"source": "mention"},
            )
            print(
                f"📥 Queued mention job {job.id}"
                f" (queue depth: {message_queue.size()})"
            )
            first_loop = False
            continue
                
    finally:
        # Clean up connection
        if progress_task and not progress_task.done():
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass
        if 'worker_task' in locals():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        command_listener_task.cancel()
        try:
            await command_listener_task
        except Exception:
            pass
        if tool_manager:
            try:
                await tool_manager.shutdown()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\\n\\n👋 Monitor stopped by user")
        sys.exit(130)
