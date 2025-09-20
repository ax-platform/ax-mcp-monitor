from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import EvalRunConfig

logger = logging.getLogger(__name__)


def build_summary_message(summary: Mapping[str, Any], run_dir: Path) -> str:
    template = summary.get("template", "pairwise")
    candidate_a = summary.get("candidate_a", "A")
    candidate_b = summary.get("candidate_b", "B")
    judge = summary.get("judge", "judge")
    wins = summary.get("wins", {})
    wins_a = wins.get("A", 0)
    wins_b = wins.get("B", 0)
    total = summary.get("total_decisions", 0)
    preference = summary.get("preference_A", 0.0)
    tags = summary.get("tags", [])

    tag_line = " ".join(tags)
    parts: list[str] = []
    if tag_line:
        parts.append(tag_line)

    parts.append(f"Evaluation run ({template}) completed: {candidate_a} vs {candidate_b} → preference_A={preference:.2f}")
    parts.append(f"Wins: {wins_a} - {wins_b} (judge: {judge}, total decisions: {total})")
    parts.append(f"Log directory: {run_dir}")

    return "\n".join(parts)


class AxAnnouncer:
    """Streams evaluation updates into aX via MCP when configuration is present."""

    def __init__(self, client: "MCPClient", config: "EvalRunConfig", run_dir: Path) -> None:
        self._client = client
        self._config = config
        self._run_dir = run_dir
        self._results_path = run_dir / "results.jsonl"
        self._enabled = True
        self._tags_line = " ".join(tag for tag in config.session_tags if tag)
        self._expected = max(1, config.max_samples)

    @classmethod
    async def create(cls, run_dir: Path, config: "EvalRunConfig") -> Optional["AxAnnouncer"]:
        config_path = os.getenv("MCP_CONFIG_PATH")
        if not config_path or not Path(config_path).is_file():
            return None
        try:
            from ax_mcp_wait_client.config_loader import parse_mcp_config  # type: ignore
            from ax_mcp_wait_client.mcp_client import MCPClient  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("MCP client modules unavailable: %s", exc)
            return None

        try:
            cfg = parse_mcp_config(config_path)
        except Exception as exc:
            logger.warning("Unable to parse MCP config for announcements: %s", exc)
            return None

        try:
            client = MCPClient(
                server_url=cfg.server_url,
                oauth_server=cfg.oauth_url,
                agent_name=cfg.agent_name,
                token_dir=cfg.token_dir,
            )
        except Exception as exc:
            logger.warning("Unable to initialise MCP client for announcements: %s", exc)
            return None

        return cls(client, config, run_dir)

    async def close(self) -> None:
        if not self._enabled:
            return
        try:
            await self._client.disconnect()
        except Exception:
            pass

    async def send_start(self) -> None:
        dataset = ""
        if getattr(self._config.dataset, "path", None):
            dataset = str(self._config.dataset.path)
        elif self._config.dataset.prompts:
            dataset = f"{len(self._config.dataset.prompts)} prompts"

        lines = self._baseline_lines()
        lines.extend(
            [
                "🎬 Evaluation starting",
                f"Template: {self._config.template}",
                f"Candidates: {self._config.candidate_a.model} vs {self._config.candidate_b.model}",
                f"Judge: {self._config.judge.model}",
                f"Planned samples: {self._expected}",
            ]
        )
        if dataset:
            lines.append(f"Dataset: {dataset}")
        lines.append(f"Logs: {self._run_dir}")
        await self._send("\n".join(lines))

    async def send_progress(self, sample_id: int, record: Mapping[str, Any], wins: Mapping[str, int], total_processed: int) -> None:
        verdict = record.get("verdict", {})
        winner = verdict.get("winner", "UNCERTAIN")
        confidence = verdict.get("confidence", 0.0)
        reason = verdict.get("reason") or ""
        prompt = record.get("prompt", "")

        lines = self._baseline_lines()
        lines.append(
            f"🎯 Sample {sample_id + 1}/{self._expected}: winner={winner} (conf={confidence:.2f})"
        )

        if reason:
            lines.append(f"Reason: {self._clip(reason)}")
        if prompt:
            lines.append(f"Prompt: {self._clip(prompt)}")

        score_line = f"Score → A:{wins.get('A', 0)} • B:{wins.get('B', 0)}"
        uncertain = max(0, total_processed - (wins.get("A", 0) + wins.get("B", 0)))
        if uncertain:
            score_line += f" • Uncertain:{uncertain}"
        lines.append(score_line + f" (judge: {self._config.judge.model})")
        lines.append(f"Results: {self._results_path}")

        await self._send("\n".join(lines))

    async def send_final(self, summary: Mapping[str, Any]) -> None:
        message = build_summary_message(summary, self._run_dir)
        await self._send(message)

    async def send_error(self, error: str) -> None:
        lines = self._baseline_lines()
        lines.append("⚠️ Evaluation aborted")
        lines.append(self._clip(error))
        await self._send("\n".join(lines))

    async def _send(self, message: str) -> None:
        if not self._enabled or not message.strip():
            return
        try:
            ok = await self._client.send_message(message)
        except Exception as exc:
            self._enabled = False
            logger.warning("Failed to send evaluation update to aX: %s", exc)
            print("⚠️  Failed to send evaluation update to aX; streaming disabled.")
            return
        if not ok:
            self._enabled = False
            logger.warning("aX message send reported failure; disabling further streaming.")
            print("⚠️  aX declined evaluation update; streaming disabled.")

    def _baseline_lines(self) -> list[str]:
        lines: list[str] = []
        if self._tags_line:
            lines.append(self._tags_line)
        return lines

    @staticmethod
    def _clip(text: str, limit: int = 160) -> str:
        normalized = " ".join(text.strip().split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."


async def maybe_create_announcer(run_dir: Path, config: "EvalRunConfig") -> Optional[AxAnnouncer]:
    announcer = await AxAnnouncer.create(run_dir, config)
    return announcer
