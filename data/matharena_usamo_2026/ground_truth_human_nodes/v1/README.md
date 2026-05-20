# MathArena USAMO 2026 Human Node Ground Truth v1

This directory contains finalized structured node-level human ground truth for the local MathArena USAMO 2026 dataset.

The source set started from 48 high-confidence human prose labels reviewed in `docs/human_label_reviews/usable_human_node_labels.jsonl`. The finalized set includes labels that converted to valid structured rubric judgments, computed to the MathArena human score, and passed audit against the human comment and judge context. Three non-score-changing `no-progress` boolean warnings were repaired and revalidated.

Files:

- `human_node_ground_truth.v1.jsonl`: finalized structured human judgments.
- `human_node_ground_truth_atoms.v1.jsonl`: flattened node-level rows derived from the finalized judgments.
- `excluded_rows.v1.jsonl`: high-confidence prose labels excluded from v1.
- `manifest.v1.json`: provenance, counts, and inclusion policy.

Summary: 44 approved rows, 4 excluded rows, 334 atom rows.
