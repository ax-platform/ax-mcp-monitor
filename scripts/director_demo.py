#!/usr/bin/env python3
"""Director-led Prediction Market Demo - Simple & Clean.

@director posts question, agents respond. That's it!
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient

try:
    from rich.console import Console
    from rich.panel import Panel
except ImportError:
    print("Need: uv add rich")
    sys.exit(1)


console = Console()


async def post_prediction_market():
    """Post prediction market question from @director."""

    console.print(Panel(
        "[bold white]🎯 Client - Prediction Market Demo[/bold white]\n"
        "[dim]@director initiates distributed AI collaboration[/dim]",
        style="bold blue",
    ))
    console.print()

    # The question
    message = """@open_router_grok4_fast @HaloScript @Aurora

🎯 **Prediction Market Question**

Will S&P 500 close above 6000 today?

**Instructions:**
- @open_router_grok4_fast: Use web search for current data
- @HaloScript & @Aurora: Provide analysis-based predictions
- Format: [YES/NO] [Confidence %] [Reasoning]

#boa-prediction-market
"""

    console.print("[cyan]📤 @director posting market question...[/cyan]")

    try:
        client = MCPClient.from_config_file("configs/mcp_config_director.json")
        await client.create_all_sessions()

        server_name = list(client.config.get("mcpServers", {}).keys())[0]
        session = client.get_session(server_name)

        await session.call_tool("messages", arguments={
            "action": "send",
            "content": message,
        })

        await client.close_all_sessions()

        console.print("[green]✅ Market question posted![/green]\n")

        console.print(Panel(
            "[bold]What happens next:[/bold]\n\n"
            "1. Agents monitoring aX see the @mention\n"
            "2. @open_router_grok4_fast searches web for S&P 500 data\n"
            "3. @HaloScript and @Aurora analyze and predict\n"
            "4. All predictions appear in aX within 1-2 minutes\n\n"
            "[yellow]👉 Check aX now to see live responses![/yellow]\n\n"
            "[dim]Search for: #boa-prediction-market[/dim]",
            title="[bold green]✅ Demo Running![/bold green]",
            border_style="green",
        ))

        console.print()
        console.print("[bold]💡 For Client:[/bold]")
        console.print("  • Show distributed AI agents working autonomously")
        console.print("  • @grok uses real-time web search")
        console.print("  • Multiple agents provide diverse perspectives")
        console.print("  • No human intervention needed")
        console.print("  • Full audit trail in aX platform")

        return True

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        return False


async def main():
    success = await post_prediction_market()

    if not success:
        console.print("\n[yellow]Troubleshooting:[/yellow]")
        console.print("  • Verify configs/mcp_config_director.json exists")
        console.print("  • Check OAuth token is cached for @director")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())