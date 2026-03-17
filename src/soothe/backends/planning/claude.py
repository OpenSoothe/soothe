"""ClaudePlanner -- PlannerProtocol via compiled Claude subagent graph."""

from __future__ import annotations

import logging
import os
import re
import shutil

from langchain_core.messages import AIMessage, HumanMessage

from soothe.protocols.planner import (
    Plan,
    PlanContext,
    PlanStep,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_MIN_STEP_DESCRIPTION_LENGTH = 5

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
        msg = "Claude CLI ('claude') not found on PATH. Install it: npm install -g @anthropic-ai/claude-code"
        raise RuntimeError(msg)
    has_key = any(k.startswith("ANTHROPIC_") for k in os.environ)
    if not has_key:
        msg = "No ANTHROPIC_ environment variables found. Set ANTHROPIC_API_KEY to use the Claude planner."
        raise RuntimeError(msg)


def _parse_plan_from_text(goal: str, text: str) -> Plan:
    """Extract a Plan from Claude's markdown output."""
    steps: list[PlanStep] = []
    matches = _PLAN_STEP_RE.findall(text)
    for i, (_num, title) in enumerate(matches, 1):
        steps.append(PlanStep(id=f"step_{i}", description=title.strip()))
    if not steps:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:10], 1):
            cleaned = re.sub(r"^[\d\-\*\.]+\s*", "", line)
            if cleaned and len(cleaned) > _MIN_STEP_DESCRIPTION_LENGTH:
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
        """Initialize the Claude planner.

        Args:
            cwd: Working directory for the Claude CLI.

        Raises:
            RuntimeError: If Claude CLI or ANTHROPIC_ env vars are missing.
        """
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
        except Exception:
            logger.warning("ClaudePlanner revise_plan failed", exc_info=True)
            return plan
        else:
            return revised

    async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
        """Dependency-aware reflection (RFC-0010)."""
        completed = sum(1 for r in step_results if r.success)
        failed_list = [r for r in step_results if not r.success]
        total = len(plan.steps)

        if not failed_list:
            return Reflection(
                assessment=f"{completed}/{total} steps completed successfully",
                should_revise=False,
                feedback="",
            )

        failed_ids = {r.step_id for r in failed_list}
        blocked: list[str] = []
        direct_failed: list[str] = []
        for r in failed_list:
            step = next((s for s in plan.steps if s.id == r.step_id), None)
            if step and any(dep in failed_ids for dep in step.depends_on):
                blocked.append(r.step_id)
            else:
                direct_failed.append(r.step_id)

        failed_details = {r.step_id: (r.output[:200] if r.output else "no output") for r in failed_list}

        parts = [f"{completed}/{total} steps completed, {len(failed_list)} failed"]
        if direct_failed:
            parts.append(f"Directly failed: {direct_failed}")
        if blocked:
            parts.append(f"Blocked by dependencies: {blocked}")

        logger.debug(
            "Reflection: completed=%d failed=%d blocked=%d direct_failed=%d",
            completed,
            len(failed_list),
            len(blocked),
            len(direct_failed),
        )
        return Reflection(
            assessment=". ".join(parts),
            should_revise=True,
            feedback=f"Failed steps: {direct_failed}. Blocked: {blocked}.",
            blocked_steps=blocked,
            failed_details=failed_details,
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
