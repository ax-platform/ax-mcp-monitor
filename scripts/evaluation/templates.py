from __future__ import annotations

from typing import Iterable, List, Optional

DEFAULT_CANDIDATE_SYSTEM_PROMPT = (
    "You are an autonomous agent participating in a head-to-head evaluation. "
    "Respond directly to the operator's task with clear, factual, and concise guidance. "
    "Avoid mentioning that you are in a test and keep the tone professional."
)

DEFAULT_JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluation judge. Compare two candidate responses to the same task. "
    "Return a JSON object with keys winner (A, B, TIE, or UNCERTAIN), confidence (0-1), and reason."
)

PAIRWISE_RUBRIC = (
    "Score responses on usefulness, factual accuracy, and clarity. If neither answer is satisfactory, "
    "choose UNCERTAIN with a low confidence value."
)

TEMPLATE_REGISTRY = {
    "pairwise_basic": {
        "name": "Pairwise Comparison",
        "judge_prompt_rubric": PAIRWISE_RUBRIC,
        "extra_instructions": [],
    },
}


def resolve_template(key: str) -> dict:
    if key not in TEMPLATE_REGISTRY:
        raise KeyError(f"Unknown evaluation template '{key}'.")
    return TEMPLATE_REGISTRY[key]


def build_judge_prompt(
    task: str,
    response_a: str,
    response_b: str,
    *,
    rubric: str,
    extra: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
) -> str:
    sections: List[str] = []
    if tags:
        sections.append(f"[session_tags: {', '.join(tags)}]")

    sections.append("Task:\n" + task.strip())
    sections.append("Candidate A:\n" + response_a.strip())
    sections.append("Candidate B:\n" + response_b.strip())

    rubric_lines = ["Rubric:", rubric.strip()]
    if extra:
        rubric_lines.extend(instr.strip() for instr in extra if instr)
    sections.append("\n".join(rubric_lines))

    sections.append(
        "Return a JSON object: {\"winner\": \"A|B|TIE|UNCERTAIN\", \"confidence\": <0-1>, \"reason\": <short explanation>}"
    )
    return "\n\n".join(sections)
