"""SimplePlanner -- single LLM call planner for simple/medium tasks."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from soothe.backends.planning._shared import reflect_heuristic
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)


def _extract_text_content(content: Any) -> str:
    """Normalise LLM response content to a plain string.

    Handles both the simple string case and the Anthropic-style list-of-blocks
    case (e.g. ``[{'type': 'text', 'text': '...'}, {'type': 'tool_use', ...}]``).

    Args:
        content: The ``content`` attribute from a LangChain AIMessage.

    Returns:
        Plain text, joining all ``text``-type blocks when content is a list.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


def _load_llm_json_dict(response: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response string."""
    json_str = response.strip()

    if "```json" in json_str:
        start = json_str.find("```json") + 7
        end = json_str.find("```", start)
        if end > start:
            json_str = json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.find("```") + 3
        newline_pos = json_str.find("\n", start)
        if newline_pos > start:
            start = newline_pos + 1
        end = json_str.find("```", start)
        if end > start:
            json_str = json_str[start:end].strip()

    if not json_str:
        raise ValueError("Empty LLM response — cannot parse JSON")

    if not json_str.startswith("{"):
        match = re.search(r"(\{.*\})", json_str, re.DOTALL)
        if match:
            json_str = match.group(1).strip()

    loaded = json.loads(json_str)
    if not isinstance(loaded, dict):
        raise TypeError("LLM JSON root must be an object")
    return loaded


def agent_decision_from_dict(data: dict[str, Any], _goal: str) -> Any:
    """Build AgentDecision from a parsed JSON object (step list at top level)."""
    from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

    known_subagents = {"browser", "weaver", "skillify", "claude", "research"}

    steps = []
    for i, step_data in enumerate(data.get("steps", [])):
        if not isinstance(step_data, dict):
            continue
        deps = step_data.get("dependencies")
        deps = [] if deps is None or not isinstance(deps, list) else [str(d) for d in deps if d is not None]

        tools = step_data.get("tools") or []
        if tools:
            subagent_tools = [t for t in tools if t in known_subagents]
            if subagent_tools:
                if not step_data.get("subagent"):
                    step_data["subagent"] = subagent_tools[0]
                    logger.debug("Normalized subagent '%s' from tools to subagent field", subagent_tools[0])
                remaining_tools = [t for t in tools if t not in known_subagents]
                step_data["tools"] = remaining_tools or None

        steps.append(
            StepAction(
                id=f"step_{i}",
                description=step_data.get("description", ""),
                tools=step_data.get("tools"),
                subagent=step_data.get("subagent"),
                expected_output=step_data.get("expected_output", ""),
                dependencies=deps,
            )
        )

    return AgentDecision(
        type=data.get("type", "execute_steps"),
        steps=steps,
        execution_mode=data.get("execution_mode", "sequential"),
        reasoning=data.get("reasoning", ""),
        adaptive_granularity=data.get("adaptive_granularity"),
    )


def _default_agent_decision(goal: str) -> Any:
    """Minimal single-step decision used when parsing fails."""
    from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="step_0",
                description=goal,
                expected_output="Task completion",
            )
        ],
        execution_mode="sequential",
        reasoning="Default decision due to parse error",
    )


def parse_reason_response_text(response: str, goal: str) -> Any:
    """Parse unified Reason JSON into ReasonResult."""
    from soothe.cognition.loop_agent.schemas import ReasonResult

    try:
        data = _load_llm_json_dict(response)
    except Exception:
        logger.exception("Failed to parse reason response")
        return ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal),
            reasoning="Failed to parse model response",
            user_summary="Could not read the model plan — trying a fresh approach",
            soothe_next_action="I'll try again with a simpler plan.",
            progress_detail=None,
        )

    # Legacy flat plan (steps at root, no reason fields)
    if "status" not in data and "steps" in data:
        try:
            decision = agent_decision_from_dict(data, goal)
        except Exception:
            logger.exception("Failed to parse legacy plan shape")
            decision = _default_agent_decision(goal)
        return ReasonResult(
            status="continue",
            plan_action="new",
            decision=decision,
            reasoning=decision.reasoning,
            user_summary="Planned next steps",
            soothe_next_action="I'll run the steps in this plan next.",
            progress_detail=None,
        )

    status = data.get("status", "replan")
    if status not in ("continue", "replan", "done"):
        status = "replan"

    plan_action = data.get("plan_action", "new")
    if plan_action not in ("keep", "new"):
        plan_action = "new"

    reasoning = str(data.get("reasoning", "") or "")
    user_summary = str(data.get("user_summary", "") or "").strip()
    if not user_summary:
        user_summary = "Working toward the goal"

    soothe_next_action = str(data.get("soothe_next_action", "") or "").strip()

    progress_detail = data.get("progress_detail")
    if progress_detail is not None:
        progress_detail = str(progress_detail).strip() or None

    decision = None
    if plan_action == "new":
        raw_decision = data.get("decision")
        if isinstance(raw_decision, dict):
            try:
                decision = agent_decision_from_dict(raw_decision, goal)
            except Exception:
                logger.exception("Failed to parse nested decision")
                decision = _default_agent_decision(goal) if status != "done" else None
        elif status != "done":
            decision = _default_agent_decision(goal)

    if plan_action == "keep":
        decision = None

    try:
        return ReasonResult(
            status=status,
            plan_action=plan_action,
            decision=decision,
            goal_progress=float(data.get("goal_progress", 0.0)),
            confidence=float(data.get("confidence", 0.8)),
            reasoning=reasoning,
            user_summary=user_summary,
            soothe_next_action=soothe_next_action,
            progress_detail=progress_detail,
            evidence_summary=str(data.get("evidence_summary", "") or ""),
            next_steps_hint=data.get("next_steps_hint"),
        )
    except Exception:
        logger.exception("Invalid ReasonResult fields")
        return ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal),
            reasoning="Invalid reason payload",
            user_summary="Adjusting the plan after an invalid model response",
            soothe_next_action="I'll adjust and try a cleaner plan.",
        )


def _parse_step_decision_text(response: str, goal: str) -> Any:
    """Parse LLM response into AgentDecision (legacy JSON shape)."""
    try:
        return agent_decision_from_dict(_load_llm_json_dict(response), goal)
    except Exception:
        logger.exception("Failed to parse step decision")
        return _default_agent_decision(goal)


def build_loop_reason_prompt(goal: str, state: LoopState, context: PlanContext) -> str:
    """Shared Reason-phase prompt for Layer 2 (SimplePlanner / ClaudePlanner)."""
    parts = [
        f"Goal: {goal}\n",
        f"Loop iteration: {state.iteration} (max {state.max_iterations})\n",
    ]

    if state.step_results:
        parts.append("\nEvidence from steps run so far in this goal:")
        parts.extend(r.to_evidence_string() for r in state.step_results)

    if context.completed_steps:
        parts.append("\nPlanner context — completed step summaries (do not repeat work):")
        for step in context.completed_steps:
            status = "✓" if step.success else "✗"
            output_preview = step.output[:100] if step.output else "no output"
            parts.append(f"- {step.step_id}: {status} {output_preview}")

    prev = state.previous_reason
    if prev:
        parts.append("\nYour previous assessment (for continuity):")
        parts.append(f"- Status: {prev.status}")
        parts.append(f"- Progress estimate: {prev.goal_progress:.0%}")
        parts.append(f"- Summary: {prev.user_summary or prev.reasoning[:200]}")
        if prev.next_steps_hint:
            parts.append(f"- Hint: {prev.next_steps_hint}")

    if state.current_decision and prev and prev.should_continue():
        parts.append(
            "\nCurrent plan is still active. If the strategy remains valid and "
            'dependencies allow, you may set plan_action to "keep" and omit "decision" '
            "to run the next ready steps of the existing plan. "
            'Otherwise set plan_action to "new" and supply a full replacement decision.'
        )

    if context.available_capabilities:
        parts.append(f"\nAvailable tools/subagents: {', '.join(context.available_capabilities)}")

    parts.extend(
        [
            "\n\nYou are the Reason step in a ReAct loop. In ONE response you must:",
            "\n1. Estimate how complete the goal is (goal_progress 0.0-1.0) and your confidence.",
            '\n2. Choose status: "done" (goal fully achieved), "continue" (more work with same or adjusted plan),',
            '   or "replan" (abandon current approach).',
            "\n3. Write user_summary: one short, friendly sentence for the user (no jargon).",
            "\n4. Write soothe_next_action: ONE sentence in first person as the assistant Soothe",
            '   (use "I" / "I will" / "I\'ll"), describing the immediate next action you will take.',
            "   If status is done, say you are finishing or presenting the result (still first person).",
            "\n5. Optionally write progress_detail: 1-2 sentences explaining what's left or what changed.",
            "\n6. reasoning: INTERNAL ONLY - concise technical analysis, third person or neutral,",
            "   NOT first person, NOT shown to the user. Never put user-facing text only in reasoning.",
            '\n7. Choose plan_action: "keep" only if an existing multi-step plan should continue unchanged;',
            '   otherwise "new" and include a full "decision" object.',
            '\n8. For "decision" when plan_action is "new", use the same shape as before:',
            "   type, steps[], execution_mode, adaptive_granularity, reasoning (plan-focused).",
            "\n9. Do NOT repeat work already shown in evidence or completed summaries.",
            "\n\nReturn JSON:",
            "{",
            '  "status": "done" | "continue" | "replan",',
            '  "goal_progress": 0.0,',
            '  "confidence": 0.0,',
            '  "reasoning": "internal technical analysis, not first person, not for user UI",',
            '  "user_summary": "Short friendly line for the user",',
            '  "soothe_next_action": "I will ... (first person, Soothe)",',
            '  "progress_detail": "Optional extra context for the user",',
            '  "plan_action": "keep" | "new",',
            '  "next_steps_hint": null,',
            '  "decision": {',
            '    "type": "execute_steps",',
            '    "steps": [',
            "      {",
            '        "description": "...",',
            '        "tools": [],',
            '        "subagent": null,',
            '        "expected_output": "...",',
            '        "dependencies": []',
            "      }",
            "    ],",
            '    "execution_mode": "sequential" | "parallel" | "dependency",',
            '    "adaptive_granularity": "atomic" | "semantic",',
            '    "reasoning": "why these steps"',
            "  }",
            "}",
            '\nWhen status is "done", you may omit "decision" or set plan_action to "keep" with no decision.',
            '\nWhen plan_action is "keep", omit "decision" entirely.',
        ]
    )

    return "\n".join(parts)


_SIMPLE_PLANNER_HINT_MAP = {
    "browser": "subagent",
    "weaver": "subagent",
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


class SimplePlanner:
    """PlannerProtocol using single LLM call for planning.

    For simple/medium tasks. Produces flat plans (typically 1-3 steps).

    Optimizations:
    - Unified planning prompt combines classification + planning
    - Heuristic reflection (no LLM needed)

    Args:
        model: Langchain BaseChatModel supporting structured output.
    """

    def __init__(
        self,
        model: Any,
    ) -> None:
        """Initialize SimplePlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
        """
        self._model = model

    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Create plan via LLM structured output."""
        # Direct LLM call - no template fallback
        plan = await self._create_plan_via_llm(goal, context)

        # Override execution hints when the user explicitly requested a subagent
        preferred = (
            getattr(context.unified_classification, "preferred_subagent", None)
            if context.unified_classification
            else None
        )
        if preferred:
            plan = self._apply_preferred_subagent(plan, preferred)

        return plan

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise plan based on reflection feedback."""
        prompt = self._build_revision_prompt(plan, reflection)

        try:
            structured_model = self._model.with_structured_output(Plan)
            revised = await structured_model.ainvoke(prompt)
            revised.status = "revised"
            return self._normalize_hints(revised)
        except Exception as e:
            logger.warning("Plan revision failed: %s", e)
            return plan

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Heuristic reflection (no LLM needed for simple plans)."""
        return reflect_heuristic(plan, step_results, goal_context)

    async def _invoke(self, prompt: str) -> str:
        """Invoke the LLM with a free-form prompt and return the response.

        Used for synthesis and other LLM-based operations.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            The LLM's response as a string.
        """
        from langchain_core.messages import HumanMessage

        try:
            response = await self._model.ainvoke([HumanMessage(content=prompt)])
            content = getattr(response, "content", str(response))
            return _extract_text_content(content)
        except Exception as e:
            logger.warning("SimplePlanner._invoke failed: %s", e)
            return ""

    async def _create_plan_via_llm(self, goal: str, context: PlanContext) -> Plan:
        """Create plan via LLM structured output with fallback parsing."""
        prompt = self._build_plan_prompt(goal, context)

        try:
            structured_model = self._model.with_structured_output(Plan)
            plan = await structured_model.ainvoke(prompt)
            return self._normalize_hints(plan)
        except Exception as e:
            logger.warning("Structured output failed, trying manual parse: %s", e)
            return await self._fallback_parse(goal, prompt)

    async def _fallback_parse(self, goal: str, prompt: str) -> Plan:
        """Fallback plan parsing from raw LLM response."""
        try:
            response = await self._model.ainvoke(prompt)
            content = getattr(response, "content", str(response))
            return self._parse_json_from_response(_extract_text_content(content), goal)
        except Exception as e:
            logger.warning("Fallback parsing failed: %s", e)
            return Plan(
                goal=goal or "Unnamed goal",
                steps=[{"id": "S_1", "description": goal or "Execute task"}],
            )

    def _parse_json_from_response(self, content: str, fallback_goal: str) -> Plan:
        """Parse Plan from JSON content, optionally wrapped in markdown.

        Args:
            content: JSON string, optionally wrapped in ```json``` markdown block
            fallback_goal: Goal to use if parsing fails

        Returns:
            Parsed Plan object or fallback single-step plan
        """
        try:
            # Try JSON extraction from markdown code blocks
            if json_match := re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL):
                data = json.loads(json_match.group(1))
                return Plan(**self._normalize_hints_in_dict(data))

            # Try plain JSON
            data = json.loads(content)
            return Plan(**self._normalize_hints_in_dict(data))
        except Exception as e:
            logger.warning("JSON parsing failed: %s", e)
            return Plan(
                goal=fallback_goal or "Unnamed goal",
                steps=[{"id": "S_1", "description": fallback_goal or "Execute task"}],
            )

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        """Build unified planning prompt with XML sections (RFC-104 alignment)."""
        sections = []

        # Goal section
        sections.append(f"<PLANNING_GOAL>\n{goal}\n</PLANNING_GOAL>")

        # Workspace context as XML section
        if context.workspace:
            logger.debug("Planner: using workspace=%s", context.workspace)
            workspace_content = [
                f"Primary working directory: {context.workspace}",
                "",
                "<TOOL_ROUTING_RULES>",
                "- listing files/directories → list_files tool or run_command with 'ls'",
                "- reading files → read_file tool",
                "- searching files → search_files tool",
                "- shell commands (pwd, ls, cat) → run_command tool",
                "- web URLs/sites → browser subagent (ONLY for http/https URLs)",
                "</TOOL_ROUTING_RULES>",
                "",
                "<FORBIDDEN_ACTIONS>",
                "- using ANY subagent (browser, claude, research) for local file operations",
                "- browser/claude for: pwd, ls, cat, file read, directory listing",
                "- searching system directories (/etc, /Library, /usr, /System, /Applications)",
                "- listing root filesystem (/)",
                "</FORBIDDEN_ACTIONS>",
            ]
            sections.append("<PLANNING_WORKSPACE>\n" + "\n".join(workspace_content) + "\n</PLANNING_WORKSPACE>")

        # Available capabilities
        if context.available_capabilities:
            caps = ", ".join(context.available_capabilities)
            sections.append(f"<PLANNING_CAPABILITIES>\n{caps}\n</PLANNING_CAPABILITIES>")

        # Completed steps context
        if context.completed_steps:
            completed_lines = []
            for step in context.completed_steps:
                status = "✓" if step.success else "✗"
                output_preview = step.output[:80] if step.output else "no output"
                completed_lines.append(f"{step.step_id}: {status} {output_preview}")
            sections.append("<PLANNING_COMPLETED>\n" + "\n".join(completed_lines) + "\n</PLANNING_COMPLETED>")

        # Output format specification
        output_spec = [
            "Return JSON with this structure:",
            "{",
            '  "goal": "<goal text>",',
            '  "is_plan_only": false,',
            '  "reasoning": "<brief classification>",',
            '  "steps": [',
            "    {",
            '      "id": "S_1",',
            '      "description": "<concrete action>",',
            '      "execution_hint": "tool"',
            "    }",
            "  ]",
            "}",
            "",
            "<PLANNING_RULES>",
            "- Return 1 step for trivial tasks, 2-3 for normal, 4-5 only if essential",
            "- Each step must be independently executable",
            "- execution_hint: 'tool' (direct tool), 'subagent' (delegate), 'auto' (LLM reasoning)",
            "- If user requests specific subagent, set execution_hint='subagent'",
            "- Return ONLY valid JSON (no markdown blocks)",
            "</PLANNING_RULES>",
            "",
            "<EFFICIENCY_RULES>",
            "- For exploration/analysis: use 1 step with list_files + selective read_file",
            "- For project structure: single step listing top-level directories",
            "- Avoid redundant steps (listing then reading same files)",
            "- Batch related operations in one step when possible",
            "</EFFICIENCY_RULES>",
        ]
        sections.append("<PLANNING_OUTPUT>\n" + "\n".join(output_spec) + "\n</PLANNING_OUTPUT>")

        return "\n\n".join(sections)

    def _build_revision_prompt(self, plan: Plan, reflection: str) -> str:
        """Build plan revision prompt."""
        return (
            f"Revise this plan based on feedback.\n\n"
            f"Goal: {plan.goal}\n"
            f"Current steps: {[s.description for s in plan.steps]}\n"
            f"Feedback: {reflection}\n\n"
            f"Return a revised plan with the same JSON structure."
        )

    def _normalize_hints(self, plan: Plan) -> Plan:
        """Normalize execution_hint values to valid options."""
        for step in plan.steps:
            if step.execution_hint not in ("tool", "subagent", "remote", "auto"):
                original = step.execution_hint
                step.execution_hint = _SIMPLE_PLANNER_HINT_MAP.get(original, "auto")
                logger.warning("Normalized hint '%s' to '%s'", original, step.execution_hint)

        return plan

    @staticmethod
    def _apply_preferred_subagent(plan: Plan, subagent_name: str) -> Plan:
        """Override plan execution hints to route through an explicitly requested subagent.

        Skips the first step (typically "understand requirements") and the last
        step if it looks like a summary/validation step, so only the core action
        steps are delegated.

        Args:
            plan: Plan to modify (mutated in place and returned).
            subagent_name: Name of the subagent to delegate to.

        Returns:
            The modified plan.
        """
        action_steps = plan.steps[1:] if len(plan.steps) > 1 else plan.steps
        for step in action_steps:
            if step.execution_hint in ("tool", "auto"):
                step.execution_hint = "subagent"
                lowered = f"{step.description[0].lower()}{step.description[1:]}"
                step.description = f"Using the {subagent_name} subagent, {lowered}"
        logger.info("Applied preferred_subagent=%s to %d step(s)", subagent_name, len(action_steps))
        return plan

    def _normalize_hints_in_dict(self, data: dict) -> dict:
        """Normalize execution_hint in dict before Plan creation."""
        if "steps" in data:
            for step in data["steps"]:
                if "execution_hint" in step:
                    hint = step["execution_hint"]
                    if hint not in ("tool", "subagent", "remote", "auto"):
                        step["execution_hint"] = _SIMPLE_PLANNER_HINT_MAP.get(hint, "auto")
        return data

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> Any:
        """Layer 2 Reason phase: assess progress and plan the next act in one LLM call."""
        from soothe.cognition.loop_agent.schemas import ReasonResult

        prompt = self._build_reason_prompt(goal, state, context)
        try:
            response = await self._invoke(prompt)
            return parse_reason_response_text(response, goal)
        except Exception:
            logger.exception("SimplePlanner.reason failed")
            return ReasonResult(
                status="replan",
                plan_action="new",
                decision=_default_agent_decision(goal),
                reasoning="Reason call failed",
                user_summary="Retrying with a simpler plan after a model error",
                soothe_next_action="I'll retry with a simpler next step.",
            )

    def _build_reason_prompt(self, goal: str, state: LoopState, context: PlanContext) -> str:
        """Build unified Reason prompt (assessment + next steps)."""
        return build_loop_reason_prompt(goal, state, context)
