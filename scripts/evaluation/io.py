from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1].parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.append(str(REPO_ROOT / "src"))

from plugins.ollama_plugin import OllamaPlugin  # noqa: E402

from .config import CandidateConfig, JudgeConfig
from .templates import DEFAULT_CANDIDATE_SYSTEM_PROMPT, DEFAULT_JUDGE_SYSTEM_PROMPT


@contextmanager
def temporary_env(**updates: Optional[str]):
    previous: Dict[str, Optional[str]] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _invoke_plugin(prompt: str, *, model: str, system_prompt: Optional[str]) -> str:
    env_updates: Dict[str, Optional[str]] = {
        "OLLAMA_MODEL": model,
        "OLLAMA_SYSTEM_PROMPT": system_prompt,
        "OLLAMA_SYSTEM_PROMPT_FILE": None,
        "OLLAMA_BASE_PROMPT_FILE": None,
    }

    with temporary_env(**env_updates):
        plugin = OllamaPlugin({"model": model, "thinking_tags": "hide"})
        response = await plugin.process_message(prompt, context={})
    return response.strip()


async def generate_candidate_response(task: str, config: CandidateConfig) -> str:
    system_prompt = config.system_prompt or DEFAULT_CANDIDATE_SYSTEM_PROMPT
    return await _invoke_plugin(task, model=config.model, system_prompt=system_prompt)


async def generate_judge_response(prompt: str, config: JudgeConfig) -> str:
    system_prompt = config.system_prompt or DEFAULT_JUDGE_SYSTEM_PROMPT
    return await _invoke_plugin(prompt, model=config.model, system_prompt=system_prompt)


def run_async(coro) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return asyncio.ensure_future(coro)
    return asyncio.run(coro)
