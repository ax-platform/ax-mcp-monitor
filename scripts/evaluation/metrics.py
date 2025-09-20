from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Verdict:
    """Structured representation of a judge decision."""

    winner: str
    confidence: float
    reason: str

    @property
    def is_decision(self) -> bool:
        return self.winner in {"A", "B"}


def confidence_ok(verdict: Verdict, threshold: float) -> bool:
    return verdict.is_decision and verdict.confidence >= threshold
