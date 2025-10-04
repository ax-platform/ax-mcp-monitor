#!/usr/bin/env python3
"""Multi-agent game controller with chaos detection.

Launch 5+ agents and watch them play coordinated games with collision detection,
timing rules, and emergent chaos when messages cross paths.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
except ImportError:
    print("❌ Missing 'rich' library. Install with: uv add rich")
    exit(1)


@dataclass
class GameState:
    """Track game state across all agents."""
    game_type: str
    agents: List[str]
    current_it: Optional[str] = None
    scores: Dict[str, int] = field(default_factory=dict)
    message_log: List[Dict] = field(default_factory=list)
    collision_count: int = 0
    started_at: datetime = field(default_factory=datetime.now)


class MultiAgentGame:
    """Orchestrate multi-agent games with chaos detection."""

    GAMES = {
        "hot_potato": {
            "name": "Hot Potato 🥔",
            "description": "Pass IT status before timeout. Double-mention = you lose!",
            "timeout": 30,
            "rules": [
                "Agent with IT must @mention another agent within 30s",
                "If you get mentioned while you're IT = -1 point",
                "Successfully passing IT = +1 point",
                "Last agent standing wins",
            ],
        },
        "collision_tag": {
            "name": "Collision Tag 💥",
            "description": "Tag others but avoid simultaneous mentions",
            "timeout": 60,
            "rules": [
                "You're IT if someone tags you",
                "Tag someone else within 60s",
                "Can't tag previous tagger",
                "If 2+ agents tag you at once = collision = +2 points for you",
            ],
        },
        "chain_story": {
            "name": "Story Chain 📖",
            "description": "Build a story one sentence at a time",
            "timeout": 45,
            "rules": [
                "Each agent adds ONE sentence",
                "Must @mention next agent",
                "Story must be coherent",
                "Can't mention yourself",
                "Loop back to Agent 1 to complete",
            ],
        },
        "relay_race": {
            "name": "Relay Race 🏃",
            "description": "Pass the baton through all agents as fast as possible",
            "timeout": 20,
            "rules": [
                "Each agent passes to the next in order",
                "Fastest complete loop wins",
                "Can't skip agents",
                "Double-mentions = restart",
            ],
        },
    }

    def __init__(self, game_type: str, agents: List[str]):
        self.game_type = game_type
        self.state = GameState(
            game_type=game_type,
            agents=agents,
            scores={agent: 0 for agent in agents},
        )
        self.console = Console()

    def detect_collision(self, messages: List[Dict], window_seconds: int = 5) -> List[Dict]:
        """Detect when multiple agents mentioned the same target within time window."""
        collisions = []

        # Group messages by target and check timestamps
        target_groups: Dict[str, List[Dict]] = {}

        for msg in messages:
            target = msg.get("target")
            if not target:
                continue

            if target not in target_groups:
                target_groups[target] = []
            target_groups[target].append(msg)

        # Check each group for timing collisions
        for target, msgs in target_groups.items():
            if len(msgs) < 2:
                continue

            # Sort by timestamp
            sorted_msgs = sorted(msgs, key=lambda m: m["timestamp"])

            # Check for messages within window
            for i in range(len(sorted_msgs) - 1):
                msg1 = sorted_msgs[i]
                msg2 = sorted_msgs[i + 1]

                time_diff = (msg2["timestamp"] - msg1["timestamp"]).total_seconds()

                if time_diff <= window_seconds:
                    collisions.append({
                        "target": target,
                        "sources": [msg1["sender"], msg2["sender"]],
                        "time_diff": time_diff,
                        "type": "collision",
                    })

        return collisions

    def render_scoreboard(self) -> Table:
        """Render current scores."""
        table = Table(title="🏆 Scoreboard", show_header=True)
        table.add_column("Agent", style="cyan")
        table.add_column("Score", style="yellow", justify="right")
        table.add_column("Status", style="dim")

        for agent in self.state.agents:
            score = self.state.scores.get(agent, 0)
            status = "🔥 IT" if agent == self.state.current_it else ""
            table.add_row(agent, str(score), status)

        return table

    def render_game_info(self) -> Panel:
        """Render game rules and info."""
        game_info = self.GAMES[self.game_type]

        rules_text = "\n".join(f"  • {rule}" for rule in game_info["rules"])

        content = f"""[bold]{game_info['name']}[/bold]
{game_info['description']}

[bold yellow]Rules:[/bold yellow]
{rules_text}

[dim]Timeout: {game_info['timeout']}s | Collisions: {self.state.collision_count}[/dim]
"""

        return Panel(content, border_style="blue")

    def render_message_feed(self, last_n: int = 10) -> Panel:
        """Render recent messages."""
        if not self.state.message_log:
            content = "[dim]No messages yet...[/dim]"
        else:
            lines = []
            for msg in self.state.message_log[-last_n:]:
                timestamp = msg["timestamp"].strftime("%H:%M:%S")
                sender = msg["sender"]
                target = msg.get("target", "?")
                collision = "💥" if msg.get("collision") else ""
                lines.append(f"[dim]{timestamp}[/dim] {sender} → {target} {collision}")
            content = "\n".join(lines)

        return Panel(content, title="📡 Message Feed", border_style="green")

    def render_display(self):
        """Render full game display."""
        self.console.clear()
        self.console.print(self.render_game_info())
        self.console.print()
        self.console.print(self.render_scoreboard())
        self.console.print()
        self.console.print(self.render_message_feed())
        self.console.print()
        self.console.print("[yellow]Monitoring game... Press Ctrl+C to stop[/yellow]")

    async def start_game(self):
        """Start the game by sending initial kickoff message."""
        game_info = self.GAMES[self.game_type]

        # TODO: Send kickoff message to first agent
        self.state.current_it = self.state.agents[0]

        self.console.print(f"[green]🎮 Starting {game_info['name']}![/green]")
        self.console.print(f"[cyan]{self.state.agents[0]} is IT![/cyan]")

    async def monitor_game(self):
        """Monitor messages and update game state."""
        self.render_display()

        while True:
            # TODO: Check messages from aX platform
            # TODO: Parse @mentions to detect moves
            # TODO: Detect collisions
            # TODO: Update scores
            # TODO: Check for game end conditions

            await asyncio.sleep(2)
            self.render_display()


async def main():
    console = Console()

    # Game selection
    console.print("[bold cyan]🎮 Multi-Agent Game Controller[/bold cyan]\n")
    console.print("Available games:")
    for idx, (key, game) in enumerate(MultiAgentGame.GAMES.items(), 1):
        console.print(f"  [{idx}] {game['name']} - {game['description']}")

    # TODO: Get user input for game selection
    # TODO: Detect available agents from configs
    # TODO: Launch game

    console.print("\n[yellow]⚠️  This is a prototype - full implementation coming![/yellow]")
    console.print("[dim]Game ideas:[/dim]")
    console.print("  • Hot Potato: Pass IT status before timeout")
    console.print("  • Collision Tag: Detect simultaneous @mentions")
    console.print("  • Story Chain: Build collaborative story")
    console.print("  • Relay Race: Speed run through all agents")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Game stopped")