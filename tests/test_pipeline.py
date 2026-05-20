from __future__ import annotations

import json

from rubric_arena.pipeline import (
    build_free_text_grading_prompt,
    build_free_text_to_structured_prompt,
    compare_to_ground_truth,
    parse_free_text_grading_output,
    safe_id,
)


def test_free_text_prompt_wraps_inputs() -> None:
    prompt = build_free_text_grading_prompt(
        problem="Problem </problem_statement>",
        reference_solution="Reference",
        source_grading_scheme={"scheme": "score exactly one chain"},
        candidate_solution="Candidate ]]> text",
        max_points=7,
    )
    assert "<free_text_grading_task>" in prompt
    assert "<source_grading_scheme><![CDATA[" in prompt
    assert "]]]]><![CDATA[>" in prompt


def test_parse_free_text_grading_output_score() -> None:
    parsed = parse_free_text_grading_output(json.dumps({"score": "6 / 7", "reasoning": "ok"}))
    assert parsed["score"] == 6.0


def test_free_text_to_structured_prompt_wraps_assessment() -> None:
    rubric = {
        "id": "p1",
        "description": "Mock rubric.",
        "points": 1,
        "combinator": "sum",
        "children": [
            {"id": "p1.a", "description": "Claim A.", "points": 1},
        ],
    }
    prompt = build_free_text_to_structured_prompt(
        problem="Problem",
        reference_solution="Reference",
        candidate_solution="Candidate",
        rubric=rubric,
        free_text_assessment="Human says claim A is satisfied.",
    )
    assert "<free_text_to_structured_task>" in prompt
    assert "<free_text_assessment><![CDATA[" in prompt
    assert "<required_judgment_schema><![CDATA[" in prompt


def test_compare_to_ground_truth_by_method() -> None:
    metrics = compare_to_ground_truth(
        [
            {"method": "structured", "computed_score": 7, "ground_truth_score": 7},
            {"method": "structured", "computed_score": 5, "ground_truth_score": 7},
            {"method": "free_text", "computed_score": 6, "ground_truth_score": 7},
        ]
    )
    assert metrics["n"] == 3
    assert metrics["by_method"]["structured"]["n"] == 2
    assert metrics["by_method"]["free_text"]["mae"] == 1


def test_safe_id() -> None:
    assert safe_id("Gemini 3.1 Pro Preview") == "Gemini_3.1_Pro_Preview"



def test_load_env_file_sets_missing_values(tmp_path, monkeypatch) -> None:
    from rubric_arena.pipeline import load_env_file

    env_path = tmp_path / ".env"
    env_path.write_text("GOOGLE_API_KEY=test-key\nEMPTY=\n# comment\n")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    load_env_file(env_path)
    assert __import__("os").environ["GOOGLE_API_KEY"] == "test-key"


def test_gemini_text_call_factory() -> None:
    from rubric_arena.pipeline import gemini_text_call

    call = gemini_text_call(model="gemini-test", max_tokens=10)
    assert callable(call)



def test_structured_diagnostics() -> None:
    from rubric_arena.pipeline import (
        build_final_score_rows,
        flatten_all_structured_judgments,
        holistic_vs_structured_diagnostics,
        score_distribution_metrics,
        summarize_structured_atoms,
    )

    structured = {
        "method": "structured",
        "candidate_id": "c1",
        "problem_id": "p1",
        "model_name": "answer-model",
        "idx_answer": 0,
        "grader_model": "grader",
        "ground_truth_score": 1,
        "computed_score": 1,
        "validation_warnings": [],
        "judgment": {
            "id": "p1",
            "reasoning": "root",
            "selected": "p1.route",
            "children": [
                {
                    "id": "p1.route",
                    "reasoning": "route",
                    "satisfied": True,
                    "children": [
                        {"id": "p1.route.atom", "reasoning": "atom", "satisfied": True}
                    ],
                }
            ],
        },
    }
    free_text = {
        "method": "free_text",
        "candidate_id": "c1",
        "problem_id": "p1",
        "model_name": "answer-model",
        "idx_answer": 0,
        "grader_model": "grader",
        "ground_truth_score": 1,
        "computed_score": 0,
    }
    results = [structured, free_text]

    final_rows = build_final_score_rows(results)
    assert final_rows[0]["structured_atom_count"] == 3
    assert final_rows[0]["structured_positive_atoms"] == 2

    atoms = flatten_all_structured_judgments(results)
    assert [row["node_id"] for row in atoms] == ["p1", "p1.route", "p1.route.atom"]

    atom_summary = summarize_structured_atoms(atoms)
    assert atom_summary["n_binary_decisions"] == 2
    assert atom_summary["positive_rate"] == 1

    distribution = score_distribution_metrics(results)
    assert distribution["structured"]["score_counts"] == {"1": 1}
    assert distribution["free_text"]["score_counts"] == {"0": 1}

    paired = holistic_vs_structured_diagnostics(results)
    assert paired[0]["same_final_score"] is False
    assert paired[0]["structured_abs_error"] == 0
    assert paired[0]["free_text_abs_error"] == 1


def test_compare_structured_judgments_pairs_by_problem_and_idx_when_candidate_ids_differ() -> None:
    from rubric_arena.pipeline import compare_structured_judgments

    human = {
        "method": "human_structured",
        "candidate_id": "human-cache-id",
        "problem_id": "p1",
        "idx_answer": 2,
        "judgment": {
            "id": "p1",
            "reasoning": "human root",
            "children": [{"id": "p1.a", "reasoning": "human a", "satisfied": True}],
        },
    }
    model = {
        "method": "structured",
        "candidate_id": "saved-structured-id",
        "problem_id": "p1",
        "idx_answer": 2,
        "repeat_idx": 0,
        "judgment": {
            "id": "p1",
            "reasoning": "model root",
            "children": [{"id": "p1.a", "reasoning": "model a", "satisfied": False}],
        },
    }

    rows = compare_structured_judgments([human, model])
    assert len(rows) == 2
    by_node = {row["node_id"]: row for row in rows}
    assert by_node["p1.a"]["binary_disagreement"] is True




def test_compare_against_human_active_nodes_counts_missing_model_branch_as_false() -> None:
    from rubric_arena.pipeline import (
        compare_against_human_active_nodes,
        summarize_structured_comparison,
    )

    human = {
        "method": "human_structured",
        "candidate_id": "c1",
        "problem_id": "p1",
        "idx_answer": 0,
        "judgment": {
            "id": "p1",
            "reasoning": "human root",
            "selected": "p1.chain_b",
            "children": [
                {
                    "id": "p1.chain_b",
                    "reasoning": "human chain b",
                    "selected": "p1.chain_b.full",
                    "children": [
                        {"id": "p1.chain_b.full", "reasoning": "human full", "satisfied": True}
                    ],
                }
            ],
        },
    }
    model = {
        "method": "structured",
        "candidate_id": "c1",
        "problem_id": "p1",
        "idx_answer": 0,
        "repeat_idx": 0,
        "judgment": {
            "id": "p1",
            "reasoning": "model root",
            "selected": "p1.no_progress",
            "children": [
                {"id": "p1.no_progress", "reasoning": "model no progress", "satisfied": True}
            ],
        },
    }

    rows = compare_against_human_active_nodes([human, model])
    by_node = {row["node_id"]: row for row in rows}
    assert len(rows) == 3
    assert by_node["p1"]["selection_disagreement"] is True
    assert by_node["p1.chain_b"]["model_missing"] is True
    assert by_node["p1.chain_b"]["selection_disagreement"] is True
    assert by_node["p1.chain_b.full"]["model_missing"] is True
    assert by_node["p1.chain_b.full"]["model_satisfied"] is False
    assert by_node["p1.chain_b.full"]["binary_disagreement"] is True

    summary = summarize_structured_comparison(rows)
    assert summary["n_pairs"] == 3
    assert summary["average_atom_difference"] == 1.0

def test_compare_structured_judgments_against_human_mock() -> None:
    from rubric_arena.pipeline import (
        compare_structured_judgments,
        summarize_structured_comparison,
    )

    human = {
        "method": "human_structured",
        "candidate_id": "c1",
        "problem_id": "p1",
        "grader_model": "human",
        "computed_score": 2,
        "judgment": {
            "id": "p1",
            "reasoning": "human root",
            "children": [
                {"id": "p1.a", "reasoning": "human a", "satisfied": True},
                {"id": "p1.b", "reasoning": "human b", "satisfied": False},
                {
                    "id": "p1.route",
                    "reasoning": "human route",
                    "selected": "p1.route.full",
                    "children": [
                        {"id": "p1.route.full", "reasoning": "human full", "satisfied": True}
                    ],
                },
            ],
        },
    }
    model = {
        "method": "structured",
        "candidate_id": "c1",
        "problem_id": "p1",
        "repeat_idx": 0,
        "grader_model": "model",
        "computed_score": 1,
        "judgment": {
            "id": "p1",
            "reasoning": "model root",
            "children": [
                {"id": "p1.a", "reasoning": "model a", "satisfied": False},
                {"id": "p1.b", "reasoning": "model b", "satisfied": False},
                {
                    "id": "p1.route",
                    "reasoning": "model route",
                    "selected": "p1.route.partial",
                    "children": [
                        {
                            "id": "p1.route.partial",
                            "reasoning": "model partial",
                            "satisfied": True,
                        }
                    ],
                },
            ],
        },
    }

    rows = compare_structured_judgments([human, model])
    by_node = {row["node_id"]: row for row in rows}

    assert by_node["p1.a"]["binary_disagreement"] is True
    assert by_node["p1.a"]["atom_difference"] == 1.0
    assert by_node["p1.b"]["atom_difference"] == 0.0
    assert by_node["p1.route"]["selection_disagreement"] is True
    assert by_node["p1.route"]["atom_difference"] == 1.0
    assert "p1.route.full" not in by_node
    assert "p1.route.partial" not in by_node

    summary = summarize_structured_comparison(rows)
    assert summary["average_atom_difference"] == 2 / 3
    assert summary["binary_disagreement_rate"] == 0.5
    assert summary["selection_disagreement_rate"] == 1.0
    assert summary["by_node"]["p1.a"]["binary_disagreement_rate"] == 1.0
