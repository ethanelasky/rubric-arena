#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubric_arena.matharena_loader import load_matharena_usamo_pipeline_rows
from rubric_arena.pipeline import (
    anthropic_text_call,
    build_final_score_rows,
    compare_to_ground_truth,
    flatten_all_structured_judgments,
    generate_structured_rubric,
    grade_free_text,
    grade_structured,
    holistic_vs_structured_diagnostics,
    safe_id,
    score_distribution_metrics,
    summarize_structured_atoms,
    write_jsonl,
)


DEFAULT_DATA_ROOT = Path("data/matharena_usamo_2026")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run structured-vs-free-text rubric grading on local MathArena rows."
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--problem-idx", type=int, default=2)
    parser.add_argument("--model-name", default="Gemini 3.1 Pro Preview")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--grader-model", default="claude-sonnet-4-6")
    parser.add_argument("--rubric-model", default=None)
    parser.add_argument("--method", choices=["structured", "free_text", "both"], default="both")
    parser.add_argument("--reuse-rubric", action="store_true")
    args = parser.parse_args()

    rubric_model = args.rubric_model or args.grader_model
    rows = load_matharena_usamo_pipeline_rows(
        args.data_root,
        problem_idx=args.problem_idx,
        model_name=args.model_name,
        limit=args.limit,
    )
    if not rows:
        raise SystemExit("No local MathArena rows matched the requested filters")

    call = anthropic_text_call(model=args.grader_model, temperature=0.0)
    rubric_call = anthropic_text_call(model=rubric_model, temperature=0.0)

    rubric = None
    rubric_path = args.data_root / "rubrics" / f"matharena_usamo_2026_p{args.problem_idx}.{safe_id(rubric_model)}.rubric.v4.json"
    if args.method in {"structured", "both"}:
        if args.reuse_rubric and rubric_path.exists():
            rubric = json.loads(rubric_path.read_text())
        else:
            generated = generate_structured_rubric(rows[0], llm_call=rubric_call, rubric_model=rubric_model)
            rubric = generated["rubric"]
            rubric_path.parent.mkdir(parents=True, exist_ok=True)
            rubric_path.write_text(json.dumps(rubric, indent=2, ensure_ascii=False) + "\n")
            raw_path = rubric_path.with_suffix(".generation.json")
            raw_path.write_text(json.dumps(generated, indent=2, ensure_ascii=False) + "\n")
            print("wrote", rubric_path)

    results = []
    for row in rows:
        if args.method in {"structured", "both"}:
            assert rubric is not None
            results.append(grade_structured(row, rubric=rubric, llm_call=call, grader_model=args.grader_model))
        if args.method in {"free_text", "both"}:
            results.append(grade_free_text(row, llm_call=call, grader_model=args.grader_model))

    out_dir = args.data_root / "grading_runs"
    out_name = f"p{args.problem_idx}.{safe_id(args.model_name)}.{safe_id(args.grader_model)}.{args.method}.jsonl"
    out_path = out_dir / out_name
    write_jsonl(out_path, results)
    final_score_rows = build_final_score_rows(results)
    atom_rows = flatten_all_structured_judgments(results)
    paired_rows = holistic_vs_structured_diagnostics(results)
    metrics = compare_to_ground_truth(results)
    metrics["score_distributions"] = score_distribution_metrics(results)
    metrics["structured_atoms"] = summarize_structured_atoms(atom_rows)

    metrics_path = out_path.with_suffix(".metrics.json")
    final_scores_path = out_path.with_suffix(".final_scores.jsonl")
    atoms_path = out_path.with_suffix(".structured_atoms.jsonl")
    paired_path = out_path.with_suffix(".paired_diagnostics.jsonl")

    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    write_jsonl(final_scores_path, final_score_rows)
    write_jsonl(atoms_path, atom_rows)
    write_jsonl(paired_path, paired_rows)

    print("wrote", out_path)
    print("wrote", metrics_path)
    print("wrote", final_scores_path)
    print("wrote", atoms_path)
    print("wrote", paired_path)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
