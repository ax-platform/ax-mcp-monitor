#!/usr/bin/env python3
"""Orchestrated Prediction Market - Everything in ONE script!

No monitors needed. Script calls each agent directly in round-robin fashion.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich import box
except ImportError:
    print("Need: uv add rich")
    sys.exit(1)


console = Console()


AGENTS = [
    {
        "name": "@open_router_grok4_fast",
        "config": "configs/mcp_config_grok4.json",
        "prompt": "Use your DuckDuckGo web search to research current S&P 500 data. What's the current price and trend? Make your prediction: [YES/NO] [Confidence %] [Brief reasoning with data]",
        "capability": "🔍 Web Search",
    },
    {
        "name": "@HaloScript",
        "config": "configs/mcp_config_halo_script.json",
        "prompt": "Based on market analysis and patterns, make your prediction on whether S&P 500 will close above 6000 today. Format: [YES/NO] [Confidence %] [Brief reasoning]",
        "capability": "🧠 Analysis",
    },
    {
        "name": "@Aurora",
        "config": "configs/mcp_config_Aurora.json",
        "prompt": "Provide your perspective on S&P 500 closing above 6000 today. Format: [YES/NO] [Confidence %] [Brief reasoning]",
        "capability": "💡 Insights",
    },
]


async def send_message(config_path: str, content: str, agent_name: str):
    """Send a message from a specific agent."""
    try:
        client = MCPClient.from_config_file(config_path)
        await client.create_all_sessions()

        server_name = list(client.config.get("mcpServers", {}).keys())[0]
        session = client.get_session(server_name)

        result = await session.call_tool("messages", arguments={
            "action": "send",
            "content": content,
        })

        await client.close_all_sessions()
        return True

    except Exception as e:
        console.print(f"[red]Error from {agent_name}: {e}[/red]")
        return False


async def call_agent_for_prediction(agent: dict, market_question: str):
    """Call a specific agent to make a prediction."""

    console.print(f"\n[cyan]{'='*60}[/cyan]")
    console.print(f"[bold cyan]🤖 Calling {agent['name']} {agent['capability']}[/bold cyan]")
    console.print(f"[cyan]{'='*60}[/cyan]\n")

    # Build the message to this agent
    message = f"""🎯 **Prediction Market Question**

{market_question}

**Your task:**
{agent['prompt']}

#boa-prediction-market #round-robin-demo
"""

    console.print(f"[dim]📤 Sending to {agent['name']}...[/dim]")

    success = await send_message(agent["config"], message, agent["name"])

    if success:
        console.print(f"[green]✅ {agent['name']} received request[/green]")
        console.print(f"[dim]   Agent will process and respond to aX[/dim]")
    else:
        console.print(f"[red]❌ Failed to reach {agent['name']}[/red]")

    return success


async def main():
    console.clear()

    # Header
    console.print(Panel(
        "[bold white]🏦 Client - Orchestrated Prediction Market[/bold white]\n"
        "[dim]Round-robin AI agent coordination - No monitors needed![/dim]",
        style="bold blue",
        box=box.DOUBLE,
    ))
    console.print()

    # Show agents
    agent_table = Table(title="🤖 Agents in Round-Robin", show_header=True, box=box.ROUNDED)
    agent_table.add_column("Order", style="yellow", width=7)
    agent_table.add_column("Agent", style="cyan")
    agent_table.add_column("Capability", style="green")

    for idx, agent in enumerate(AGENTS, 1):
        status = "✅" if Path(agent["config"]).exists() else "❌"
        agent_table.add_row(
            f"{idx}. {status}",
            agent["name"],
            agent["capability"],
        )

    console.print(agent_table)
    console.print()

    # Market question
    market_question = "Will S&P 500 close above 6000 today?"

    console.print(Panel(
        f"[bold]Question:[/bold] {market_question}\n\n"
        "[dim]Each agent will be called in sequence to make their prediction.[/dim]",
        title="[bold]📊 Market Question[/bold]",
        border_style="blue",
    ))
    console.print()

    input("Press Enter to start round-robin agent calls... ")
    console.print()

    # Call each agent in sequence
    for idx, agent in enumerate(AGENTS, 1):
        if not Path(agent["config"]).exists():
            console.print(f"[yellow]⚠️  Skipping {agent['name']} - config not found[/yellow]\n")
            continue

        await call_agent_for_prediction(agent, market_question)

        # Pause between agents
        if idx < len(AGENTS):
            console.print(f"\n[dim]⏳ Waiting 3 seconds before next agent...[/dim]")
            await asyncio.sleep(3)

    # Summary
    console.print(f"\n[cyan]{'='*60}[/cyan]")
    console.print()

    console.print(Panel(
        "[bold green]✅ All Agents Called![/bold green]\n\n"
        "[bold]What just happened:[/bold]\n"
        "1. Script called each agent directly (no @mentions needed)\n"
        "2. Agents processed requests in round-robin order\n"
        "3. Each agent posts their prediction to aX\n"
        "4. Predictions appear in #boa-prediction-market\n\n"
        "[yellow]👉 Check aX now to see all predictions![/yellow]\n\n"
        "[dim]Search: #boa-prediction-market[/dim]",
        border_style="green",
    ))

    console.print()
    console.print("[bold]💡 For Client:[/bold]")
    console.print("  • Orchestrated multi-agent system")
    console.print("  • Round-robin coordination")
    console.print("  • Each agent brings unique capability")
    console.print("  • @grok searches web in real-time")
    console.print("  • Fully automated, no human intervention")
    console.print("  • Transparent decision trail in aX")


if __name__ == "__main__":
    asyncio.run(main())