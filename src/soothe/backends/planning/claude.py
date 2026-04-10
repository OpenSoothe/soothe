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
from soothe.backends.planning.simple import (
    _default_agent_decision,
    parse_reason_response_text,
)
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.config import SootheConfig
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
        config: Optional Soothe config for RFC-104-aligned planning/reason prefixes.

    Raises:
        RuntimeError: If Claude CLI or ANTHROPIC_ env vars are missing.
    """

    def __init__(
        self,
        cwd: str | None = None,
        reflection_model: object | None = None,
        config: SootheConfig | None = None,
    ) -> None:
        """Initialize the Claude planner.

        Args:
            cwd: Working directory for the Claude CLI.
            reflection_model: Optional chat model for LLM-assisted reflection.
            config: Optional configuration for shared context XML in prompts.

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
        self._config = config
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

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> object:
        """Layer 2 Reason phase via Claude subagent (same JSON contract as SimplePlanner)."""
        from soothe.cognition.loop_agent.schemas import ReasonResult
        from soothe.core.prompts import PromptBuilder

        prompt_builder = PromptBuilder(self._config)
        prompt = prompt_builder.build_reason_prompt(goal, state, context)
        try:
            text = await self._invoke(prompt)
            return parse_reason_response_text(text, goal)
        except Exception:
            logger.warning("ClaudePlanner.reason failed", exc_info=True)
            return ReasonResult(
                status="replan",
                plan_action="new",
                decision=_default_agent_decision(goal),
                reasoning="Claude planner failed",
                soothe_next_action="I'll fall back to a minimal plan and continue.",
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
        from soothe.core.prompts.context_xml import build_shared_environment_workspace_prefix

        parts: list[str] = []
        if self._config is not None:
            parts.append(
                build_shared_environment_workspace_prefix(
                    self._config,
                    context.workspace,
                    context.git_status,
                    include_workspace_extras=True,
                ).rstrip()
            )
        parts.append(f"Create a detailed, structured plan for this goal:\n\n{goal}")
        if context.available_capabilities:
            parts.append(f"Available capabilities: {', '.join(context.available_capabilities)}")
        if context.completed_steps:
            parts.append(f"Already completed: {[s.step_id for s in context.completed_steps]}")
        parts.append(
            "Produce a numbered plan with **Step N: Title** format. "
            "Include description, rationale, dependencies, verification, and effort."
        )
        return "\n\n".join(parts)
