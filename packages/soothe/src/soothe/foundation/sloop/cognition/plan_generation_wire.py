"""Minimal plan-generate wire schema and adapter (IG-568).

LLMs emit ``PlanGenerationWire``; ``plan_generation_wire_to_model`` builds runtime
``PlanGeneration`` with derived ``type``, ``execution_mode``, and step routing.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from soothe.foundation.sloop.state.schemas import (
    DEFAULT_MAX_PLAN_STEPS_PER_WAVE,
    PlanGenerateStep,
    PlanGeneration,
    resolve_step_wire_subagent,
)

_WIRE_PSEUDO_STEP_TOKENS = frozenset(
    {"execution_mode", "reasoning", "type", "adaptive_granularity"}
)


class PlanGenerateStepWire(BaseModel):
    """Single plan-generate step in LLM wire output."""

    id: str | None = None
    description: str = Field(..., description="Milestone summary under 20 words.")
    expected_output: str = Field(
        default="Step completed successfully",
        description="Checkable completion signal.",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="In-wave or cross-wave step ids; use [] when none.",
    )
    delegate: str | None = Field(
        default=None,
        description="Optional subagent name when this step should delegate.",
    )


class PlanClarifyWire(BaseModel):
    """Clarification-only plan wave (replaces ask_user step in steps[])."""

    questions: list[str] = Field(..., min_length=1)


class PlanGenerationWire(BaseModel):
    """LLM-facing plan-generate structured output."""

    reasoning: str = Field(
        default="",
        max_length=500,
        description="First-person plan rationale for the cognition card.",
    )
    steps: list[PlanGenerateStepWire] = Field(default_factory=list)
    clarify: PlanClarifyWire | None = None

    @model_validator(mode="after")
    def _validate_wire_shape(self) -> PlanGenerationWire:
        has_clarify = self.clarify is not None and bool(self.clarify.questions)
        has_steps = bool(self.steps)
        if has_clarify and has_steps:
            msg = "clarify and non-empty steps are mutually exclusive"
            raise ValueError(msg)
        if not has_clarify and not has_steps:
            msg = "plan requires non-empty steps or clarify.questions"
            raise ValueError(msg)
        return self


def _normalize_dependency_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = str(item).strip()
        if not token or token in seen:
            continue
        out.append(token)
        seen.add(token)
    return out


def _salvage_steps_array(steps_raw: Any) -> list[Any]:
    """Drop pseudo-field strings and keep step objects from a malformed steps list."""
    if not isinstance(steps_raw, list):
        return []
    kept: list[Any] = []
    for item in steps_raw:
        if isinstance(item, dict):
            kept.append(item)
            continue
        if isinstance(item, str):
            if item.strip().lower() in _WIRE_PSEUDO_STEP_TOKENS:
                continue
            continue
    return kept


def _legacy_ask_user_to_clarify(steps: list[Any]) -> dict[str, Any] | None:
    """Convert a lone legacy ask_user step into wire clarify shape."""
    if len(steps) != 1:
        return None
    only = steps[0]
    if not isinstance(only, dict):
        return None
    if only.get("kind") != "ask_user":
        return None
    questions = only.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    return {"questions": [str(q).strip() for q in questions if str(q).strip()]}


def coerce_plan_generation_wire_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Salvage glm-style malformations and legacy PlanGeneration dicts for wire validation."""
    if not isinstance(data, dict):
        return data

    reasoning = str(data.get("reasoning") or "").strip()
    clarify_raw = data.get("clarify")
    if isinstance(clarify_raw, dict) and clarify_raw.get("questions"):
        questions = [str(q).strip() for q in clarify_raw.get("questions", []) if str(q).strip()]
        if questions:
            return {"reasoning": reasoning, "steps": [], "clarify": {"questions": questions}}

    steps_salvaged = _salvage_steps_array(data.get("steps"))
    legacy_clarify = _legacy_ask_user_to_clarify(steps_salvaged)
    if legacy_clarify is not None:
        return {"reasoning": reasoning, "steps": [], "clarify": legacy_clarify}

    wire_steps: list[dict[str, Any]] = []
    for index, item in enumerate(steps_salvaged):
        if not isinstance(item, dict):
            continue
        step_id = item.get("id")
        if step_id is not None:
            step_id = str(step_id).strip() or None
        if step_id is None:
            step_id = f"{index + 1:02d}"
        deps = _normalize_dependency_list(item.get("dependencies"))
        if not deps and item.get("continues_from"):
            deps = _normalize_dependency_list(item.get("continues_from"))
        delegate = item.get("delegate")
        if delegate is None and item.get("execution_hint") == "subagent":
            delegate = item.get("subagent")
        wire_steps.append(
            {
                "id": step_id,
                "description": str(item.get("description") or "").strip(),
                "expected_output": str(
                    item.get("expected_output") or "Step completed successfully"
                ).strip(),
                "dependencies": deps,
                "delegate": str(delegate).strip() if delegate else None,
            }
        )

    return {"reasoning": reasoning, "steps": wire_steps}


def _execution_mode_from_wire_steps(
    steps: list[PlanGenerateStepWire],
) -> Literal["parallel", "dependency"]:
    if any(step.dependencies for step in steps):
        return "dependency"
    return "parallel"


def plan_generation_wire_to_model(wire: PlanGenerationWire) -> PlanGeneration:
    """Adapt wire LLM output to runtime ``PlanGeneration``."""
    if wire.clarify is not None:
        questions = [q.strip() for q in wire.clarify.questions if q.strip()]
        return PlanGeneration(
            type="execute_steps",
            execution_mode="parallel",
            reasoning=wire.reasoning or "",
            steps=[
                PlanGenerateStep(
                    id="01",
                    description="Clarification needed",
                    kind="ask_user",
                    questions=questions,
                    dependencies=[],
                )
            ],
        )

    plan_steps: list[PlanGenerateStep] = []
    for index, step in enumerate(wire.steps):
        step_id = (step.id or "").strip() or f"{index + 1:02d}"
        deps = _normalize_dependency_list(step.dependencies) or None
        execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
        subagent: str | None = None
        delegate = (step.delegate or "").strip()
        if delegate and resolve_step_wire_subagent(execution_hint="subagent", subagent=delegate):
            execution_hint = "subagent"
            subagent = delegate
        plan_steps.append(
            PlanGenerateStep(
                id=step_id,
                description=step.description,
                expected_output=step.expected_output or "Step completed successfully",
                dependencies=deps,
                execution_hint=execution_hint,
                subagent=subagent,
            )
        )

    return PlanGeneration(
        type="execute_steps",
        execution_mode=_execution_mode_from_wire_steps(wire.steps),
        reasoning=wire.reasoning or "",
        steps=plan_steps,
    )


def capped_plan_generation_wire_model(
    max_steps: int = DEFAULT_MAX_PLAN_STEPS_PER_WAVE,
) -> type[PlanGenerationWire]:
    """Structured-output schema for plan-generate, capped per wave."""

    class PlanGenerationWireCapped(PlanGenerationWire):
        steps: list[PlanGenerateStepWire] = Field(default_factory=list, max_length=max_steps)

    return PlanGenerationWireCapped


__all__ = [
    "PlanClarifyWire",
    "PlanGenerateStepWire",
    "PlanGenerationWire",
    "capped_plan_generation_wire_model",
    "coerce_plan_generation_wire_dict",
    "plan_generation_wire_to_model",
]
