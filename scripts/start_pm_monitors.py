#!/usr/bin/env python3
"""Launch multiple LangGraph monitors with live, prefixed streaming output.

Example:
    ./scripts/start_pm_monitors.py \
        --agent configs/mcp_config_cbms_local.json:@cbms \
        --agent configs/mcp_config_jwt_local.json:@jwt \
        --agent configs/mcp_config_Aurora.json:@Aurora

Press Ctrl+C to stop all monitors; their temporary message databases are removed
automatically on shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = REPO_ROOT / "prompts" / "prediction_market_system_prompt.txt"
DEFAULT_BACKEND = "openrouter"
DEFAULT_WAIT_TIMEOUT = 25
DEFAULT_STALL_THRESHOLD = 180


@dataclass
class MonitorSpec:
    config_path: Path
    handle: str
    message_db: Path
    process: asyncio.subprocess.Process


def _parse_agent_entry(entry: str) -> tuple[Path, str]:
    if ":" not in entry:
        raise argparse.ArgumentTypeError(
            f"Agent entry '{entry}' must look like 'config_path:@handle'"
        )
    config_str, handle = entry.split(":", 1)
    config_path = Path(config_str).expanduser().resolve()
    if not config_path.is_file():
        raise argparse.ArgumentTypeError(f"Config not found: {config_path}")
    handle = handle.strip()
    if not handle:
        raise argparse.ArgumentTypeError(f"Missing handle in entry '{entry}'")
    if not handle.startswith("@"):
        handle = f"@{handle}"
    return config_path, handle


def _python_executable() -> str:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


async def _pipe_stream(stream: asyncio.StreamReader, label: str, colour: str) -> None:
    prefix = f"{colour}[{label}]\x1b[0m "
    try:
        while not stream.at_eof():
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            print(f"{prefix}{text}")
    except asyncio.CancelledError:
        pass


async def launch_monitor(
    config: Path,
    handle: str,
    prompt_path: Path,
    backend: str,
    wait_timeout: int,
    stall_threshold: int,
    colour: str,
) -> MonitorSpec:
    db_fd, db_path_str = tempfile.mkstemp(
        prefix=f"{handle.lstrip('@')}_pm_",
        suffix=".db",
        dir=REPO_ROOT / "data" / "demo",
    )
    os.close(db_fd)
    db_path = Path(db_path_str)

    env = os.environ.copy()
    env.update(
        {
            "MESSAGE_DB_PATH": str(db_path),
            "LANGGRAPH_SYSTEM_PROMPT_FILE": str(prompt_path),
            "LANGGRAPH_BACKEND": backend,
            "MCP_BEARER_MODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )

    python_cmd = _python_executable()
    proc = await asyncio.create_subprocess_exec(
        python_cmd,
        str(REPO_ROOT / "scripts" / "mcp_use_heartbeat_monitor.py"),
        "--config",
        str(config),
        "--plugin",
        "langgraph",
        "--wait-timeout",
        str(wait_timeout),
        "--stall-threshold",
        str(stall_threshold),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    colour_code = {
        "red": "\x1b[31m",
        "green": "\x1b[32m",
        "yellow": "\x1b[33m",
        "blue": "\x1b[34m",
        "magenta": "\x1b[35m",
        "cyan": "\x1b[36m",
    }.get(colour.lower(), "\x1b[36m")

    asyncio.create_task(_pipe_stream(proc.stdout, handle, colour_code))
    print(f"🔌 Launched {handle} (PID {proc.pid}, DB {db_path.name})")
    return MonitorSpec(config_path=config, handle=handle, message_db=db_path, process=proc)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Start multiple LangGraph monitors with live output")
    parser.add_argument(
        "--agent",
        action="append",
        help="Monitor spec as config:@handle (can repeat). Defaults to cbms/jwt/Aurora.",
    )
    parser.add_argument(
        "--prompt",
        default=str(DEFAULT_PROMPT),
        help="System prompt file for all monitors.",
    )
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        help="LANGGRAPH_BACKEND value (default openrouter).",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=DEFAULT_WAIT_TIMEOUT,
        help="messages.check wait timeout in seconds",
    )
    parser.add_argument(
        "--stall-threshold",
        type=int,
        default=DEFAULT_STALL_THRESHOLD,
        help="Reconnect threshold in seconds",
    )
    args = parser.parse_args()

    agent_entries = args.agent or [
        "configs/mcp_config_cbms_local.json:@cbms",
        "configs/mcp_config_jwt_local.json:@jwt",
        "configs/mcp_config_Aurora.json:@Aurora",
    ]

    specs: List[tuple[Path, str]] = [_parse_agent_entry(entry) for entry in agent_entries]

    prompt_path = Path(args.prompt).expanduser().resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    data_dir = REPO_ROOT / "data" / "demo"
    data_dir.mkdir(parents=True, exist_ok=True)

    colours = ["cyan", "magenta", "yellow", "green", "blue"]

    monitors: List[MonitorSpec] = []
    try:
        for idx, (config_path, handle) in enumerate(specs):
            colour = colours[idx % len(colours)]
            spec = await launch_monitor(
                config_path,
                handle,
                prompt_path,
                args.backend,
                args.wait_timeout,
                args.stall_threshold,
                colour,
            )
            monitors.append(spec)

        print("\n🎯 Monitors running. Streaming output appears above.")
        print("Press Ctrl+C to stop all monitors.\n")

        # Keep the script alive until cancelled
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        print("\n👋 Ctrl+C received; shutting down monitors...")
    finally:
        for spec in monitors:
            if spec.process.returncode is None:
                spec.process.terminate()
                try:
                    await asyncio.wait_for(spec.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    spec.process.kill()
                    await spec.process.wait()
            if spec.message_db.exists():
                spec.message_db.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())

