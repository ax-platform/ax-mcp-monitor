#!/usr/bin/env python3
"""Interactive terminal controller for Client fraud demo.

Provides a clean, professional interface for running the scripted demo with
real-time status updates and single-keypress controls.
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.text import Text
    from rich.layout import Layout
except ImportError:
    print("❌ Missing 'rich' library. Install with: uv pip install rich")
    sys.exit(1)

from scripts.demo_canned_message import STEPS, _send_message, _normalise_handle

console = Console()


class DemoController:
    def __init__(self):
        self.messages_sent = []
        self.start_time = datetime.now()
        self.current_step = 0
        self.auto_running = False

    def get_status_table(self) -> Table:
        """Build status table showing monitors and readiness."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Status", style="bold")
        table.add_column("Agent", style="cyan")
        table.add_column("Location")

        # Check if config files exist to show "ready"
        configs = {
            "@HaloScript": "configs/mcp_config_halo_script.json",
            "@Grok": "configs/mcp_config_grok4.json",
            "@alerts": "configs/mcp_config_alerts.json",
        }

        for agent, config_path in configs.items():
            if Path(config_path).exists():
                table.add_row("✅ READY", agent, "[GCP]")
            else:
                table.add_row("⚠️  MISSING", agent, f"{config_path}")

        return table

    def get_flow_table(self) -> Table:
        """Build demo flow table with steps."""
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="bold yellow", width=5)
        table.add_column("Step")
        table.add_column("Flow", style="dim")

        steps_list = [
            ("1", "🚨 Alert Kickoff", "@alerts → @HaloScript"),
            ("2", "🤝 Halo Hand-off", "@HaloScript → @Grok"),
            ("3", "🔍 Grok Analysis", "@Grok → @HaloScript"),
            ("4", "✅ Halo Closeout", "@HaloScript → @alerts"),
        ]

        for key, name, flow in steps_list:
            step_num = int(key) - 1
            if step_num < len(self.messages_sent):
                # Already sent - show in green
                table.add_row(f"[green]{key}[/green]", f"[green]{name}[/green]", f"[green]{flow}[/green]")
            elif step_num == self.current_step and self.auto_running:
                # Currently sending - show in yellow
                table.add_row(f"[yellow]{key}[/yellow]", f"[yellow]{name}...[/yellow]", f"[yellow]{flow}[/yellow]")
            else:
                table.add_row(key, name, flow)

        table.add_row("", "", "")
        table.add_row("[bold cyan]R[/bold cyan]", "[bold]Run Full Sequence[/bold]", "[dim]Auto-run all steps[/dim]")
        table.add_row("[bold red]Q[/bold red]", "[bold]Quit[/bold]", "")

        return table

    def get_feed_text(self) -> Text:
        """Build live feed of sent messages."""
        if not self.messages_sent:
            return Text("  [Empty - Waiting for demo to start...]", style="dim")

        feed = Text()
        for msg in self.messages_sent[-5:]:  # Show last 5 messages
            timestamp = msg["time"].strftime("%H:%M:%S")
            feed.append(f"  [{timestamp}] ", style="dim")
            feed.append(f"{msg['step']}", style="cyan")
            feed.append(f" {msg['flow']}\n", style="dim")

        return feed

    def render_display(self):
        """Render the full display."""
        from rich.box import ROUNDED

        # Header
        console.print(Panel(
            "[bold white]🏦 Client - Fraud Detection Demo[/bold white]\n"
            "[dim]aX AI Agent Platform[/dim]",
            style="bold blue",
            box=ROUNDED,
        ))
        console.print()

        # Status section
        console.print(Panel(
            self.get_status_table(),
            title="[bold]Monitors Status[/bold]",
            border_style="blue",
            box=ROUNDED,
        ))
        console.print()

        # Flow section
        console.print(Panel(
            self.get_flow_table(),
            title="[bold]Demo Flow[/bold]",
            border_style="blue",
            box=ROUNDED,
        ))
        console.print()

        # Feed section
        console.print(Panel(
            self.get_feed_text(),
            title="[bold]Live Feed[/bold]",
            border_style="blue",
            box=ROUNDED,
        ))
        console.print()

        console.print("[bold yellow]Press number to send step, R for full auto-run, Q to quit[/bold yellow]")

    async def send_step(self, step_name: str) -> bool:
        """Send a specific demo step."""
        if step_name not in STEPS:
            return False

        step = STEPS[step_name]
        config_path = step.default_config
        target_handle = step.default_target

        if not Path(config_path).exists():
            console.print(f"[red]❌ Config not found: {config_path}[/red]")
            return False

        try:
            message = step.render(target_handle)
            idem_key = f"demo-canned-{step.name}-{int(time.time())}"

            await _send_message(
                config_path=config_path,
                content=message,
                idempotency_key=idem_key,
            )

            # Track sent message
            self.messages_sent.append({
                "time": datetime.now(),
                "step": step.description,
                "flow": f"{config_path.split('_')[-1].replace('.json', '')} → {target_handle}",
            })

            return True
        except Exception as e:
            console.print(f"[red]❌ Failed to send {step_name}: {e}[/red]")
            return False

    async def run_full_sequence(self):
        """Run all steps with natural timing."""
        self.auto_running = True
        steps = ["alert-kickoff", "halo-hand-off", "grok-status", "halo-closeout"]

        for idx, step_name in enumerate(steps):
            self.current_step = idx

            success = await self.send_step(step_name)

            if not success:
                console.print(f"[red]❌ Auto-run stopped at step {idx + 1}[/red]")
                break

            # Wait between steps (except after last one)
            if idx < len(steps) - 1:
                await asyncio.sleep(3)

        self.auto_running = False
        self.current_step = 0

    async def run(self):
        """Main controller loop."""
        console.clear()
        self.render_display()
        console.print("\n[bold cyan]>[/bold cyan] ", end="")

        while True:
            # Get user input
            try:
                key = await asyncio.to_thread(sys.stdin.read, 1)
                key = key.lower().strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not key:
                continue

            # Handle commands
            if key == 'q':
                console.print("\n\n[yellow]👋 Demo controller stopped[/yellow]")
                break

            elif key == 'r':
                console.clear()
                console.print("[cyan]🚀 Running full sequence...[/cyan]\n")
                await self.run_full_sequence()
                console.print("\n[green]✅ Full sequence completed![/green]")
                await asyncio.sleep(2)
                console.clear()
                self.render_display()
                console.print("\n[bold cyan]>[/bold cyan] ", end="")

            elif key in ['1', '2', '3', '4']:
                step_map = {
                    '1': 'alert-kickoff',
                    '2': 'halo-hand-off',
                    '3': 'grok-status',
                    '4': 'halo-closeout',
                }
                step_name = step_map[key]

                console.print(f"\n[cyan]📤 Sending {step_name}...[/cyan]")
                success = await self.send_step(step_name)

                if success:
                    console.print("[green]✅ Sent![/green]")

                await asyncio.sleep(1)
                console.clear()
                self.render_display()
                console.print("\n[bold cyan]>[/bold cyan] ", end="")

            else:
                console.print(f"\n[dim]Unknown command: {key}[/dim]")
                console.print("[bold cyan]>[/bold cyan] ", end="")


async def main():
    # Check for required dependencies
    required_configs = [
        "configs/mcp_config_alerts.json",
        "configs/mcp_config_halo_script.json",
        "configs/mcp_config_grok4.json",
    ]

    missing = [c for c in required_configs if not Path(c).exists()]

    if missing:
        console.print("[yellow]⚠️  Warning: Some configs are missing:[/yellow]")
        for config in missing:
            console.print(f"  - {config}")
        console.print("\n[dim]Demo will show these as not ready.[/dim]\n")
        await asyncio.sleep(2)

    controller = DemoController()
    await controller.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n\n[yellow]👋 Demo controller stopped[/yellow]")
        sys.exit(0)