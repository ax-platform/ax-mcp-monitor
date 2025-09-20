from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(slots=True)
class CandidateConfig:
    """Configuration for a candidate model under evaluation."""

    label: str
    model: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None


@dataclass(slots=True)
class JudgeConfig:
    """Configuration for the judge model that scores a pair of candidates."""

    model: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    rubric: Optional[str] = None


@dataclass(slots=True)
class DatasetConfig:
    """Location of prompts used for evaluation."""

    path: Optional[Path] = None
    prompts: List[str] = field(default_factory=list)

    @classmethod
    def from_prompts(cls, prompts: Iterable[str]) -> "DatasetConfig":
        return cls(path=None, prompts=list(prompts))


@dataclass(slots=True)
class EvalRunConfig:
    """Top-level run configuration used by the pairwise evaluator."""

    candidate_a: CandidateConfig
    candidate_b: CandidateConfig
    judge: JudgeConfig
    dataset: DatasetConfig
    template: str = "pairwise_basic"
    max_samples: int = 20
    output_dir: Path = Path("logs/evaluations")
    session_tags: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.6
    low_confidence_retry: bool = True

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
