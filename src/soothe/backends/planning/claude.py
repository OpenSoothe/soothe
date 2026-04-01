"""ClaudePlanner -- PlannerProtocol via compiled Claude subagent graph."""

from __future__ import annotations

import logging
import os
import shutil

from langchain_core.messages import AIMessage, HumanMessage

from soothe.backends.planning._shared import (
    parse_plan_from_text,
    reflect_heuristic,
    reflect_with_llm,
)
from soothe.protocols.planner import (
    GoalContext,
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


def _check_claude_available() -> None:
    """Validate that the Claude CLI and required env vars are present.

    Raises:
        RuntimeError: If ``claude`` CLI is not found or ``ANTHROPIC_*``
            is not set.
    """
    if not shutil.which("claude"):
        msg = "Claude CLI ('claude') not found on PATH. Install it: npm install -g @anthropic-ai/claude-code"
        raise RuntimeError(msg)
    has_key = any(k.startswith("ANTHROPIC_") for k in os.environ)
    if not has_key:
        msg = "No ANTHROPIC_ environment variables found. Set ANTHROPIC_API_KEY to use the Claude planner."
        raise RuntimeError(msg)


class ClaudePlanner:
    """PlannerProtocol via compiled Claude subagent graph.

    Reuses ``create_claude_subagent()`` with a planning-focused system prompt.
    Validates Claude CLI availability and ANTHROPIC_ env vars at init.

    Args:
        cwd: Working directory for the Claude CLI.
        reflection_model: Optional LLM for LLM-assisted reflection. Claude CLI
            is used for planning but a standard chat model is more efficient
            for reflection analysis.

    Raises:
        RuntimeError: If Claude CLI or ANTHROPIC_ env vars are missing.
    """

    def __init__(
        self,
        cwd: str | None = None,
        reflection_model: object | None = None,
    ) -> None:
        """Initialize the Claude planner.

        Args:
            cwd: Working directory for the Claude CLI.
            reflection_model: Optional chat model for LLM-assisted reflection.

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
        self._reflection_model = reflection_model
        self._call_count = 0

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan by invoking Claude with a planning prompt."""
        prompt = self._build_prompt(goal, context)
        try:
            text = await self._invoke(prompt)
            return parse_plan_from_text(goal, text)
        except Exception:
            logger.warning("ClaudePlanner create_plan failed", exc_info=True)
            return Plan(goal=goal, steps=[PlanStep(id="S_1", description=goal)])

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
            revised = parse_plan_from_text(plan.goal, text)
            revised.status = "revised"
        except Exception:
            logger.warning("ClaudePlanner revise_plan failed", exc_info=True)
            return plan
        else:
            return revised

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Reflection with LLM-assisted analysis when failures exist (RFC-0010, RFC-0007 §5.4)."""
        failed_list = [r for r in step_results if not r.success]
        if failed_list and self._reflection_model:
            return await reflect_with_llm(self._reflection_model, plan, step_results, goal_context)
        return reflect_heuristic(plan, step_results, goal_context)

    async def decide_steps(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: object | None = None,
    ) -> object:
        """Decide what steps to execute for Layer 2 goal execution (RFC-0008).

        Uses Claude CLI to determine step execution strategy.

        Args:
            goal: Goal description
            context: Planning context
            previous_judgment: Previous JudgeResult if replanning

        Returns:
            AgentDecision with steps to execute
        """
        # Build prompt for step decision
        prompt = self._build_step_decision_prompt(goal, context, previous_judgment)

        try:
            text = await self._invoke(prompt)
            # Import here to avoid circular imports
            from soothe.backends.planning.simple import _parse_step_decision_text

            return _parse_step_decision_text(text, goal)
        except Exception:
            logger.warning("ClaudePlanner decide_steps failed", exc_info=True)
            # Fallback to single-step decision
            from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

            return AgentDecision(
                steps=[StepAction(id="S_1", description=goal, expected_output="complete goal")],
                execution_mode="sequential",
                reasoning="Claude planner failed, fallback to single step",
            )

    def _build_step_decision_prompt(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: object | None,
    ) -> str:
        """Build prompt for step decision."""
        parts = [f"Goal: {goal}\n"]

        # Include completed steps to avoid repetitive planning
        if context.completed_steps:
            parts.append("\nAlready executed steps (DO NOT repeat these):")
            for step in context.completed_steps:
                status = "✓" if step.success else "✗"
                output_preview = step.output[:100] if step.output else "no output"
                parts.append(f"- {step.step_id}: {status} {output_preview}")

        if previous_judgment:
            parts.append("\nPrevious judgment:")
            parts.append(f"- Status: {getattr(previous_judgment, 'status', 'unknown')}")
            parts.append(f"- Progress: {getattr(previous_judgment, 'goal_progress', 0):.0%}")
            parts.append(f"- Evidence: {getattr(previous_judgment, 'evidence_summary', 'none')[:200]}")

        if context.available_capabilities:
            parts.append(f"\nAvailable capabilities: {', '.join(context.available_capabilities)}")

        parts.append(
            "\nDecide what steps to execute next. **Do NOT repeat already executed steps.**\n"
            "Output JSON format:\n"
            '{"steps": [{"id": "S_1", "description": "...", "execution_hint": "auto"}], '
            '"execution_mode": "sequential", "reasoning": "..."}'
        )
        return "\n".join(parts)

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
