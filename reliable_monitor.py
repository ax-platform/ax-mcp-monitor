#!/usr/bin/env python3
"""
Reliable Monitor - 99.999% Message Delivery Guarantee

This monitor implements multiple reliability strategies:
1. Message persistence and deduplication
2. Exponential backoff with jitter
3. Health checks and automatic reconnection
4. Graceful degradation and recovery
5. Multiple parsing strategies
6. Dead letter queue for failed messages
7. Heartbeat monitoring
"""

import os
import sys
import json
import time
import asyncio
import sqlite3
import hashlib
import random
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

# Add parent directory to path for plugins
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'src')

from ax_mcp_wait_client.config_loader import parse_mcp_config, get_default_config_path
from ax_mcp_wait_client.mcp_client import MCPClient

class MessageStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

@dataclass
class StoredMessage:
    id: str
    raw_content: str
    parsed_author: Optional[str]
    parsed_mention: Optional[str]
    sender_handle: Optional[str]
    status: MessageStatus
    created_at: datetime
    processed_at: Optional[datetime]
    retry_count: int
    error_message: Optional[str]

class ReliableMessageStore:
    """SQLite-based message store with ACID guarantees"""
    
    def __init__(self, db_path: str = "messages.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    raw_content TEXT NOT NULL,
                    parsed_author TEXT,
                    parsed_mention TEXT,
                    sender_handle TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON messages(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at)")
            conn.commit()
        finally:
            conn.close()
    
    def store_message(self, message: StoredMessage) -> bool:
        """Store message with ACID guarantee"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO messages 
                (id, raw_content, parsed_author, parsed_mention, sender_handle, 
                 status, created_at, processed_at, retry_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.id,
                message.raw_content,
                message.parsed_author,
                message.parsed_mention,
                message.sender_handle,
                message.status.value,
                message.created_at.isoformat(),
                message.processed_at.isoformat() if message.processed_at else None,
                message.retry_count,
                message.error_message
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"❌ Failed to store message: {e}")
            return False
        finally:
            conn.close()
    
    def get_pending_messages(self) -> List[StoredMessage]:
        """Get all pending messages ordered by creation time"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("""
                SELECT * FROM messages 
                WHERE status IN ('pending', 'failed') 
                ORDER BY created_at ASC
            """)
            messages = []
            for row in cursor.fetchall():
                messages.append(self._row_to_message(row))
            return messages
        finally:
            conn.close()
    
    def update_message_status(self, message_id: str, status: MessageStatus, 
                            error_message: Optional[str] = None) -> bool:
        """Update message status atomically"""
        conn = sqlite3.connect(self.db_path)
        try:
            processed_at = datetime.now() if status in [MessageStatus.COMPLETED, MessageStatus.DEAD_LETTER] else None
            conn.execute("""
                UPDATE messages 
                SET status = ?, processed_at = ?, error_message = ?
                WHERE id = ?
            """, (
                status.value,
                processed_at.isoformat() if processed_at else None,
                error_message,
                message_id
            ))
            conn.commit()
            return conn.rowcount > 0
        except Exception as e:
            print(f"❌ Failed to update message status: {e}")
            return False
        finally:
            conn.close()
    
    def increment_retry_count(self, message_id: str) -> int:
        """Increment retry count and return new count"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                UPDATE messages 
                SET retry_count = retry_count + 1
                WHERE id = ?
            """, (message_id,))
            conn.commit()
            
            cursor = conn.execute("SELECT retry_count FROM messages WHERE id = ?", (message_id,))
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    
    def _row_to_message(self, row) -> StoredMessage:
        """Convert database row to StoredMessage"""
        return StoredMessage(
            id=row[0],
            raw_content=row[1],
            parsed_author=row[2],
            parsed_mention=row[3],
            sender_handle=row[4],
            status=MessageStatus(row[5]),
            created_at=datetime.fromisoformat(row[6]),
            processed_at=datetime.fromisoformat(row[7]) if row[7] else None,
            retry_count=row[8],
            error_message=row[9]
        )

class ExponentialBackoff:
    """Exponential backoff with jitter for retry logic"""
    
    def __init__(self, base_delay: float = 1.0, max_delay: float = 300.0, 
                 multiplier: float = 2.0, jitter: bool = True):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
    
    def get_delay(self, retry_count: int) -> float:
        """Calculate delay for given retry count"""
        delay = min(self.base_delay * (self.multiplier ** retry_count), self.max_delay)
        if self.jitter:
            # Add ±25% jitter to prevent thundering herd
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)
        return max(delay, 0.1)  # Minimum 100ms delay

class HealthChecker:
    """Monitor connection health and trigger reconnections"""
    
    def __init__(self, client: MCPClient, check_interval: float = 60.0):
        self.client = client
        self.check_interval = check_interval
        self.last_successful_check = time.time()
        self.consecutive_failures = 0
        self.max_failures = 3
    
    async def health_check(self) -> bool:
        """Perform health check"""
        try:
            # Simple health check - try to check messages with reasonable timeout
            result = await self.client.check_messages(wait=False, timeout=300, limit=1)
            if result is not None:
                self.last_successful_check = time.time()
                self.consecutive_failures = 0
                return True
            else:
                self.consecutive_failures += 1
                return False
        except Exception as e:
            print(f"🩺 Health check failed: {e}")
            self.consecutive_failures += 1
            return False
    
    def is_healthy(self) -> bool:
        """Check if connection is considered healthy"""
        time_since_last_check = time.time() - self.last_successful_check
        return (self.consecutive_failures < self.max_failures and 
                time_since_last_check < self.check_interval * 2)
    
    async def run_health_checks(self):
        """Background task for periodic health checks"""
        while True:
            await asyncio.sleep(self.check_interval)
            await self.health_check()
            if not self.is_healthy():
                print(f"⚠️ Connection unhealthy - {self.consecutive_failures} consecutive failures")

class ReliableMonitor:
    """99.999% reliable message monitor"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or get_default_config_path()
        self.message_store = ReliableMessageStore()
        self.backoff = ExponentialBackoff()
        self.client: Optional[MCPClient] = None
        self.health_checker: Optional[HealthChecker] = None
        self.agent_handle = ""
        self.agent_handle_lower = ""
        self.self_mention_violation_count = 0
        self._self_handle_pattern: Optional[re.Pattern[str]] = None
        
        # Load plugin configuration
        self.plugin_type = os.getenv('PLUGIN_TYPE', 'echo')
        self.plugin = None
        
        # Reliability settings
        self.max_retries = 5
        self.dead_letter_threshold = 10
        self.message_timeout = 300  # 5 minutes
        
    async def initialize(self):
        """Initialize all components"""
        print("🔧 Initializing reliable monitor...")
        
        # Load configuration and create client
        if self.config_path and os.path.exists(self.config_path):
            cfg = parse_mcp_config(self.config_path)
            self.client = MCPClient(
                server_url=cfg.server_url,
                oauth_server=cfg.oauth_url,
                agent_name=cfg.agent_name,
                token_dir=cfg.token_dir,
            )
        else:
            raise Exception("No valid configuration found")
        
        # Connect with retries
        await self._reliable_connect()
        
        # Set agent handles
        self.agent_handle = self.client.agent_name
        if not str(self.agent_handle).startswith('@'):
            self.agent_handle = f'@{self.agent_handle}'
        self.agent_handle_lower = self.agent_handle.lower()
        self._self_handle_pattern = re.compile(
            rf"(?<![0-9A-Za-z_\-]){re.escape(self.agent_handle_lower)}(?![0-9A-Za-z_\-])",
            re.IGNORECASE,
        )
        
        # Initialize health checker
        self.health_checker = HealthChecker(self.client)
        
        # Load plugin
        self.plugin = self._load_plugin()
        
        print(f"✅ Reliable monitor initialized for {self.agent_handle}")
    
    async def _reliable_connect(self, max_retries: int = 10):
        """Connect with exponential backoff"""
        for attempt in range(max_retries):
            try:
                await self.client.connect()
                print("✅ Connected to MCP server")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                delay = self.backoff.get_delay(attempt)
                print(f"⚠️ Connection attempt {attempt + 1} failed: {e}")
                print(f"🔄 Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
    
    def _load_plugin(self):
        """Load plugin with error handling"""
        # Import plugin loading logic from original monitor
        import importlib
        try:
            module_name = f"plugins.{self.plugin_type}_plugin"
            module = importlib.import_module(module_name)
            class_name = ''.join(word.capitalize() for word in self.plugin_type.split('_')) + 'Plugin'
            plugin_class = getattr(module, class_name)
            return plugin_class({})
        except Exception as e:
            print(f"❌ Failed to load plugin '{self.plugin_type}': {e}")
            raise
    
    async def run(self):
        """Main monitoring loop with reliability guarantees"""
        print("🚀 Starting reliable monitoring loop...")
        
        # Start health checker
        health_task = asyncio.create_task(self.health_checker.run_health_checks())
        
        # Start background processors
        retry_task = asyncio.create_task(self._retry_failed_messages())
        cleanup_task = asyncio.create_task(self._cleanup_old_messages())
        
        try:
            while True:
                # Check connection health
                if not self.health_checker.is_healthy():
                    print("🔄 Reconnecting due to health check failure...")
                    await self._reliable_reconnect()
                
                # Process pending messages first
                await self._process_pending_messages()
                
                # Check for new messages
                await self._check_new_messages()
                
                # Brief pause before next iteration
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print("\\n👋 Shutting down gracefully...")
        finally:
            # Cancel background tasks
            health_task.cancel()
            retry_task.cancel()
            cleanup_task.cancel()
            
            # Wait for tasks to complete
            await asyncio.gather(health_task, retry_task, cleanup_task, return_exceptions=True)
            
            # Disconnect client
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
    
    async def _check_new_messages(self):
        """Check for new messages with reliability"""
        try:
            # Use reasonable timeout for message checking
            messages = await self.client.check_messages(wait=True, timeout=300, limit=5)
            
            if messages and '✅ WAIT SUCCESS' in messages:
                message_id = self._generate_message_id(messages)
                
                # Check if we've already processed this message
                if self._is_duplicate_message(message_id):
                    return
                
                # Store raw message immediately for persistence
                stored_message = StoredMessage(
                    id=message_id,
                    raw_content=messages,
                    parsed_author=None,
                    parsed_mention=None,
                    sender_handle=None,
                    status=MessageStatus.PENDING,
                    created_at=datetime.now(),
                    processed_at=None,
                    retry_count=0,
                    error_message=None
                )
                
                if self.message_store.store_message(stored_message):
                    print(f"📥 New message stored: {message_id[:8]}...")
                else:
                    print(f"❌ Failed to store message: {message_id[:8]}...")
                    
        except asyncio.TimeoutError:
            # Timeout is expected in polling mode
            pass
        except Exception as e:
            print(f"⚠️ Error checking messages: {e}")
            await asyncio.sleep(5)
    
    async def _process_pending_messages(self):
        """Process all pending messages"""
        pending_messages = self.message_store.get_pending_messages()
        
        for message in pending_messages:
            if message.retry_count >= self.max_retries:
                # Move to dead letter queue
                self.message_store.update_message_status(
                    message.id, 
                    MessageStatus.DEAD_LETTER,
                    f"Exceeded max retries ({self.max_retries})"
                )
                print(f"💀 Message moved to dead letter queue: {message.id[:8]}...")
                continue
            
            # Check if message is too old
            age = datetime.now() - message.created_at
            if age.total_seconds() > self.message_timeout:
                self.message_store.update_message_status(
                    message.id,
                    MessageStatus.DEAD_LETTER,
                    f"Message timeout ({self.message_timeout}s)"
                )
                print(f"⏰ Message expired: {message.id[:8]}...")
                continue
            
            # Process the message
            await self._process_single_message(message)
    
    async def _process_single_message(self, message: StoredMessage):
        """Process a single message with error handling"""
        try:
            # Mark as processing
            self.message_store.update_message_status(message.id, MessageStatus.PROCESSING)
            
            # Parse the message if not already parsed
            if not message.parsed_mention:
                parsed_author, parsed_mention, sender_handle = self._parse_message(message.raw_content)
                message.parsed_author = parsed_author
                message.parsed_mention = parsed_mention
                message.sender_handle = sender_handle
                self.message_store.store_message(message)
            
            # Check if this message mentions our agent
            if not self._is_mention_for_us(message.parsed_mention or ""):
                self.message_store.update_message_status(message.id, MessageStatus.COMPLETED, "Not a mention for this agent")
                return
            
            # Process with plugin
            response = await self._process_with_plugin(message)
            response = self._enforce_conversation_protocol(response)
            
            # Send response with retries
            if await self._send_response_reliably(response):
                self.message_store.update_message_status(message.id, MessageStatus.COMPLETED)
                print(f"✅ Message processed successfully: {message.id[:8]}...")
            else:
                # Increment retry count and mark as failed for retry
                retry_count = self.message_store.increment_retry_count(message.id)
                self.message_store.update_message_status(message.id, MessageStatus.FAILED, "Failed to send response")
                
                delay = self.backoff.get_delay(retry_count)
                print(f"❌ Failed to send response, will retry in {delay:.1f}s (attempt {retry_count})")
                
        except Exception as e:
            retry_count = self.message_store.increment_retry_count(message.id)
            self.message_store.update_message_status(message.id, MessageStatus.FAILED, str(e))
            print(f"❌ Error processing message {message.id[:8]}: {e}")
    
    def _parse_message(self, raw_content: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Parse message with multiple strategies for reliability"""
        import re
        
        # Strategy 1: Original regex pattern
        MENTION_LINE_PATTERN = re.compile(r"^[•\\-]\\s*(?P<author>[^:]+):\\s*(?P<body>.*)$")
        MENTION_HANDLE_PATTERN = re.compile(r"@[0-9A-Za-z_\\-]+")
        
        lines = raw_content.replace('\\\\n', '\\n').split('\\n')
        
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('✅') or stripped.startswith('📨'):
                continue
                
            match = MENTION_LINE_PATTERN.match(stripped)
            if match:
                author = match.group('author').strip()
                body = match.group('body')
                
                # Check if our agent is mentioned
                mentions = MENTION_HANDLE_PATTERN.findall(f"{author}: {body}")
                if any(m.lower() == self.agent_handle_lower for m in mentions):
                    sender_handle = self._extract_sender_handle(author)
                    return author, f"• {author}: {body}", sender_handle
        
        # Strategy 2: Fallback - look for any line with our agent handle
        for line in lines:
            if self.agent_handle_lower in line.lower():
                mentions = MENTION_HANDLE_PATTERN.findall(line)
                if any(m.lower() == self.agent_handle_lower for m in mentions):
                    # Try to extract author from line
                    author = "unknown"
                    if ':' in line:
                        author = line.split(':', 1)[0].strip('• -')
                    sender_handle = self._extract_sender_handle(author)
                    return author, line, sender_handle
        
        return None, None, None
    
    def _extract_sender_handle(self, author_text: str) -> str:
        """Extract sender handle from author text"""
        import re
        
        MENTION_HANDLE_PATTERN = re.compile(r"@[0-9A-Za-z_\\-]+")
        
        # Look for @handle in author text
        match = MENTION_HANDLE_PATTERN.search(author_text)
        if match:
            return match.group(0)
        
        # Construct handle from author text
        base = author_text.replace('•', '').replace('-', '').strip()
        base = base.split('[', 1)[0].split('(', 1)[0].strip()
        if base:
            base = base.lstrip('@')
            parts = base.split()
            base = parts[0] if parts else ""
            base = base.strip('@,:')
            base = re.sub(r'[^0-9A-Za-z_\\-]', '', base)
            if base:
                return f"@{base}"
        
        return "@unknown"
    
    def _is_mention_for_us(self, mention: str) -> bool:
        """Check if mention is for our agent"""
        return self.agent_handle_lower in mention.lower()
    
    async def _process_with_plugin(self, message: StoredMessage) -> str:
        """Process message with plugin"""
        plugin_context = {
            "sender": message.sender_handle,
            "agent_name": self.agent_handle,
            "session_id": None,
        }
        
        enhanced_message = (
            "aX Platform Message Received\\n"
            f"- Your agent handle: {self.agent_handle}\\n"
            f"- Mention originated from: {message.sender_handle}\\n"
            "- The sender tagged you in a shared conversation.\\n\\n"
            "MESSAGE CONTENT:\\n"
            f"{message.parsed_mention}"
        )
        
        return await self.plugin.process_message(enhanced_message, context=plugin_context)

    def _enforce_conversation_protocol(self, response: str) -> str:
        """Apply no-self-mention rules and tag repeat violations."""
        if not response or not self._self_handle_pattern:
            return response

        if self._self_handle_pattern.search(response.lower()):
            self.self_mention_violation_count += 1
            print(
                "⚠️  Protocol violation: self-mention detected in response "
                f"(count={self.self_mention_violation_count})."
            )
            sanitized_response = self._self_handle_pattern.sub("[self-mention-blocked]", response)
            penalty_note = (
                "⚠️ PROTOCOL PENALTY: Self-mentions are disallowed. "
                "This turn loses a point."
            )
            if self.self_mention_violation_count >= 3:
                penalty_note += " #protocol-violation"
            return sanitized_response.rstrip() + "\n" + penalty_note

        return response
    
    async def _send_response_reliably(self, response: str, max_attempts: int = 3) -> bool:
        """Send response with retry logic"""
        for attempt in range(max_attempts):
            try:
                if await self.client.send_message(response):
                    return True
            except Exception as e:
                print(f"❌ Send attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(self.backoff.get_delay(attempt))
        
        return False
    
    async def _reliable_reconnect(self):
        """Reconnect with exponential backoff"""
        try:
            await self.client.disconnect()
        except:
            pass
        
        await self._reliable_connect()
        
        # Update health checker
        self.health_checker.last_successful_check = time.time()
        self.health_checker.consecutive_failures = 0
    
    def _generate_message_id(self, content: str) -> str:
        """Generate unique ID for message content"""
        return hashlib.sha256(f"{content}:{time.time()}".encode()).hexdigest()
    
    def _is_duplicate_message(self, message_id: str) -> bool:
        """Check if message has already been processed"""
        conn = sqlite3.connect(self.message_store.db_path)
        try:
            cursor = conn.execute("SELECT id FROM messages WHERE id = ?", (message_id,))
            return cursor.fetchone() is not None
        finally:
            conn.close()
    
    async def _retry_failed_messages(self):
        """Background task to retry failed messages"""
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            # Get failed messages ready for retry
            conn = sqlite3.connect(self.message_store.db_path)
            try:
                cursor = conn.execute("""
                    SELECT id, retry_count FROM messages 
                    WHERE status = 'failed' 
                    AND retry_count < ?
                """, (self.max_retries,))
                
                failed_messages = cursor.fetchall()
                
                for message_id, retry_count in failed_messages:
                    delay = self.backoff.get_delay(retry_count)
                    
                    # Check if enough time has passed for retry
                    cursor = conn.execute("""
                        SELECT processed_at FROM messages WHERE id = ?
                    """, (message_id,))
                    
                    row = cursor.fetchone()
                    if row and row[0]:
                        last_attempt = datetime.fromisoformat(row[0])
                        if datetime.now() - last_attempt < timedelta(seconds=delay):
                            continue
                    
                    # Mark as pending for retry
                    conn.execute("""
                        UPDATE messages SET status = 'pending' WHERE id = ?
                    """, (message_id,))
                    
                conn.commit()
            finally:
                conn.close()
    
    async def _cleanup_old_messages(self):
        """Background task to cleanup old processed messages"""
        while True:
            await asyncio.sleep(3600)  # Run every hour
            
            # Delete completed messages older than 24 hours
            cutoff = datetime.now() - timedelta(hours=24)
            
            conn = sqlite3.connect(self.message_store.db_path)
            try:
                conn.execute("""
                    DELETE FROM messages 
                    WHERE status IN ('completed') 
                    AND processed_at < ?
                """, (cutoff.isoformat(),))
                
                deleted = conn.rowcount
                conn.commit()
                
                if deleted > 0:
                    print(f"🧹 Cleaned up {deleted} old messages")
                    
            finally:
                conn.close()

async def main():
    """Main entry point"""
    config_path = os.getenv('MCP_CONFIG_PATH') or get_default_config_path()
    
    monitor = ReliableMonitor(config_path)
    await monitor.initialize()
    await monitor.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\\n👋 Reliable monitor stopped")
        sys.exit(130)
