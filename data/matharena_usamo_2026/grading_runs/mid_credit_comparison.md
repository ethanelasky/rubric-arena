# Mid-credit comparison: structured-rubric vs free-text vs human

**Setup.** USAMO 2026, candidate solutions from `Gemini 3.1 Pro Preview`, graded by `gemini-3.1-pro-preview` under both methods. Mid-credit dev set: 10 rows where `1 ≤ ground_truth ≤ 6` out of 7. Rubrics generated fresh from `translation_prompt.md`; grading uses `grading_prompt.md`.

Source files: `p{1,3,5,6}.Gemini_3.1_Pro_Preview.gemini-3.1-pro-preview.mid_credit_v1.{jsonl,final_scores.jsonl,structured_atoms.jsonl,paired_diagnostics.jsonl,metrics.json}`.

## Per-row table

| problem | idx | human | structured | s − human | free-text | ft − human | structured regime |
|---|---|---|---|---|---|---|---|
| p1 | 2 | 6 | 7 | +1 | 7 | +1 | upper-bound → general |
| p1 | 3 | 4 | 5 | +1 | 6 | +2 | upper-bound → coprime |
| p3 | 1 | 5 | 7 | +2 | 7 | +2 | chain-b → complete |
| p3 | 2 | 1 | 1 | 0 | 1 | 0 | chain-b → setup |
| p3 | 3 | 6 | 7 | +1 | 6 | 0 | chain-b → complete |
| p5 | 2 | 6 | 5 | −1 | 6 | 0 | complex-minor-error |
| p6 | 0 | 5 | 7 | +2 | 7 | +2 | (sum root, no one_of) |
| p6 | 1 | 2 | 4 | +2 | 4 | +2 | (sum root, no one_of) |
| p6 | 2 | 5 | 7 | +2 | 7 | +2 | (sum root, no one_of) |
| p6 | 3 | 1 | 0 | −1 | 2 | +1 | (sum root, no one_of) |

`regime` is the chain of `one_of` selections in the structured judgment, leaf-most last. Problems whose root rubric is `sum` (p1, p6) have no top-level regime; nested one_of selections are reported when present.

## Aggregates (n = 10)

| metric | structured-rubric | free-text |
|---|---|---|
| MAE | **1.30** | **1.20** |
| RMSE | 1.45 | 1.48 |
| Signed bias (mean error) | +0.90 | +1.20 |
| Exact-match rate | 10% (1/10) | 30% (3/10) |
| Within-1 rate | 60% | 50% |

## Per-problem breakdown

| problem | n | structured MAE | structured bias | structured exact | free-text MAE | free-text bias | free-text exact |
|---|---|---|---|---|---|---|---|
| p1 | 2 | 1.00 | +1.00 | 0% | 1.50 | +1.50 | 0% |
| p3 | 3 | 1.00 | +1.00 | 33% | 0.67 | +0.67 | 67% |
| p5 | 1 | 1.00 | −1.00 | 0% | 0.00 | 0.00 | 100% |
| p6 | 4 | 1.75 | +1.25 | 0% | 1.75 | +1.75 | 0% |

## Verdict (≈200 words)

On these 10 mid-credit rows, **structured-rubric does not beat free-text against the human reference**. Free-text has lower MAE (1.20 vs 1.30) and three times the exact-match rate (30% vs 10%). Structured is closer in two senses that don't show up in the headline numbers: it has a smaller upward bias (+0.90 vs +1.20) and a higher within-1 rate (60% vs 50%) — i.e., structured rarely nails the score but lands one off more often, while free-text more often nails it or misses by 2.

Both methods are systematically lenient on partial-credit work: 8 of 10 rows are over-scored, only 2 under-scored, and the two methods agree on the over-scoring direction in every case where they err. The largest co-errors are on p6 (3 of 4 rows are +2 over for both methods) and p3[1] (+2 for both); the human evidently took off points the rubrics don't surface as discrete leaves.

Where they diverge: free-text picks up the exact match on p3[3] and p5[2] where structured drifts one off — both of these are problems where the human's deduction looks like a graceful penalty across multiple sub-claims rather than a single binary leaf failing. Per-problem the picture is mixed: structured wins p1 (n=2), free-text wins p3 (n=3) and p5 (n=1), tied on p6 (n=4).

## Caveats

- n = 10, single solver model, single grader model, single contest year. Aggregates are directional, not statistical.
- The two methods share a grader, so error correlations (e.g., both giving 7s) reflect grader properties, not method properties.
- Structured "regime" is reported as the deepest-nested `one_of` chain. p1 and p6 have `sum` roots — they expose no top-level regime, so the structured tree's discriminating power on those problems comes entirely from leaf judgments, not routing.
- Two over-scored p3 rows both routed to `chain-b → complete` (the "complete coordinate bash" regime). The human evidently treated those papers as containing gaps that the binary "complete" leaf does not represent. Whether this is a grading-prompt issue or a rubric-granularity issue is not determined from this data alone.
