from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

from .config import CandidateConfig, DatasetConfig, EvalRunConfig, JudgeConfig
from .metrics import Verdict, confidence_ok
from .parsers import parse_verdict
from .templates import build_judge_prompt, resolve_template
from . import io
from .utils import build_summary_message, maybe_create_announcer

DEFAULT_OUTPUT_BASE = Path("logs/evaluations")
SUPPORTED_JSON_KEYS = ("prompt", "input", "question", "task")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pairwise LLM evaluator")
    parser.add_argument("--candidate-a-model", required=True, help="Model name for candidate A")
    parser.add_argument("--candidate-b-model", required=True, help="Model name for candidate B")
    parser.add_argument("--judge-model", required=True, help="Model used as the judge")
    parser.add_argument("--prompt", help="Single prompt to evaluate")
    parser.add_argument("--dataset", help="Path to dataset (jsonl or txt)")
    parser.add_argument("--template", default="pairwise_basic", help="Evaluation template key")
    parser.add_argument("--max-samples", type=int, default=10)
    parser.add_argument("--tag", action="append", default=[], help="Session tag (can repeat)")
    parser.add_argument("--output-dir", help="Directory for logs (defaults to logs/evaluations)")
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument(
        "--no-low-confidence-retry",
        action="store_true",
        help="Skip additional judge pass when verdict lacks confidence",
    )
    return parser.parse_args()


def load_prompts(dataset_path: Path) -> List[str]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
    if dataset_path.suffix.lower() in {".jsonl", ".ndjson"}:
        prompts: List[str] = []
        with dataset_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for key in SUPPORTED_JSON_KEYS:
                    if key in payload and payload[key]:
                        prompts.append(str(payload[key]))
                        break
        if not prompts:
            raise ValueError(f"No prompts found in JSONL file {dataset_path}")
        return prompts
    # Fallback: treat file as newline-delimited prompts
    with dataset_path.open("r", encoding="utf-8") as fh:
        prompts = [line.strip() for line in fh if line.strip()]
    if not prompts:
        raise ValueError(f"No prompts found in text file {dataset_path}")
    return prompts


def build_run_config(args: argparse.Namespace) -> EvalRunConfig:
    if not args.prompt and not args.dataset:
        raise ValueError("Provide --prompt or --dataset to evaluate.")

    if args.dataset:
        dataset_path = Path(args.dataset).expanduser().resolve()
        prompts = load_prompts(dataset_path)
        dataset = DatasetConfig(path=dataset_path, prompts=prompts)
    else:
        dataset = DatasetConfig.from_prompts([args.prompt])

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_BASE

    candidate_a = CandidateConfig(label="A", model=args.candidate_a_model)
    candidate_b = CandidateConfig(label="B", model=args.candidate_b_model)
    judge = JudgeConfig(model=args.judge_model)

    return EvalRunConfig(
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        judge=judge,
        dataset=dataset,
        template=args.template,
        max_samples=max(1, args.max_samples),
        output_dir=output_dir,
        session_tags=list(dict.fromkeys(tag.strip() for tag in args.tag if tag.strip())),
        confidence_threshold=max(0.0, min(1.0, args.confidence_threshold)),
        low_confidence_retry=not args.no_low_confidence_retry,
    )


def iter_samples(config: EvalRunConfig) -> Iterator[Tuple[int, str]]:
    for idx, prompt in enumerate(config.dataset.prompts):
        if idx >= config.max_samples:
            break
        yield idx, prompt


async def evaluate_sample(
    sample_id: int,
    prompt: str,
    config: EvalRunConfig,
    template: dict,
) -> dict:
    response_a = await io.generate_candidate_response(prompt, config.candidate_a)
    response_b = await io.generate_candidate_response(prompt, config.candidate_b)

    rubric = template.get("judge_prompt_rubric", "")
    extra = template.get("extra_instructions", [])
    judge_prompt = build_judge_prompt(
        prompt,
        response_a,
        response_b,
        rubric=rubric,
        extra=extra,
        tags=config.session_tags,
    )

    judge_raw = await io.generate_judge_response(judge_prompt, config.judge)
    verdict = parse_verdict(judge_raw)

    if config.low_confidence_retry and not confidence_ok(verdict, config.confidence_threshold):
        retry_prompt = build_judge_prompt(
            prompt,
            response_a,
            response_b,
            rubric=rubric,
            extra=list(extra) + ["Re-evaluate carefully. The previous answer was uncertain."],
            tags=config.session_tags,
        )
        judge_raw = await io.generate_judge_response(retry_prompt, config.judge)
        verdict = parse_verdict(judge_raw)

    record = {
        "sample_id": sample_id,
        "prompt": prompt,
        "candidate_a": response_a,
        "candidate_b": response_b,
        "judge_prompt": judge_prompt,
        "judge_raw": judge_raw,
        "verdict": {
            "winner": verdict.winner,
            "confidence": verdict.confidence,
            "reason": verdict.reason,
        },
        "timestamp": time.time(),
    }
    return record


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def run(config: EvalRunConfig) -> tuple[Path, dict]:
    template = resolve_template(config.template)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    run_dir = config.ensure_output_dir() / f"{timestamp}_{config.template}"
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "template": config.template,
        "candidate_a": config.candidate_a.model,
        "candidate_b": config.candidate_b.model,
        "judge": config.judge.model,
        "tags": config.session_tags,
        "confidence_threshold": config.confidence_threshold,
        "records": [],
    }

    results_path = run_dir / "results.jsonl"
    wins = {"A": 0, "B": 0}
    announcer = await maybe_create_announcer(run_dir, config)

    try:
        if announcer:
            await announcer.send_start()

        for sample_id, prompt in iter_samples(config):
            record = await evaluate_sample(sample_id, prompt, config, template)
            append_jsonl(results_path, record)
            summary["records"].append(record["verdict"])

            winner = record["verdict"]["winner"]
            if winner in wins:
                wins[winner] += 1

            print(
                f"#{sample_id} winner={record['verdict']['winner']} "
                + f"conf={record['verdict']['confidence']:.2f}"
            )

            if announcer:
                await announcer.send_progress(sample_id, record, wins, sample_id + 1)

    except Exception as exc:
        if announcer:
            await announcer.send_error(str(exc))
        raise
    else:
        total = wins["A"] + wins["B"]
        preference = wins["A"] / total if total else 0.0
        summary.update({"wins": wins, "total_decisions": total, "preference_A": preference})

        summary_path = run_dir / "summary.json"
        write_json(summary_path, summary)
        print("\nRun complete. Summary written to", summary_path)

        if announcer:
            await announcer.send_final(summary)

        return run_dir, summary
    finally:
        if announcer:
            await announcer.close()


def main() -> int:
    args = parse_args()
    try:
        config = build_run_config(args)
    except Exception as exc:
        print(f"❌ {exc}")
        return 1

    try:
        run_dir, summary = asyncio.run(run(config))
    except KeyboardInterrupt:
        print("Interrupted by user")
        return 130
    except Exception as exc:
        print(f"❌ Evaluation failed: {exc}")
        return 1

    message = build_summary_message(summary, run_dir)
    print("\n" + message + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
