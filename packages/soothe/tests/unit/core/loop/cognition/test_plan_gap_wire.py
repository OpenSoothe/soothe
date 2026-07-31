"""Tests for PlanGapAnalysis wire coercion (IG-593)."""

from __future__ import annotations

import jsonschema
import pytest

from soothe.sloop.cognition.plan_gap_wire import (
    coerce_goal_component_status_dict,
    coerce_plan_gap_analysis_wire_dict,
)
from soothe.sloop.state.schemas import PlanGapAnalysis


def test_coerce_name_alias_to_component() -> None:
    raw = {
        "components": [
            {
                "name": "Public API Health Response",
                "status": "partial",
                "evidence": "401 on health",
                "gap": "HTTP 403 on port 80",
            },
            {
                "component": "ECS upstream path",
                "status": "satisfied",
                "evidence": "tailnet OK",
                "gap": "",
            },
        ],
        "evidence_summary": "Public HTTPS works; HTTP redirect blocked.",
        "remaining_gaps": ["document ICP redirect gap"],
        "distance_from_goal": "near",
        "gap_reasoning": "Core readiness verified; residual gap is non-blocking.",
    }
    coerced = coerce_plan_gap_analysis_wire_dict(raw)
    assert coerced["components"][0]["component"] == "Public API Health Response"
    assert "name" not in coerced["components"][0]
    assert coerced["components"][1]["component"] == "ECS upstream path"
    schema = PlanGapAnalysis.model_json_schema()
    jsonschema.validate(instance=coerced, schema=schema)
    gap = PlanGapAnalysis(**coerced)
    assert gap.components[0].component == "Public API Health Response"


def test_component_field_wins_over_alias() -> None:
    coerced = coerce_goal_component_status_dict(
        {"component": "canonical", "name": "alias-should-drop", "status": "partial"}
    )
    assert coerced["component"] == "canonical"
    assert "name" not in coerced


@pytest.mark.parametrize("alias_key", ["name", "title", "label"])
def test_e217_style_payload_validates_after_coerce(alias_key: str) -> None:
    """Reproduction of loop e217: alias instead of ``component`` on item [4]."""
    components = [
        {"component": f"c{i}", "status": "satisfied", "evidence": "", "gap": ""} for i in range(4)
    ]
    components.append(
        {
            alias_key: "Public API Health Response",
            "status": "partial",
            "evidence": "401 expected",
            "gap": "HTTP 403",
        }
    )
    raw = {
        "components": components,
        "evidence_summary": "summary",
        "remaining_gaps": ["redirect"],
        "distance_from_goal": "near",
        "gap_reasoning": "near complete",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=raw, schema=PlanGapAnalysis.model_json_schema())

    coerced = coerce_plan_gap_analysis_wire_dict(raw)
    jsonschema.validate(instance=coerced, schema=PlanGapAnalysis.model_json_schema())
    PlanGapAnalysis(**coerced)


def test_missing_component_synthesized_from_evidence() -> None:
    """Loop 0d7a: components[] often omit ``component`` and only send status+evidence."""
    raw = {
        "components": [
            {
                "status": "satisfied",
                "evidence": "Ledger confirms patch versions bumped and tagged for all clients.",
            }
        ],
        "evidence_summary": "All client patch releases committed and tagged.",
        "remaining_gaps": [],
        "distance_from_goal": "near",
        "gap_reasoning": "Version bumps complete; optional push remains.",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=raw, schema=PlanGapAnalysis.model_json_schema())

    coerced = coerce_plan_gap_analysis_wire_dict(raw)
    jsonschema.validate(instance=coerced, schema=PlanGapAnalysis.model_json_schema())
    gap = PlanGapAnalysis(**coerced)
    assert gap.components[0].component.startswith("Ledger confirms")
    assert gap.components[0].status == "satisfied"


def test_overlong_fields_and_status_aliases_are_clipped() -> None:
    raw = {
        "components": [
            {
                "status": "done",
                "evidence": "e" * 3000,
                "gap": "g" * 3000,
            }
        ],
        "evidence_summary": "s" * 3000,
        "remaining_gaps": ["r" * 3000, "keep", "x", "y", "z", "a", "drop-me"],
        "distance_from_goal": "close",
        "gap_reasoning": "r" * 3000,
    }
    coerced = coerce_plan_gap_analysis_wire_dict(raw)
    jsonschema.validate(instance=coerced, schema=PlanGapAnalysis.model_json_schema())
    gap = PlanGapAnalysis(**coerced)
    assert gap.components[0].status == "satisfied"
    assert gap.distance_from_goal == "near"
    assert len(gap.components[0].evidence) <= 2048
    assert len(gap.evidence_summary) <= 2048
    assert len(gap.remaining_gaps) <= 6
