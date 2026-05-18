from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Union


_REPO_ROOT = Path(__file__).resolve().parents[2]


class RubricError(Exception):
    """Raised when a rubric is invalid or cannot be scored."""


class JudgmentError(Exception):
    """Raised when a judgment is invalid for a rubric."""


class ModelOutputError(Exception):
    """Raised when model rubric-grading output cannot be parsed."""


PointSpec = Union[int, dict[str, Any]]
NodeShape = Literal["leaf", "satisfied_when", "combinator"]


@dataclass(frozen=True)
class ValidationResult:
    warnings: list[str] = field(default_factory=list)


def _path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RubricError(f"{path} must be an object")
    return value


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RubricError(f"{path} must be a non-empty string")
    return value


def _require_int(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RubricError(f"{path} must be an integer")
    return value


def _points_default(points: Optional[PointSpec], path: str) -> int:
    if points is None:
        raise RubricError(f"{path}.points is required")
    if isinstance(points, int) and not isinstance(points, bool):
        if points < 0:
            raise RubricError(f"{path}.points must be non-negative")
        return points
    if isinstance(points, dict):
        return _require_int(points.get("default"), f"{path}.points.default")
    raise RubricError(f"{path}.points must be an integer or range object")


def _is_range_points(points: Optional[PointSpec]) -> bool:
    return isinstance(points, dict)


def _range_values(points: dict[str, Any], path: str) -> set[int]:
    scale = points.get("scale")
    if not isinstance(scale, list) or not scale:
        raise RubricError(f"{path}.points.scale must be a non-empty list")

    values: set[int] = set()
    for index, entry in enumerate(scale):
        if not isinstance(entry, dict):
            raise RubricError(f"{path}.points.scale[{index}] must be an object")
        value = _require_int(entry.get("value"), f"{path}.points.scale[{index}].value")
        _require_str(entry.get("criterion"), f"{path}.points.scale[{index}].criterion")
        values.add(value)
    return values


def validate_points(points: Optional[PointSpec], path: str) -> list[str]:
    warnings: list[str] = []

    if isinstance(points, int) and not isinstance(points, bool):
        if points < 0:
            raise RubricError(f"{path}.points must be non-negative")
        return warnings

    if not isinstance(points, dict):
        raise RubricError(f"{path}.points must be an integer or range object")

    minimum = _require_int(points.get("min"), f"{path}.points.min")
    maximum = _require_int(points.get("max"), f"{path}.points.max")
    default = _require_int(points.get("default"), f"{path}.points.default")
    if minimum < 0 or maximum < 0 or default < 0:
        raise RubricError(f"{path}.points range values must be non-negative")
    if not (minimum <= default <= maximum):
        raise RubricError(f"{path}.points must satisfy min <= default <= max")

    scale = points.get("scale")
    if not isinstance(scale, list) or not scale:
        raise RubricError(f"{path}.points.scale must be a non-empty list")

    values: list[int] = []
    for index, entry in enumerate(scale):
        if not isinstance(entry, dict):
            raise RubricError(f"{path}.points.scale[{index}] must be an object")
        value = _require_int(entry.get("value"), f"{path}.points.scale[{index}].value")
        criterion = entry.get("criterion")
        _require_str(criterion, f"{path}.points.scale[{index}].criterion")
        if not (minimum <= value <= maximum):
            raise RubricError(
                f"{path}.points.scale[{index}].value outside points range"
            )
        values.append(value)

    if minimum not in values or maximum not in values:
        raise RubricError(f"{path}.points.scale must include min and max values")
    if len(values) != len(set(values)):
        warnings.append(f"{path}.points.scale has duplicate values")

    return warnings


def node_shape(node: dict[str, Any], path: str) -> NodeShape:
    has_combinator = "combinator" in node
    has_satisfied_when = "satisfied_when" in node
    if has_combinator and has_satisfied_when:
        raise RubricError(f"{path} cannot have both combinator and satisfied_when")
    if has_combinator:
        return "combinator"
    if has_satisfied_when:
        return "satisfied_when"
    return "leaf"


def validate_rubric(rubric: dict[str, Any]) -> ValidationResult:
    _require_dict(rubric, "rubric")
    if "rubric_version" in rubric:
        _require_str(rubric.get("rubric_version"), "rubric.rubric_version")
    if node_shape(rubric, "rubric") == "leaf":
        raise RubricError("rubric root must have combinator or satisfied_when")

    seen: set[str] = set()
    warnings: list[str] = []
    _validate_rubric_node(rubric, "rubric", parent_id=None, seen=seen, warnings=warnings)

    if rubric.get("combinator") == "one_of":
        has_no_progress = any(
            _points_default(child.get("points"), f"rubric.children[{index}]") == 0
            and "none" in str(child.get("selection_signal", "")).lower()
            for index, child in enumerate(rubric.get("children", []))
            if isinstance(child, dict)
        )
        if not has_no_progress:
            warnings.append("rubric top-level one_of should include a no-progress regime")

    return ValidationResult(warnings=warnings)


def _validate_rubric_node(
    node: dict[str, Any],
    path: str,
    *,
    parent_id: Optional[str],
    seen: set[str],
    warnings: list[str],
    parent_is_satisfied_when: bool = False,
    parent_is_one_of: bool = False,
) -> None:
    node_id = _require_str(node.get("id"), f"{path}.id")
    _require_str(node.get("description"), f"{path}.description")

    if node_id in seen:
        raise RubricError(f"Duplicate rubric node id: {node_id}")
    seen.add(node_id)

    if parent_id is not None and not node_id.startswith(f"{parent_id}."):
        warnings.append(f"{path}.id does not follow parent dot-path convention")

    if parent_is_one_of:
        _require_str(node.get("selection_signal"), f"{path}.selection_signal")

    has_points = "points" in node
    if parent_is_satisfied_when and has_points:
        raise RubricError(f"{path}.points is not allowed under satisfied_when parent")
    if not parent_is_satisfied_when:
        if not has_points:
            raise RubricError(f"{path}.points is required")
        warnings.extend(validate_points(node.get("points"), path))

    guidelines = node.get("guidelines", [])
    if guidelines is not None:
        if not isinstance(guidelines, list) or not all(
            isinstance(item, str) for item in guidelines
        ):
            raise RubricError(f"{path}.guidelines must be a list of strings")

    shape = node_shape(node, path)
    children = node.get("children", [])

    if shape == "leaf":
        if children not in (None, []):
            raise RubricError(f"{path}.children must be absent or empty for a leaf")
        return

    if not isinstance(children, list) or not children:
        raise RubricError(f"{path}.children must be a non-empty list")

    for index, child in enumerate(children):
        if not isinstance(child, dict):
            raise RubricError(f"{path}.children[{index}] must be an object")

    if shape == "satisfied_when":
        _validate_satisfied_when(node["satisfied_when"], f"{path}.satisfied_when")
        for index, child in enumerate(children):
            _validate_rubric_node(
                child,
                f"{path}.children[{index}]",
                parent_id=node_id,
                seen=seen,
                warnings=warnings,
                parent_is_satisfied_when=True,
            )
        return

    combinator = node.get("combinator")
    if combinator not in {"sum", "one_of"}:
        raise RubricError(f"{path}.combinator must be 'sum' or 'one_of'")

    for index, child in enumerate(children):
        _validate_rubric_node(
            child,
            f"{path}.children[{index}]",
            parent_id=node_id,
            seen=seen,
            warnings=warnings,
            parent_is_one_of=combinator == "one_of",
        )

    parent_default = _points_default(node.get("points"), path)
    child_defaults = [
        _points_default(child.get("points"), f"{path}.children[{index}]")
        for index, child in enumerate(children)
    ]
    if combinator == "sum":
        child_sum = sum(child_defaults)
        if parent_default != child_sum:
            raise RubricError(
                f"{path}.points.default must equal sum of children defaults "
                f"({parent_default} != {child_sum})"
            )
    else:
        child_max = max(child_defaults)
        if parent_default < child_max:
            raise RubricError(
                f"{path}.points.default must be >= max child default "
                f"({parent_default} < {child_max})"
            )


def _validate_satisfied_when(value: Any, path: str) -> None:
    if value in {"all", "any"}:
        return
    if isinstance(value, dict):
        keys = set(value)
        if keys != {"count_at_least"}:
            raise RubricError(f"{path} object must only contain count_at_least")
        count = _require_int(value["count_at_least"], f"{path}.count_at_least")
        if count <= 0:
            raise RubricError(f"{path}.count_at_least must be positive")
        return
    raise RubricError(f"{path} must be 'all', 'any', or count_at_least object")


def compute_score(rubric: dict[str, Any], judgment: dict[str, Any]) -> int:
    validate_rubric(rubric)
    validate_judgment(rubric, judgment)
    return _compute_node_score(rubric, judgment, "judgment")


def validate_judgment(
    rubric: dict[str, Any], judgment: dict[str, Any]
) -> ValidationResult:
    validate_rubric(rubric)
    warnings: list[str] = []
    _validate_judgment_node(rubric, judgment, "judgment", warnings)
    return ValidationResult(warnings=warnings)


def _validate_judgment_node(
    rubric_node: dict[str, Any],
    judgment_node: Any,
    path: str,
    warnings: list[str],
) -> None:
    if not isinstance(judgment_node, dict):
        raise JudgmentError(f"{path} must be an object")

    rubric_id = rubric_node["id"]
    if judgment_node.get("id") != rubric_id:
        raise JudgmentError(
            f"{path}.id must match rubric node id {rubric_id!r}, "
            f"got {judgment_node.get('id')!r}"
        )
    _require_judgment_reasoning(judgment_node, path)

    shape = node_shape(rubric_node, f"rubric node {rubric_id}")
    points = rubric_node.get("points")

    if shape == "leaf":
        _validate_leaf_judgment(rubric_node, judgment_node, path)
        _validate_points_awarded(rubric_node, judgment_node, path)
        return

    if shape == "satisfied_when":
        _validate_atomic_judgment(rubric_node, judgment_node, path, warnings)
        _validate_points_awarded(rubric_node, judgment_node, path)
        return

    if "satisfied" in judgment_node:
        raise JudgmentError(f"{path}.satisfied is not allowed for combinator nodes")

    combinator = rubric_node["combinator"]
    if combinator == "sum":
        if "selected" in judgment_node:
            raise JudgmentError(f"{path}.selected is not allowed for sum nodes")
        children = judgment_node.get("children")
        rubric_children = rubric_node["children"]
        if not isinstance(children, list):
            raise JudgmentError(f"{path}.children must be a list")
        expected = [child["id"] for child in rubric_children]
        actual = [child.get("id") for child in children if isinstance(child, dict)]
        if actual != expected:
            raise JudgmentError(
                f"{path}.children must match rubric children {expected}, got {actual}"
            )
        for index, (rubric_child, judgment_child) in enumerate(
            zip(rubric_children, children)
        ):
            _validate_judgment_node(
                rubric_child, judgment_child, f"{path}.children[{index}]", warnings
            )
        _reject_points_awarded_for_fixed_or_composing(points, judgment_node, path)
        return

    if combinator == "one_of":
        children = judgment_node.get("children")
        selected = judgment_node.get("selected")
        if not isinstance(selected, str) or not selected:
            raise JudgmentError(f"{path}.selected must be a non-empty string")
        if not isinstance(children, list) or len(children) != 1:
            raise JudgmentError(f"{path}.children must contain exactly one child")

        rubric_children = {child["id"]: child for child in rubric_node["children"]}
        selected_rubric_child = rubric_children.get(selected)
        if selected_rubric_child is None:
            raise JudgmentError(f"{path}.selected does not name a rubric child")
        if not isinstance(children[0], dict) or children[0].get("id") != selected:
            raise JudgmentError(f"{path}.children[0].id must equal selected")

        reasoning = str(judgment_node.get("reasoning", "")).lower()
        signal = str(selected_rubric_child.get("selection_signal", "")).lower()
        if signal and not any(token in reasoning for token in signal.split()[:3]):
            warnings.append(
                f"{path}.reasoning may not ground selected regime in selection_signal"
            )

        _validate_judgment_node(
            selected_rubric_child, children[0], f"{path}.children[0]", warnings
        )
        _reject_points_awarded_for_fixed_or_composing(points, judgment_node, path)
        return

    raise JudgmentError(f"Unknown combinator: {combinator!r}")


def _require_judgment_reasoning(judgment_node: dict[str, Any], path: str) -> None:
    reasoning = judgment_node.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise JudgmentError(f"{path}.reasoning must be a non-empty string")


def _validate_leaf_judgment(
    rubric_node: dict[str, Any], judgment_node: dict[str, Any], path: str
) -> None:
    if not isinstance(judgment_node.get("satisfied"), bool):
        raise JudgmentError(f"{path}.satisfied must be boolean")
    if "selected" in judgment_node:
        raise JudgmentError(f"{path}.selected is not allowed for leaf nodes")
    if judgment_node.get("children") not in (None, []):
        raise JudgmentError(f"{path}.children is not allowed for leaf nodes")


def _validate_atomic_judgment(
    rubric_node: dict[str, Any],
    judgment_node: dict[str, Any],
    path: str,
    warnings: list[str],
) -> None:
    if "selected" in judgment_node:
        raise JudgmentError(f"{path}.selected is not allowed for satisfied_when nodes")
    if not isinstance(judgment_node.get("satisfied"), bool):
        raise JudgmentError(f"{path}.satisfied must be boolean")

    children = judgment_node.get("children")
    rubric_children = rubric_node["children"]
    if not isinstance(children, list):
        raise JudgmentError(f"{path}.children must be a list")
    expected = [child["id"] for child in rubric_children]
    actual = [child.get("id") for child in children if isinstance(child, dict)]
    if actual != expected:
        raise JudgmentError(
            f"{path}.children must match rubric children {expected}, got {actual}"
        )

    for index, (rubric_child, judgment_child) in enumerate(
        zip(rubric_children, children)
    ):
        _validate_judgment_node(
            rubric_child, judgment_child, f"{path}.children[{index}]", warnings
        )

    child_satisfaction = [child["satisfied"] for child in children]
    computed = _satisfaction_value(rubric_node["satisfied_when"], child_satisfaction)
    if judgment_node["satisfied"] != computed:
        raise JudgmentError(
            f"{path}.satisfied must equal satisfied_when result {computed}"
        )


def _satisfaction_value(condition: Any, values: list[bool]) -> bool:
    if condition == "all":
        return all(values)
    if condition == "any":
        return any(values)
    if isinstance(condition, dict) and "count_at_least" in condition:
        return sum(values) >= int(condition["count_at_least"])
    raise JudgmentError(f"Invalid satisfied_when condition: {condition!r}")


def _validate_points_awarded(
    rubric_node: dict[str, Any], judgment_node: dict[str, Any], path: str
) -> None:
    points = rubric_node.get("points")
    contributes = bool(judgment_node.get("satisfied"))

    if _is_range_points(points):
        if contributes:
            if "points_awarded" not in judgment_node:
                raise JudgmentError(f"{path}.points_awarded is required")
            awarded = _require_int(judgment_node["points_awarded"], f"{path}.points_awarded")
            values = _range_values(points, f"rubric node {rubric_node['id']}")
            if awarded not in values:
                raise JudgmentError(
                    f"{path}.points_awarded must be one of {sorted(values)}"
                )
        elif "points_awarded" in judgment_node:
            raise JudgmentError(
                f"{path}.points_awarded is not allowed when node is not satisfied"
            )
    elif "points_awarded" in judgment_node:
        raise JudgmentError(f"{path}.points_awarded is only allowed for range points")


def _reject_points_awarded_for_fixed_or_composing(
    points: Optional[PointSpec], judgment_node: dict[str, Any], path: str
) -> None:
    if "points_awarded" in judgment_node:
        raise JudgmentError(f"{path}.points_awarded is not allowed for composing nodes")


def _compute_node_score(
    rubric_node: dict[str, Any], judgment_node: dict[str, Any], path: str
) -> int:
    shape = node_shape(rubric_node, f"rubric node {rubric_node['id']}")
    points = rubric_node.get("points")

    if shape in {"leaf", "satisfied_when"}:
        if not judgment_node["satisfied"]:
            return 0
        if _is_range_points(points):
            return int(judgment_node["points_awarded"])
        return _points_default(points, f"rubric node {rubric_node['id']}")

    if rubric_node["combinator"] == "sum":
        return sum(
            _compute_node_score(rubric_child, judgment_child, f"{path}.children[{index}]")
            for index, (rubric_child, judgment_child) in enumerate(
                zip(rubric_node["children"], judgment_node["children"])
            )
        )

    selected = judgment_node["selected"]
    selected_rubric_child = next(
        child for child in rubric_node["children"] if child["id"] == selected
    )
    return _compute_node_score(
        selected_rubric_child, judgment_node["children"][0], f"{path}.children[0]"
    )


def cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def xml_block(tag: str, content: str) -> str:
    return f"<{tag}>{cdata(content)}</{tag}>"


def make_required_judgment_schema(rubric: dict[str, Any]) -> dict[str, Any]:
    validate_rubric(rubric)
    return _judgment_schema_for_node(rubric)


def _judgment_schema_for_node(rubric_node: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": rubric_node["id"],
        "reasoning": "Brief node-specific grading rationale.",
    }
    shape = node_shape(rubric_node, f"rubric node {rubric_node['id']}")

    if shape == "leaf":
        base["satisfied"] = "true | false"
        if _is_range_points(rubric_node.get("points")):
            base["points_awarded"] = "Required if satisfied; one rubric scale value."
        return base

    if shape == "satisfied_when":
        base["satisfied"] = "true | false; must match satisfied_when over children"
        if _is_range_points(rubric_node.get("points")):
            base["points_awarded"] = "Required if satisfied; one rubric scale value."
        base["children"] = [
            _judgment_schema_for_node(child) for child in rubric_node["children"]
        ]
        return base

    if rubric_node["combinator"] == "sum":
        base["children"] = [
            _judgment_schema_for_node(child) for child in rubric_node["children"]
        ]
        return base

    base["selected"] = "ID of exactly one selected child regime"
    base["children"] = ["Judgment for selected child only"]
    return base


def format_rubric_for_prompt(rubric: dict[str, Any]) -> str:
    validate_rubric(rubric)
    return json.dumps(rubric, indent=2, ensure_ascii=False)


def format_output_schema_for_prompt(rubric: dict[str, Any]) -> str:
    return json.dumps(make_required_judgment_schema(rubric), indent=2, ensure_ascii=False)


def build_grading_prompt(
    *,
    problem: str,
    reference_solution: str,
    candidate_solution: str,
    rubric: dict[str, Any],
) -> str:
    rubric_json = format_rubric_for_prompt(rubric)
    schema_json = format_output_schema_for_prompt(rubric)
    grading_prompt_md = (_REPO_ROOT / "grading_prompt.md").read_text().strip()
    return f"""{grading_prompt_md}

---

{xml_block("problem_statement", problem)}

{xml_block("reference_solution", reference_solution)}

{xml_block("rubric_json", rubric_json)}

{xml_block("candidate_solution", candidate_solution)}

{xml_block("required_judgment_schema", schema_json)}
""".strip()


def build_prompt(
    *,
    problem: str,
    reference_solution: str,
    candidate_solution: str,
    rubric: dict[str, Any],
) -> str:
    return build_grading_prompt(
        problem=problem,
        reference_solution=reference_solution,
        candidate_solution=candidate_solution,
        rubric=rubric,
    )


def extract_first_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.I | re.S)
    if fence:
        candidate = fence.group(1).strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    if start == -1:
        raise ModelOutputError("No JSON object found in model output")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        raise ModelOutputError(f"Malformed JSON object: {exc}") from exc
                    if not isinstance(parsed, dict):
                        raise ModelOutputError("Model output JSON must be an object")
                    return parsed

    raise ModelOutputError("Could not find a balanced JSON object")




def repair_common_judgment_model_errors(
    rubric: dict[str, Any], judgment: dict[str, Any]
) -> dict[str, Any]:
    """Repair common LLM judgment formatting misses before strict validation."""
    repaired = json.loads(json.dumps(judgment))

    def coerce_bool(value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower in {"true", "yes", "satisfied", "earned"}:
                return True
            if lower in {"false", "no", "not satisfied", "not_earned", "not earned"}:
                return False
        return value

    def walk(rubric_node: dict[str, Any], judgment_node: dict[str, Any]) -> None:
        if "satisfied" in judgment_node:
            judgment_node["satisfied"] = coerce_bool(judgment_node["satisfied"])

        shape = node_shape(rubric_node, f"rubric node {rubric_node.get('id')}")
        points = rubric_node.get("points")
        if not _is_range_points(points) and "points_awarded" in judgment_node:
            judgment_node.pop("points_awarded", None)


        if shape == "leaf":
            return

        if shape == "satisfied_when":
            rubric_children = rubric_node.get("children", [])
            judgment_children = judgment_node.get("children", [])
            if isinstance(judgment_children, list):
                by_id = {child.get("id"): child for child in judgment_children if isinstance(child, dict)}
                for child in rubric_children:
                    match = by_id.get(child.get("id"))
                    if isinstance(match, dict):
                        walk(child, match)
                if "satisfied" not in judgment_node:
                    values = [
                        child.get("satisfied")
                        for child in judgment_children
                        if isinstance(child, dict)
                    ]
                    if values and all(isinstance(value, bool) for value in values):
                        judgment_node["satisfied"] = _satisfaction_value(
                            rubric_node["satisfied_when"], values
                        )
            return

        if rubric_node.get("combinator") == "sum":
            rubric_children = rubric_node.get("children", [])
            judgment_children = judgment_node.get("children", [])
            if isinstance(judgment_children, list):
                by_id = {child.get("id"): child for child in judgment_children if isinstance(child, dict)}
                for child in rubric_children:
                    match = by_id.get(child.get("id"))
                    if isinstance(match, dict):
                        walk(child, match)
            return

        if rubric_node.get("combinator") == "one_of":
            selected = judgment_node.get("selected")
            selected_rubric = None
            for child in rubric_node.get("children", []):
                if child.get("id") == selected:
                    selected_rubric = child
                    break
            judgment_children = judgment_node.get("children", [])
            if selected_rubric and isinstance(judgment_children, list) and judgment_children:
                if isinstance(judgment_children[0], dict):
                    walk(selected_rubric, judgment_children[0])

    walk(rubric, repaired)
    return repaired

def grade_from_model_output(
    *,
    rubric: dict[str, Any],
    raw_model_output: str,
) -> dict[str, Any]:
    judgment = extract_first_json_object(raw_model_output)
    judgment = repair_common_judgment_model_errors(rubric, judgment)
    validation = validate_judgment(rubric, judgment)
    computed_score = compute_score(rubric, judgment)
    declared_score = _extract_declared_score(judgment)
    return {
        "computed_score": computed_score,
        "model_declared_score": declared_score,
        "score_consistent": (
            None if declared_score is None else declared_score == computed_score
        ),
        "judgment": judgment,
        "validation_warnings": validation.warnings,
        "raw_model_output": raw_model_output,
    }


def _extract_declared_score(judgment: dict[str, Any]) -> Optional[int]:
    for key in ("final_score", "score", "computed_score"):
        if key not in judgment:
            continue
        try:
            return int(judgment[key])
        except (TypeError, ValueError):
            continue
    summary = judgment.get("score_summary")
    if isinstance(summary, dict):
        for key in ("final_score", "score", "computed_score"):
            if key not in summary:
                continue
            try:
                return int(summary[key])
            except (TypeError, ValueError):
                continue
    return None



def build_rubric_generation_prompt(
    *,
    problem_id: str,
    problem: str,
    source_grading_scheme: Any,
    sample_solution: str = "",
    max_points: int = 7,
) -> str:
    """Build a prompt that asks an LLM to translate a source rubric to JSON."""
    if not isinstance(source_grading_scheme, str):
        source_grading_scheme_text = json.dumps(
            source_grading_scheme, indent=2, ensure_ascii=False
        )
    else:
        source_grading_scheme_text = source_grading_scheme

    translation_prompt_md = (_REPO_ROOT / "translation_prompt.md").read_text().strip()
    rubric_requirements = (
        f"Rubric id (use this as the root `id` and the prefix for all dot-path child ids): {problem_id!r}\n"
        f"Total points (rubric root `points`): {max_points}"
    )

    return f"""{translation_prompt_md}

---

{xml_block("problem_statement", problem)}

{xml_block("sample_solution", sample_solution)}

{xml_block("source_grading_scheme", source_grading_scheme_text)}

{xml_block("rubric_requirements", rubric_requirements)}
""".strip()




def repair_common_rubric_model_errors(rubric: dict[str, Any]) -> dict[str, Any]:
    """Repair common LLM formatting misses without changing scoring intent.

    This is intentionally conservative: it fills fields that can be inferred
    directly from local node data, then strict validation still decides whether
    the rubric is usable.
    """
    repaired = json.loads(json.dumps(rubric))
    def walk(node: dict[str, Any], parent_id: str | None = None, index: int = 0) -> None:
        if not node.get("id") and parent_id:
            node["id"] = f"{parent_id}.node_{index}"
        if not node.get("description"):
            node["description"] = str(
                node.get("selection_signal") or node.get("title") or node.get("id")
            )
        if isinstance(node.get("guidelines"), str):
            node["guidelines"] = [
                line.strip(" -")
                for line in node["guidelines"].splitlines()
                if line.strip(" -")
            ]
        children = node.get("children")
        if isinstance(children, list):
            for child_index, child in enumerate(children):
                if isinstance(child, dict):
                    walk(child, node.get("id"), child_index)
        if "points" not in node and node.get("combinator") in {"sum", "one_of"} and isinstance(children, list):
            values: list[int] = []
            for child in children:
                if not isinstance(child, dict) or "points" not in child:
                    return
                points = child["points"]
                if isinstance(points, int) and not isinstance(points, bool):
                    values.append(points)
                elif isinstance(points, dict) and isinstance(points.get("default"), int):
                    values.append(points["default"])
                else:
                    return
            if node.get("combinator") == "sum":
                node["points"] = sum(values)
            elif values:
                node["points"] = max(values)

    walk(repaired)
    return repaired

def rubric_from_model_output(raw_model_output: str) -> dict[str, Any]:
    """Parse, conservatively repair, and validate a model-produced rubric."""
    rubric = extract_first_json_object(raw_model_output)
    rubric = repair_common_rubric_model_errors(rubric)
    validate_rubric(rubric)
    return rubric
