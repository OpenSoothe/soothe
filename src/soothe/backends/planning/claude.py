"""ClaudePlanner -- PlannerProtocol via compiled Claude subagent graph."""

from __future__ import annotations

import logging
import os
import re
import shutil
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from soothe.protocols.planner import (
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_PLANNING_SYSTEM_PROMPT = """\
You are a senior technical architect and planning specialist.

Your sole job is to produce a structured, actionable plan for the given goal.
Analyse requirements, identify dependencies, estimate effort, and define
verification criteria for each step.

Output format -- use this exact structure for every step:

**Step N: Title**
- **Description**: What to do.
- **Rationale**: Why this step matters.
- **Dependencies**: Which prior steps must complete first.
- **Verification**: How to confirm the step is done.
- **Effort**: small / medium / large.

End with a brief summary of total effort, key risks, and prerequisites.
Do NOT implement anything -- only plan.
"""

_PLAN_STEP_RE = re.compile(r"\*\*Step\s+(\d+)[:\s]*(.+?)\*\*", re.IGNORECASE)


def _check_claude_available() -> None:
    """Validate that the Claude CLI and required env vars are present.

    Raises:
        RuntimeError: If ``claude`` CLI is not found or ``ANTHROPIC_API_KEY``
            is not set.
    """
    if not shutil.which("claude"):
        raise RuntimeError(
            "Claude CLI ('claude') not found on PATH. Install it: npm install -g @anthropic-ai/claude-code"
        )
    has_key = any(k.startswith("ANTHROPIC_") for k in os.environ)
    if not has_key:
        raise RuntimeError(
            "No ANTHROPIC_ environment variables found. Set ANTHROPIC_API_KEY to use the Claude planner."
        )


def _parse_plan_from_text(goal: str, text: str) -> Plan:
    """Extract a Plan from Claude's markdown output."""
    steps: list[PlanStep] = []
    matches = _PLAN_STEP_RE.findall(text)
    for i, (num, title) in enumerate(matches, 1):
        steps.append(PlanStep(id=f"step_{i}", description=title.strip()))
    if not steps:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:10], 1):
            cleaned = re.sub(r"^[\d\-\*\.]+\s*", "", line)
            if cleaned and len(cleaned) > 5:
                steps.append(PlanStep(id=f"step_{i}", description=cleaned))
    if not steps:
        steps = [PlanStep(id="step_1", description=goal)]
    return Plan(goal=goal, steps=steps)


class ClaudePlanner:
    """PlannerProtocol via compiled Claude subagent graph.

    Reuses ``create_claude_subagent()`` with a planning-focused system prompt.
    Validates Claude CLI availability and ANTHROPIC_ env vars at init.

    Args:
        cwd: Working directory for the Claude CLI.

    Raises:
        RuntimeError: If Claude CLI or ANTHROPIC_ env vars are missing.
    """

    def __init__(self, cwd: str | None = None) -> None:
        _check_claude_available()

        from soothe.subagents.claude import create_claude_subagent

        spec = create_claude_subagent(
            system_prompt=_PLANNING_SYSTEM_PROMPT,
            max_turns=10,
            cwd=cwd,
        )
        self._runnable = spec["runnable"]
        self._call_count = 0

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan by invoking Claude with a planning prompt."""
        prompt = self._build_prompt(goal, context)
        try:
            text = await self._invoke(prompt)
            return _parse_plan_from_text(goal, text)
        except Exception:
            logger.warning("ClaudePlanner create_plan failed", exc_info=True)
            return Plan(goal=goal, steps=[PlanStep(id="step_1", description=goal)])

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan via Claude."""
        prompt = (
            f"Revise this plan based on feedback.\n\n"
            f"Goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan using the **Step N: Title** format."
        )
        try:
            text = await self._invoke(prompt)
            revised = _parse_plan_from_text(plan.goal, text)
            revised.status = "revised"
            return revised
        except Exception:
            logger.warning("ClaudePlanner revise_plan failed", exc_info=True)
            return plan

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Simple reflection based on step outcomes."""
        completed = sum(1 for r in step_results if r.success)
        failed = sum(1 for r in step_results if not r.success)
        total = len(plan.steps)
        if failed > 0:
            return Reflection(
                assessment=f"{completed}/{total} steps completed, {failed} failed",
                should_revise=True,
                feedback=f"Steps failed: {[r.step_id for r in step_results if not r.success]}",
            )
        return Reflection(
            assessment=f"{completed}/{total} steps completed successfully",
            should_revise=False,
            feedback="",
        )

    async def _invoke(self, prompt: str) -> str:
        """Run the compiled Claude graph and extract final response."""
        self._call_count += 1
        result = await self._runnable.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
        )
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _build_prompt(self, goal: str, context: PlanContext) -> str:
        parts = [f"Create a detailed, structured plan for this goal:\n\n{goal}"]
        if context.available_capabilities:
            parts.append(f"Available capabilities: {', '.join(context.available_capabilities)}")
        if context.completed_steps:
            parts.append(f"Already completed: {[s.step_id for s in context.completed_steps]}")
        parts.append(
            "Produce a numbered plan with **Step N: Title** format. "
            "Include description, rationale, dependencies, verification, and effort."
        )
        return "\n\n".join(parts)
