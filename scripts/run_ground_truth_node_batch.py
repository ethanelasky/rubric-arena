#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_mid_credit_eval as mid  # noqa: E402
from rubric_arena.matharena_loader import read_jsonl  # noqa: E402
from rubric_arena.pipeline import (  # noqa: E402
    build_free_text_to_structured_prompt,
    compare_against_human_active_nodes,
    load_env_file,
    safe_id,
    summarize_structured_comparison,
    write_jsonl,
)
from rubric_arena.rubric_grading import (  # noqa: E402
    JudgmentError,
    ModelOutputError,
    compute_score,
    extract_first_json_object,
    repair_common_judgment_model_errors,
    validate_judgment,
    xml_block,
)

GT_DIR = mid.DATA_ROOT / "ground_truth_human_nodes" / "v1"
GT_PATH = GT_DIR / "human_node_ground_truth.v1.jsonl"
OUT_DIR = mid.RUN_DIR / "ground_truth_node_batches"


def parse_xml_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S | re.I)
    return match.group(1).strip() if match else None


def parse_free_text_xml_output(raw: str) -> dict[str, Any]:
    score_text = parse_xml_tag(raw, "score")
    assessment = parse_xml_tag(raw, "assessment") or ""
    errors = parse_xml_tag(raw, "errors") or ""
    if score_text is None:
        raise ModelOutputError("Free-text XML output missing <score>")
    match = re.search(r"-?\d+(?:\.\d+)?", score_text)
    if not match:
        raise ModelOutputError(f"Free-text XML score is not numeric: {score_text!r}")
    return {"score": float(match.group(0)), "assessment": assessment, "errors": errors}


def build_current_free_text_prompt(row: dict[str, Any]) -> str:
    prompt_md = (REPO_ROOT / "free_text_prompt.md").read_text().strip()
    strict_output = """
Final output reminder: respond with only this XML shape and no markdown fences:
<score>INTEGER_FROM_0_TO_7</score>
<assessment>Detailed grading analysis.</assessment>
<errors>Specific errors, or empty if none.</errors>
""".strip()
    return (
        f"{prompt_md}\n\n{strict_output}\n\n---\n\n"
        f"{xml_block('problem_statement', row.get('problem', ''))}\n\n"
        f"{xml_block('reference_solution', row.get('sample_solution') or '')}\n\n"
        f"{xml_block('marking_scheme', mid.normalize_grading_scheme(row.get('grading_scheme')))}\n\n"
        f"{xml_block('proof_solution', row.get('candidate_solution') or '')}"
    ).strip()


def _aggressive_repair_judgment_shape(rubric: dict[str, Any], judgment: dict[str, Any]) -> dict[str, Any]:
    def synthesize_false(rubric_node: dict[str, Any]) -> dict[str, Any]:
        node = {
            "id": rubric_node.get("id"),
            "reasoning": "Synthesized as unsatisfied to repair malformed structured conversion output.",
        }
        if "children" not in rubric_node:
            node["satisfied"] = False
            return node
        if rubric_node.get("satisfied_when"):
            node["children"] = [synthesize_false(child) for child in rubric_node.get("children", [])]
            node["satisfied"] = False
            return node
        if rubric_node.get("combinator") == "sum":
            node["children"] = [synthesize_false(child) for child in rubric_node.get("children", [])]
            return node
        if rubric_node.get("combinator") == "one_of":
            children = rubric_node.get("children", [])
            if children:
                selected = min(children, key=lambda child: int(child.get("points") or 0))
                node["selected"] = selected.get("id")
                node["children"] = [synthesize_false(selected)]
            return node
        node["satisfied"] = False
        return node

    def child_points(child: dict[str, Any]) -> int:
        try:
            return int(child.get("points") or 0)
        except Exception:
            return 0

    def walk(rubric_node: dict[str, Any], judgment_node: dict[str, Any]) -> None:
        if not isinstance(judgment_node, dict):
            return
        if judgment_node.get("id") != rubric_node.get("id"):
            judgment_node["id"] = rubric_node.get("id")
        judgment_node.setdefault("reasoning", "Repaired malformed structured conversion output.")

        rubric_children = rubric_node.get("children", [])
        if not rubric_children:
            judgment_node.pop("children", None)
            judgment_node.pop("selected", None)
            if not isinstance(judgment_node.get("satisfied"), bool):
                judgment_node["satisfied"] = False
            return

        children = judgment_node.get("children")
        if isinstance(children, dict):
            children = list(children.values())
            judgment_node["children"] = children

        if rubric_node.get("satisfied_when") or rubric_node.get("combinator") == "sum":
            if not isinstance(children, list):
                children = []
            by_id = {child.get("id"): child for child in children if isinstance(child, dict)}
            repaired_children = []
            for rubric_child in rubric_children:
                child = by_id.get(rubric_child.get("id"))
                if not isinstance(child, dict):
                    child = synthesize_false(rubric_child)
                walk(rubric_child, child)
                repaired_children.append(child)
            judgment_node["children"] = repaired_children
            if rubric_node.get("combinator") == "sum":
                judgment_node.pop("selected", None)
                judgment_node.pop("satisfied", None)
            else:
                judgment_node.pop("selected", None)
                values = [bool(child.get("satisfied")) for child in repaired_children]
                mode = rubric_node.get("satisfied_when")
                judgment_node["satisfied"] = all(values) if mode == "all" else any(values)
            return

        if rubric_node.get("combinator") == "one_of":
            rubric_by_id = {child.get("id"): child for child in rubric_children}
            children_list = children if isinstance(children, list) else []
            child_by_id = {child.get("id"): child for child in children_list if isinstance(child, dict)}
            selected = judgment_node.get("selected")
            if selected not in rubric_by_id:
                valid_child_ids = [child_id for child_id in child_by_id if child_id in rubric_by_id]
                if valid_child_ids:
                    selected = valid_child_ids[0]
                else:
                    selected = min(rubric_children, key=child_points).get("id")
                judgment_node["selected"] = selected
            selected_rubric = rubric_by_id[selected]
            selected_child = child_by_id.get(selected)
            if not isinstance(selected_child, dict):
                selected_child = children_list[0] if children_list and isinstance(children_list[0], dict) else synthesize_false(selected_rubric)
                selected_child["id"] = selected
            walk(selected_rubric, selected_child)
            judgment_node["children"] = [selected_child]
            judgment_node.pop("satisfied", None)

    walk(rubric, judgment)
    return judgment


def parse_structured_result(*, row: dict[str, Any], rubric: dict[str, Any], raw: str, prompt: str, method: str, grader_model: str) -> dict[str, Any]:
    judgment = extract_first_json_object(raw)
    judgment = repair_common_judgment_model_errors(rubric, judgment)
    judgment = _aggressive_repair_judgment_shape(rubric, judgment)
    validation = validate_judgment(rubric, judgment)
    computed_score = compute_score(rubric, judgment)
    return {
        "method": method,
        "candidate_id": row.get("id"),
        "problem_id": row.get("problem_id"),
        "model_name": row.get("model_name"),
        "idx_answer": row.get("idx_answer"),
        "grader_model": grader_model,
        "ground_truth_score": row.get("ground_truth_score"),
        "ground_truth_max_points": row.get("ground_truth_max_points"),
        "computed_score": computed_score,
        "judgment": judgment,
        "validation_warnings": validation.warnings,
        "raw_model_output": raw,
        "prompt": prompt,
        "repeat_idx": 0,
    }


def call_with_retries(fn, *, attempts: int, backoff_sec: float) -> Any:
    last_exc = None
    for attempt in range(attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(backoff_sec * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run structured then free-text grading on sampled finalized human node ground truth rows.")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260520)
    parser.add_argument("--parallel", type=int, default=20)
    parser.add_argument("--grader-model", default=mid.DEFAULT_GRADER_MODEL)
    parser.add_argument("--rubric-model", default=None)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    parser.add_argument("--timeout-ms", type=int, default=600000)
    parser.add_argument("--retry-attempts", type=int, default=2)
    parser.add_argument("--retry-backoff-sec", type=float, default=2.0)
    parser.add_argument("--reuse-rubric", action="store_true")
    parser.add_argument("--selected-ids-path", type=Path, default=None)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--phase", choices=["all", "structured", "free_text"], default="all")
    parser.add_argument("--json-mode", action="store_true")
    parser.add_argument("--out-tag", default="gt20_structured_free_text_v1")
    args = parser.parse_args()

    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_env_file(env_path)
    if not os.environ.get("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required")

    from google import genai

    gt_rows = read_jsonl(GT_PATH)
    rng = random.Random(args.seed)
    if args.selected_ids_path:
        selected_ids_from_file = [
            line.strip()
            for line in args.selected_ids_path.read_text().splitlines()
            if line.strip()
        ]
        selected_gt = [row for row in gt_rows if row["candidate_id"] in selected_ids_from_file]
        missing = sorted(set(selected_ids_from_file) - {row["candidate_id"] for row in selected_gt})
        if missing:
            raise SystemExit(f"selected ids missing from ground truth: {missing}")
    elif args.candidate_id:
        selected_gt = [row for row in gt_rows if row["candidate_id"] in set(args.candidate_id)]
        missing = sorted(set(args.candidate_id) - {row["candidate_id"] for row in selected_gt})
        if missing:
            raise SystemExit(f"candidate ids missing from ground truth: {missing}")
    else:
        selected_gt = gt_rows[:]
        rng.shuffle(selected_gt)
        selected_gt = selected_gt[: args.sample_size]
    selected_ids = [row["candidate_id"] for row in selected_gt]
    gt_by_id = {row["candidate_id"]: row for row in selected_gt}
    pipeline_by_id = {row.get("id"): row for row in read_jsonl(mid.DATA_ROOT / "pipeline_rows.jsonl")}
    rows = [pipeline_by_id[candidate_id] for candidate_id in selected_ids]

    rubric_model = args.rubric_model or args.grader_model
    rubric_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    rubrics: dict[str, dict[str, Any]] = {}
    for problem_id in sorted({row["problem_id"] for row in rows}):
        problem_rows = [row for row in rows if row["problem_id"] == problem_id]
        rubrics[problem_id] = mid.load_or_generate_rubric(
            client=rubric_client,
            rows=problem_rows,
            rubric_model=rubric_model,
            reuse_rubric=args.reuse_rubric,
        )

    created = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_stem = f"{safe_id(args.grader_model)}.{safe_id(args.out_tag)}.{created}"
    out_path = OUT_DIR / f"{out_stem}.jsonl"
    failures_path = out_path.with_suffix(".failures.jsonl")
    selected_path = out_path.with_suffix(".selected_ids.txt")
    selected_path.write_text("\n".join(selected_ids) + "\n")

    results: list[dict[str, Any]] = list(selected_gt)
    failures: list[dict[str, Any]] = []

    def llm_call(prompt: str, *, json_mode: bool = False) -> str:
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        if json_mode:
            from google.genai import types

            response = client.models.generate_content(
                model=args.grader_model,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    max_output_tokens=args.max_output_tokens,
                    temperature=0.0,
                    response_mime_type="application/json",
                    http_options=types.HttpOptions(timeout=args.timeout_ms),
                ),
            )
            text = getattr(response, "text", None)
            if text:
                return text
            parts: list[str] = []
            for candidate in getattr(response, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    part_text = getattr(part, "text", "")
                    if part_text:
                        parts.append(part_text)
            return "".join(parts)
        return mid.gemini_stream(
            client,
            args.grader_model,
            prompt,
            max_output_tokens=args.max_output_tokens,
            timeout_ms=args.timeout_ms,
            verbose=False,
        )

    def structured_task(row: dict[str, Any]) -> dict[str, Any]:
        rubric = rubrics[row["problem_id"]]
        prompt = mid.build_structured_grading_prompt(row, rubric)
        return call_with_retries(
            lambda: parse_structured_result(
                row=row,
                rubric=rubric,
                raw=llm_call(prompt, json_mode=args.json_mode),
                prompt=prompt,
                method="structured",
                grader_model=args.grader_model,
            ),
            attempts=args.retry_attempts,
            backoff_sec=args.retry_backoff_sec,
        )

    def free_text_task(row: dict[str, Any]) -> list[dict[str, Any]]:
        rubric = rubrics[row["problem_id"]]
        ft_prompt = build_current_free_text_prompt(row)
        raw = call_with_retries(
            lambda: (lambda value: (parse_free_text_xml_output(value), value))(llm_call(ft_prompt)),
            attempts=args.retry_attempts,
            backoff_sec=args.retry_backoff_sec,
        )
        parsed, raw = raw
        ft_result = {
            "method": "free_text",
            "candidate_id": row.get("id"),
            "problem_id": row.get("problem_id"),
            "model_name": row.get("model_name"),
            "idx_answer": row.get("idx_answer"),
            "grader_model": args.grader_model,
            "ground_truth_score": row.get("ground_truth_score"),
            "ground_truth_max_points": row.get("ground_truth_max_points"),
            "computed_score": parsed["score"],
            "parsed_model_output": parsed,
            "raw_model_output": raw,
            "prompt": ft_prompt,
            "repeat_idx": 0,
        }
        convert_prompt = build_free_text_to_structured_prompt(
            problem=row.get("problem", ""),
            reference_solution=row.get("sample_solution") or "",
            candidate_solution=row.get("candidate_solution") or "",
            rubric=rubric,
            free_text_assessment=raw,
        )
        converted = call_with_retries(
            lambda: parse_structured_result(
                row=row,
                rubric=rubric,
                raw=llm_call(convert_prompt, json_mode=args.json_mode),
                prompt=convert_prompt,
                method="free_text_structured",
                grader_model=args.grader_model,
            ),
            attempts=args.retry_attempts,
            backoff_sec=args.retry_backoff_sec,
        )
        converted["source_free_text_result"] = {
            "computed_score": ft_result["computed_score"],
            "raw_model_output": raw,
            "parsed_model_output": parsed,
        }
        return [ft_result, converted]

    def run_phase(name: str, task_fn) -> None:
        print(f"\n=== phase {name}: rows={len(rows)} parallel={args.parallel} ===", flush=True)
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(task_fn, row): row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    value = future.result()
                    phase_results = value if isinstance(value, list) else [value]
                    results.extend(phase_results)
                    print(f"[done] {name} {row['id']} -> {[(r.get('method'), r.get('computed_score')) for r in phase_results]}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    failure = {
                        "phase": name,
                        "candidate_id": row.get("id"),
                        "problem_id": row.get("problem_id"),
                        "model_name": row.get("model_name"),
                        "idx_answer": row.get("idx_answer"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    failures.append(failure)
                    print(f"[error] {name} {row['id']} {failure['error']}", flush=True)
                write_jsonl(out_path, results)
                write_jsonl(failures_path, failures)

    print(f"[select] sample_size={len(rows)} seed={args.seed}", flush=True)
    print("[rows] " + ", ".join(selected_ids), flush=True)
    if args.phase in ("all", "structured"):
        run_phase("structured", structured_task)
    if args.phase in ("all", "free_text"):
        run_phase("free_text", free_text_task)

    by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    for result in results:
        by_candidate.setdefault(result["candidate_id"], {})[result["method"]] = result
    structured_rows: list[dict[str, Any]] = []
    free_text_rows: list[dict[str, Any]] = []
    for candidate_id, grouped in by_candidate.items():
        if "human_node_ground_truth" in grouped and "structured" in grouped:
            structured_rows.extend(compare_against_human_active_nodes([grouped["human_node_ground_truth"], grouped["structured"]], human_method="human_node_ground_truth", model_method="structured"))
        if "human_node_ground_truth" in grouped and "free_text_structured" in grouped:
            free_text_rows.extend(compare_against_human_active_nodes([grouped["human_node_ground_truth"], grouped["free_text_structured"]], human_method="human_node_ground_truth", model_method="free_text_structured"))

    write_jsonl(out_path.with_suffix(".structured_vs_human_active_nodes.jsonl"), structured_rows)
    write_jsonl(out_path.with_suffix(".free_text_vs_human_active_nodes.jsonl"), free_text_rows)
    summary = {
        "sample_size": len(rows),
        "seed": args.seed,
        "selected_ids_path": str(selected_path),
        "raw_results_path": str(out_path),
        "failures_path": str(failures_path),
        "result_rows": len(results),
        "failures": failures,
        "structured_candidate_n": sum(1 for grouped in by_candidate.values() if "structured" in grouped),
        "free_text_candidate_n": sum(1 for grouped in by_candidate.values() if "free_text_structured" in grouped),
        "both_candidate_n": sum(1 for grouped in by_candidate.values() if "structured" in grouped and "free_text_structured" in grouped),
        "structured_vs_human_active_nodes": summarize_structured_comparison(structured_rows),
        "free_text_vs_human_active_nodes": summarize_structured_comparison(free_text_rows),
    }
    out_path.with_suffix(".node_metrics.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
