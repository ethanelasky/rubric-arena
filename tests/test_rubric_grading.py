from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from rubric_arena import rubric_grading


USEMO1_RUBRIC = json.loads(
    Path("data/usemo_2020/rubrics/usemo_2020_p1.rubric.v4.json").read_text()
)


def partial_v2_judgment() -> dict:
    return {
        "id": "usemo_2020_p1",
        "reasoning": "The paper has even construction and at least one substantial valuation case but is incomplete.",
        "selected": "usemo_2020_p1.partial_v2",
        "children": [
            {
                "id": "usemo_2020_p1.partial_v2",
                "reasoning": "It earns both additive items in the v2 partial route.",
                "children": [
                    {
                        "id": "usemo_2020_p1.partial_v2.even_construction",
                        "reasoning": "It gives x=1,z=1,y=n for k=2n.",
                        "satisfied": True,
                    },
                    {
                        "id": "usemo_2020_p1.partial_v2.substantial_case",
                        "reasoning": "It handles the case where v2(y) is strictly maximal.",
                        "satisfied": True,
                    },
                ],
            }
        ],
    }


def test_usemo_fixture_validates() -> None:
    result = rubric_grading.validate_rubric(USEMO1_RUBRIC)
    assert result.warnings == []


def test_partial_v2_scores_two_points() -> None:
    assert rubric_grading.compute_score(USEMO1_RUBRIC, partial_v2_judgment()) == 2


def test_rejects_bad_one_of_selection() -> None:
    judgment = partial_v2_judgment()
    judgment["selected"] = "usemo_2020_p1.no_progress"
    with pytest.raises(rubric_grading.JudgmentError):
        rubric_grading.validate_judgment(USEMO1_RUBRIC, judgment)


def test_rejects_bad_sum_arithmetic() -> None:
    rubric = deepcopy(USEMO1_RUBRIC)
    rubric["children"][1]["points"] = 3
    with pytest.raises(rubric_grading.RubricError, match="sum of children"):
        rubric_grading.validate_rubric(rubric)


def test_rubric_generation_prompt_and_parse() -> None:
    prompt = rubric_grading.build_rubric_generation_prompt(
        problem_id="demo",
        problem="Problem",
        source_grading_scheme={"rubric": "source"},
        sample_solution="Solution",
    )
    assert "<source_grading_scheme><![CDATA[" in prompt
    parsed = rubric_grading.rubric_from_model_output(json.dumps(USEMO1_RUBRIC))
    assert parsed["schema_version"] == "v4"



def test_rubric_from_model_output_repairs_common_model_errors() -> None:
    rough = {
        "schema_version": "v4",
        "rubric_version": "1.0",
        "id": "demo",
        "description": "Demo rubric",
        "points": 1,
        "guidelines": "First guideline\nSecond guideline",
        "combinator": "one_of",
        "children": [
            {
                "id": "demo.partial",
                "selection_signal": "Some partial progress",
                "combinator": "sum",
                "children": [
                    {
                        "id": "demo.partial.item",
                        "description": "Earns one point.",
                        "points": 1,
                    }
                ],
            },
            {
                "id": "demo.none",
                "description": "No progress.",
                "selection_signal": "none of the above applies",
                "points": 0,
            },
        ],
    }
    parsed = rubric_grading.rubric_from_model_output(json.dumps(rough))
    assert parsed["guidelines"] == ["First guideline", "Second guideline"]
    assert parsed["children"][0]["description"] == "Some partial progress"
    assert parsed["children"][0]["points"] == 1



def test_grade_from_model_output_repairs_missing_atomic_parent_satisfied() -> None:
    rubric = {
        "schema_version": "v4",
        "rubric_version": "1.0",
        "id": "demo_judgment",
        "description": "Demo judgment repair.",
        "points": 1,
        "satisfied_when": "all",
        "children": [
            {"id": "demo_judgment.a", "description": "A is true."},
            {"id": "demo_judgment.b", "description": "B is true."},
        ],
    }
    judgment = {
        "id": "demo_judgment",
        "reasoning": "Both conditions are met.",
        "children": [
            {"id": "demo_judgment.a", "reasoning": "A", "satisfied": "true"},
            {"id": "demo_judgment.b", "reasoning": "B", "satisfied": True},
        ],
    }
    result = rubric_grading.grade_from_model_output(
        rubric=rubric,
        raw_model_output=json.dumps(judgment),
    )
    assert result["computed_score"] == 1
    assert result["judgment"]["satisfied"] is True
