"""SubagentPlanner -- PlannerProtocol via subagent orchestration.

Provides scout and planner subagents that can be orchestrated by the agent
following the scout-then-plan skill workflow.
"""

from __future__ import annotations

import logging
from time import perf_counter
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

_SYSTEM_PROMPT = """\
You are a planning assistant. You MUST use the available subagent tools to \
produce high-quality plans. Do NOT answer directly -- always delegate.

## Required Workflow

1. **Scout first** -- call the `task` tool with the `scout` subagent to explore \
the codebase or data relevant to the goal.  You may launch multiple scout calls \
in parallel for different areas.
2. **Synthesize** -- once scout results are back, analyze the findings and \
identify gaps.
3. **Plan** -- call the `task` tool with the `planner` subagent, providing \
the synthesized scout findings as context.  The planner will return a structured \
plan with numbered steps.
4. **Return** -- output the planner's structured plan verbatim (do not rewrite it).

IMPORTANT: You MUST call at least the `planner` subagent via the `task` tool. \
Skipping tool calls and answering directly will produce low-quality plans."""


class SubagentPlanner:
    """PlannerProtocol via subagent orchestration.

    Provides both scout and planner subagents, allowing the agent to follow
    the scout-then-plan skill workflow for enhanced planning quality.

    The scout-then-plan skill (automatically loaded) guides the agent to:
    1. Launch parallel scout subagents for exploration
    2. Synthesize findings with analysis and reflection
    3. Invoke planner subagent with enriched context

    Args:
        model: LLM model (instance or string).
        cwd: Working directory for the planner's filesystem tools.
        skills: Optional list of skill paths to load into the planning agent.
    """

    def __init__(
        self,
        model: Any,
        cwd: str | None = None,
        skills: list[str] | None = None,
    ) -> None:
        """Initialize the subagent planner.

        Args:
            model: LLM model (instance or string).
            cwd: Working directory for the planner's filesystem tools.
            skills: Optional list of skill paths to load into the planning agent.
        """
        from deepagents import create_deep_agent
        from langgraph.checkpoint.memory import MemorySaver

        from soothe.subagents.planner import create_planner_subagent
        from soothe.subagents.scout import create_scout_subagent

        scout_spec = create_scout_subagent(model=model, cwd=cwd)
        planner_spec = create_planner_subagent(model=model, cwd=cwd)

        self._graph = create_deep_agent(
            model=model,
            subagents=[scout_spec, planner_spec],
            system_prompt=_SYSTEM_PROMPT,
            skills=skills,
            checkpointer=MemorySaver(),
        )
        self._model = model
        self._call_count = 0

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create a plan using subagent orchestration.

        The agent will follow the scout-then-plan skill to:
        1. Scout relevant areas of the codebase
        2. Synthesize findings
        3. Generate a structured plan
        """
        prompt = self._build_prompt(goal, context)
        logger.info("SubagentPlanner create_plan started - goal: %s", goal[:120])
        t0 = perf_counter()
        try:
            text = await self._invoke(prompt)
            plan = parse_plan_from_text(goal, text)
        except Exception:
            elapsed_ms = (perf_counter() - t0) * 1000
            logger.warning(
                "SubagentPlanner create_plan failed after %.1fms, using fallback",
                elapsed_ms,
                exc_info=True,
            )
            return Plan(goal=goal, steps=[PlanStep(id="step_1", description=goal)])
        else:
            elapsed_ms = (perf_counter() - t0) * 1000
            logger.info(
                "SubagentPlanner create_plan completed in %.1fms - %d steps, goal: %s",
                elapsed_ms,
                len(plan.steps),
                goal[:80],
            )
            if plan.steps:
                logger.debug(
                    "SubagentPlanner plan steps: %s",
                    [s.description[:60] for s in plan.steps[:8]],
                )
            return plan

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise a plan based on feedback.

        The agent can use scout and planner subagents to revise the plan
        based on the feedback provided.
        """
        prompt = (
            f"Revise this plan based on feedback.\n\n"
            f"Goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Use the scout subagent to explore any areas highlighted in the feedback, "
            f"then use the planner subagent to generate a revised plan with numbered steps."
        )
        logger.info(
            "SubagentPlanner revise_plan started - goal: %s, feedback: %s",
            plan.goal[:80],
            reflection[:80],
        )
        t0 = perf_counter()
        try:
            text = await self._invoke(prompt)
            revised = parse_plan_from_text(plan.goal, text)
            revised.status = "revised"
            elapsed_ms = (perf_counter() - t0) * 1000
            logger.info(
                "SubagentPlanner revise_plan completed in %.1fms - %d steps",
                elapsed_ms,
                len(revised.steps),
            )
        except Exception:
            elapsed_ms = (perf_counter() - t0) * 1000
            logger.warning(
                "SubagentPlanner revise_plan failed after %.1fms",
                elapsed_ms,
                exc_info=True,
            )
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
            logger.info(
                "SubagentPlanner reflect (LLM) - %d/%d steps failed",
                len(failed_list),
                len(step_results),
            )
            return await reflect_with_llm(self._model, plan, step_results, goal_context)
        logger.debug(
            "SubagentPlanner reflect (heuristic) - %d results",
            len(step_results),
        )
        return reflect_heuristic(plan, step_results, goal_context)

    async def _invoke(self, prompt: str) -> str:
        """Run the compiled planner graph via streaming and extract the final AI response.

        Uses ``astream`` instead of ``ainvoke`` so that internal subagent
        progress events (tool calls, scout/planner activity) are emitted
        through the LangGraph stream writer and logged by ``emit_progress``.
        """
        self._call_count += 1
        thread_id = f"subagent-planner-{self._call_count}"
        logger.info("SubagentPlanner _invoke #%d started (thread=%s)", self._call_count, thread_id)
        t0 = perf_counter()

        config = {"configurable": {"thread_id": thread_id}}
        messages_input = {"messages": [HumanMessage(content=prompt)]}

        final_ai_text = ""
        tool_call_count = 0
        subagent_names_seen: set[str] = set()

        async for chunk in self._graph.astream(
            messages_input,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
            config=config,
        ):
            if not isinstance(chunk, tuple) or len(chunk) != 3:  # noqa: PLR2004
                continue

            namespace, mode, data = chunk

            # Log custom events from inner subagents (tool progress, etc.)
            if mode == "custom" and isinstance(data, dict):
                event_type = data.get("type", "")
                logger.info("SubagentPlanner inner event: %s", event_type)

            # Track tool calls via updates
            if mode == "updates" and isinstance(data, dict):
                for node_name, node_data in data.items():
                    if node_name == "tools" and isinstance(node_data, dict):
                        tool_call_count += 1
                    # Detect subagent delegation
                    if "task" in node_name.lower() or node_name in ("scout", "planner"):
                        subagent_names_seen.add(node_name)

            # Accumulate final AI message from the top-level graph
            if mode == "messages" and not namespace and isinstance(data, tuple) and len(data) == 2:  # noqa: PLR2004
                msg, _meta = data
                if isinstance(msg, AIMessage) and msg.content:
                    text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    final_ai_text += text

        elapsed_ms = (perf_counter() - t0) * 1000
        logger.info(
            "SubagentPlanner _invoke #%d completed in %.1fms (tool_calls=%d, subagents=%s, response_len=%d)",
            self._call_count,
            elapsed_ms,
            tool_call_count,
            sorted(subagent_names_seen) or "none",
            len(final_ai_text),
        )
        if not final_ai_text:
            logger.warning("SubagentPlanner _invoke #%d returned empty response", self._call_count)
        else:
            logger.debug(
                "SubagentPlanner _invoke #%d response preview: %s",
                self._call_count,
                final_ai_text[:200],
            )

        return final_ai_text

    def _build_prompt(self, goal: str, context: PlanContext) -> str:
        """Build the planning prompt with context information."""
        parts = [f"Create a detailed, structured plan for this goal:\n\n{goal}"]
        if context.available_capabilities:
            parts.append(f"Available capabilities: {', '.join(context.available_capabilities)}")
        if context.completed_steps:
            parts.append(f"Already completed: {[s.step_id for s in context.completed_steps]}")
        parts.append(
            "You MUST use the scout-then-plan workflow: first call the scout subagent to explore "
            "the codebase, then call the planner subagent with the scout findings to generate a "
            "structured plan with numbered steps. Each step should have a title, description, "
            "dependencies, and verification criteria."
        )
        return "\n\n".join(parts)
