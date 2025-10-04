#!/usr/bin/env python3
"""Director-Orchestrated Prediction Market - Director chooses the flow!

@director makes intelligent decisions about:
- Which agent to call first, second, third
- What questions to ask each agent
- When to synthesize results

True AI orchestration!
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
except ImportError:
    print("Need: uv add rich")
    sys.exit(1)


console = Console()


async def send_as_director(content: str):
    """Send a message from @director."""
    try:
        client = MCPClient.from_config_file("configs/mcp_config_director.json")
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
        console.print(f"[red]Error: {e}[/red]")
        return False


async def main():
    console.clear()

    console.print(Panel(
        "[bold white]🏦 Client - Director Orchestration Demo[/bold white]\n"
        "[dim]@director makes intelligent decisions about agent coordination[/dim]",
        style="bold blue",
        box=box.DOUBLE,
    ))
    console.print()

    # Step 1: Director announces and chooses first agent
    console.print("[cyan]Step 1: @director initiates and chooses first agent[/cyan]\n")

    message1 = """🎯 **Prediction Market - Director Orchestrated**

I'm initiating a prediction market on: Will S&P 500 close above 6000 today?

**My decision:** I'll start with @open_router_grok4_fast since they have web search capability to get current market data.

@open_router_grok4_fast - Please search for:
1. Current S&P 500 price
2. Today's market trend
3. Major news affecting the market

Make your prediction: [YES/NO] [Confidence %] [Data-driven reasoning]

Then I'll decide who analyzes your findings next.

#director-orchestrated #boa-demo
"""

    console.print("[dim]@director posting...[/dim]")
    success = await send_as_director(message1)

    if success:
        console.print("[green]✅ @director's first message sent![/green]")
        console.print("[dim]   @director chose @grok first (web search capability)[/dim]")
    else:
        console.print("[red]❌ Failed[/red]")
        return

    console.print()
    input("Press Enter when @grok has responded (check aX)... ")
    console.print()

    # Step 2: Director responds to grok and chooses next agent
    console.print("[cyan]Step 2: @director reviews and chooses next agent[/cyan]\n")

    message2 = """@open_router_grok4_fast Thanks for the web search data!

Based on your findings, I'm now bringing in @HaloScript for analytical review.

@HaloScript - Review @grok's web research above. Does the data support their prediction? Add your analytical perspective:
[YES/NO] [Confidence %] [Reasoning]

I'll synthesize both views before making a final call.

#director-orchestrated #boa-demo
"""

    console.print("[dim]@director choosing next agent...[/dim]")
    success = await send_as_director(message2)

    if success:
        console.print("[green]✅ @director chose @HaloScript next![/green]")
        console.print("[dim]   @director is coordinating the analysis flow[/dim]")
    else:
        console.print("[red]❌ Failed[/red]")
        return

    console.print()
    input("Press Enter when @HaloScript has responded (check aX)... ")
    console.print()

    # Step 3: Director chooses third agent
    console.print("[cyan]Step 3: @director adds final perspective[/cyan]\n")

    message3 = """Thanks @HaloScript for the analysis!

I'm bringing in @Aurora for a final independent perspective.

@Aurora - We have:
- @grok's web research
- @HaloScript's analysis

Question: Will S&P 500 close above 6000 today?

Your prediction: [YES/NO] [Confidence %] [Reasoning]

After your input, I'll synthesize all three perspectives.

#director-orchestrated #boa-demo
"""

    console.print("[dim]@director adding final agent...[/dim]")
    success = await send_as_director(message3)

    if success:
        console.print("[green]✅ @director chose @Aurora for final input![/green]")
        console.print("[dim]   @director is building multi-perspective analysis[/dim]")
    else:
        console.print("[red]❌ Failed[/red]")
        return

    console.print()
    input("Press Enter when @Aurora has responded (check aX)... ")
    console.print()

    # Step 4: Director synthesizes
    console.print("[cyan]Step 4: @director synthesizes all predictions[/cyan]\n")

    message4 = """**Market Synthesis - Director's Decision**

I've reviewed all three agent predictions:

✅ @open_router_grok4_fast - Web search data
✅ @HaloScript - Analytical review
✅ @Aurora - Independent perspective

**Market Decision:** [Check consensus from above responses]

This demonstrates distributed AI decision-making with intelligent orchestration. Each agent brought unique capabilities, and I coordinated the flow based on their strengths.

#director-orchestrated #boa-demo #market-closed
"""

    console.print("[dim]@director synthesizing results...[/dim]")
    success = await send_as_director(message4)

    if success:
        console.print("[green]✅ @director synthesized all predictions![/green]")
    else:
        console.print("[red]❌ Failed[/red]")
        return

    # Summary
    console.print()
    console.print(Panel(
        "[bold green]✅ Director Orchestration Complete![/bold green]\n\n"
        "[bold]What happened:[/bold]\n"
        "1. @director chose @grok first (web search needed)\n"
        "2. @director chose @HaloScript second (analytical review)\n"
        "3. @director chose @Aurora third (independent view)\n"
        "4. @director synthesized all perspectives\n\n"
        "[yellow]👉 Check aX to see full orchestrated flow![/yellow]\n\n"
        "[dim]Search: #director-orchestrated[/dim]",
        border_style="green",
    ))

    console.print()
    console.print("[bold]🎯 For Client:[/bold]")
    console.print("  • AI-driven orchestration (not scripted)")
    console.print("  • @director makes intelligent choices")
    console.print("  • Each agent called for their unique capability")
    console.print("  • Real-time web search + analysis + synthesis")
    console.print("  • Transparent decision-making process")
    console.print("  • Fully autonomous - no human intervention")


if __name__ == "__main__":
    asyncio.run(main())