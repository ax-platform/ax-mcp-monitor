#!/usr/bin/env python3
"""Orchestrated prediction market demo - full control!

This script controls EVERYTHING:
1. Posts market question to aX
2. Starts agent monitors to respond
3. Shows live stats as they respond
4. Tracks votes and timing
5. Declares winners

No reliance on @mentions - we run the agents ourselves!
"""

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    from rich.live import Live
except ImportError:
    print("❌ Missing 'rich' library. Install with: uv add rich")
    sys.exit(1)

from mcp_use import MCPClient


class OrchestratedDemo:
    """Control entire prediction market demo."""

    AGENTS = [
        {
            "name": "@open_router_grok4_fast",
            "config": "configs/mcp_config_grok4.json",
            "capability": "🔍 Web Search",
        },
        {
            "name": "@HaloScript",
            "config": "configs/mcp_config_halo_script.json",
            "capability": "🧠 Analysis",
        },
        {
            "name": "@Aurora",
            "config": "configs/mcp_config_Aurora.json",
            "capability": "💡 Insights",
        },
    ]

    MARKETS = [
        {
            "id": "PM-LIVE-001",
            "question": "Will S&P 500 close above 6000 today?",
            "description": "Market resolves at 4:00 PM ET based on closing price",
        },
        {
            "id": "PM-LIVE-002",
            "question": "Will Bitcoin exceed $110k within 7 days?",
            "description": "Resolves YES if BTC hits $110k on any major exchange",
        },
    ]

    def __init__(self):
        self.console = Console()
        self.market = None
        self.agent_processes: Dict[str, subprocess.Popen] = {}
        self.agent_stats = {agent["name"]: {"responded": False, "tokens": 0, "time": 0}
                           for agent in self.AGENTS}

    def render_setup_screen(self):
        """Show demo setup screen."""
        self.console.clear()

        header = Panel(
            "[bold white]🎯 Orchestrated Prediction Market Demo[/bold white]\n"
            "[dim]Full control - we run the agents![/dim]",
            style="bold blue",
            box=box.DOUBLE,
        )

        self.console.print(header)
        self.console.print()

        # Available agents
        agent_table = Table(title="🤖 Available Agents", show_header=True, box=box.ROUNDED)
        agent_table.add_column("Agent", style="cyan")
        agent_table.add_column("Config", style="dim")
        agent_table.add_column("Capability", style="yellow")

        for agent in self.AGENTS:
            config_exists = "✅" if Path(agent["config"]).exists() else "❌"
            agent_table.add_row(
                agent["name"],
                f"{config_exists} {agent['config']}",
                agent["capability"],
            )

        self.console.print(agent_table)
        self.console.print()

        # Available markets
        market_table = Table(title="📊 Available Markets", show_header=True, box=box.ROUNDED)
        market_table.add_column("#", style="yellow", width=3)
        market_table.add_column("Question", style="cyan")

        for idx, market in enumerate(self.MARKETS, 1):
            market_table.add_row(str(idx), market["question"])

        self.console.print(market_table)
        self.console.print()

    async def post_market(self, market_id: str, question: str, description: str):
        """Post market question to aX."""
        self.console.print("[dim]📡 Posting market to aX...[/dim]")

        # Build message WITHOUT @mentions (we control the agents directly!)
        message = f"""🎯 **Prediction Market {market_id}**

**Question:** {question}

**Details:** {description}

**Instructions:**
Agents will respond with predictions below. Format: [YES/NO] [Confidence %] [Reasoning]

#prediction-market #{market_id}
"""

        try:
            client = MCPClient.from_config_file("configs/mcp_config_alerts.json")
            await client.create_all_sessions()

            server_name = list(client.config.get("mcpServers", {}).keys())[0]
            session = client.get_session(server_name)

            await session.call_tool("messages", arguments={
                "action": "send",
                "content": message,
                "idempotency_key": f"orchestrated-{market_id}",
            })

            await client.close_all_sessions()
            self.console.print("[green]✅ Market posted to aX[/green]")
            return True

        except Exception as e:
            self.console.print(f"[red]❌ Failed: {e}[/red]")
            return False

    def start_agent_monitor(self, agent_config: str, agent_name: str, market_id: str):
        """Start a single agent monitor process."""
        self.console.print(f"[dim]🚀 Starting {agent_name}...[/dim]")

        # Use simple_working_monitor.py with the agent's config
        cmd = [
            "uv", "run", "python", "simple_working_monitor.py",
            "--loop",
        ]

        env = {
            **subprocess.os.environ,
            "MCP_CONFIG_PATH": agent_config,
            "PLUGIN_TYPE": "echo",  # Start with echo for speed
            # Could use "ollama" or "langgraph" for real AI
        }

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.agent_processes[agent_name] = proc
            self.console.print(f"[green]✅ {agent_name} started (PID: {proc.pid})[/green]")
            return True
        except Exception as e:
            self.console.print(f"[red]❌ Failed to start {agent_name}: {e}[/red]")
            return False

    def stop_all_agents(self):
        """Stop all running agent monitors."""
        self.console.print("\n[yellow]🛑 Stopping all agents...[/yellow]")
        for name, proc in self.agent_processes.items():
            try:
                proc.terminate()
                proc.wait(timeout=5)
                self.console.print(f"[dim]Stopped {name}[/dim]")
            except Exception:
                proc.kill()

    def render_live_dashboard(self):
        """Show live stats of running agents."""
        table = Table(title="📊 Live Agent Status", show_header=True, box=box.ROUNDED)
        table.add_column("Agent", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("PID", justify="right", style="dim")
        table.add_column("Prediction", style="yellow")

        for agent in self.AGENTS:
            name = agent["name"]
            proc = self.agent_processes.get(name)

            if proc and proc.poll() is None:
                status = "[green]🟢 Running[/green]"
                pid = str(proc.pid)
            elif proc:
                status = "[red]🔴 Stopped[/red]"
                pid = "—"
            else:
                status = "[dim]⚪ Not started[/dim]"
                pid = "—"

            stats = self.agent_stats.get(name, {})
            prediction = stats.get("prediction", "—")

            table.add_row(name, status, pid, prediction)

        self.console.print(table)

    async def run_demo_flow(self):
        """Execute full demo: post market → start agents → monitor → stop."""
        self.render_setup_screen()

        # Select market
        choice = input("\nSelect market (1-2) or Q to quit: ").strip()
        if choice.lower() == 'q':
            return

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(self.MARKETS):
                self.console.print("[red]Invalid selection[/red]")
                return

            self.market = self.MARKETS[idx]

        except ValueError:
            self.console.print("[red]Invalid input[/red]")
            return

        # Post market
        self.console.print(f"\n[cyan]📊 Creating market: {self.market['question']}[/cyan]")
        success = await self.post_market(
            self.market["id"],
            self.market["question"],
            self.market["description"],
        )

        if not success:
            return

        # Ask if we should start agents
        self.console.print("\n[yellow]Start agent monitors?[/yellow]")
        self.console.print("[dim]This will start background processes for each agent[/dim]")
        start = input("Start agents? (y/n): ").strip().lower()

        if start == 'y':
            # Start each agent
            for agent in self.AGENTS:
                if Path(agent["config"]).exists():
                    self.start_agent_monitor(
                        agent["config"],
                        agent["name"],
                        self.market["id"],
                    )
                    await asyncio.sleep(2)  # Stagger starts
                else:
                    self.console.print(f"[yellow]⚠️  Skipping {agent['name']} - config not found[/yellow]")

            # Monitor live
            self.console.print("\n[green]✅ All agents started![/green]")
            self.console.print("[dim]Agents are now monitoring for the market question[/dim]")
            self.console.print("[dim]Press Ctrl+C to stop all agents[/dim]\n")

            try:
                while True:
                    self.console.clear()
                    self.render_live_dashboard()
                    await asyncio.sleep(5)
            except KeyboardInterrupt:
                pass

        # Cleanup
        self.stop_all_agents()
        self.console.print("\n[green]✅ Demo complete![/green]")

    async def run(self):
        """Main entry point."""
        try:
            await self.run_demo_flow()
        except KeyboardInterrupt:
            self.console.print("\n[yellow]👋 Demo interrupted[/yellow]")
            self.stop_all_agents()


async def main():
    demo = OrchestratedDemo()
    await demo.run()


if __name__ == "__main__":
    asyncio.run(main())