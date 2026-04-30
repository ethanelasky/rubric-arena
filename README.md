# rubric-arena

Granular rubric-based grading for math-olympiad LLM evaluation.

The goal: take [MathArena](https://matharena.ai/)'s grading style and replace its coarse judging with a more granular, structured rubric (USEMO Schema v4). We then benchmark the rubric grader against MathArena's existing LLM judges, and — if it works — fold it into our debate-based judging stack ([ai-debate](https://github.com/ethanelasky/ai-debate)).

## Contents

- `math_rubric_schema.md` — USEMO v4 rubric schema (structured, per-problem, machine-checkable).
- `grading_prompt.md` — grader prompt: problem + reference solutions + v4 rubric + contestant paper → structured judgment JSON.
- `translation_prompt.md` — prompt for translating freeform reference solutions / answer keys into v4 rubrics.

## Status

Untested. First experiments will compare rubric-grader scores against MathArena human and LLM judgments on a shared problem set.


## Local Pipeline

The repo now contains executable pieces for the v4 rubric-grading loop:

- `src/rubric_arena/rubric_grading.py` — v4 rubric validation, judgment validation, deterministic scoring, rubric-generation prompts, grading prompts, and model-output parsing.
- `notebooks/rubric_v4_usemo_lab.ipynb` — notebook lab for USEMO and MathArena experiments.
- `data/usemo_2020/rubrics/usemo_2020_p1.rubric.v4.json` — initial hand-normalized v4 rubric fixture.
- `scripts/download_matharena_usamo_2026.py` — downloads MathArena USAMO 2026 problems and model outputs into local JSONL files.

Download MathArena locally:

```bash
uv run python scripts/download_matharena_usamo_2026.py \
  --model-name "Gemini 3.1 Pro Preview"
```

This writes:

```text
data/matharena_usamo_2026/problems.jsonl
data/matharena_usamo_2026/outputs.jsonl
data/matharena_usamo_2026/pipeline_rows.jsonl
```

`pipeline_rows.jsonl` joins each model answer to its problem, sample solution, source grading scheme, and MathArena judge score. That is the local integration surface for rubric-generation and rubric-grading experiments.

Run tests:

```bash
uv run pytest
```
