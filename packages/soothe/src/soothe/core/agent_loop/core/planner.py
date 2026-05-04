"""LLMPlanner -- RFC-604 Plan-phase planner (sequential structured LLM calls)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

from soothe.core.agent_loop.state.schemas import AgentDecision, LoopState, StepAction
from soothe.core.agent_loop.utils.json_parsing import (
    _extract_balanced_json_object,
    _load_llm_json_dict,
    _repair_truncated_json,
    _strip_markdown_json_fence,
    _try_parse_json_dict,
)
from soothe.core.agent_loop.utils.messages import LoopHumanMessage
from soothe.core.agent_loop.utils.reflection import (
    _default_agent_decision,
    _extract_text_content,
    reflect_heuristic,
)
from soothe.middleware.llm_rate_limit import _estimate_content_chars
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.text_preview import create_output_summary, preview_first

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def _calculate_evidence_based_confidence(
    state: LoopState,
    plan_result: Any,
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
        plan_result: Plan result with LLM confidence

    Returns:
        Float between 0.0 and 1.0
    """
    # LLM confidence (50% weight)
    llm_confidence = plan_result.confidence or 0.5

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
        llm_confidence * 0.5
        + success_rate * 0.3
        + evidence_volume_score * 0.3
        + iteration_efficiency * 0.4
    ) / 1.5

    return min(max(confidence, 0.0), 1.0)  # Clamp to [0, 1]


def _plan_phase_chat_model(model: Any) -> Any:
    """Return model for RFC-604 assess/plan structured calls (IG-358).

    Binds ``temperature=0`` when the chat model supports it so structured JSON is
    faster and more deterministic on most providers.
    """
    try:
        return model.bind(temperature=0)  # type: ignore[union-attr]
    except Exception:
        return model


def _detect_completion_fallback(
    state: LoopState,
    plan_result: Any,
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
        plan_result: Plan result from LLM
        goal: The original goal

    Returns:
        PlanResult with status potentially updated to "done"
    """
    # Only override if LLM returned status != "done"
    if plan_result.status == "done":
        return plan_result

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
                    "[Completion] action-repeat: '%s' → '%s'",
                    action1,
                    action2,
                )

    # 2. Evidence volume threshold
    total_evidence_chars = sum(
        r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0 for r in state.step_results
    )
    if total_evidence_chars >= 10_000 and plan_result.goal_progress >= 0.8:
        completion_indicators.append("high_evidence_volume")
        logger.info(
            "[Completion] high-evidence: %d chars prog=%.0f%%",
            total_evidence_chars,
            plan_result.goal_progress * 100,
        )

    # 3. Diminishing returns (no evidence growth in last iteration)
    if len(state.step_results) >= 2:
        recent_size = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0
            for r in state.step_results[-2:]
        )
        earlier_size = sum(
            r.outcome.get("size_bytes", 0) if r.success and r.outcome else 0
            for r in state.step_results[:-2]
        )
        # If recent iterations added < 10% new evidence
        if earlier_size > 0 and recent_size < earlier_size * 0.1:
            completion_indicators.append("diminishing_returns")
            logger.info(
                "[Completion] diminishing: earlier=%d recent=%d",
                earlier_size,
                recent_size,
            )

    # 4. All steps successful with substantial output
    if state.step_results:
        all_successful = all(r.success for r in state.step_results)
        has_substantial_output = any(
            r.outcome.get("size_bytes", 0) > 5000
            for r in state.step_results
            if r.success and r.outcome
        )
        if all_successful and has_substantial_output and plan_result.goal_progress >= 0.85:
            completion_indicators.append("all_steps_successful")
            logger.info(
                "[Completion] all-success: %d steps prog=%.0f%%",
                len(state.step_results),
                plan_result.goal_progress * 100,
            )

    # Decision: force completion if ≥2 indicators OR action repetition
    if len(completion_indicators) >= 2 or "action_repetition" in completion_indicators:
        logger.warning(
            "[Completion] force-done: %s (LLM=%s)",
            ", ".join(completion_indicators),
            plan_result.status,
        )
        # Update result to mark as done
        updated = plan_result.model_copy(
            update={
                "status": "done",
                "goal_progress": max(plan_result.goal_progress, 0.95),
                "next_action": plan_result.next_action or "I've completed the task.",
            }
        )
        return updated

    return plan_result


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


_SIMPLE_PLANNER_HINT_MAP = {
    "browser": "subagent",
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


class LLMPlanner:
    """PlannerProtocol for AgentLoop Plan phase using RFC-604 structured LLM calls.

    For simple/medium tasks. Produces flat plans (typically 1-3 steps).

    Flow:
    - ``StatusAssessment`` runs each iteration.
    - If status is not ``done``, ``PlanGeneration`` runs (two LLM calls).
    - If status is ``done`` after assessment, goal-completion policy runs without plan generation.

    Heuristic reflection uses no LLM (see ``reflect``).

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

    def _planner_langfuse_run_config(
        self,
        *,
        thread_id: str | None,
        phase: str,
    ) -> dict[str, Any] | None:
        """RunnableConfig for planner LLM calls when Langfuse is enabled (IG-369)."""
        if self._config is None:
            return None
        base: dict[str, Any] = {}
        tn = (self._config.observability.langfuse.trace_name or "").strip()
        run_name = f"{tn}:{phase}" if tn else phase
        merged = merge_langfuse_runnable_config(
            base,
            self._config,
            session_id=thread_id,
            run_name=run_name,
        )
        if merged is base:
            return None
        return merged

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

    async def revise_plan(
        self,
        plan: Plan,
        reflection: str,
        *,
        thread_id: str | None = None,
    ) -> Plan:
        """Revise plan based on reflection feedback."""
        prompt = self._build_revision_prompt(plan, reflection)

        try:
            structured_model = self._model.with_structured_output(Plan)
            lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="revise-plan")
            if lf_cfg is not None:
                revised = await structured_model.ainvoke(prompt, config=lf_cfg)
            else:
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
        agentloop_result: Any | None = None,  # IG-154: AgentLoop GoalResult
    ) -> Reflection:
        """Reflection with AgentLoop integration support (IG-154).

        When agentloop_result is provided (from AgentLoop delegation), uses
        AgentLoop's evidence and judgment for reflection instead of step_results.

        Args:
            plan: The plan (None when AgentLoop handles execution).
            step_results: Step execution results (empty when AgentLoop handles execution).
            goal_context: Goal DAG context for autonomous goal management.
            agentloop_result: GoalResult from AgentLoop delegation (when delegating).

        Returns:
            Reflection with assessment and goal directives for DAG restructuring.
        """
        # IG-154: AgentLoop integration - use GoalResult when available
        if agentloop_result:
            logger.info(
                "Using AgentLoop result for reflection (status=%s, progress=%.0f%%, confidence=%.0f%%)",
                agentloop_result.status,
                agentloop_result.goal_progress * 100,
                agentloop_result.confidence * 100,
            )

            # Build assessment from AgentLoop evidence
            evidence_preview = (
                agentloop_result.evidence_summary[:300] if agentloop_result.evidence_summary else ""
            )
            assessment = f"AgentLoop achieved {agentloop_result.goal_progress:.0%} progress (confidence {agentloop_result.confidence:.0%}). "

            if agentloop_result.status == "completed":
                assessment += f"Goal successfully completed. {evidence_preview}"
            elif agentloop_result.status == "failed":
                assessment += f"Goal execution failed. {evidence_preview}"
            else:
                assessment += f"Goal execution in progress. {evidence_preview}"

            # Determine if revision needed
            should_revise = agentloop_result.status == "failed" or (
                agentloop_result.goal_progress < 0.7 and agentloop_result.confidence < 0.6
            )

            # Generate feedback
            if agentloop_result.status == "completed":
                feedback = "Goal achieved successfully via AgentLoop execution."
            elif agentloop_result.status == "failed":
                feedback = "Goal not achieved. Consider alternative approach or create dependency prerequisites."
            else:
                feedback = "Goal partially achieved. May need continuation or alternative strategy."

            # Generate goal directives based on AgentLoop outcome
            from soothe.protocols.planner import GoalDirective

            directives = []

            if agentloop_result.status == "failed" and goal_context:
                # Failed goal: try alternative approach or decompose
                logger.info("AgentLoop goal failed, generating recovery directives")

                # Create alternative goal with lower priority
                directives.append(
                    GoalDirective(
                        action="create",
                        description=f"Alternative approach for: {goal_context.current_goal_id}",
                        priority=max(
                            goal_context.current_goal_id.priority - 10
                            if hasattr(goal_context.current_goal_id, "priority")
                            else 40,
                            10,
                        ),
                        reason="Primary approach failed via AgentLoop",
                    )
                )

                # Or decompose into smaller sub-goals
                if agentloop_result.goal_progress < 0.3:
                    directives.append(
                        GoalDirective(
                            action="decompose",
                            goal_id=goal_context.current_goal_id,
                            description="Decompose failed goal into simpler subtasks",
                            reason="Very low progress suggests goal too complex for current approach",
                        )
                    )

            elif agentloop_result.status == "completed" and agentloop_result.goal_progress > 0.95:
                # Successfully completed: mark goal complete
                directives.append(
                    GoalDirective(
                        action="complete",
                        goal_id=goal_context.current_goal_id if goal_context else None,
                        description="Goal completed successfully",
                        reason="AgentLoop achieved >95% progress with high confidence",
                    )
                )

            return Reflection(
                assessment=assessment,
                should_revise=should_revise,
                feedback=feedback,
                goal_directives=directives,
            )

        # Fallback: Use heuristic reflection for step_results-based analysis
        return reflect_heuristic(plan, step_results, goal_context)

    async def _invoke_messages(self, messages: list[Any]) -> str:
        """Invoke the LLM with a message list and return the response (RFC-207).

        Used for Plan phase with SystemMessage/HumanMessage separation.

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
        try:
            human_msg = LoopHumanMessage(content=prompt)  # No thread context
            response = await self._model.ainvoke([human_msg])
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
            lf_cfg = self._planner_langfuse_run_config(
                thread_id=context.thread_id, phase="create-plan-structured"
            )
            if lf_cfg is not None:
                plan = await structured_model.ainvoke(prompt, config=lf_cfg)
            else:
                plan = await structured_model.ainvoke(prompt)
            return self._normalize_hints(plan)
        except Exception as e:
            logger.warning("Structured output failed, trying manual parse: %s", e)
            return await self._fallback_parse(goal, prompt, thread_id=context.thread_id)

    async def _fallback_parse(
        self, goal: str, prompt: str, *, thread_id: str | None = None
    ) -> Plan:
        """Fallback plan parsing from raw LLM response."""
        try:
            lf_cfg = self._planner_langfuse_run_config(
                thread_id=thread_id, phase="create-plan-fallback"
            )
            if lf_cfg is not None:
                response = await self._model.ainvoke(prompt, config=lf_cfg)
            else:
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
                "- delegating browser, claude, or research for trivial local file ops (use direct file tools)",
                "- using explore for writes, deletes, shell mutation, or anything outside readonly search",
                "- searching system directories (/etc, /Library, /usr, /System, /Applications)",
                "- listing root filesystem (/)",
                "</FORBIDDEN_ACTIONS>",
            ]
            sections.append(
                "<PLANNING_WORKSPACE>\n" + "\n".join(workspace_content) + "\n</PLANNING_WORKSPACE>"
            )

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
            sections.append(
                "<PLANNING_COMPLETED>\n" + "\n".join(completed_lines) + "\n</PLANNING_COMPLETED>"
            )

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
            "- Trivial local skim: one step (list_files + selective read_file); heavy readonly recon: prefer subagent explore (scoped target per step)",
            "- For project structure: single step listing top-level directories",
            "- Avoid duplicate paths; batch sequential related reads—independent readonly probes may stay separate steps",
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
    def _preferred_subagent_step_description(description: str, subagent_name: str) -> str:
        """User-facing step text when wiring an explicit subagent (IG-349, shared with Plan path)."""
        desc = (description or "").strip()
        if not desc:
            return f"Using the {subagent_name} subagent."
        lowered = f"{desc[0].lower()}{desc[1:]}"
        return f"Using the {subagent_name} subagent, {lowered}"

    @staticmethod
    def _apply_preferred_subagent(plan: Plan, subagent_name: str) -> Plan:
        """Override plan execution hints to route through an explicitly requested subagent.

        Action steps (same skip rule as ``_apply_preferred_subagent_to_decision``: skip the
        first step when the plan has more than one step) get ``PlanStep.subagent`` set so the
        delegate is explicit. Tool/auto hints become ``execution_hint=subagent`` with rewritten
        descriptions. DeepAgents surfaces delegation as the ``task`` tool; Act streaming turns
        those completions into RFC-211 outcomes that ``PlanPhase`` feeds back like other tools
        (IG-352).

        Args:
            plan: Plan to modify (mutated in place and returned).
            subagent_name: Name of the subagent to delegate to.

        Returns:
            The modified plan.
        """
        action_steps = plan.steps[1:] if len(plan.steps) > 1 else plan.steps
        for step in action_steps:
            step.subagent = subagent_name
            if step.execution_hint in ("tool", "auto"):
                step.execution_hint = "subagent"
                step.description = LLMPlanner._preferred_subagent_step_description(
                    step.description, subagent_name
                )
        logger.info("Applied preferred_subagent=%s to %d step(s)", subagent_name, len(action_steps))
        return plan

    @staticmethod
    def _apply_preferred_subagent_to_decision(
        decision: AgentDecision,
        subagent_name: str,
    ) -> AgentDecision:
        """Apply wire ``preferred_subagent`` to ``AgentDecision`` steps (IG-349, mirrors Plan path)."""
        if not decision.steps:
            return decision
        n = len(decision.steps)
        start = 1 if n > 1 else 0
        new_steps: list[StepAction] = []
        for i, step in enumerate(decision.steps):
            if i < start:
                new_steps.append(step)
                continue
            new_steps.append(
                step.model_copy(
                    update={
                        "subagent": subagent_name,
                        "description": LLMPlanner._preferred_subagent_step_description(
                            step.description, subagent_name
                        ),
                    }
                )
            )
        out = decision.model_copy(update={"steps": new_steps})
        logger.info(
            "Applied preferred_subagent=%s to AgentDecision (%d action step(s))",
            subagent_name,
            n - start,
        )
        return out

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
        *,
        thread_id: str | None,
    ) -> Any:
        """StatusAssessment call: assess goal progress without plan generation (RFC-604).

        Lightweight structured output call to evaluate current goal status.
        Generates ~200-250 tokens per call.

        Args:
            messages: Assess-phase messages from ``build_plan_messages(..., plan_phase=\"assess\")``
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            StatusAssessment with status, progress, confidence.
        """
        from soothe.core.agent_loop.state.schemas import StatusAssessment

        structured_model = _plan_phase_chat_model(self._model).with_structured_output(
            StatusAssessment
        )

        try:
            lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="plan-assess")
            if lf_cfg is not None:
                assessment = await structured_model.ainvoke(messages, config=lf_cfg)
            else:
                assessment = await structured_model.ainvoke(messages)

            if assessment is None:
                raise ValueError("StatusAssessment returned None")

            logger.debug(
                "Assess: status=%s prog=%.0f%% conf=%.0f%%",
                assessment.status,
                assessment.goal_progress * 100,
                assessment.confidence * 100,
            )

            return assessment

        except Exception as e:
            logger.warning("[LLMPlanner] StatusAssessment failed: %s", str(e)[:200])
            # Fallback: return conservative assessment (minimal fields)
            return StatusAssessment(
                status="replan",
                goal_progress=0.0,
                confidence=0.5,
                require_goal_completion=False,  # Default: skip synthesis
            )

    async def _generate_plan(
        self,
        messages: list[Any],
        assessment: Any,
        goal: str,
        iteration: int,
        *,
        thread_id: str | None,
    ) -> Any:
        """PlanGeneration call: generate execution plan when goal incomplete (RFC-604).

        Conditional structured output call to generate plan when status != "done".
        Generates ~500-800 tokens per call.

        Args:
            messages: Generate-phase messages from ``build_plan_messages(..., plan_phase=\"generate\")``
            assessment: StatusAssessment result from previous call
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            PlanGeneration with plan_action, decision.
        """
        from langchain_core.messages import SystemMessage

        from soothe.core.agent_loop.state.schemas import PlanGeneration

        # Add assessment context to plan generation prompt
        context_msg = SystemMessage(
            content=f"Status: {assessment.status}, Progress: {assessment.goal_progress:.0%}"
        )
        plan_messages = messages + [context_msg]

        structured_model = _plan_phase_chat_model(self._model).with_structured_output(
            PlanGeneration
        )

        try:
            lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="plan-generate")
            if lf_cfg is not None:
                plan_result = await structured_model.ainvoke(plan_messages, config=lf_cfg)
            else:
                plan_result = await structured_model.ainvoke(plan_messages)

            if plan_result is None:
                raise ValueError("PlanGeneration returned None")

            logger.debug(
                "Plan: action=%s steps=%d next=%s",
                plan_result.plan_action,
                len(plan_result.decision.steps) if plan_result.decision else 0,
                preview_first(plan_result.next_action, chars=80),
            )

            return plan_result

        except Exception as e:
            logger.warning("[LLMPlanner] PlanGeneration failed: %s", str(e)[:200])
            # Fallback: return default plan with LLM-like message
            return PlanGeneration(
                plan_action="new",
                decision=_default_agent_decision(goal, iteration),
                next_action="I'll proceed with a default plan.",
            )

    def _combine_results(
        self,
        assessment: Any,
        plan_result: Any,
    ) -> Any:
        """Combine StatusAssessment and PlanGeneration results (RFC-604, IG-152).

        Uses plan_result.next_action for the user-facing action line (IG-329).

        Args:
            assessment: StatusAssessment result
            plan_result: PlanGeneration result

        Returns:
            PlanResult with combined reasoning and action fields
        """
        from soothe.core.agent_loop.state.schemas import PlanResult
        from soothe.utils.text_preview import preview_first

        # Use plan_result.next_action (concrete, actionable)
        action_text = plan_result.next_action.strip()

        logger.debug("Plan action: %s", preview_first(action_text, chars=80))

        # Build final PlanResult
        return PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            confidence=assessment.confidence,
            assessment_reasoning="",
            plan_reasoning="",
            plan_action=plan_result.plan_action,
            decision=plan_result.decision,
            next_action=action_text,
            require_goal_completion=assessment.require_goal_completion,
        )

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
    ) -> Any:
        """Plan execution using two-call architecture (RFC-604).

        StatusAssessment call: lightweight status check (compact assess-only system prompt, IG-372)
        PlanGeneration call: conditional plan generation (execution policies + plan-generate instructions, IG-329)

        Returns combined PlanResult with evidence-based metrics applied.
        """
        from soothe.core.agent_loop.state.schemas import PlanResult, StatusAssessment

        max_retries = 3
        result = None

        for attempt in range(max_retries):
            assess_messages = self._prompt_builder.build_plan_messages(
                goal, state, context, plan_phase="assess"
            )
            messages_for_retry = assess_messages

            msg_types = [type(m).__name__ for m in assess_messages]
            plan_human = next(
                (m for m in reversed(assess_messages) if isinstance(m, HumanMessage)), None
            )
            human_preview = (
                create_output_summary(str(plan_human.content), first_chars=200, last_chars=100)
                if plan_human is not None
                else ""
            )
            logger.debug(
                "Plan msgs=%d types=%s human=%s", len(assess_messages), msg_types, human_preview
            )

            try:
                t_assess = time.perf_counter()
                assessment = await self._assess_status(
                    assess_messages, goal, state.iteration, thread_id=state.thread_id
                )
                assess_ms = (time.perf_counter() - t_assess) * 1000
                plan_gen_ms = 0.0
                llm_calls = 1

                # Guard against false "done" at iteration 0
                if assessment.status == "done":
                    guard_enabled = False
                    if self._config is not None:
                        guard_enabled = self._config.agentic.reject_done_at_iteration_zero

                    if guard_enabled and state.iteration == 0 and len(state.step_results) == 0:
                        logger.warning("[Guard] Reject 'done' at iter=0 no execution")
                        assessment.status = "replan"
                        assessment.goal_progress = 0.0

                # Early completion: apply goal-completion policy (IG-298)
                if assessment.status == "done":
                    from soothe.core.agent_loop.policies.goal_completion_policy import (
                        determine_goal_completion_needs,
                    )

                    gc_mode = (
                        self._config.agentic.goal_completion_mode
                        if self._config is not None
                        else "llm_only"
                    )
                    logger.debug("Plan early-complete: goal_completion_mode=%s", gc_mode)

                    require_completion = determine_goal_completion_needs(
                        llm_decision=assessment.require_goal_completion,
                        state=state,
                        mode=gc_mode,
                    )

                    logger.debug(
                        "Plan goal_completion: mode=%s LLM=%s final=%s",
                        gc_mode,
                        assessment.require_goal_completion,
                        require_completion,
                    )

                    result = PlanResult(
                        status=assessment.status,
                        goal_progress=assessment.goal_progress,
                        confidence=assessment.confidence,
                        assessment_reasoning="",
                        plan_reasoning="",
                        plan_action="keep",
                        decision=None,
                        next_action="Goal achieved successfully",
                        require_goal_completion=require_completion,
                        full_output=state.last_execute_assistant_text,
                    )
                else:
                    generate_messages = self._prompt_builder.build_plan_messages(
                        goal, state, context, plan_phase="generate"
                    )
                    messages_for_retry = generate_messages
                    t_plan = time.perf_counter()
                    plan_result = await self._generate_plan(
                        generate_messages,
                        assessment,
                        goal,
                        state.iteration,
                        thread_id=state.thread_id,
                    )
                    plan_gen_ms = (time.perf_counter() - t_plan) * 1000
                    llm_calls = 2

                    result = self._combine_results(assessment, plan_result)

                decision_info = ""
                if result.decision:
                    decision_info = (
                        f" steps={len(result.decision.steps)} mode={result.decision.execution_mode}"
                    )
                logger.debug(
                    "Plan result: status=%s plan=%s prog=%.0f%% conf=%.0f%%%s",
                    result.status,
                    result.plan_action,
                    result.goal_progress * 100,
                    result.confidence * 100,
                    decision_info,
                )
                prompt_chars = sum(
                    _estimate_content_chars(getattr(m, "content", None)) for m in assess_messages
                )
                if assessment.status != "done":
                    prompt_chars += sum(
                        _estimate_content_chars(getattr(m, "content", None))
                        for m in generate_messages
                    )
                logger.info(
                    "[LLMPlanner] timings iter=%d assess_ms=%.1f plan_gen_ms=%.1f llm_calls=%d "
                    "prompt_chars=%d",
                    state.iteration,
                    assess_ms,
                    plan_gen_ms,
                    llm_calls,
                    prompt_chars,
                )
                break

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
                            "Retry invalid JSON: len=%d preview=%s",
                            len(truncated_json),
                            create_output_summary(truncated_json, first_chars=400, last_chars=200),
                        )

                if attempt < max_retries - 1:
                    logger.warning(
                        "[Retry] attempt %d/%d error=%s msg=%s",
                        attempt + 1,
                        max_retries,
                        error_type,
                        error_msg[:100] if is_json_error else error_msg[:150],
                    )
                    # Fallback: regular model + manual JSON parsing (Layer 3)
                    if is_json_error and attempt == max_retries - 2:
                        logger.info("[Retry] fallback: manual JSON parse")
                        try:
                            lf_retry = self._planner_langfuse_run_config(
                                thread_id=state.thread_id, phase="plan-json-retry"
                            )
                            if lf_retry is not None:
                                response = await self._model.ainvoke(
                                    messages_for_retry, config=lf_retry
                                )
                            else:
                                response = await self._model.ainvoke(messages_for_retry)
                            raw_content = _extract_text_content(response.content)

                            logger.debug(
                                "Retry raw response: len=%d preview=%s",
                                len(raw_content),
                                create_output_summary(raw_content, first_chars=250, last_chars=150),
                            )

                            # Extract and repair JSON
                            json_str = _strip_markdown_json_fence(raw_content)
                            json_obj = _extract_balanced_json_object(json_str)

                            if json_obj:
                                repaired_json = _repair_truncated_json(json_obj)
                                parsed_dict = _try_parse_json_dict(repaired_json)

                                if parsed_dict:
                                    # Parse as StatusAssessment and build PlanResult
                                    try:
                                        assessment = StatusAssessment(**parsed_dict)
                                        result = PlanResult(
                                            status=assessment.status,
                                            goal_progress=assessment.goal_progress,
                                            confidence=assessment.confidence,
                                            assessment_reasoning="",
                                            plan_reasoning="",
                                            plan_action="new",
                                            decision=_default_agent_decision(goal, state.iteration),
                                            next_action="Proceeding with default plan",
                                        )
                                    except Exception:
                                        # Fallback: parse as PlanResult directly
                                        result = PlanResult(**parsed_dict)

                                    logger.info(
                                        "Retry manual JSON parse OK: attempt %d", attempt + 1
                                    )
                                    break
                        except Exception as fallback_error:
                            logger.warning("[Retry] fallback failed: %s", str(fallback_error)[:150])
                else:
                    # Final attempt failed
                    logger.exception("[Retry] failed after %d attempts", max_retries)
                    return PlanResult(
                        status="replan",
                        plan_action="new",
                        decision=_default_agent_decision(goal, state.iteration),
                        assessment_reasoning="",
                        plan_reasoning="",
                        next_action="Retrying with simpler approach",
                    )

        # IG-349: Wire preferred_subagent into AgentDecision (parity with create_plan / Plan).
        if result is not None and result.decision is not None:
            preferred = (
                getattr(context.unified_classification, "preferred_subagent", None)
                if context.unified_classification
                else None
            )
            if preferred:
                result = result.model_copy(
                    update={
                        "decision": self._apply_preferred_subagent_to_decision(
                            result.decision, preferred
                        )
                    }
                )

        # RFC-603: Apply evidence-based confidence; goal_progress stays LLM assess output (IG-376).
        result.confidence = _calculate_evidence_based_confidence(state, result)

        # Fallback completion detection (IG-134)
        result = _detect_completion_fallback(state, result, goal)

        return result
