#!/usr/bin/env python3
"""Chained Prediction Market - Agents build on each other's responses!

Flow:
Round 1: @director → @grok (grok researches)
Round 2: @grok → @HaloScript (halo sees grok's research)
Round 3: @HaloScript → @Aurora (aurora sees both)
Round 4: @Aurora → @director (closes the loop)

Each agent mentions the next, creating a conversation thread!
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
    from rich import box
    from rich.progress import Progress, SpinnerColumn, TextColumn
except ImportError:
    print("Need: uv add rich")
    sys.exit(1)


console = Console()


# Chain: director → grok → halo → aurora → director
CHAIN = [
    {
        "from": "@director",
        "to": "@open_router_grok4_fast",
        "config": "configs/mcp_config_director.json",
        "message": """@open_router_grok4_fast

🎯 **Prediction Market - Round 1**

Will S&P 500 close above 6000 today?

You're first! Use your DuckDuckGo web search to research:
- Current S&P 500 price
- Today's market trend
- Major market news

Make your prediction: [YES/NO] [Confidence %] [Reasoning with data]

Then @mention @HaloScript to get their analysis.

#boa-chained-market""",
    },
    {
        "from": "@open_router_grok4_fast",
        "to": "@HaloScript",
        "config": "configs/mcp_config_grok4.json",
        "message": """@HaloScript

🎯 **Prediction Market - Round 2**

Building on my web search findings, what's your analysis?

Question: Will S&P 500 close above 6000 today?

Review my research above and add your perspective:
[YES/NO] [Confidence %] [Your reasoning]

Then @mention @Aurora for final input.

#boa-chained-market""",
    },
    {
        "from": "@HaloScript",
        "to": "@Aurora",
        "config": "configs/mcp_config_halo_script.json",
        "message": """@Aurora

🎯 **Prediction Market - Round 3**

We have @open_router_grok4_fast's web research and my analysis above.

Question: Will S&P 500 close above 6000 today?

What's your take? [YES/NO] [Confidence %] [Your reasoning]

Then @mention @director with your conclusion.

#boa-chained-market""",
    },
]


async def send_message(config_path: str, content: str, from_agent: str):
    """Send a message from a specific agent."""
    try:
        client = MCPClient.from_config_file(config_path)
        await client.create_all_sessions()

        server_name = list(client.config.get("mcpServers", {}).keys())[0]
        session = client.get_session(server_name)

        await session.call_tool("messages", arguments={
            "action": "send",
            "content": content,
        })

        await client.close_all_sessions()
        return True

    except Exception as e:
        console.print(f"[red]Error from {from_agent}: {e}[/red]")
        return False


def render_chain_visualization(current_step: int):
    """Show visual chain of agents."""
    agents = ["@director", "@grok", "@HaloScript", "@Aurora", "@director"]

    visual = ""
    for i in range(len(agents) - 1):
        if i < current_step:
            visual += f"[green]{agents[i]}[/green] → "
        elif i == current_step:
            visual += f"[yellow]{agents[i]}[/yellow] → "
        else:
            visual += f"[dim]{agents[i]}[/dim] → "

    # Last agent
    if current_step >= len(agents) - 1:
        visual += f"[green]{agents[-1]}[/green]"
    else:
        visual += f"[dim]{agents[-1]}[/dim]"

    return visual


async def execute_chain_step(step: dict, step_num: int, total: int):
    """Execute one step in the chain."""

    console.print(f"\n[cyan]{'='*70}[/cyan]")
    console.print(f"[bold cyan]Step {step_num}/{total}: {step['from']} → {step['to']}[/bold cyan]")
    console.print(f"[cyan]{'='*70}[/cyan]\n")

    # Show chain visualization
    console.print(Panel(
        render_chain_visualization(step_num - 1),
        title="[bold]🔗 Agent Chain[/bold]",
        border_style="blue",
    ))
    console.print()

    if not Path(step["config"]).exists():
        console.print(f"[red]❌ Config not found: {step['config']}[/red]")
        return False

    console.print(f"[dim]📤 {step['from']} sending message...[/dim]")

    success = await send_message(step["config"], step["message"], step["from"])

    if success:
        console.print(f"[green]✅ Message sent![/green]")
        console.print(f"[dim]   {step['to']} will see this and respond[/dim]")
    else:
        console.print(f"[red]❌ Failed to send message[/red]")

    return success


async def main():
    console.clear()

    # Header
    console.print(Panel(
        "[bold white]🏦 Client - Chained Prediction Market[/bold white]\n"
        "[dim]Agents collaborate in sequence, building on each other's insights[/dim]",
        style="bold blue",
        box=box.DOUBLE,
    ))
    console.print()

    # Show the chain
    console.print("[bold]🔗 Collaboration Chain:[/bold]")
    console.print()
    console.print("  1. [cyan]@director[/cyan] kicks off → [cyan]@grok[/cyan] researches web")
    console.print("  2. [cyan]@grok[/cyan] shares findings → [cyan]@HaloScript[/cyan] analyzes")
    console.print("  3. [cyan]@HaloScript[/cyan] adds analysis → [cyan]@Aurora[/cyan] concludes")
    console.print("  4. [cyan]@Aurora[/cyan] summarizes → [cyan]@director[/cyan] closes loop")
    console.print()

    console.print("[bold]💡 Each agent sees previous responses and builds on them![/bold]")
    console.print()

    input("Press Enter to start the chain... ")

    # Execute chain
    for idx, step in enumerate(CHAIN, 1):
        success = await execute_chain_step(step, idx, len(CHAIN))

        if not success:
            console.print(f"\n[yellow]⚠️  Chain interrupted at step {idx}[/yellow]")
            break

        # Pause between steps
        if idx < len(CHAIN):
            console.print(f"\n[dim]⏳ Waiting 5 seconds for agent to process...[/dim]")
            await asyncio.sleep(5)

    # Summary
    console.print(f"\n[cyan]{'='*70}[/cyan]")
    console.print()

    console.print(Panel(
        "[bold green]✅ Chain Complete![/bold green]\n\n"
        "[bold]What just happened:[/bold]\n"
        "1. @director initiated the market question\n"
        "2. @grok searched web and posted findings\n"
        "3. @HaloScript saw grok's data and added analysis\n"
        "4. @Aurora reviewed both and made final prediction\n\n"
        "[yellow]👉 Check aX to see the full conversation thread![/yellow]\n\n"
        "[dim]Search: #boa-chained-market[/dim]",
        border_style="green",
    ))

    console.print()
    console.print("[bold]🎯 For Client:[/bold]")
    console.print("  • Collaborative AI decision-making")
    console.print("  • Each agent builds on previous insights")
    console.print("  • @grok provides real-time web data")
    console.print("  • Chain creates transparent reasoning trail")
    console.print("  • Demonstrates true multi-agent coordination")


if __name__ == "__main__":
    asyncio.run(main())