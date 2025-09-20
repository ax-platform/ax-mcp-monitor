from __future__ import annotations

import json
import re
from typing import Any

from .metrics import Verdict

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def extract_json_block(text: str) -> str:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no JSON object found in judge output")
    return match.group(0)


def parse_verdict(text: str) -> Verdict:
    """Parse a verdict from the judge output."""

    try:
        block = extract_json_block(text)
        data: Any = json.loads(block)
    except Exception:
        return Verdict("UNCERTAIN", 0.0, text.strip())

    winner = str(data.get("winner", "UNCERTAIN")).strip().upper()
    if winner not in {"A", "B", "TIE", "UNCERTAIN"}:
        winner = "UNCERTAIN"

    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = _clamp(float(confidence_raw))
    except (TypeError, ValueError):
        confidence = 0.0

    reason = str(data.get("reason", "")).strip() or "Judge provided no explanation."

    return Verdict(winner, confidence, reason)
