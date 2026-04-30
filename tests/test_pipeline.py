from __future__ import annotations

import json

from rubric_arena.pipeline import (
    build_free_text_grading_prompt,
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


def test_compare_to_ground_truth_by_method() -> None:
    metrics = compare_to_ground_truth(
        [
            {"method": "structured_v4", "computed_score": 7, "ground_truth_score": 7},
            {"method": "structured_v4", "computed_score": 5, "ground_truth_score": 7},
            {"method": "free_text", "computed_score": 6, "ground_truth_score": 7},
        ]
    )
    assert metrics["n"] == 3
    assert metrics["by_method"]["structured_v4"]["n"] == 2
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
        "method": "structured_v4",
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
    assert distribution["structured_v4"]["score_counts"] == {"1": 1}
    assert distribution["free_text"]["score_counts"] == {"0": 1}

    paired = holistic_vs_structured_diagnostics(results)
    assert paired[0]["same_final_score"] is False
    assert paired[0]["structured_abs_error"] == 0
    assert paired[0]["free_text_abs_error"] == 1
