#!/usr/bin/env python3
"""Live streaming monitor for prediction markets with agent stats.

Shows real-time agent responses, token counts, vote tracking, and timing stats.
"""

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich import box
    from rich.layout import Layout
    from rich.text import Text
except ImportError:
    print("❌ Missing 'rich' library. Install with: uv add rich")
    sys.exit(1)

from mcp_use import MCPClient


@dataclass
class AgentResponse:
    """Track individual agent responses."""
    agent: str
    responded: bool = False
    prediction: Optional[str] = None  # "YES 95%"
    reasoning: Optional[str] = None
    token_count: int = 0
    response_time: Optional[float] = None
    message_id: Optional[str] = None
    votes_received: List[str] = field(default_factory=list)  # ["👍 @HaloScript", "🚀 @Aurora"]
    timestamp: Optional[datetime] = None


class LivePredictionMonitor:
    """Monitor prediction market with live stats."""

    def __init__(self, market_id: str, question: str, config_path: str = "configs/mcp_config_alerts.json"):
        self.market_id = market_id
        self.question = question
        self.config_path = config_path
        self.console = Console()

        self.agents = {
            "@open_router_grok4_fast": AgentResponse("@open_router_grok4_fast"),
            "@HaloScript": AgentResponse("@HaloScript"),
            "@Aurora": AgentResponse("@Aurora"),
        }

        self.start_time = datetime.now()
        self.total_messages = 0

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token)."""
        return len(text) // 4

    def parse_prediction(self, text: str) -> Optional[str]:
        """Extract prediction like 'YES 95%' or 'NO 60%'."""
        # Look for patterns like: YES 95%, NO 60%, etc.
        match = re.search(r'\b(YES|NO)\s+(\d+)%', text, re.IGNORECASE)
        if match:
            return f"{match.group(1).upper()} {match.group(2)}%"

        # Also try without percentage
        match = re.search(r'\b(YES|NO)\b', text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        return None

    def parse_vote(self, text: str, sender: str) -> Optional[str]:
        """Check if message is a vote (contains emoji + no prediction)."""
        # If it's a short message with emoji and no YES/NO, it's a vote
        if len(text) < 100 and not self.parse_prediction(text):
            # Extract emoji
            emojis = re.findall(r'[👍👎🚀💡🤔🔥💯⭐]', text)
            if emojis:
                return f"{emojis[0]} {sender}"
        return None

    def render_agent_row(self, agent_name: str, response: AgentResponse) -> Table:
        """Render a single agent's status."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("", style="cyan", width=30)
        table.add_column("", width=50)

        if response.responded:
            # Agent has responded
            status = f"[green]✅ {agent_name}[/green]"
            pred = f"[yellow]{response.prediction or 'Unknown'}[/yellow]"
            tokens = f"[dim]Tokens: {response.token_count}[/dim]"

            if response.response_time:
                timing = f"[dim]Response: {response.response_time:.1f}s[/dim]"
            else:
                timing = ""

            votes = ", ".join(response.votes_received) if response.votes_received else "[dim]No votes yet[/dim]"

            table.add_row(status, "")
            table.add_row("  Prediction:", pred)
            table.add_row("  Stats:", f"{tokens}  {timing}")
            if response.votes_received:
                table.add_row("  Votes:", votes)
        else:
            # Still waiting
            table.add_row(f"[dim]⏳ {agent_name}[/dim]", "[dim]Waiting for response...[/dim]")

        return table

    def render_display(self) -> Layout:
        """Render complete live display."""
        # Header
        header = Panel(
            f"[bold white]📊 Prediction Market {self.market_id} - LIVE MONITOR[/bold white]\n"
            f"[dim]{self.question}[/dim]",
            style="bold blue",
            box=box.DOUBLE,
        )

        # Agent responses
        agent_display = []
        for agent_name in ["@open_router_grok4_fast", "@HaloScript", "@Aurora"]:
            response = self.agents[agent_name]
            agent_display.append(self.render_agent_row(agent_name, response))

        # Stats summary
        responded_count = sum(1 for a in self.agents.values() if a.responded)
        total_tokens = sum(a.token_count for a in self.agents.values())
        avg_time = sum(a.response_time for a in self.agents.values() if a.response_time) / max(responded_count, 1)

        stats = Table(show_header=False, box=box.ROUNDED)
        stats.add_column("Metric", style="cyan")
        stats.add_column("Value", style="yellow", justify="right")
        stats.add_row("Responses", f"{responded_count}/3")
        stats.add_row("Total Tokens", f"{total_tokens:,}")
        if responded_count > 0:
            stats.add_row("Avg Response Time", f"{avg_time:.1f}s")
        stats.add_row("Messages Seen", str(self.total_messages))

        elapsed = (datetime.now() - self.start_time).total_seconds()
        stats.add_row("Elapsed", f"{int(elapsed)}s")

        # Build layout
        self.console.clear()
        self.console.print(header)
        self.console.print()

        for agent_table in agent_display:
            self.console.print(agent_table)
            self.console.print()

        self.console.print(Panel(stats, title="[bold]📊 Stats[/bold]", border_style="green"))

    async def check_messages(self) -> List[Dict]:
        """Poll for new messages."""
        try:
            client = MCPClient.from_config_file(self.config_path)
            await client.create_all_sessions()

            server_name = list(client.config.get("mcpServers", {}).keys())[0]
            session = client.get_session(server_name)

            # Search for messages in this market
            search_result = await session.call_tool("search", arguments={
                "action": "search",
                "query": f"#{self.market_id}",
                "limit": 20,
                "scope": "messages",
            })

            await client.close_all_sessions()

            # Parse search results
            messages = []
            if hasattr(search_result, "structuredContent"):
                data = search_result.structuredContent
                if isinstance(data, dict) and "messages" in data:
                    messages = data["messages"]

            return messages

        except Exception as e:
            self.console.print(f"[red]Error checking messages: {e}[/red]")
            return []

    async def process_message(self, msg: Dict):
        """Process a message and update agent stats."""
        sender = msg.get("author") or msg.get("sender", "")
        content = msg.get("content") or msg.get("text", "")

        # Clean up sender
        if isinstance(sender, str):
            sender = sender.strip().split()[0]  # Get first word (handle)
            if not sender.startswith("@"):
                sender = f"@{sender}"

        # Skip if not from our tracked agents
        if sender not in self.agents:
            # Check if it's a vote for someone
            vote = self.parse_vote(content, sender)
            if vote:
                # Find which agent this is voting for (look for @mentions in content)
                for agent_name in self.agents.keys():
                    if agent_name in content:
                        self.agents[agent_name].votes_received.append(vote)
            return

        response = self.agents[sender]

        # Skip if already processed
        if response.responded:
            return

        # Parse prediction
        prediction = self.parse_prediction(content)
        if not prediction:
            return  # Not a prediction message

        # Update response
        response.responded = True
        response.prediction = prediction
        response.reasoning = content[:100] + "..." if len(content) > 100 else content
        response.token_count = self.estimate_tokens(content)
        response.message_id = msg.get("id")
        response.timestamp = datetime.now()

        # Calculate response time
        if self.start_time:
            response.response_time = (response.timestamp - self.start_time).total_seconds()

    async def monitor(self):
        """Main monitoring loop."""
        self.console.print("[cyan]🚀 Starting live prediction market monitor...[/cyan]")
        self.console.print(f"[dim]Market: {self.market_id}[/dim]")
        self.console.print(f"[dim]Question: {self.question}[/dim]\n")

        await asyncio.sleep(2)

        try:
            while True:
                # Fetch latest messages
                messages = await self.check_messages()
                self.total_messages = len(messages)

                # Process new messages
                for msg in messages:
                    await self.process_message(msg)

                # Render display
                self.render_display()

                # Check if all responded
                if all(a.responded for a in self.agents.values()):
                    self.console.print("\n[green]✅ All agents have responded![/green]")
                    self.console.print("\n[dim]Press Ctrl+C to exit[/dim]")

                # Wait before next poll
                await asyncio.sleep(5)

        except KeyboardInterrupt:
            self.console.print("\n\n[yellow]👋 Monitor stopped[/yellow]")


async def main():
    # TODO: Get market ID from args or recent market
    monitor = LivePredictionMonitor(
        market_id="PM-001",
        question="Will S&P 500 close above 6000 today?",
    )
    await monitor.monitor()


if __name__ == "__main__":
    asyncio.run(main())