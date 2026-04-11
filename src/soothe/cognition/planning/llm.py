"""LLMPlanner -- single LLM call planner for simple/medium tasks."""

from __future__ import annotations

import json
import logging
from typing import Any

from soothe.cognition.planning._shared import reflect_heuristic
from soothe.cognition.agent_loop.schemas import LoopState
from soothe.config import SootheConfig
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)
from soothe.utils.text_preview import create_output_summary

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


def _repair_truncated_json(text: str) -> str:
    """Repair truncated JSON by closing unclosed strings and brackets.

    Handles cases where LLM output is cut off mid-string or mid-structure.
    Attempt to make it parseable by adding necessary closing characters.

    Args:
        text: Potentially truncated JSON string

    Returns:
        Repaired JSON string (may still be invalid if severely truncated)
    """
    # Track bracket depth and string state
    bracket_stack: list[str] = []
    in_string = False
    backslash = False
    last_char = ""

    # Scan the string to find unclosed structures
    for c in text:
        if backslash:
            backslash = False
        elif in_string:
            if c == "\\":
                backslash = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c in "{[":
            bracket_stack.append(c)
        elif c == "}":
            if bracket_stack and bracket_stack[-1] == "{":
                bracket_stack.pop()
        elif c == "]":
            if bracket_stack and bracket_stack[-1] == "[":
                bracket_stack.pop()
        last_char = c

    # Build repair: close unclosed structures
    repair = ""

    # If still in a string, close it
    if in_string:
        repair += '"'

    # Close any remaining brackets in reverse order
    while bracket_stack:
        open_bracket = bracket_stack.pop()
        if open_bracket == "{":
            repair += "}"
        elif open_bracket == "[":
            repair += "]"

    # If the text ends with a comma (truncated before next value), remove it
    if last_char == ",":
        text = text[:-1]

    repaired = text + repair

    if repair:
        logger.debug(
            "[LLMPlanner] JSON repair: added %d closing chars (%s) to truncated JSON",
            len(repair),
            repair,
        )

    return repaired


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
    from soothe.cognition.agent_loop.schemas import StepAction

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
    from soothe.cognition.agent_loop.schemas import AgentDecision, StepAction

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
    from soothe.cognition.agent_loop.schemas import AgentDecision, StepAction

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


def _detect_completion_fallback(
    state: LoopState,
    reason_result: Any,
    goal: str,
) -> Any:
    """Detect completion when LLM fails to set status="done" despite evidence.

    This is a fallback mechanism to prevent infinite loops when the LLM
    doesn't recognize clear completion signals.

    Criteria for forced completion:
    1. High evidence volume (≥10,000 chars) with no new discoveries
    2. Action repetition across iterations
    3. Diminishing returns (no evidence growth in recent iterations)
    4. All steps successful with substantial output

    Args:
        state: Current loop state with step results
        reason_result: Reason result from LLM
        goal: The original goal

    Returns:
        ReasonResult with status potentially updated to "done"
    """
    # Only override if LLM returned status != "done"
    if reason_result.status == "done":
        return reason_result

    # Check completion indicators
    completion_indicators = []

    # 1. Action repetition detection
    if len(state.action_history) >= 2:
        recent_actions = state.get_recent_actions(2)
        if len(recent_actions) == 2:
            # Normalize actions for comparison
            action1 = recent_actions[0].lower().strip()
            action2 = recent_actions[1].lower().strip()
            if action1 == action2 or _actions_semantically_similar(action1, action2):
                completion_indicators.append("action_repetition")
                logger.info(
                    "[Completion Detection] Detected action repetition: '%s' -> '%s'",
                    action1[:50],
                    action2[:50],
                )

    # 2. Evidence volume threshold
    total_evidence_chars = sum(
        r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results
    )
    if total_evidence_chars >= 10_000 and reason_result.goal_progress >= 0.8:
        completion_indicators.append("high_evidence_volume")
        logger.info(
            "[Completion Detection] High evidence volume: %d chars, progress %.0f%%",
            total_evidence_chars,
            reason_result.goal_progress * 100,
        )

    # 3. Diminishing returns (no evidence growth in last iteration)
    if len(state.step_results) >= 2:
        recent_size = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results[-2:]
        )
        earlier_size = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results[:-2]
        )
        # If recent iterations added < 10% new evidence
        if earlier_size > 0 and recent_size < earlier_size * 0.1:
            completion_indicators.append("diminishing_returns")
            logger.info(
                "[Completion Detection] Diminishing returns: earlier=%d, recent=%d",
                earlier_size,
                recent_size,
            )

    # 4. All steps successful with substantial output
    if state.step_results:
        all_successful = all(r.success for r in state.step_results)
        has_substantial_output = any(
            r.outcome.get("size_bytes", 0) > 5000 for r in state.step_results if r.success and r.outcome
        )
        if all_successful and has_substantial_output and reason_result.goal_progress >= 0.85:
            completion_indicators.append("all_steps_successful")
            logger.info(
                "[Completion Detection] All %d steps successful with substantial output",
                len(state.step_results),
            )

    # Decision: force completion if ≥2 indicators OR action repetition
    if len(completion_indicators) >= 2 or "action_repetition" in completion_indicators:
        logger.warning(
            "[Completion Detection] Forcing status='done' due to: %s (LLM returned status='%s')",
            ", ".join(completion_indicators),
            reason_result.status,
        )
        # Update result to mark as done
        updated = reason_result.model_copy(
            update={
                "status": "done",
                "goal_progress": max(reason_result.goal_progress, 0.95),
                "next_action": reason_result.next_action or "I've completed the task.",
            }
        )
        return updated

    return reason_result


def _actions_semantically_similar(action1: str, action2: str) -> bool:
    """Check if two actions are semantically similar despite wording differences.

    Args:
        action1: First action description
        action2: Second action description

    Returns:
        True if actions are semantically similar
    """
    # Normalize both actions
    norm1 = action1.lower().strip()
    norm2 = action2.lower().strip()

    # Remove common filler words
    fillers = {"use", "using", "will", "to", "the", "in", "for", "and", "with"}
    words1 = set(w for w in norm1.split() if w not in fillers)
    words2 = set(w for w in norm2.split() if w not in fillers)

    # Check Jaccard similarity
    if not words1 or not words2:
        return False

    intersection = words1 & words2
    union = words1 | words2
    similarity = len(intersection) / len(union)

    return similarity >= 0.7  # 70% word overlap indicates similar actions


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
    from soothe.cognition.agent_loop.schemas import ReasonResult

    try:
        data = _load_llm_json_dict(response)
    except Exception:
        logger.exception("[PARSE ERROR] Failed to parse LLM response")
        return ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal, iteration),
            reasoning="Failed to parse model response",
            next_action="I'll try again with a simpler plan.",
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
            next_action="I'll run the steps in this plan next.",
        )

    status = data.get("status", "replan")
    if status not in ("continue", "replan", "done"):
        status = "replan"

    plan_action = data.get("plan_action", "new")
    if plan_action not in ("keep", "new"):
        plan_action = "new"

    reasoning = str(data.get("reasoning", "") or "")

    next_action = str(data.get("next_action", "") or str(data.get("soothe_next_action", "") or "")).strip()

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
            next_action=next_action,
            evidence_summary=str(data.get("evidence_summary", "") or ""),
        )
    except Exception:
        logger.exception("Invalid ReasonResult fields")
        return ReasonResult(
            status="replan",
            plan_action="new",
            decision=_default_agent_decision(goal, iteration),
            reasoning="Invalid reason payload",
            next_action="I'll adjust and try a cleaner plan.",
        )


_SIMPLE_PLANNER_HINT_MAP = {
    "browser": "subagent",
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


class LLMPlanner:
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
        """Initialize LLMPlanner.

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
            logger.warning("LLMPlanner._invoke failed: %s", e)
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

    async def _assess_status(
        self,
        messages: list[Any],
        goal: str,
        iteration: int,
    ) -> Any:
        """Phase 1: Quick status assessment (RFC-604 Layer 2).

        Lightweight call to assess goal progress without full plan generation.
        Generates ~200-250 tokens per call.

        Args:
            messages: Prompt messages from build_reason_messages()
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback

        Returns:
            StatusAssessment with status, progress, confidence, brief_reasoning, next_action
        """
        from soothe.cognition.agent_loop.schemas import StatusAssessment

        structured_model = self._model.with_structured_output(StatusAssessment)

        logger.debug("[LLMPlanner] Calling StatusAssessment")

        try:
            assessment = await structured_model.ainvoke(messages)

            if assessment is None:
                raise ValueError("StatusAssessment returned None")

            logger.debug(
                "[LLMPlanner] StatusAssessment result: status=%s, progress=%.0f%%, action=%s",
                assessment.status,
                assessment.goal_progress * 100,
                assessment.next_action[:50] if assessment.next_action else "",
            )

            return assessment

        except Exception as e:
            logger.warning("[LLMPlanner] StatusAssessment failed: %s", str(e)[:200])
            # Fallback: return conservative assessment
            return StatusAssessment(
                status="replan",
                goal_progress=0.0,
                confidence=0.5,
                brief_reasoning="Status assessment failed, proceeding with conservative defaults",
                next_action="I'll retry with a simpler approach.",
            )

    async def _generate_plan(
        self,
        messages: list[Any],
        assessment: Any,
        goal: str,
        iteration: int,
    ) -> Any:
        """Phase 2: Generate execution plan (RFC-604 Layer 2).

        Conditional call to generate plan when status != "done".
        Generates ~500-800 tokens per call.

        Args:
            messages: Original prompt messages
            assessment: Phase 1 status assessment
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback

        Returns:
            PlanGeneration with plan_action, decision, brief_reasoning, next_action
        """
        from langchain_core.messages import SystemMessage
        from soothe.cognition.agent_loop.schemas import PlanGeneration

        # Add assessment context to plan generation prompt
        context_msg = SystemMessage(content=f"Status: {assessment.status}, Progress: {assessment.goal_progress:.0%}")
        plan_messages = messages + [context_msg]

        structured_model = self._model.with_structured_output(PlanGeneration)

        logger.debug(
            "[LLMPlanner] Calling PlanGeneration (status=%s, progress=%.0f%%)",
            assessment.status,
            assessment.goal_progress * 100,
        )

        try:
            plan_result = await structured_model.ainvoke(plan_messages)

            if plan_result is None:
                raise ValueError("PlanGeneration returned None")

            logger.debug(
                "[LLMPlanner] PlanGeneration result: plan_action=%s, steps=%d, action=%s",
                plan_result.plan_action,
                len(plan_result.decision.steps) if plan_result.decision else 0,
                plan_result.next_action[:50] if plan_result.next_action else "",
            )

            return plan_result

        except Exception as e:
            logger.warning("[LLMPlanner] PlanGeneration failed: %s", str(e)[:200])
            # Fallback: return default plan
            return PlanGeneration(
                plan_action="new",
                decision=_default_agent_decision(goal, iteration),
                brief_reasoning="Plan generation failed, using default plan",
                next_action="I'll proceed with a fallback plan.",
            )

    def _combine_results(
        self,
        assessment: Any,
        plan_result: Any,
    ) -> Any:
        """Combine Phase 1 and Phase 2 results (RFC-604 Layer 2).

        Concatenates reasoning and next_action from both phases.

        Args:
            assessment: Phase 1 StatusAssessment
            plan_result: Phase 2 PlanGeneration

        Returns:
            ReasonResult with combined reasoning and next_action
        """
        from soothe.cognition.agent_loop.schemas import ReasonResult

        # Concatenate reasoning from both phases
        combined_reasoning = f"[Assessment] {assessment.brief_reasoning}\n[Plan] {plan_result.brief_reasoning}"

        # Concatenate next_action from both phases
        combined_next_action = f"{assessment.next_action}\n{plan_result.next_action}"

        # Build final ReasonResult
        return ReasonResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            confidence=assessment.confidence,
            reasoning=combined_reasoning,
            plan_action=plan_result.plan_action,
            decision=plan_result.decision,
            next_action=combined_next_action,
        )

    async def reason(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> Any:
        """Layer 2 Reason phase: two-call architecture (RFC-604).

        Phase 1: StatusAssessment (lightweight, ~200-250 tokens)
        Phase 2: PlanGeneration (conditional, ~500-800 tokens)

        Returns combined ReasonResult with evidence-based metrics applied.
        """
        from soothe.cognition.agent_loop.schemas import ReasonResult, StatusAssessment

        messages = self._prompt_builder.build_reason_messages(goal, state, context)

        # Compact LLM input summary
        msg_summary = {
            "count": len(messages),
            "types": [type(m).__name__ for m in messages],
        }
        from langchain_core.messages import HumanMessage

        for msg in messages:
            if isinstance(msg, HumanMessage):
                preview = create_output_summary(msg.content, first_chars=300, last_chars=200)
                msg_summary["human_msg_preview"] = preview
                break
        logger.debug("[LLMPlanner] Input messages: %s", msg_summary)

        # RFC-604 Layer 3: Retry logic with fallback
        max_retries = 3
        result = None

        for attempt in range(max_retries):
            try:
                # Status Assessment
                assessment = await self._assess_status(messages, goal, state.iteration)

                # Early completion optimization: skip plan generation if status="done"
                if assessment.status == "done":
                    logger.debug("[LLMPlanner] Early completion: status=done, skipping plan generation")
                    # Build ReasonResult from assessment only
                    result = ReasonResult(
                        status=assessment.status,
                        goal_progress=assessment.goal_progress,
                        confidence=assessment.confidence,
                        reasoning=assessment.brief_reasoning,
                        plan_action="keep",  # No plan needed
                        decision=None,
                        next_action=assessment.next_action,
                    )
                else:
                    # Plan Generation
                    plan_result = await self._generate_plan(messages, assessment, goal, state.iteration)

                    # Combine results
                    result = self._combine_results(assessment, plan_result)

                # Success
                result_dict = {
                    "status": result.status,
                    "plan": result.plan_action,
                    "progress": f"{result.goal_progress * 100:.0f}%",
                    "conf": f"{result.confidence * 100:.0f}%",
                }
                if result.decision:
                    result_dict["decision"] = {
                        "type": result.decision.type,
                        "mode": result.decision.execution_mode,
                        "steps": len(result.decision.steps),
                    }
                if result.reasoning:
                    result_dict["reasoning"] = result.reasoning[:200]
                logger.debug("[LLMPlanner] Combined output: %s", result_dict)
                break  # Success, exit retry loop

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)

                is_json_error = "json_invalid" in error_msg.lower() or "JSON" in error_type
                if is_json_error:
                    import re

                    input_value_match = re.search(r"input_value='([^']+)'", error_msg)
                    if input_value_match:
                        truncated_json = input_value_match.group(1)
                        logger.debug(
                            "[LLMPlanner] Invalid JSON payload (length ~%d chars): %s",
                            len(truncated_json),
                            create_output_summary(truncated_json, first_chars=800, last_chars=400),
                        )

                if attempt < max_retries - 1:
                    logger.warning(
                        "[LLMPlanner] Reason call failed (attempt %d/%d): %s - %s. Retrying...",
                        attempt + 1,
                        max_retries,
                        error_type,
                        error_msg[:200] if is_json_error else error_msg,
                    )
                    # Fallback: regular model + manual JSON parsing (Layer 3)
                    if is_json_error and attempt == max_retries - 2:
                        logger.info("[LLMPlanner] Trying fallback: regular model + manual JSON parsing")
                        try:
                            response = await self._model.ainvoke(messages)
                            raw_content = _extract_text_content(response.content)

                            logger.debug(
                                "[LLMPlanner] Fallback raw response: %s",
                                create_output_summary(raw_content, first_chars=500, last_chars=300),
                            )

                            # Extract and repair JSON
                            json_str = _strip_markdown_json_fence(raw_content)
                            json_obj = _extract_balanced_json_object(json_str)

                            if json_obj:
                                repaired_json = _repair_truncated_json(json_obj)
                                parsed_dict = _try_parse_json_dict(repaired_json)

                                if parsed_dict:
                                    # Try to parse as StatusAssessment first, then as PlanGeneration
                                    try:
                                        assessment = StatusAssessment(**parsed_dict)
                                        # If status != "done", try to get plan
                                        if assessment.status != "done":
                                            # Need to parse plan separately
                                            # For simplicity, use default decision
                                            result = ReasonResult(
                                                status=assessment.status,
                                                goal_progress=assessment.goal_progress,
                                                confidence=assessment.confidence,
                                                reasoning=assessment.brief_reasoning,
                                                plan_action="new",
                                                decision=_default_agent_decision(goal, state.iteration),
                                                next_action=assessment.next_action,
                                            )
                                        else:
                                            result = ReasonResult(
                                                status=assessment.status,
                                                goal_progress=assessment.goal_progress,
                                                confidence=assessment.confidence,
                                                reasoning=assessment.brief_reasoning,
                                                plan_action="keep",
                                                decision=None,
                                                next_action=assessment.next_action,
                                            )
                                    except Exception:
                                        # Fallback: parse as ReasonResult directly
                                        result = ReasonResult(**parsed_dict)

                                    logger.info("[LLMPlanner] Manual JSON parsing succeeded on retry %d", attempt + 1)
                                    break
                        except Exception as fallback_error:
                            logger.warning("[LLMPlanner] Fallback parsing also failed: %s", str(fallback_error)[:200])
                else:
                    # Final attempt failed
                    logger.exception("[LLMPlanner] Reason call failed after %d attempts", max_retries)
                    return ReasonResult(
                        status="replan",
                        plan_action="new",
                        decision=_default_agent_decision(goal, state.iteration),
                        reasoning=f"Reason call failed after {max_retries} retries: {error_msg[:100]}",
                        next_action="I'll retry with a simpler next step.",
                    )

        # RFC-603: Apply evidence-based confidence and progress
        result.confidence = _calculate_evidence_based_confidence(state, result)
        result.goal_progress = _calculate_evidence_based_progress(state, result)

        # Fallback completion detection (IG-134)
        result = _detect_completion_fallback(state, result, goal)

        return result
