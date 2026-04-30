#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROBLEMS_REPO = "MathArena/usamo_2026"
OUTPUTS_REPO = "MathArena/usamo_2026_outputs"
DEFAULT_OUTPUT_DIR = Path("data/matharena_usamo_2026")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_hf_rows(repo: str, split: str, revision: str | None) -> list[dict[str, Any]]:
    from datasets import load_dataset

    kwargs: dict[str, Any] = {"split": split}
    if revision:
        kwargs["revision"] = revision
    dataset = load_dataset(repo, **kwargs)
    return [dict(row) for row in dataset]


def build_pipeline_rows(
    problems: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    model_name: str | None,
) -> list[dict[str, Any]]:
    problems_by_idx = {int(row["problem_idx"]): row for row in problems}
    rows: list[dict[str, Any]] = []
    for output in outputs:
        if model_name and output.get("model_name") != model_name:
            continue
        problem_idx = int(output["problem_idx"])
        problem = problems_by_idx.get(problem_idx)
        if problem is None:
            continue
        problem_id = f"matharena_usamo_2026_p{problem_idx}"
        rows.append(
            {
                "id": f"{problem_id}_{output.get('model_name', 'unknown').replace(' ', '_')}_{output.get('idx_answer')}",
                "problem_id": problem_id,
                "problem_idx": problem_idx,
                "problem": problem.get("problem", ""),
                "sample_solution": problem.get("sample_solution", ""),
                "grading_scheme": problem.get("grading_scheme"),
                "max_points": problem.get("points", output.get("max_points_judge_1", 7)),
                "candidate_solution": output.get("answer", ""),
                "model_name": output.get("model_name"),
                "model_config": output.get("model_config"),
                "idx_answer": output.get("idx_answer"),
                "ground_truth_score": output.get("points_judge_1"),
                "ground_truth_max_points": output.get("max_points_judge_1"),
                "ground_truth_grading_details": output.get("grading_details_judge_1"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download MathArena USAMO 2026 problems and outputs locally."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--split", default="train")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--limit-outputs", type=int, default=None)
    args = parser.parse_args()

    problems = load_hf_rows(PROBLEMS_REPO, args.split, args.revision)
    outputs = load_hf_rows(OUTPUTS_REPO, args.split, args.revision)
    if args.limit_outputs is not None:
        outputs = outputs[: args.limit_outputs]

    pipeline_rows = build_pipeline_rows(problems, outputs, args.model_name)

    write_jsonl(args.output_dir / "problems.jsonl", problems)
    write_jsonl(args.output_dir / "outputs.jsonl", outputs)
    write_jsonl(args.output_dir / "pipeline_rows.jsonl", pipeline_rows)

    print(f"wrote {len(problems)} problems to {args.output_dir / 'problems.jsonl'}")
    print(f"wrote {len(outputs)} outputs to {args.output_dir / 'outputs.jsonl'}")
    print(f"wrote {len(pipeline_rows)} joined pipeline rows to {args.output_dir / 'pipeline_rows.jsonl'}")


if __name__ == "__main__":
    main()
