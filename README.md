# rubric-arena

Granular rubric-based grading for math-olympiad LLM evaluation.

The goal: take [MathArena](https://matharena.ai/)'s grading style and replace its coarse judging with a more granular, structured rubric (USEMO Schema v4). We then benchmark the rubric grader against MathArena's existing LLM judges, and — if it works — fold it into our debate-based judging stack ([ai-debate](https://github.com/ethanelasky/ai-debate)).

## Contents

- `math_rubric_schema.md` — USEMO v4 rubric schema (structured, per-problem, machine-checkable).
- `grading_prompt.md` — grader prompt: problem + reference solutions + v4 rubric + contestant paper → structured judgment JSON.
- `translation_prompt.md` — prompt for translating freeform reference solutions / answer keys into v4 rubrics.

## Status

Untested. First experiments will compare rubric-grader scores against MathArena human and LLM judgments on a shared problem set.
