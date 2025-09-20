import json

from scripts.evaluation.metrics import Verdict, confidence_ok
from scripts.evaluation.parsers import extract_json_block, parse_verdict
from scripts.evaluation.templates import build_judge_prompt
from scripts.evaluation.utils import build_summary_message


def test_build_judge_prompt_contains_sections():
    prompt = build_judge_prompt(
        "Explain the topic",
        "Response A",
        "Response B",
        rubric="Consider clarity",
        extra=["Be fair"],
        tags=["eval", "demo"],
    )
    assert "Task:" in prompt
    assert "Candidate A" in prompt
    assert "Candidate B" in prompt
    assert "Rubric" in prompt
    assert "session_tags" in prompt


def test_extract_json_block_success():
    payload = {"winner": "A", "confidence": 0.5, "reason": "clear"}
    text = "Verdict->" + json.dumps(payload)
    block = extract_json_block(text)
    assert json.loads(block) == payload


def test_parse_verdict_handles_bad_data():
    verdict = parse_verdict("no json here")
    assert verdict.winner == "UNCERTAIN"
    assert verdict.confidence == 0.0


def test_confidence_ok():
    assert confidence_ok(Verdict("A", 0.7, ""), 0.6)
    assert not confidence_ok(Verdict("B", 0.5, ""), 0.6)


def test_build_summary_message_formats_output(tmp_path):
    run_dir = tmp_path / "20240101_pairwise"
    run_dir.mkdir()
    summary = {
        "template": "pairwise_basic",
        "candidate_a": "model-a",
        "candidate_b": "model-b",
        "judge": "judge-model",
        "wins": {"A": 3, "B": 2},
        "total_decisions": 5,
        "preference_A": 0.6,
        "tags": ["demo", "eval"],
    }

    message = build_summary_message(summary, run_dir)

    assert "demo eval" in message
    assert "model-a vs model-b" in message
    assert "Wins: 3 - 2" in message
    assert str(run_dir) in message
