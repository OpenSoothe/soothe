"""SimplePlanner -- single LLM call planner for simple/medium tasks."""

from __future__ import annotations

import json
import logging
from typing import Any

from soothe.backends.planning._shared import reflect_heuristic
from soothe.cognition.loop_agent.schemas import LoopState
from soothe.config import SootheConfig
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)

logger = logging.getLogger(__name__)

_LAYER2_GOAL_ALIGN_SNIP_LEN = 400
_DEFAULT_DECISION_GOAL_SNIP_LEN = 350


def _strip_leading_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    return text.lstrip("\ufeff")


def _strip_markdown_json_fence(response: str) -> str:
    """Extract JSON from ```json ... ``` or generic ``` ... ``` blocks."""
    json_str = response.strip()

    if "```json" in json_str:
        start = json_str.find("```json") + 7
        end = json_str.find("```", start)
        if end > start:
            return json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.find("```") + 3
        newline_pos = json_str.find("\n", start)
        if newline_pos > start:
            start = newline_pos + 1
        end = json_str.find("```", start)
        if end > start:
            return json_str[start:end].strip()

    return json_str


def _extract_balanced_json_object(text: str, start: int | None = None) -> str | None:
    """Return the substring from first ``{`` through its matching ``}``, string-aware.

    Avoids greedy ``{.*}`` mistakes when strings contain ``}`` or when prose follows JSON.
    """
    if start is None:
        start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    backslash = False
    i = start
    while i < len(text):
        c = text[i]
        if backslash:
            backslash = False
        elif in_string:
            if c == "\\":
                backslash = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def _strip_trailing_commas_json(text: str) -> str:
    """Remove JSON trailing commas (`,}` / `,]`) outside of string literals."""
    out: list[str] = []
    in_string = False
    backslash = False
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if backslash:
            out.append(c)
            backslash = False
            i += 1
            continue
        if in_string:
            if c == "\\":
                backslash = True
                out.append(c)
            elif c == '"':
                in_string = False
                out.append(c)
            else:
                out.append(c)
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue

        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\n\r":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue

        out.append(c)
        i += 1

    return "".join(out)


def _try_parse_json_dict(raw: str) -> dict[str, Any] | None:
    """Parse ``raw`` as a JSON object; try trailing-comma repair on failure."""
    relaxed = _strip_trailing_commas_json(raw)
    variants = [raw] if raw == relaxed else [raw, relaxed]
    for candidate in variants:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


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
    """Extract the first JSON object from an LLM response string.

    Tolerates markdown fences, leading prose, trailing commas, and stray text after JSON
    via balanced-brace extraction (string-aware).
    """
    json_str = _strip_leading_bom(_strip_markdown_json_fence(response)).strip()

    if not json_str:
        raise ValueError("Empty LLM response — cannot parse JSON")

    candidates: list[str] = []
    seen: set[str] = set()

    def _add_candidate(s: str) -> None:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    _add_candidate(json_str)

    balanced = _extract_balanced_json_object(json_str)
    if balanced:
        _add_candidate(balanced)

    last_error: json.JSONDecodeError | None = None
    for cand in candidates:
        parsed = _try_parse_json_dict(cand)
        if parsed is not None:
            if cand != candidates[0]:
                logger.debug("Parsed LLM JSON using fallback candidate (length=%d)", len(cand))
            return parsed
        try:
            loaded = json.loads(_strip_trailing_commas_json(cand))
        except json.JSONDecodeError as e:
            last_error = e
        else:
            if not isinstance(loaded, dict):
                last_error = json.JSONDecodeError(
                    "LLM JSON root must be an object (got non-object)",
                    cand,
                    0,
                )

    if last_error is not None:
        raise last_error
    raise TypeError("LLM JSON root must be an object")


def _align_layer2_step_descriptions(goal: str, steps: list[Any]) -> None:
    """Rewrite step text that only echoes the user goal (Layer 1/Layer 2 alignment)."""
    from soothe.cognition.loop_agent.schemas import StepAction

    g = (goal or "").strip().casefold()
    if not g:
        return
    for s in steps:
        if not isinstance(s, StepAction):
            continue
        d = (s.description or "").strip()
        if d.casefold() == g:
            lim = _LAYER2_GOAL_ALIGN_SNIP_LEN
            tail = goal if len(goal) <= lim else goal[: lim - 3] + "…"
            s.description = (
                "Using tools in the open workspace, take concrete actions toward this goal "
                f"(do not use the goal text alone as the step): {tail}"
            )


def agent_decision_from_dict(data: dict[str, Any], _goal: str) -> Any:
    """Build AgentDecision from a parsed JSON object (step list at top level)."""
    from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

    known_subagents = {"browser", "claude", "research"}

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

    _align_layer2_step_descriptions(_goal, steps)

    return AgentDecision(
        type=data.get("type", "execute_steps"),
        steps=steps,
        execution_mode=data.get("execution_mode", "sequential"),
        reasoning=data.get("reasoning", ""),
        adaptive_granularity=data.get("adaptive_granularity"),
    )


def _default_agent_decision(goal: str, iteration: int = 0) -> Any:
    """Minimal single-step decision used when parsing fails.

    Args:
        goal: The goal description
        iteration: Current iteration number for variation

    Returns:
        AgentDecision with iteration-specific action to prevent repetitions
    """
    from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

    lim = _DEFAULT_DECISION_GOAL_SNIP_LEN
    tail = goal if len(goal) <= lim else goal[: lim - 3] + "…"

    # RFC-603: Vary the default action based on iteration to prevent repetitions
    if iteration == 0:
        action_desc = f"Take initial steps toward: {tail}"
    elif iteration == 1:
        action_desc = f"Continue investigation with focused approach for: {tail}"
    else:
        action_desc = f"Refine approach for: {tail}"

    return AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                id="step_0",
                description=action_desc,
                expected_output="Concrete findings or artifacts that satisfy the goal",
            )
        ],
        execution_mode="sequential",
        reasoning=f"Default decision due to parse error at iteration {iteration}",
    )


def _calculate_evidence_based_confidence(
    state: LoopState,
    reason_result: Any,
) -> float:
    """Calculate confidence from evidence, not just LLM self-assessment.

    Formula:
    confidence = (
        llm_confidence * 0.5 +
        success_rate * 0.3 +
        evidence_volume_score * 0.3 +
        iteration_efficiency * 0.4
    ) / 1.5

    Args:
        state: Loop state with accumulated evidence
        reason_result: Reason result with LLM confidence

    Returns:
        Float between 0.0 and 1.0
    """
    # LLM confidence (50% weight)
    llm_confidence = reason_result.confidence or 0.5

    # Success rate (30% weight)
    if not state.step_results:
        success_rate = 0.0
    else:
        successful = sum(1 for r in state.step_results if r.success)
        success_rate = successful / len(state.step_results)

    # Evidence volume (30% weight)
    # 0 chars = 0.0, 2000+ chars = 1.0
    # RFC-211: Use outcome metadata to get size
    total_evidence_length = sum(
        r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results
    )
    evidence_volume_score = min(total_evidence_length / 2000.0, 1.0)

    # Iteration efficiency (40% weight)
    # Higher efficiency = reaching goal faster
    iteration = state.iteration or 1
    max_iterations = 8
    iteration_efficiency = max(0.0, 1.0 - (iteration - 1) / max_iterations)

    # Combined score
    confidence = (
        llm_confidence * 0.5 + success_rate * 0.3 + evidence_volume_score * 0.3 + iteration_efficiency * 0.4
    ) / 1.5

    return min(max(confidence, 0.0), 1.0)  # Clamp to [0, 1]


def _calculate_evidence_based_progress(
    state: LoopState,
    reason_result: Any,
) -> float:
    """Calculate progress from evidence, not just LLM estimate.

    Formula:
    progress = (
        llm_progress * 0.6 +
        step_completion_ratio * 0.2 +
        evidence_growth_rate * 0.2
    )

    Args:
        state: Loop state with accumulated evidence
        reason_result: Reason result with LLM progress

    Returns:
        Float between 0.0 and 1.0
    """
    # Special case: if status is "done", return 1.0
    if reason_result.status == "done":
        return 1.0

    # LLM progress (60% weight)
    llm_progress = reason_result.goal_progress or 0.0

    # Step completion ratio (20% weight)
    if not state.step_results:
        step_completion_ratio = 0.0
    else:
        completed = sum(1 for r in state.step_results if r.success)
        step_completion_ratio = completed / len(state.step_results)

    # Evidence growth rate (20% weight)
    # Compare recent evidence to earlier evidence
    min_results_for_growth = 2
    if len(state.step_results) < min_results_for_growth:
        evidence_growth_rate = 0.5  # Neutral if insufficient data
    else:
        # Recent evidence (last 3 results)
        # RFC-211: Use outcome metadata to get size
        recent_length = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results[-3:]
        )
        # Earlier evidence (first results)
        earlier_length = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results[:3]
        )

        evidence_growth_rate = 0.5 if earlier_length == 0 else min(recent_length / earlier_length, 1.0)

    # Combined score
    progress = llm_progress * 0.6 + step_completion_ratio * 0.2 + evidence_growth_rate * 0.2

    return min(max(progress, 0.0), 1.0)  # Clamp to [0, 1]


def parse_reason_response_text(response: str, goal: str, iteration: int = 0) -> Any:
    """Parse unified Reason JSON into ReasonResult.

    Args:
        response: LLM response text
        goal: Goal description
        iteration: Current iteration number for varied fallback actions
    """
    from soothe.cognition.loop_agent.schemas import ReasonResult

    try:
        data = _load_llm_json_dict(response)
    except Exception:
        logger.exception("[PARSE ERROR] Failed to parse LLM response")
        return ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal, iteration),
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
            decision = _default_agent_decision(goal, iteration)
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
                decision = _default_agent_decision(goal, iteration) if status != "done" else None
        elif status != "done":
            decision = _default_agent_decision(goal, iteration)

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
            decision=_default_agent_decision(goal, iteration),
            reasoning="Invalid reason payload",
            user_summary="Adjusting the plan after an invalid model response",
            soothe_next_action="I'll adjust and try a cleaner plan.",
        )


_SIMPLE_PLANNER_HINT_MAP = {
    "browser": "subagent",
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
        config: Optional Soothe config for RFC-104-aligned planning/reason prefixes.
    """

    def __init__(
        self,
        model: Any,
        config: SootheConfig | None = None,
    ) -> None:
        """Initialize SimplePlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
            config: Optional configuration for shared context XML in prompts.
        """
        from soothe.core.prompts import PromptBuilder

        self._model = model
        self._config = config
        self._prompt_builder = PromptBuilder(config)

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

    async def _invoke_messages(self, messages: list[Any]) -> str:
        """Invoke the LLM with a message list and return the response (RFC-207).

        Used for Reason phase with SystemMessage/HumanMessage separation.

        Args:
            messages: List of BaseMessage objects (SystemMessage, HumanMessage)

        Returns:
            The LLM's response as a string.
        """
        try:
            response = await self._model.ainvoke(messages)
            content = getattr(response, "content", str(response))

            if isinstance(content, str):
                return content

            # Anthropic-style list-of-blocks response
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif hasattr(block, "type") and block.type == "text":
                        text_parts.append(getattr(block, "text", ""))
                return "".join(text_parts)

            return str(content)
        except Exception:
            logger.exception("LLM invocation failed")
            raise

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
            data = _load_llm_json_dict(content)
            return Plan(**self._normalize_hints_in_dict(data))
        except Exception as e:
            logger.warning("JSON parsing failed: %s", e)
            return Plan(
                goal=fallback_goal or "Unnamed goal",
                steps=[{"id": "S_1", "description": fallback_goal or "Execute task"}],
            )

    def _build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        """Build unified planning prompt with XML sections (RFC-104 alignment)."""
        from soothe.core.prompts.context_xml import build_shared_environment_workspace_prefix

        sections = []

        # Goal section
        sections.append(f"<PLANNING_GOAL>\n{goal}\n</PLANNING_GOAL>")

        # Workspace context as XML section
        if context.workspace:
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
                # RFC-211: Use outcome metadata instead of output
                output_preview = step.to_evidence_string(truncate=True)[:80]
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

        body = "\n\n".join(sections)
        if self._config is not None:
            prefix = build_shared_environment_workspace_prefix(
                self._config,
                context.workspace,
                context.git_status,
                include_workspace_extras=True,
            )
            return f"{prefix}{body}"
        return body

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

        messages = self._prompt_builder.build_reason_messages(goal, state, context)

        # LLM tracing - verbose debug logs for prompt analysis
        logger.debug("[SimplePlanner.reason] ====== Messages to LLM ======")
        logger.debug("[SimplePlanner.reason] Message count: %d", len(messages))
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            content_len = len(str(msg.content)) if hasattr(msg, "content") else len(str(msg))
            logger.debug(
                "[SimplePlanner.reason] Message %d: type=%s, content_len=%d",
                i,
                msg_type,
                content_len,
            )
            # Log FULL message content for complete visibility
            full_content = str(msg.content) if hasattr(msg, "content") else str(msg)
            logger.debug(
                "[SimplePlanner.reason] Message %d FULL CONTENT:\n%s",
                i,
                full_content,
            )
        logger.debug("[SimplePlanner.reason] ====== End Messages ======")

        try:
            # Use structured output to enforce ReasonResult schema (fixes tool-call token issue)
            structured_model = self._model.with_structured_output(ReasonResult)
            result = await structured_model.ainvoke(messages)

            # LLM tracing - verbose debug logs for structured result
            logger.debug("[SimplePlanner.reason] ====== Structured ReasonResult ======")
            logger.debug("[SimplePlanner.reason] Status: %s", result.status)
            logger.debug(
                "[SimplePlanner.reason] Plan action: %s, has_decision: %s",
                result.plan_action,
                result.decision is not None,
            )
            logger.debug(
                "[SimplePlanner.reason] Progress: %.0f%%, Confidence: %.0f%%",
                result.goal_progress * 100,
                result.confidence * 100,
            )
            logger.debug("[SimplePlanner.reason] ====== End Structured Result ======")
        except Exception:
            logger.exception("SimplePlanner.reason failed")
            return ReasonResult(
                status="replan",
                plan_action="new",
                decision=_default_agent_decision(goal, state.iteration),
                reasoning="Reason call failed",
                user_summary="Retrying with a simpler plan after a model error",
                soothe_next_action="I'll retry with a simpler next step.",
            )
        else:
            # RFC-603: Apply evidence-based confidence and progress
            result.confidence = _calculate_evidence_based_confidence(state, result)
            result.goal_progress = _calculate_evidence_based_progress(state, result)
            return result
