from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_MATHARENA_USAMO_DIR = Path("data/matharena_usamo_2026")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_matharena_usamo_pipeline_rows(
    root: str | Path = DEFAULT_MATHARENA_USAMO_DIR,
    *,
    problem_idx: int | None = None,
    model_name: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = read_jsonl(Path(root) / "pipeline_rows.jsonl")
    if problem_idx is not None:
        rows = [row for row in rows if int(row["problem_idx"]) == int(problem_idx)]
    if model_name is not None:
        rows = [row for row in rows if row.get("model_name") == model_name]
    if limit is not None:
        rows = rows[:limit]
    return rows
