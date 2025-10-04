#!/usr/bin/env python3
"""Client Demo with Live Monitoring.

Shows what's happening in real-time as agents respond.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_use import MCPClient

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
except ImportError:
    print("❌ Need rich: uv add rich")
    sys.exit(1)


console = Console()


async def send_message(config_path: str, content: str):
    """Send a message via MCP."""
    console.print(f"[dim]📤 Sending via {Path(config_path).stem}...[/dim]")

    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()

    server_name = list(client.config.get("mcpServers", {}).keys())[0]
    session = client.get_session(server_name)

    await session.call_tool("messages", arguments={
        "action": "send",
        "content": content,
    })

    await client.close_all_sessions()
    console.print("[green]✅ Message sent![/green]")


async def check_for_responses(config_path: str, search_query: str):
    """Poll for responses."""
    client = MCPClient.from_config_file(config_path)
    await client.create_all_sessions()

    server_name = list(client.config.get("mcpServers", {}).keys())[0]
    session = client.get_session(server_name)

    result = await session.call_tool("search", arguments={
        "action": "search",
        "query": search_query,
        "limit": 5,
        "scope": "messages",
    })

    await client.close_all_sessions()

    # Parse results
    messages = []
    if hasattr(result, "structuredContent"):
        data = result.structuredContent
        if isinstance(data, dict) and "messages" in data:
            messages = data.get("messages", [])

    return messages


def render_status(stage: str, grok_responded: bool = False, response_text: str = ""):
    """Render current demo status."""
    table = Table(show_header=False, box=box.ROUNDED, width=70)
    table.add_column("", style="cyan", width=25)
    table.add_column("", width=45)

    # Stage indicator
    if stage == "posting":
        table.add_row("🎯 Stage", "[yellow]Posting question...[/yellow]")
    elif stage == "waiting":
        table.add_row("🎯 Stage", "[yellow]Waiting for @grok...[/yellow]")
    elif stage == "received":
        table.add_row("🎯 Stage", "[green]Response received![/green]")

    # Agent status
    grok_status = "[green]✅ Responded[/green]" if grok_responded else "[dim]⏳ Thinking...[/dim]"
    table.add_row("@open_router_grok4_fast", grok_status)

    # Response preview
    if response_text:
        preview = response_text[:100] + "..." if len(response_text) > 100 else response_text
        table.add_row("Preview", f"[dim]{preview}[/dim]")

    return Panel(
        table,
        title="[bold]🏦 Client Demo - Live[/bold]",
        border_style="blue",
        box=box.DOUBLE,
    )


async def main():
    console.clear()

    # Header
    console.print(Panel(
        "[bold white]Client - AI Prediction Market Demo[/bold white]\n"
        "[dim]Demonstrating distributed AI agents with web search[/dim]",
        style="bold blue",
        box=box.DOUBLE,
    ))
    console.print()

    # Step 1: Post question
    console.print("[cyan]Step 1: @director posts market question[/cyan]\n")

    message = """@open_router_grok4_fast

🎯 **Prediction Market - Client Demo**

Will S&P 500 close above 6000 today?

Please use your DuckDuckGo web search to check:
1. Current S&P 500 price
2. Today's market trend
3. Any major news affecting the market

Then make your prediction: [YES/NO] [Confidence %] [Reasoning with data]

#boa-demo #prediction-market
"""

    with Live(render_status("posting"), refresh_per_second=2) as live:
        await send_message("configs/mcp_config_director.json", message)
        await asyncio.sleep(2)

        # Step 2: Monitor for response
        console.print("\n[cyan]Step 2: Monitoring @open_router_grok4_fast response[/cyan]\n")

        response_received = False
        response_text = ""
        check_count = 0

        while not response_received and check_count < 30:  # 2.5 minutes max
            live.update(render_status("waiting", False))

            # Check for responses
            messages = await check_for_responses(
                "configs/mcp_config_director.json",
                "#boa-demo"
            )

            # Look for grok's response
            for msg in messages:
                author = msg.get("author", "")
                if "grok" in author.lower():
                    response_text = msg.get("content", "")
                    response_received = True
                    break

            if response_received:
                live.update(render_status("received", True, response_text))
                break

            check_count += 1
            await asyncio.sleep(5)

    console.print()

    if response_received:
        console.print("[bold green]✅ Demo Complete![/bold green]\n")
        console.print("[cyan]@open_router_grok4_fast's Response:[/cyan]")
        console.print(Panel(response_text, border_style="green"))
        console.print()
        console.print("[dim]💡 This demonstrated:[/dim]")
        console.print("[dim]  • Distributed AI agents working autonomously[/dim]")
        console.print("[dim]  • Real-time web search integration[/dim]")
        console.print("[dim]  • No human intervention required[/dim]")
    else:
        console.print("[yellow]⏰ @grok is still processing (check aX for live updates)[/yellow]")
        console.print("[dim]Note: First response may take 1-2 minutes as agent initializes[/dim]")


if __name__ == "__main__":
    asyncio.run(main())