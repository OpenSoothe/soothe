"""Tests for plan-generate wire schema and adapter (IG-568)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe.sloop.cognition.plan_generation_wire import (
    PlanGenerationWire,
    capped_plan_generation_wire_model,
    coerce_plan_generation_wire_dict,
    plan_generation_wire_to_model,
)
from soothe.sloop.state.schemas import DEFAULT_MAX_PLAN_STEPS_PER_WAVE, PlanGeneration


def test_wire_schema_requires_dependencies_on_steps() -> None:
    wire = PlanGenerationWire(
        steps=[
            {
                "description": "Fetch Shanghai weather",
                "expected_output": "Weather report",
                "dependencies": [],
            }
        ],
    )
    plan = plan_generation_wire_to_model(wire)
    assert plan.type == "execute_steps"
    assert plan.execution_mode == "parallel"
    assert len(plan.steps) == 1
    assert plan.steps[0].dependencies is None


def test_wire_dependencies_set_execution_mode_dependency() -> None:
    wire = PlanGenerationWire(
        steps=[
            {
                "id": "01",
                "description": "Fetch data",
                "expected_output": "Raw data",
                "dependencies": [],
            },
            {
                "id": "02",
                "description": "Format report",
                "expected_output": "Report",
                "dependencies": ["01"],
            },
        ],
    )
    plan = plan_generation_wire_to_model(wire)
    assert plan.execution_mode == "dependency"
    assert plan.steps[1].dependencies == ["01"]


def test_wire_clarify_maps_to_ask_user_step() -> None:
    wire = PlanGenerationWire(
        steps=[],
        clarify={"questions": ["Which format should I use?"]},
    )
    plan = plan_generation_wire_to_model(wire)
    assert len(plan.steps) == 1
    assert plan.steps[0].kind == "ask_user"
    assert plan.steps[0].questions == ["Which format should I use?"]


def test_wire_empty_steps_maps_to_final_plan() -> None:
    wire = PlanGenerationWire(
        steps=[],
    )
    plan = plan_generation_wire_to_model(wire)
    assert plan.type == "final"
    assert plan.steps == []


def test_coerce_salvages_pseudo_fields_in_steps_array() -> None:
    raw = {
        "reasoning": "I'll fetch weather.",
        "steps": [
            {
                "id": "01",
                "description": "Fetch Shanghai weather",
                "expected_output": "Weather",
                "dependencies": [],
            },
            "execution_mode",
            "reasoning",
        ],
    }
    coerced = coerce_plan_generation_wire_dict(raw)
    assert "reasoning" not in coerced
    wire = PlanGenerationWire.model_validate(coerced)
    plan = plan_generation_wire_to_model(wire)
    assert len(plan.steps) == 1
    assert plan.steps[0].description == "Fetch Shanghai weather"


def test_coerce_legacy_ask_user_step_to_clarify() -> None:
    raw = {
        "type": "execute_steps",
        "reasoning": "Need input.",
        "steps": [
            {
                "id": "01",
                "description": "Ask",
                "kind": "ask_user",
                "questions": ["Which city?"],
            }
        ],
    }
    coerced = coerce_plan_generation_wire_dict(raw)
    assert "reasoning" not in coerced
    wire = PlanGenerationWire.model_validate(coerced)
    assert wire.clarify is not None
    assert wire.steps == []


def test_wire_rejects_clarify_and_steps_together() -> None:
    with pytest.raises(ValidationError):
        PlanGenerationWire(
            steps=[
                {
                    "description": "Do work",
                    "dependencies": [],
                }
            ],
            clarify={"questions": ["Which?"]},
        )


def test_coerced_malformed_glm_sample_validates() -> None:
    """Regression for glm-5 putting reasoning/execution_mode inside steps[]."""
    raw = {
        "reasoning": "I'll look up Shanghai weather.",
        "steps": [
            {
                "id": "01",
                "description": "Fetch Shanghai current weather",
                "full_description": "ignored by wire",
                "expected_output": "Weather report",
                "kind": "action",
            },
            "execution_mode",
            "reasoning",
        ],
    }
    coerced = coerce_plan_generation_wire_dict(raw)
    wire = PlanGenerationWire.model_validate(coerced)
    plan: PlanGeneration = plan_generation_wire_to_model(wire)
    assert plan.type == "execute_steps"
    assert len(plan.steps) == 1


def test_capped_wire_schema_rejects_over_max_steps() -> None:
    schema = capped_plan_generation_wire_model()
    steps = [
        {
            "description": f"step {i}",
            "expected_output": "ok",
            "dependencies": [],
        }
        for i in range(DEFAULT_MAX_PLAN_STEPS_PER_WAVE + 1)
    ]
    with pytest.raises(ValidationError):
        schema(steps=steps)


def test_capped_wire_schema_accepts_ten_steps() -> None:
    schema = capped_plan_generation_wire_model()
    wire = schema(
        steps=[
            {
                "id": f"{i:02d}",
                "description": f"step {i}",
                "expected_output": "ok",
                "dependencies": [],
            }
            for i in range(DEFAULT_MAX_PLAN_STEPS_PER_WAVE)
        ],
    )
    assert len(wire.steps) == DEFAULT_MAX_PLAN_STEPS_PER_WAVE


def test_wire_schema_excludes_runtime_only_fields() -> None:
    props = capped_plan_generation_wire_model().model_json_schema()["properties"]
    assert "type" not in props
    assert "execution_mode" not in props
    assert "plan_action" not in props
    assert "reasoning" not in props
