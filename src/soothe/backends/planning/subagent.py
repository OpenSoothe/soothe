"""SubagentPlanner -- PlannerProtocol via compiled planner subagent graph."""

from __future__ import annotations

import logging
import re
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

_MIN_STEP_DESCRIPTION_LENGTH = 5

_PLAN_EXTRACTION_RE = re.compile(
    r"\*\*Step\s+(\d+)[:\s]*(.+?)\*\*",
    re.IGNORECASE,
)


def _parse_plan_from_text(goal: str, text: str) -> Plan:
    """Best-effort extraction of Plan from planner subagent markdown output."""
    steps: list[PlanStep] = []
    matches = _PLAN_EXTRACTION_RE.findall(text)
    for i, (_num, title) in enumerate(matches, 1):
        steps.append(
            PlanStep(
                id=f"step_{i}",
                description=title.strip(),
            )
        )
    if not steps:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:10], 1):
            cleaned = re.sub(r"^[\d\-\*\.]+\s*", "", line)
            if cleaned and len(cleaned) > _MIN_STEP_DESCRIPTION_LENGTH:
                steps.append(PlanStep(id=f"step_{i}", description=cleaned))
    if not steps:
        steps = [PlanStep(id="step_1", description=goal)]
    return Plan(goal=goal, steps=steps)


class SubagentPlanner:
    """PlannerProtocol via a compiled planner subagent graph.

    Reuses ``create_planner_subagent`` + deepagents ``create_deep_agent``
    to compile a standalone planner graph, then invokes it for planning.

    Args:
        model: LLM model (instance or string).
        cwd: Working directory for the planner's filesystem tools.
    """

    def __init__(self, model: Any, cwd: str | None = None) -> None:
        """Initialize the subagent planner.

        Args:
            model: LLM model (instance or string).
            cwd: Working directory for the planner's filesystem tools.
        """
        from deepagents import create_deep_agent
        from langgraph.checkpoint.memory import MemorySaver

        from soothe.subagents.planner import create_planner_subagent

        spec = create_planner_subagent(model=model, cwd=cwd)
        tools = spec.get("tools")
        system_prompt = spec.get("system_prompt", "")

        self._graph = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=MemorySaver(),
        )
        self._model = model
        self._call_count = 0

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan by invoking the planner subagent graph."""
        prompt = self._build_prompt(goal, context)
        try:
            text = await self._invoke(prompt)
            return _parse_plan_from_text(goal, text)
        except Exception:
            logger.warning("SubagentPlanner create_plan failed, using fallback", exc_info=True)
            return Plan(goal=goal, steps=[PlanStep(id="step_1", description=goal)])

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan by reinvoking the planner subagent with feedback."""
        prompt = (
            f"Revise this plan based on feedback.\n\n"
            f"Goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan with numbered steps."
        )
        try:
            text = await self._invoke(prompt)
            revised = _parse_plan_from_text(plan.goal, text)
            revised.status = "revised"
        except Exception:
            logger.warning("SubagentPlanner revise_plan failed", exc_info=True)
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
        """Run the compiled planner graph and extract the final AI response."""
        self._call_count += 1
        thread_id = f"subagent-planner-{self._call_count}"
        result = await self._graph.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": thread_id}},
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
            "Include description, dependencies, and verification for each step."
        )
        return "\n\n".join(parts)
