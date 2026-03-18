"""SubagentPlanner -- PlannerProtocol via compiled planner subagent graph."""

from __future__ import annotations

import logging
from typing import Any

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
            return parse_plan_from_text(goal, text)
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
            revised = parse_plan_from_text(plan.goal, text)
            revised.status = "revised"
        except Exception:
            logger.warning("SubagentPlanner revise_plan failed", exc_info=True)
            return plan
        else:
            return revised

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Reflection with LLM-assisted analysis when failures exist (RFC-0010, RFC-0011)."""
        failed_list = [r for r in step_results if not r.success]
        if failed_list and self._model:
            return await reflect_with_llm(self._model, plan, step_results, goal_context)
        return reflect_heuristic(plan, step_results, goal_context)

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
