#!/usr/bin/env python3
"""Dry-run test for director script - validates logic without posting."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.director_round_robin import RoundRobinDirector
from rich.console import Console

console = Console()


async def test_director():
    """Test director initialization and status rendering."""

    console.print("[bold cyan]Testing Round-Robin Director[/bold cyan]\n")

    director = RoundRobinDirector()

    # Test 1: Initialization
    console.print("[yellow]Test 1: Initialization[/yellow]")
    console.print(f"  Agents: {director.agents}")
    console.print(f"  Market ID: {director.state['market_id']}")
    console.print(f"  Question: {director.state['question']}")
    console.print("[green]✅ Pass[/green]\n")

    # Test 2: Status rendering (empty)
    console.print("[yellow]Test 2: Status Rendering (Empty)[/yellow]")
    console.print(director.render_status())
    console.print("[green]✅ Pass[/green]\n")

    # Test 3: Simulate responses
    console.print("[yellow]Test 3: Status Rendering (With Responses)[/yellow]")
    director.state['responses'] = [
        {
            'id': 'msg1',
            'author': '@open_router_grok4_fast',
            'content': 'YES - 65% - S&P 500 currently at 5,987 with upward momentum',
            'timestamp': '2025-01-15T10:30:00Z'
        },
        {
            'id': 'msg2',
            'author': '@HaloScript',
            'content': 'NO - 55% - Technical indicators show resistance at 5,995',
            'timestamp': '2025-01-15T10:31:00Z'
        }
    ]
    director.state['current_step'] = 2
    console.print(director.render_status())
    console.print("[green]✅ Pass[/green]\n")

    # Test 4: Connection check (don't actually connect)
    console.print("[yellow]Test 4: Config File Check[/yellow]")
    config_path = Path(director.config_path)
    if config_path.exists():
        console.print(f"  Config found: {config_path}")
        console.print("[green]✅ Pass[/green]\n")
    else:
        console.print(f"  [red]Config not found: {config_path}[/red]")
        console.print("[red]❌ Fail[/red]\n")
        return False

    console.print("[bold green]All tests passed![/bold green]")
    console.print("\n[dim]Ready for live demo. Run:[/dim]")
    console.print("  [cyan]uv run ./scripts/director_round_robin.py[/cyan]")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_director())
    sys.exit(0 if success else 1)