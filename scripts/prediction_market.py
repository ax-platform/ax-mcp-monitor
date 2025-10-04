#!/usr/bin/env python3
"""5-Agent Prediction Market with Reaction Voting.

Agents make predictions on real-world events, other agents and humans vote with
emoji reactions, reputation scores track accuracy over time.

Flow:
1. Market maker posts prediction question
2. 5 agents (@Grok, @HaloScript, @Aurora, @cbms, @copilot_nexus) make predictions
3. Everyone votes with emoji reactions (👍=bullish, 👎=bearish, 🚀=strong agree)
4. Market resolves based on actual outcome
5. Reputation scores update based on accuracy + reaction alignment
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.layout import Layout
    from rich.live import Live
    from rich import box
except ImportError:
    print("❌ Missing 'rich' library. Install with: uv add rich")
    sys.exit(1)

from mcp_use import MCPClient


@dataclass
class AgentPrediction:
    """Single agent's prediction."""
    agent: str
    prediction: str  # "YES" or "NO" or probability like "75% YES"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    timestamp: datetime
    message_id: Optional[str] = None
    reactions: Dict[str, int] = field(default_factory=dict)  # emoji -> count


@dataclass
class Market:
    """Prediction market state."""
    id: str
    question: str
    description: str
    resolution_date: datetime
    created_at: datetime
    predictions: List[AgentPrediction] = field(default_factory=list)
    resolved: bool = False
    outcome: Optional[str] = None  # "YES" or "NO"
    resolution_reasoning: Optional[str] = None


@dataclass
class AgentReputation:
    """Agent reputation tracking."""
    agent: str
    total_predictions: int = 0
    correct_predictions: int = 0
    total_reactions_received: int = 0
    reaction_breakdown: Dict[str, int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions

    @property
    def reputation_score(self) -> int:
        """Calculate overall reputation score."""
        base = self.correct_predictions * 100

        # Reaction bonuses
        reaction_values = {
            "👍": 5,
            "🚀": 10,
            "🔥": 8,
            "💯": 8,
            "⭐": 7,
            "💡": 3,
            "🤔": 2,
            "👎": -5,
            "🚩": -8,
        }

        reaction_score = sum(
            self.reaction_breakdown.get(emoji, 0) * value
            for emoji, value in reaction_values.items()
        )

        return base + reaction_score


class PredictionMarketController:
    """Control prediction markets with multiple agents."""

    AGENTS = [
        "@open_router_grok4_fast",  # Has web search!
        "@HaloScript",
        "@Aurora",
        # Using 3 agents for faster, cleaner demos
    ]

    SAMPLE_MARKETS = [
        {
            "question": "Will S&P 500 close above 6000 today?",
            "description": "Market resolves at 4:00 PM ET based on closing price",
            "category": "finance",
        },
        {
            "question": "Will Bitcoin price exceed $110k within 7 days?",
            "description": "Resolves YES if BTC hits $110k on any major exchange within 7 days",
            "category": "crypto",
        },
        {
            "question": "Will it rain in San Francisco tomorrow?",
            "description": "Resolves YES if measurable rain (>0.01 inches) recorded at SFO",
            "category": "weather",
        },
        {
            "question": "Will OpenAI announce GPT-5 this month?",
            "description": "Resolves YES if official announcement from OpenAI by end of month",
            "category": "tech",
        },
    ]

    def __init__(self, config_path: str = "configs/mcp_config_alerts.json"):
        self.console = Console()
        self.config_path = config_path
        self.markets: Dict[str, Market] = {}
        self.reputations: Dict[str, AgentReputation] = {
            agent: AgentReputation(agent=agent)
            for agent in self.AGENTS
        }

    async def send_market_question(self, market: Market) -> bool:
        """Post market question to aX and mention all agents."""

        # Build message - start with Grok who has web search!
        message = f"""@open_router_grok4_fast (🔍 use web search!) @HaloScript @Aurora

🎯 **New Prediction Market Open**

**Question:** {market.question}

**Details:** {market.description}

**Instructions:**
1. @open_router_grok4_fast - Use DuckDuckGo web search to research current data first!
2. @HaloScript & @Aurora - Make predictions based on your analysis
3. Format: [YES/NO] [Confidence %] [Brief reasoning]

**Reaction Voting:**
- 👍 = Agree / Bullish
- 👎 = Disagree / Bearish
- 🚀 = Strong conviction / Great insight
- 💡 = Interesting analysis
- 🤔 = Uncertain

Market {market.id} | Reply with your prediction!

#prediction-market #{market.id}
"""

        # Send via MCP
        try:
            self.console.print("[dim]📡 Connecting to aX...[/dim]", end="")
            client = MCPClient.from_config_file(self.config_path)

            self.console.print(" [green]✓[/green]")
            self.console.print("[dim]🔐 Authenticating...[/dim]", end="")
            await client.create_all_sessions()

            self.console.print(" [green]✓[/green]")
            server_name = list(client.config.get("mcpServers", {}).keys())[0]
            session = client.get_session(server_name)

            self.console.print(f"[dim]📤 Posting to aX (mentioning {len(self.AGENTS)} agents)...[/dim]", end="")
            payload = {
                "action": "send",
                "content": message,
                "idempotency_key": f"market-{market.id}",
            }

            await session.call_tool("messages", payload)
            self.console.print(" [green]✓[/green]")

            self.console.print("[dim]🔌 Closing connection...[/dim]", end="")
            await client.close_all_sessions()
            self.console.print(" [green]✓[/green]\n")

            self.console.print(f"[bold green]✅ Market {market.id} posted successfully![/bold green]")
            return True

        except Exception as e:
            self.console.print(f" [red]✗[/red]")
            self.console.print(f"[red]❌ Failed to post market: {e}[/red]")
            return False

    def render_market_display(self, market: Market) -> Panel:
        """Render a single market with predictions."""

        # Build predictions table
        table = Table(show_header=True, box=box.ROUNDED)
        table.add_column("Agent", style="cyan")
        table.add_column("Prediction", style="yellow")
        table.add_column("Confidence", justify="right")
        table.add_column("Reactions", justify="center")

        for pred in market.predictions:
            reactions_str = " ".join(
                f"{emoji}×{count}"
                for emoji, count in pred.reactions.items()
            ) or "—"

            table.add_row(
                pred.agent,
                pred.prediction,
                f"{pred.confidence:.0%}",
                reactions_str,
            )

        if not market.predictions:
            table.add_row("—", "Waiting for predictions...", "—", "—")

        # Status indicator
        if market.resolved:
            status = f"[green]✅ RESOLVED: {market.outcome}[/green]"
        else:
            status = "[yellow]⏳ OPEN - Awaiting predictions[/yellow]"

        content = f"""[bold]{market.question}[/bold]

{market.description}

{status}

{table}
"""

        return Panel(content, title=f"📊 Market: {market.id}", border_style="blue")

    def render_leaderboard(self) -> Table:
        """Render reputation leaderboard."""
        table = Table(title="🏆 Agent Reputation Leaderboard", show_header=True, box=box.ROUNDED)
        table.add_column("Rank", style="yellow", width=6)
        table.add_column("Agent", style="cyan")
        table.add_column("Score", justify="right", style="bold green")
        table.add_column("Accuracy", justify="right")
        table.add_column("Predictions", justify="right")
        table.add_column("Reactions", justify="right")

        # Sort by reputation score
        sorted_agents = sorted(
            self.reputations.values(),
            key=lambda r: r.reputation_score,
            reverse=True,
        )

        for idx, rep in enumerate(sorted_agents, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")

            table.add_row(
                medal,
                rep.agent,
                f"{rep.reputation_score:,}",
                f"{rep.accuracy:.1%}",
                str(rep.total_predictions),
                str(rep.total_reactions_received),
            )

        return table

    def render_dashboard(self) -> Layout:
        """Render full dashboard."""
        self.console.clear()

        # Header
        self.console.print(Panel(
            "[bold white]🎯 aX Prediction Market - Agent Intelligence Network[/bold white]\n"
            "[dim]Distributed AI agents competing to predict the future[/dim]",
            style="bold blue",
            box=box.DOUBLE,
        ))
        self.console.print()

        # Active markets
        if self.markets:
            for market in self.markets.values():
                self.console.print(self.render_market_display(market))
                self.console.print()

        # Leaderboard
        self.console.print(self.render_leaderboard())
        self.console.print()

        # Controls
        self.console.print("[yellow]Commands: [N]ew Market, [R]esolve Market, [L]eaderboard, [Q]uit[/yellow]")

    async def create_market(self, question: str, description: str) -> Market:
        """Create and post a new market."""
        market_id = f"PM-{len(self.markets) + 1:03d}"

        market = Market(
            id=market_id,
            question=question,
            description=description,
            resolution_date=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        self.markets[market_id] = market

        # Post to aX
        await self.send_market_question(market)

        return market

    async def run(self):
        """Main controller loop."""
        self.render_dashboard()

        self.console.print("\n[cyan]Welcome to the Prediction Market![/cyan]")
        self.console.print("[dim]Let's create your first market...[/dim]\n")

        # Show sample markets
        self.console.print("[bold]Sample Markets:[/bold]")
        for idx, sample in enumerate(self.SAMPLE_MARKETS, 1):
            self.console.print(f"  [{idx}] {sample['question']}")
        self.console.print(f"  [{len(self.SAMPLE_MARKETS) + 1}] Custom question")
        self.console.print("  [Q] Quit\n")

        # Get user input
        choice = input("Select market (1-5) or Q to quit: ").strip().lower()

        if choice == 'q':
            self.console.print("[yellow]👋 Market closed[/yellow]")
            return

        # Handle selection
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(self.SAMPLE_MARKETS):
                sample = self.SAMPLE_MARKETS[idx]
                self.console.print(f"\n[cyan]Creating market: {sample['question']}[/cyan]")

                # Create and post market
                market = await self.create_market(
                    question=sample['question'],
                    description=sample['description'],
                )

                self.console.print(f"\n[green]✅ Market {market.id} created and posted to aX![/green]")
                self.console.print(f"[dim]Agents tagged: {', '.join(self.AGENTS)}[/dim]")
                self.console.print(f"\n[yellow]📡 Now monitoring for agent responses...[/yellow]")
                self.console.print("[dim]Check aX to see agents making predictions![/dim]")
                self.console.print("[dim]Press Ctrl+C to stop monitoring[/dim]\n")

                # Keep running to monitor responses with activity indicator
                heartbeat_count = 0
                heartbeat_icons = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

                while True:
                    # Show we're alive
                    icon = heartbeat_icons[heartbeat_count % len(heartbeat_icons)]
                    self.console.print(f"\r{icon} Waiting for agent predictions... ({heartbeat_count * 5}s elapsed)", end="")

                    await asyncio.sleep(5)
                    heartbeat_count += 1

                    # TODO: Poll for responses and reactions
                    # TODO: Update dashboard when responses come in

                    # Show a status update every 30 seconds
                    if heartbeat_count % 6 == 0:
                        mins = (heartbeat_count * 5) // 60
                        self.console.print(f"\r[dim]💭 Still monitoring... ({mins}m elapsed)[/dim]")
                        self.console.print("[dim]   Agents should respond within 1-2 minutes[/dim]")
                        self.console.print("[dim]   Check aX for their predictions![/dim]")

            else:
                self.console.print("[red]Invalid selection[/red]")

        except ValueError:
            self.console.print("[red]Invalid input - please enter a number[/red]")
        except KeyboardInterrupt:
            self.console.print("\n[yellow]👋 Market monitoring stopped[/yellow]")


async def main():
    controller = PredictionMarketController()
    await controller.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Market closed")