#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_mid_credit_eval as mid  # noqa: E402
from rubric_arena.matharena_loader import read_jsonl  # noqa: E402
from rubric_arena.pipeline import (  # noqa: E402
    build_final_score_rows,
    build_free_text_to_structured_prompt,
    compare_structured_judgments,
    compare_to_ground_truth,
    flatten_all_structured_judgments,
    holistic_vs_structured_diagnostics,
    load_env_file,
    safe_id,
    score_distribution_metrics,
    summarize_structured_comparison,
    summarize_structured_atoms,
    write_jsonl,
)
from rubric_arena.rubric_grading import (  # noqa: E402
    JudgmentError,
    ModelOutputError,
    compute_score,
    extract_first_json_object,
    repair_common_judgment_model_errors,
    validate_judgment,
)


DEFAULT_SELECTED: dict[str, set[int]] = {
    "Gemini 3.1 Pro Preview": {1, 3, 5, 6},
    "Claude-Opus-4.6 (High)": {2, 3, 5, 6},
    "Step 3.5 Flash": {2, 3, 5, 6},
    "Qwen3.5-397b-a17b": {5, 6},
}


def parse_model_problem_spec(spec: str) -> dict[str, set[int]]:
    selected: dict[str, set[int]] = {}
    if not spec:
        return selected
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"Expected MODEL:p1,p2 format, got {chunk!r}")
        model, problem_text = chunk.split(":", 1)
        selected[model.strip()] = {
            int(value.strip()) for value in problem_text.split(",") if value.strip()
        }
    return selected


def select_rows(rows: list[dict[str, Any]], selected: dict[str, set[int]], limit: int | None) -> list[dict[str, Any]]:
    chosen = [
        row
        for row in rows
        if "Human Judge Evaluation" in str(row.get("ground_truth_grading_details"))
        and row.get("model_name") in selected
        and int(row["problem_idx"]) in selected[str(row.get("model_name"))]
    ]
    chosen.sort(key=lambda row: (row["model_name"], int(row["problem_idx"]), int(row["idx_answer"])))
    return chosen[:limit] if limit is not None else chosen


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run structured-vs-free-text grading on a human-tagged MathArena batch."
    )
    parser.add_argument("--grader-model", default=mid.DEFAULT_GRADER_MODEL)
    parser.add_argument("--rubric-model", default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=25)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--timeout-ms", type=int, default=180000)
    parser.add_argument("--include-human-structured", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reuse-rubric", action="store_true")
    parser.add_argument("--out-tag", default="human_batch_v1")
    parser.add_argument(
        "--resume-from",
        default="",
        help="Existing raw JSONL result file. Successful task rows are reused; failed/missing tasks are rerun.",
    )
    parser.add_argument("--retry-attempts", type=int, default=2)
    parser.add_argument("--retry-backoff-sec", type=float, default=2.0)
    parser.add_argument(
        "--selected",
        default="",
        help="Optional semicolon-separated MODEL:p1,p2 spec. Defaults to the current human batch.",
    )
    args = parser.parse_args()

    rubric_model = args.rubric_model or args.grader_model
    selected = parse_model_problem_spec(args.selected) if args.selected else DEFAULT_SELECTED

    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_env_file(env_path)
    if not os.environ.get("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required")

    all_rows = read_jsonl(mid.DATA_ROOT / "pipeline_rows.jsonl")
    rows = select_rows(all_rows, selected, args.limit)
    if not rows:
        raise SystemExit("No rows matched the selected human batch")

    def task_key_from_parts(method: str, row: dict[str, Any], repeat_idx: int) -> tuple[Any, ...]:
        return (
            method,
            row.get("id"),
            row.get("problem_id"),
            row.get("model_name"),
            row.get("idx_answer"),
            repeat_idx,
            args.grader_model,
        )

    def task_key_from_result(result: dict[str, Any]) -> tuple[Any, ...]:
        return (
            result.get("method"),
            result.get("candidate_id"),
            result.get("problem_id"),
            result.get("model_name"),
            result.get("idx_answer"),
            result.get("repeat_idx"),
            result.get("grader_model"),
        )

    def is_successful_result(result: dict[str, Any]) -> bool:
        return (
            result.get("method") in {"structured", "free_text", "human_structured"}
            and result.get("computed_score") is not None
            and not result.get("error")
        )

    resumed_successes: dict[tuple[Any, ...], dict[str, Any]] = {}
    resumed_failures = 0
    if args.resume_from:
        resume_path = Path(args.resume_from)
        if not resume_path.is_absolute():
            resume_path = REPO_ROOT / resume_path
        if not resume_path.exists():
            raise SystemExit(f"--resume-from does not exist: {resume_path}")
        for result in read_jsonl(resume_path):
            key = task_key_from_result(result)
            if is_successful_result(result):
                resumed_successes[key] = result
            else:
                resumed_failures += 1
        print(
            f"[resume] loaded {len(resumed_successes)} successful rows and "
            f"{resumed_failures} failed/incomplete rows from {resume_path}",
            flush=True,
        )

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["problem_idx"])].append(row)

    from google import genai

    rubric_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    results: list[dict[str, Any]] = list(resumed_successes.values())
    structured_failures: list[dict[str, Any]] = []
    out_stem = (
        f"{safe_id(args.grader_model)}.{safe_id(args.out_tag)}."
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out_path = mid.RUN_DIR / f"{out_stem}.jsonl"

    def write_outputs() -> None:
        write_jsonl(out_path, results)
        final_score_rows = build_final_score_rows(results)
        atom_rows = flatten_all_structured_judgments(results)
        paired_rows = holistic_vs_structured_diagnostics(results)
        metrics = compare_to_ground_truth(results)
        metrics["score_distributions"] = score_distribution_metrics(results)
        metrics["structured_atoms"] = summarize_structured_atoms(atom_rows)
        structured_comparison_rows = compare_structured_judgments(results)
        metrics["structured_comparison"] = summarize_structured_comparison(
            structured_comparison_rows
        )
        metrics["structured_failures"] = structured_failures
        metrics["selected_rows"] = len(rows)
        metrics["repeats"] = args.repeats
        metrics["selected"] = {model: sorted(problems) for model, problems in selected.items()}

        write_jsonl(out_path.with_suffix(".final_scores.jsonl"), final_score_rows)
        write_jsonl(out_path.with_suffix(".structured_atoms.jsonl"), atom_rows)
        write_jsonl(
            out_path.with_suffix(".structured_comparison.jsonl"),
            structured_comparison_rows,
        )
        write_jsonl(out_path.with_suffix(".paired_diagnostics.jsonl"), paired_rows)
        out_path.with_suffix(".metrics.json").write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n"
        )

    print(f"[load] selected {len(rows)} human-tagged rows; repeats={args.repeats}", flush=True)
    for problem_idx in sorted(grouped):
        problem_rows = grouped[problem_idx]
        problem_rows.sort(key=lambda row: (row["model_name"], int(row["idx_answer"])))
        rubric = mid.load_or_generate_rubric(
            client=rubric_client,
            rows=problem_rows,
            rubric_model=rubric_model,
            reuse_rubric=args.reuse_rubric,
        )
        tasks = [
            (method, problem_idx, repeat_idx, row, rubric)
            for repeat_idx in range(args.repeats)
            for row in problem_rows
            for method in (
                ("structured", "free_text", "human_structured")
                if args.include_human_structured
                else ("structured", "free_text")
            )
        ]

        def grade_task_once(task: tuple[str, int, int, dict[str, Any], dict[str, Any]]) -> tuple[
            str,
            dict[str, Any],
            str | None,
        ]:
            method, _, repeat_idx, row, task_rubric = task
            client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
            if method == "structured":
                prompt = mid.build_structured_grading_prompt(row, task_rubric)
                raw = mid.gemini_stream(
                    client,
                    args.grader_model,
                    prompt,
                    max_output_tokens=args.max_output_tokens,
                    timeout_ms=args.timeout_ms,
                    verbose=False,
                )
                try:
                    judgment = extract_first_json_object(raw)
                    judgment = repair_common_judgment_model_errors(task_rubric, judgment)
                    validation = validate_judgment(task_rubric, judgment)
                    computed_score = compute_score(task_rubric, judgment)
                    declared = None
                    for key in ("final_score", "score", "computed_score"):
                        if key in judgment:
                            try:
                                declared = int(judgment[key])
                                break
                            except (TypeError, ValueError):
                                continue
                    if declared is None and isinstance(judgment.get("score_summary"), dict):
                        for key in ("final_score", "score", "computed_score"):
                            if key in judgment["score_summary"]:
                                try:
                                    declared = int(judgment["score_summary"][key])
                                    break
                                except (TypeError, ValueError):
                                    continue
                    result = {
                        "method": "structured",
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "grader_model": args.grader_model,
                        "ground_truth_score": row.get("ground_truth_score"),
                        "ground_truth_max_points": row.get("ground_truth_max_points"),
                        "prompt": prompt,
                        "computed_score": computed_score,
                        "model_declared_score": declared,
                        "score_consistent": None if declared is None else declared == computed_score,
                        "judgment": judgment,
                        "validation_warnings": validation.warnings,
                        "raw_model_output": raw,
                        "repeat_idx": repeat_idx,
                    }
                    return method, result, None
                except (JudgmentError, ModelOutputError) as exc:
                    result = {
                        "method": "structured",
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "grader_model": args.grader_model,
                        "ground_truth_score": row.get("ground_truth_score"),
                        "ground_truth_max_points": row.get("ground_truth_max_points"),
                        "prompt": prompt,
                        "computed_score": None,
                        "raw_model_output": raw,
                        "repeat_idx": repeat_idx,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    return method, result, result["error"]

            if method == "human_structured":
                prompt = build_free_text_to_structured_prompt(
                    problem=row.get("problem", ""),
                    reference_solution=row.get("sample_solution") or "",
                    candidate_solution=row.get("candidate_solution") or "",
                    rubric=task_rubric,
                    free_text_assessment=str(row.get("ground_truth_grading_details") or ""),
                )
                raw = mid.gemini_stream(
                    client,
                    args.grader_model,
                    prompt,
                    max_output_tokens=args.max_output_tokens,
                    timeout_ms=args.timeout_ms,
                    verbose=False,
                )
                try:
                    judgment = extract_first_json_object(raw)
                    judgment = repair_common_judgment_model_errors(task_rubric, judgment)
                    validation = validate_judgment(task_rubric, judgment)
                    computed_score = compute_score(task_rubric, judgment)
                    result = {
                        "method": "human_structured",
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "grader_model": args.grader_model,
                        "ground_truth_score": row.get("ground_truth_score"),
                        "ground_truth_max_points": row.get("ground_truth_max_points"),
                        "prompt": prompt,
                        "computed_score": computed_score,
                        "judgment": judgment,
                        "validation_warnings": validation.warnings,
                        "raw_model_output": raw,
                        "repeat_idx": repeat_idx,
                    }
                    return method, result, None
                except (JudgmentError, ModelOutputError) as exc:
                    result = {
                        "method": "human_structured",
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "grader_model": args.grader_model,
                        "ground_truth_score": row.get("ground_truth_score"),
                        "ground_truth_max_points": row.get("ground_truth_max_points"),
                        "prompt": prompt,
                        "computed_score": None,
                        "raw_model_output": raw,
                        "repeat_idx": repeat_idx,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    return method, result, result["error"]

            prompt = mid.build_free_text_prompt(row)
            raw = mid.gemini_stream(
                client,
                args.grader_model,
                prompt,
                max_output_tokens=args.max_output_tokens,
                timeout_ms=args.timeout_ms,
                verbose=False,
            )
            try:
                parsed = extract_first_json_object(raw)
                ft_score = mid.parse_free_text_score(parsed)
                parsed["score"] = ft_score
                error = None
            except ModelOutputError as exc:
                parsed = {}
                ft_score = None
                error = f"{type(exc).__name__}: {exc}"
            result = {
                "method": "free_text",
                "candidate_id": row.get("id"),
                "problem_id": row.get("problem_id"),
                "model_name": row.get("model_name"),
                "idx_answer": row.get("idx_answer"),
                "grader_model": args.grader_model,
                "ground_truth_score": row.get("ground_truth_score"),
                "ground_truth_max_points": row.get("ground_truth_max_points"),
                "computed_score": ft_score,
                "parsed_model_output": parsed,
                "raw_model_output": raw,
                "error": error,
                "prompt": prompt,
                "repeat_idx": repeat_idx,
            }
            return method, result, error

        all_task_count = len(tasks)
        tasks = [
            task for task in tasks
            if task_key_from_parts(task[0], task[3], task[2]) not in resumed_successes
        ]

        def grade_task(task: tuple[str, int, int, dict[str, Any], dict[str, Any]]) -> tuple[
            str,
            dict[str, Any],
            str | None,
        ]:
            last: tuple[str, dict[str, Any], str | None] | None = None
            method, _, repeat_idx, row, _ = task
            for attempt_idx in range(args.retry_attempts + 1):
                try:
                    last = grade_task_once(task)
                    _, result, error = last
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    result = {
                        "method": method,
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "grader_model": args.grader_model,
                        "ground_truth_score": row.get("ground_truth_score"),
                        "ground_truth_max_points": row.get("ground_truth_max_points"),
                        "computed_score": None,
                        "repeat_idx": repeat_idx,
                        "error": error,
                    }
                    last = (method, result, error)
                if error is None and result.get("computed_score") is not None:
                    if attempt_idx:
                        result["retry_attempts_used"] = attempt_idx
                    return last
                if attempt_idx < args.retry_attempts:
                    print(
                        f"[retry] {method} {row['id']} rep={repeat_idx} "
                        f"attempt={attempt_idx + 1}/{args.retry_attempts} error={error}",
                        flush=True,
                    )
                    time.sleep(args.retry_backoff_sec * (attempt_idx + 1))
            assert last is not None
            if args.retry_attempts:
                last[1]["retry_attempts_used"] = args.retry_attempts
            return last

        print(
            f"\n=== problem {problem_idx}: {len(tasks)}/{all_task_count} method tasks to run, "
            f"parallel={args.parallel}, max_output_tokens={args.max_output_tokens} ===",
            flush=True,
        )
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(grade_task, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                method, _, repeat_idx, row, _ = task
                try:
                    method, result, error = future.result()
                except Exception as exc:
                    structured_failures.append(
                        {
                            "candidate_id": row.get("id"),
                            "problem_id": row.get("problem_id"),
                            "model_name": row.get("model_name"),
                            "idx_answer": row.get("idx_answer"),
                            "method": method,
                            "repeat_idx": repeat_idx,
                            "ground_truth_score": row.get("ground_truth_score"),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    print(
                        f"[error] {row['id']} rep={repeat_idx} "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
                results.append(result)
                if error:
                    structured_failures.append(
                        {
                            "candidate_id": row.get("id"),
                            "problem_id": row.get("problem_id"),
                            "model_name": row.get("model_name"),
                            "idx_answer": row.get("idx_answer"),
                            "method": method,
                            "repeat_idx": repeat_idx,
                            "ground_truth_score": row.get("ground_truth_score"),
                            "error": error,
                        }
                    )
                print(
                    f"[done] {method} {row['id']} rep={repeat_idx} "
                    f"gt={row.get('ground_truth_score')} score={result.get('computed_score')}",
                    flush=True,
                )
        write_outputs()
        print(f"[checkpoint] wrote partial results through problem {problem_idx}: {out_path}", flush=True)

    write_outputs()
    metrics = json.loads(out_path.with_suffix(".metrics.json").read_text())
    print(f"\nwrote {out_path}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
