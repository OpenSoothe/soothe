"""Populate missing plan-generate step briefs when the LLM omits ``full_description``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.sloop.vision_context import (
    extract_vision_summary,
    format_image_facts_for_brief,
)

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import PlanGenerateStep, PlanGeneration


def _needs_full_description(step: PlanGenerateStep) -> bool:
    """Return True when ``full_description`` should be synthesized."""
    if step.kind == "ask_user":
        return False
    full = (step.full_description or "").strip()
    if not full:
        return True
    if full == (step.description or "").strip():
        return True
    return len(full.split()) < 12


def synthesize_full_description(
    step: PlanGenerateStep,
    *,
    vision_summary: str | None = None,
) -> str:
    """Build a step-local execution brief without referencing the overall goal (IG-508).

    When ``vision_summary`` is set (IG-674), append capped image facts so execute
    briefs retain vision-preflight detail without restating the parent GOAL.
    """
    desc = (step.description or "").strip()
    expected = (step.expected_output or "").strip()
    parts: list[str] = []
    if desc:
        parts.append(desc)
    if expected:
        parts.append(f"Deliverable: {expected.rstrip('.')}.")
    deps = step.dependencies or []
    if deps:
        dep_ids = ", ".join(deps)
        parts.append(
            f"Use output from step(s) {dep_ids}; do NOT repeat those steps' discovery actions."
        )
    parts.append(
        "Execute independently with available tools and workspace paths (docs/, packages/, etc.)."
    )
    if (vision_summary or "").strip():
        facts = format_image_facts_for_brief(vision_summary)
        if facts:
            parts.append(facts)
    return " ".join(parts)


def populate_plan_generate_full_descriptions(
    plan_result: PlanGeneration,
    *,
    goal: str | None = None,
) -> PlanGeneration:
    """Ensure every action step has a concrete ``full_description``.

    Args:
        plan_result: Plan-generate structured result.
        goal: Optional planning goal (may include daemon vision preflight block).
    """
    if not plan_result.steps:
        return plan_result
    vision = extract_vision_summary(goal or "") if goal else None
    updated: list = []
    changed = False
    for step in plan_result.steps:
        if not _needs_full_description(step):
            updated.append(step)
            continue
        brief = synthesize_full_description(step, vision_summary=vision)
        updated.append(step.model_copy(update={"full_description": brief}))
        changed = True
    if not changed:
        return plan_result
    return plan_result.model_copy(update={"steps": updated})
