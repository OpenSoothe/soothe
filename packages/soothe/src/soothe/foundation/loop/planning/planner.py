"""LLMPlanner -- RFC-604 Plan-phase planner (sequential structured LLM calls)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from soothe.foundation.loop.state.schemas import (
    FIRST_WAVE_MAX_STEPS,
    AgentDecision,
    LoopState,
    PlanGeneration,
    StepAction,
    plan_generate_steps_to_step_actions,
    plan_generation_model_for_iteration,
    renumber_decision_local_step_ids_for_goal_continuation,
    step_actions_to_plan_generate_steps,
)
from soothe.foundation.loop.utils.json_parsing import (
    _extract_balanced_json_object,
    _load_llm_json_dict,
    _repair_truncated_json,
    _strip_markdown_json_fence,
    _try_parse_json_dict,
)
from soothe.foundation.loop.utils.messages import LoopHumanMessage
from soothe.foundation.loop.utils.reflection import (
    _default_agent_decision,
    _extract_text_content,
    reflect_heuristic,
)
from soothe.protocols.planner import (
    GoalContext,
    Plan,
    PlanContext,
    Reflection,
    StepResult,
)
from soothe.utils.llm.structured import invoke_structured_chat_typed
from soothe.utils.network_errors import calculate_network_backoff, is_transient_network_error
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.text_preview import create_output_summary, preview_first
from soothe.utils.token_counting import estimate_content_chars

if TYPE_CHECKING:
    from soothe.config import SootheConfig

# IG-454: Stuck detection thresholds
_STUCK_ACTION_REPEAT_THRESHOLD = 3  # Same action repeated N times = stuck
_STUCK_ERROR_STEP_THRESHOLD = 3  # N consecutive error steps = stuck

# IG-503: Network resilience retry configuration
_NETWORK_RETRY_MAX_ATTEMPTS = 3

logger = logging.getLogger(__name__)


def _plan_phase_chat_model(model: Any) -> Any:
    """Return model for RFC-604 assess/plan structured calls (IG-358).

    Binds ``temperature=0`` when the chat model supports it so structured JSON is
    faster and more deterministic on most providers.
    """
    try:
        return model.bind(temperature=0)  # type: ignore[union-attr]
    except Exception:
        return model


_invoke_plan_structured_output = invoke_structured_chat_typed


_SIMPLE_PLANNER_HINT_MAP = {
    "search": "tool",
    "web": "tool",
    "api": "tool",
}


def _parse_status_assessment_from_raw_message(response: Any) -> Any:
    """Parse ``StatusAssessment`` from a raw AIMessage when tool JSON is null.

    Thinking models (e.g. qwen via coding-plan) often emit valid assessment JSON
    in ``content`` or ``additional_kwargs["reasoning_content"]`` while LangChain's
    function-calling parser surfaces ``json: null`` in traces.
    """
    from soothe.foundation.loop.state.schemas import StatusAssessment
    from soothe.foundation.loop.utils.json_parsing import _load_llm_json_dict
    from soothe.utils.llm.wrappers import _extract_json_str_from_response

    parsed = _load_llm_json_dict(_extract_json_str_from_response(response))
    return StatusAssessment(**parsed)


def _detect_stuck_loop(state: LoopState) -> str | None:
    """IG-454: Detect if the loop is stuck and should be terminated or replanned.

    Checks for:
    1. Repeated identical actions (same next_action N times consecutively)
    2. Consecutive failed step results (N errors without success)

    Args:
        state: Current loop state with action_history and step_results.

    Returns:
        Reason string if stuck, None if not stuck.
    """
    # Check for repeated identical actions
    if len(state.action_history) >= _STUCK_ACTION_REPEAT_THRESHOLD:
        recent_actions = state.get_recent_actions(_STUCK_ACTION_REPEAT_THRESHOLD)
        if len(recent_actions) == _STUCK_ACTION_REPEAT_THRESHOLD:
            # All recent actions are identical
            first_action = recent_actions[0]
            if all(action == first_action for action in recent_actions):
                return f"Repeated identical action {first_action[:50]} {_STUCK_ACTION_REPEAT_THRESHOLD} times"

    # Check for consecutive failed steps
    if len(state.step_results) >= _STUCK_ERROR_STEP_THRESHOLD:
        recent_results = state.step_results[-_STUCK_ERROR_STEP_THRESHOLD:]
        if all(not r.success for r in recent_results):
            previews = [(r.error or "unknown")[:50] for r in recent_results[:2]]
            return f"Consecutive step failures: {', '.join(previews)}"

    return None


class LLMPlanner:
    """PlannerProtocol for StrangeLoop Plan phase using RFC-604 structured LLM calls.

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
        *,
        loop_id: str | None = None,
    ) -> None:
        """Initialize LLMPlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
            config: Optional configuration for shared context XML in prompts.
            loop_id: Optional loop identifier for Langfuse trace correlation.
        """
        from soothe.foundation.loop.prompts import PromptBuilder

        self._model = model
        self._config = config
        self._loop_id = loop_id
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
            loop_id=self._loop_id,
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
            getattr(context.routing_classification, "preferred_subagent", None)
            if context.routing_classification
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
        messages = [HumanMessage(content=prompt)]

        try:
            lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="revise-plan")
            revised = await _invoke_plan_structured_output(
                self._model, messages, Plan, config=lf_cfg
            )
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
        sloop_result: Any | None = None,  # IG-154: StrangeLoop GoalResult
    ) -> Reflection:
        """Reflection with StrangeLoop integration support (IG-154).

        When sloop_result is provided (from StrangeLoop delegation), uses
        StrangeLoop's evidence and judgment for reflection instead of step_results.

        Args:
            plan: The plan (None when StrangeLoop handles execution).
            step_results: Step execution results (empty when StrangeLoop handles execution).
            goal_context: Goal DAG context for autonomous goal management.
            sloop_result: GoalResult from StrangeLoop delegation (when delegating).

        Returns:
            Reflection with assessment and goal directives for DAG restructuring.
        """
        # IG-154: StrangeLoop integration - use GoalResult when available
        if sloop_result:
            logger.info(
                "Using StrangeLoop result for reflection (status=%s, progress=%s)",
                sloop_result.status,
                sloop_result.goal_progress,
            )

            # Build assessment from StrangeLoop evidence
            evidence_preview = (
                sloop_result.evidence_summary[:300] if sloop_result.evidence_summary else ""
            )
            assessment = f"StrangeLoop achieved {sloop_result.goal_progress} progress. "

            if sloop_result.status == "completed":
                assessment += f"Goal successfully completed. {evidence_preview}"
            elif sloop_result.status == "failed":
                assessment += f"Goal execution failed. {evidence_preview}"
            else:
                assessment += f"Goal execution in progress. {evidence_preview}"

            # Determine if revision needed
            should_revise = sloop_result.status == "failed" or (
                isinstance(sloop_result.goal_progress, str)
                and sloop_result.goal_progress in ["none", "low"]
            )

            # Generate feedback
            if sloop_result.status == "completed":
                feedback = "Goal achieved successfully via StrangeLoop execution."
            elif sloop_result.status == "failed":
                feedback = "Goal not achieved. Consider alternative approach or create dependency prerequisites."
            else:
                feedback = "Goal partially achieved. May need continuation or alternative strategy."

            # Generate goal directives based on StrangeLoop outcome
            from soothe.protocols.planner import GoalDirective

            directives = []

            if sloop_result.status == "failed" and goal_context:
                # Failed goal: try alternative approach or decompose
                logger.info("StrangeLoop goal failed, generating recovery directives")

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
                        reason="Primary approach failed via StrangeLoop",
                    )
                )

                # Or decompose into smaller sub-goals
                if sloop_result.goal_progress in ("none", "low"):
                    directives.append(
                        GoalDirective(
                            action="decompose",
                            goal_id=goal_context.current_goal_id,
                            description="Decompose failed goal into simpler subtasks",
                            reason="Very low progress suggests goal too complex for current approach",
                        )
                    )

            elif sloop_result.status == "completed" and sloop_result.goal_progress in (
                "high",
                "complete",
            ):
                # Successfully completed: mark goal complete
                directives.append(
                    GoalDirective(
                        action="complete",
                        goal_id=goal_context.current_goal_id if goal_context else None,
                        description="Goal completed successfully",
                        reason="StrangeLoop achieved high/complete progress",
                    )
                )

            return Reflection(
                assessment=assessment,
                should_revise=should_revise,
                feedback=feedback,
                goal_directives=directives,
            )

        # Fallback: Use heuristic reflection for step_results-based analysis
        failure_cfg = None
        if self._config and hasattr(self._config, "optimization"):
            failure_cfg = self._config.optimization.failure_intent
        return reflect_heuristic(
            plan,
            step_results,
            goal_context,
            failure_config=failure_cfg,
        )

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
        messages = [HumanMessage(content=prompt)]

        try:
            lf_cfg = self._planner_langfuse_run_config(
                thread_id=context.thread_id, phase="create-plan-structured"
            )
            plan = await _invoke_plan_structured_output(self._model, messages, Plan, config=lf_cfg)
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
        from soothe.foundation.loop.prompts.context_xml import (
            build_shared_environment_workspace_prefix,
        )

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
                "- web URLs/sites → search_web / crawl_web tools (or a browsing-capable subagent if listed in capabilities)",
                "</TOOL_ROUTING_RULES>",
                "",
                "<FORBIDDEN_ACTIONS>",
                "- delegating research or other subagents for trivial local file ops (use direct file tools)",
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
            '      "description": "<brief summary, under 20 words for TUI display>",',
            '      "full_description": "<detailed execution prompt with file paths, identifiers, key inputs (50-150 words)>",',
            '      "expected_output": "<expected result>",',
            '      "execution_hint": "tool",',
            '      "subagent": null',
            "    }",
            "  ]",
            "}",
            "",
            "<PLANNING_RULES>",
            "- Return 1 step for trivial tasks, 2-3 for normal, 4-5 only if essential",
            "- Each step must be independently executable",
            "- description: Brief summary for TUI display (under 20 words)",
            "- full_description: Detailed execution context (50-150 words) including key file paths, identifiers, parameters, and context needed to execute without referencing the original goal",
            "- execution_hint: 'tool' (direct tool), 'subagent' (delegate), 'auto' (LLM reasoning)",
            "- When execution_hint='subagent', set subagent to a capability name (usually 'explore' for readonly repo search)",
            "- If user requests specific subagent, set execution_hint='subagent' and subagent accordingly",
            "- Return ONLY valid JSON (no markdown blocks)",
            "</PLANNING_RULES>",
            "",
            "<EFFICIENCY_RULES>",
            "- Trivial local skim: one step (list_files + selective read_file); heavy readonly recon: set execution_hint='subagent' and subagent='explore' (scoped target per step)",
            "- For project structure: single step listing top-level directories",
            "- Avoid duplicate paths; combine related reads in one step when safe—independent readonly probes may stay separate steps",
            "- explore subagent steps: name likely subtrees (e.g. docs/, packages/, benchmarks/) in the step text so search stays scoped; avoid vague whole-repo recon without directory hints",
            "</EFFICIENCY_RULES>",
        ]
        sections.append("<PLANNING_OUTPUT>\n" + "\n".join(output_spec) + "\n</PLANNING_OUTPUT>")

        body = "\n\n".join(sections)
        if self._config is not None:
            prefix = build_shared_environment_workspace_prefix(
                self._config,
                context.workspace,
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
        """Apply wire ``preferred_subagent`` to ``AgentDecision`` step descriptions (IG-349)."""
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
                        "description": LLMPlanner._preferred_subagent_step_description(
                            step.description, subagent_name
                        ),
                        "execution_hint": "subagent",
                        "subagent": subagent_name,
                        "wire_subagent": subagent_name,
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

    async def _assess_status_with_response(
        self,
        messages: list[Any],
        goal: str,
        iteration: int,
        *,
        thread_id: str | None,
    ) -> tuple[Any, Any]:
        """StatusAssessment call with raw response for ledger recording (RFC-214).

        Returns both the parsed assessment and the raw LLM response object
        so the caller can record the AI message in the ledger.

        Args:
            messages: Assess-phase messages from ``build_plan_messages(..., plan_phase=\"assess\")``
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            Tuple of (StatusAssessment, raw_response) or (StatusAssessment, None) on fallback.
        """
        from soothe.foundation.loop.state.schemas import StatusAssessment

        model = _plan_phase_chat_model(self._model)
        lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="plan-assess")

        # IG-503: Retry loop for transient network errors
        network_attempts = 0
        last_error: Exception | None = None

        while network_attempts < _NETWORK_RETRY_MAX_ATTEMPTS:
            try:
                assessment = await _invoke_plan_structured_output(
                    model, messages, StatusAssessment, config=lf_cfg
                )

                if assessment is None:
                    raise ValueError("StatusAssessment returned None")

                logger.debug(
                    "[Assess] status=%s prog=%s",
                    assessment.status,
                    assessment.goal_progress,
                )

                return assessment, assessment

            except asyncio.CancelledError:
                raise

            except Exception as e:
                # Check for transient network error (IG-503)
                if is_transient_network_error(e):
                    network_attempts += 1
                    last_error = e
                    backoff = calculate_network_backoff(network_attempts - 1)
                    logger.warning(
                        "[LLMPlanner] StatusAssessment network error (attempt %d/%d): %s - "
                        "retrying in %.1fs",
                        network_attempts,
                        _NETWORK_RETRY_MAX_ATTEMPTS,
                        str(e)[:100],
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                # Non-transient error: log and fall through to fallback
                logger.warning("[LLMPlanner] StatusAssessment failed: %s", str(e)[:200])
                last_error = e
                break

        # All network retries exhausted or non-transient error
        if network_attempts >= _NETWORK_RETRY_MAX_ATTEMPTS and last_error:
            logger.error(
                "[LLMPlanner] StatusAssessment network error after %d retries: %s",
                _NETWORK_RETRY_MAX_ATTEMPTS,
                str(last_error)[:100],
            )

        # Fallback: try raw message parsing
        try:
            raw = await model.ainvoke(messages, config=lf_cfg)
            # Debug: log raw response content structure
            content_preview = ""
            if hasattr(raw, "content"):
                content_preview = str(raw.content)[:200] if raw.content else "empty"
            reasoning_preview = ""
            if hasattr(raw, "additional_kwargs") and "reasoning_content" in raw.additional_kwargs:
                reasoning_preview = str(raw.additional_kwargs.get("reasoning_content", ""))[:200]
            logger.debug(
                "[Assess] Raw fallback response: content=%s, reasoning_content=%s, type=%s",
                content_preview,
                reasoning_preview,
                type(raw).__name__,
            )
            assessment = _parse_status_assessment_from_raw_message(raw)
            logger.info(
                "[Assess] Recovered status=%s prog=%s from raw message after structured failure",
                assessment.status,
                assessment.goal_progress,
            )
            return assessment, assessment
        except Exception as fallback_exc:
            logger.warning(
                "[LLMPlanner] StatusAssessment raw fallback failed: %s",
                str(fallback_exc)[:200],
            )
        return StatusAssessment(
            status="replan",
            goal_progress="none",
            require_goal_completion=False,
        ), None

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
        assessment, _ = await self._assess_status_with_response(
            messages, goal, iteration, thread_id=thread_id
        )
        return assessment

    async def assess_continuation(
        self,
        *,
        current_goal: str,
        prior_goals: list[dict],
        capabilities: list[str],
        thread_id: str | None = None,
    ) -> Any:
        """RFC-226: discriminator LLM call routing continuations to bootstrap or plan_generate.

        Invoked from ``plan_assess`` on iter=0 of any agentic query where
        ``continue_loop_mode`` is True and the loop has at least one completed
        prior goal. Returns a ``ContinuationAssessment`` Pydantic instance.

        Args:
            current_goal: The new user query (``LoopState.goal``).
            prior_goals: Compact summary of completed prior goals
                (from ``_prior_goal_summaries(checkpoint)``).
            capabilities: Available tool + subagent names.
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            ``ContinuationAssessment`` with ``action``, ``reasoning``, ``goal_progress``.
            On LLM failure or invalid output, falls back to ``action="plan_generate"``.
        """
        from langchain_core.messages import HumanMessage

        from soothe.foundation.loop.planning.continuation_prompts import (
            format_loop_continuation_assess_prompt,
        )
        from soothe.foundation.loop.state.schemas import ContinuationAssessment

        prompt = format_loop_continuation_assess_prompt(
            current_goal=current_goal,
            prior_goals=prior_goals,
            capabilities=capabilities,
        )
        messages = [HumanMessage(content=prompt)]
        model = _plan_phase_chat_model(self._model)
        try:
            lf_cfg = self._planner_langfuse_run_config(
                thread_id=thread_id, phase="continuation-assess"
            )
            result = await _invoke_plan_structured_output(
                model, messages, ContinuationAssessment, config=lf_cfg
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[LLMPlanner] ContinuationAssessment failed: %s (fallback to plan_generate)",
                str(exc)[:200],
            )
            return ContinuationAssessment(
                action="plan_generate",
                reasoning="LLM call failed; safe fallback to full planner.",
                goal_progress="none",
            )

        if result is None or getattr(result, "action", None) not in ("bootstrap", "plan_generate"):
            logger.warning(
                "[LLMPlanner] ContinuationAssessment returned invalid action; "
                "fallback to plan_generate"
            )
            return ContinuationAssessment(
                action="plan_generate",
                reasoning="Invalid LLM output; safe fallback to full planner.",
                goal_progress="none",
            )

        logger.debug(
            "[ContinuationAssess] action=%s reason=%s",
            result.action,
            (result.reasoning or "")[:120],
        )
        return result

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
            PlanGeneration with plan_action and top-level decision fields.
        """
        plan_result, _ = await self._generate_plan_with_response(
            messages, assessment, goal, iteration, thread_id=thread_id
        )
        return plan_result

    async def _generate_plan_with_response(
        self,
        messages: list[Any],
        assessment: Any,
        goal: str,
        iteration: int,
        *,
        thread_id: str | None,
    ) -> tuple[Any, Any]:
        """PlanGeneration call with raw response for ledger recording (RFC-214).

        Returns both the parsed plan and the raw LLM response object
        so the caller can record the AI message in the ledger.

        Args:
            messages: Generate-phase messages from ``build_plan_messages(..., plan_phase=\"generate\")``
            assessment: StatusAssessment result from previous call
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            Tuple of (PlanGeneration, raw_response) or (PlanGeneration, None) on fallback.
        """
        from langchain_core.messages import SystemMessage

        plan_schema = plan_generation_model_for_iteration(iteration)

        # Add assessment context to plan generation prompt
        context_msg = SystemMessage(
            content=f"Status: {assessment.status}, Progress: {assessment.goal_progress}"
        )
        plan_messages = messages + [context_msg]

        model = _plan_phase_chat_model(self._model)

        # Retry structured output up to 2 times when None returned (IG-xxx)
        max_retries = 2
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                lf_cfg = self._planner_langfuse_run_config(
                    thread_id=thread_id, phase="plan-generate"
                )
                plan_result = await _invoke_plan_structured_output(
                    model, plan_messages, plan_schema, config=lf_cfg
                )

                if plan_result is None:
                    if attempt < max_retries:
                        logger.warning(
                            "[LLMPlanner] PlanGeneration returned None (attempt %d/%d), retrying",
                            attempt + 1,
                            max_retries,
                        )
                        continue
                    raise ValueError("PlanGeneration returned None after retries")

                logger.debug(
                    "[Plan] action=%s steps=%d next=%s",
                    plan_result.plan_action,
                    len(plan_result.steps)
                    if plan_result.plan_action == "new" and isinstance(plan_result.steps, list)
                    else 0,
                    preview_first(plan_result.next_action, chars=80),
                )

                return plan_result, plan_result

            except asyncio.CancelledError:
                raise
            except ValidationError as e:
                err_parts: list[str] = []
                for err in e.errors()[:3]:
                    loc = ".".join(str(p) for p in err.get("loc", ()))
                    msg = str(err.get("msg", ""))
                    if loc:
                        err_parts.append(f"{loc}: {msg}")
                    else:
                        err_parts.append(msg)
                detail = "; ".join(err_parts) if err_parts else str(e)
                logger.warning("[LLMPlanner] PlanGeneration validation failed: %s", detail[:240])
                last_error = e
                if attempt < max_retries:
                    logger.debug(
                        "[LLMPlanner] Retrying after validation error (attempt %d/%d)",
                        attempt + 1,
                        max_retries,
                    )
                    continue
            except Exception as e:
                # IG-503: Check for transient network error first
                if is_transient_network_error(e):
                    # Retry with exponential backoff (separate counter)
                    network_attempts = 0
                    while network_attempts < _NETWORK_RETRY_MAX_ATTEMPTS:
                        network_attempts += 1
                        backoff = calculate_network_backoff(network_attempts - 1)
                        logger.warning(
                            "[LLMPlanner] PlanGeneration network error (attempt %d/%d): %s - "
                            "retrying in %.1fs",
                            network_attempts,
                            _NETWORK_RETRY_MAX_ATTEMPTS,
                            str(e)[:100],
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        try:
                            lf_cfg_retry = self._planner_langfuse_run_config(
                                thread_id=thread_id, phase="plan-generate-retry"
                            )
                            plan_result = await _invoke_plan_structured_output(
                                model, plan_messages, plan_schema, config=lf_cfg_retry
                            )
                            if plan_result is not None:
                                logger.debug(
                                    "[Plan] action=%s steps=%d next=%s (after network retry)",
                                    plan_result.plan_action,
                                    len(plan_result.steps)
                                    if plan_result.plan_action == "new"
                                    and isinstance(plan_result.steps, list)
                                    else 0,
                                    preview_first(plan_result.next_action, chars=80),
                                )
                                return plan_result, plan_result
                        except Exception as retry_exc:
                            if is_transient_network_error(retry_exc):
                                e = retry_exc
                                continue
                            # Non-transient error on retry: break and fall through
                            break

                    # All network retries exhausted
                    logger.error(
                        "[LLMPlanner] PlanGeneration network error after %d retries: %s",
                        _NETWORK_RETRY_MAX_ATTEMPTS,
                        str(e)[:100],
                    )
                    last_error = e
                    # Fall through to fallback
                    break

                # Non-transient error: standard retry handling
                logger.warning("[LLMPlanner] PlanGeneration failed: %s", str(e)[:200])
                last_error = e
                if attempt < max_retries:
                    logger.debug(
                        "[LLMPlanner] Retrying after error (attempt %d/%d)",
                        attempt + 1,
                        max_retries,
                    )
                    continue

        # Fallback after all retries exhausted
        error_detail = str(last_error)[:100] if last_error else "unknown"
        logger.warning(
            "[LLMPlanner] PlanGeneration failed after %d attempts, using fallback (last error: %s)",
            max_retries + 1,
            error_detail,
        )
        return PlanGeneration(
            plan_action="new",
            type="execute_steps",
            execution_mode="parallel",
            reasoning="Fallback default plan after plan generation failure.",
            steps=step_actions_to_plan_generate_steps(
                _default_agent_decision(goal, iteration).steps
            ),
            next_action="I'll proceed with a default plan.",
        ), None

    @staticmethod
    def _plan_generation_to_decision(plan_result: Any) -> AgentDecision | None:
        """Rebuild `AgentDecision` from flattened `PlanGeneration` fields."""
        if plan_result.plan_action != "new":
            return None
        if (
            plan_result.type is None
            or plan_result.execution_mode is None
            or not isinstance(plan_result.steps, list)
        ):
            return None
        if plan_result.type == "execute_steps" and not plan_result.steps:
            return None
        return AgentDecision(
            type=plan_result.type,
            steps=plan_generate_steps_to_step_actions(plan_result.steps),
            execution_mode=plan_result.execution_mode,
            reasoning=plan_result.reasoning or "",
            adaptive_granularity=plan_result.adaptive_granularity,
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
        from soothe.foundation.loop.state.schemas import PlanResult
        from soothe.utils.text_preview import preview_first

        # Use plan_result.next_action (concrete, actionable)
        action_text = plan_result.next_action.strip()

        logger.debug("[PlanAction] %s", preview_first(action_text, chars=80))
        decision = self._plan_generation_to_decision(plan_result)

        # Build final PlanResult
        return PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning="",
            plan_reasoning="",
            plan_action=plan_result.plan_action,
            decision=decision,
            next_action=action_text,
            require_goal_completion=assessment.require_goal_completion,
        )

    def _finalize_generated_plan_result(
        self,
        *,
        result: Any,
        state: LoopState,
        context: PlanContext,
        goal: str,
    ) -> Any:
        """Apply postprocessing shared by one-shot and split generate flows."""
        if (
            result is not None
            and result.plan_action == "new"
            and result.decision is not None
            and result.decision.steps
        ):
            if state.iteration == 0 and len(result.decision.steps) > FIRST_WAVE_MAX_STEPS:
                logger.warning(
                    "[PlanGen] Truncated first-wave steps from %d to %d",
                    len(result.decision.steps),
                    FIRST_WAVE_MAX_STEPS,
                )
                result = result.model_copy(
                    update={
                        "decision": result.decision.model_copy(
                            update={
                                "steps": result.decision.steps[:FIRST_WAVE_MAX_STEPS],
                            }
                        ),
                    }
                )

            result = result.model_copy(
                update={
                    "decision": renumber_decision_local_step_ids_for_goal_continuation(
                        result.decision,
                        state,
                    ),
                }
            )

        if result is not None and result.decision is not None:
            from soothe.foundation.loop.state.schemas import apply_step_wire_subagents

            wired_steps = apply_step_wire_subagents(result.decision.steps)
            result = result.model_copy(
                update={
                    "decision": result.decision.model_copy(update={"steps": wired_steps}),
                }
            )
            preferred = (
                getattr(context.routing_classification, "preferred_subagent", None)
                if context.routing_classification
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

        return result

    async def assess_status(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        context_engine: Any | None = None,
    ) -> Any:
        """Assess-only planner call used by split graph flow (RFC-214).

        Records the plan-assess user/AI pair in the ledger after the LLM call.
        These messages are NOT injected into CoreAgent thread.
        """
        assess_messages = self._prompt_builder.build_plan_messages(
            goal, state, context, plan_phase="assess"
        )
        assessment, ai_response = await self._assess_status_with_response(
            assess_messages,
            goal,
            state.iteration,
            thread_id=state.thread_id,
        )

        # RFC-214: Record plan-assess pair in ledger (not injected into CoreAgent)
        # Find the LoopHumanMessage (last message in assess_messages)
        human_msg = None
        for msg in reversed(assess_messages):
            if isinstance(msg, LoopHumanMessage):
                human_msg = msg
                break

        if human_msg is not None and ai_response is not None:
            from soothe.foundation.loop.planning.ledger_compaction import (
                compact_planning_human_content,
            )
            from soothe.foundation.loop.utils.messages import LoopAIMessage, _record_ledger_message

            # Compact the recorded human so the next assess sees cache-stable
            # prompt prefix (C1 + D1), while preserving full AI response in ledger.
            recorded_human = human_msg.model_copy(
                update={"content": compact_planning_human_content(str(human_msg.content))}
            )
            ai_msg = LoopAIMessage(
                content=str(ai_response.model_dump())
                if hasattr(ai_response, "model_dump")
                else str(ai_response),
                thread_id=state.thread_id,
                iteration=state.iteration,
                phase="plan_assess",
            )
            _record_ledger_message(
                context_engine,
                recorded_human,
                "plan_assess",
            )
            _record_ledger_message(
                context_engine,
                ai_msg,
                "plan_assess",
            )
            logger.debug(
                "Recorded plan-assess ledger pair: human=%d chars, ai=%d chars",
                len(str(recorded_human.content)),
                len(str(ai_msg.content)),
            )

        # IG-454: Check for stuck loop patterns
        stuck_reason = _detect_stuck_loop(state)
        if stuck_reason:
            logger.warning("[Plan] Stuck detected: %s, forcing replan", stuck_reason)
            assessment.status = "replan"
            assessment.goal_progress = "none"
            assessment.assessment_reasoning = f"Loop stuck: {stuck_reason}"

        if assessment.status == "done":
            # Guard: always reject premature 'done' at iteration 0 with no execution
            if state.iteration == 0 and len(state.step_results) == 0:
                logger.warning("[Guard] Reject 'done' at iter=0 no execution")
                assessment.status = "replan"
                assessment.goal_progress = "none"
        return assessment

    async def generate_from_assessment(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: Any,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
    ) -> Any:
        """Generate plan after an existing assess result (split graph flow, RFC-214).

        Records the plan-generate user/AI pair in the ledger after the LLM call.
        These messages are NOT injected into CoreAgent thread.
        """
        from soothe.foundation.context.planning.completion import (
            determine_goal_completion_needs,
        )
        from soothe.foundation.loop.state.schemas import PlanResult

        if assessment.status == "done":
            gc_mode = (
                self._config.agent.loop.goal_completion_mode
                if self._config is not None
                else "llm_only"
            )
            require_completion = determine_goal_completion_needs(
                llm_decision=assessment.require_goal_completion,
                mode=gc_mode,
                dag_failed_steps=sum(1 for r in state.step_results if not r.success),
                dag_completed_steps=sum(1 for r in state.step_results if r.success),
                last_execute_wave_parallel_multi_step=state.last_execute_wave_parallel_multi_step,
                last_wave_hit_subagent_cap=state.last_wave_hit_subagent_cap,
                current_decision_steps=(
                    state.current_decision.steps if state.current_decision else None
                ),
            )
            return PlanResult(
                status=assessment.status,
                goal_progress=assessment.goal_progress,
                assessment_reasoning="",
                plan_reasoning="",
                plan_action="keep",
                decision=None,
                next_action="Goal achieved successfully",
                require_goal_completion=require_completion,
                full_output=state.last_execute_assistant_text,
            )

        # RFC-630: the legacy simple-query bypass (prefixed 1-step plan) is
        # removed. The ``trivial`` intake label now handles single-step goals
        # via ``build_trivial_plan`` in init_or_resume (no plan_generate call);
        # the ``simple`` label uses ``generate_lightweight``. Neither produces
        # the "I will complete this goal directly:" prefix.

        # Build DAG context for progressive planning (IG-400)
        dag_context = None
        if plan_manager is not None:
            dag_ctx = plan_manager.get_planning_context()
            if dag_ctx.has_prior_state:
                from soothe.foundation.loop.prompts.builder import _format_dag_context

                dag_context = _format_dag_context(dag_ctx)

        # RFC-624: Build ContextBundle from ContextEngine when available
        context_bundle = None
        if context_engine is not None:
            try:
                context_bundle = await context_engine.project()
            except Exception:
                logger.debug("ContextEngine.project() failed, proceeding without bundle")

        generate_messages = self._prompt_builder.build_plan_messages(
            goal,
            state,
            context,
            plan_phase="generate",
            dag_context=dag_context,
            context_bundle=context_bundle,
        )
        plan_result, ai_response = await self._generate_plan_with_response(
            generate_messages,
            assessment,
            goal,
            state.iteration,
            thread_id=state.thread_id,
        )

        # Guard: reject premature type="final" at iteration 0 with no execution
        if plan_result.plan_action == "new" and plan_result.type == "final":
            if state.iteration == 0 and len(state.step_results) == 0:
                logger.warning(
                    "[Guard] Reject 'final' type at iter=0 no execution; forcing execute_steps"
                )
                plan_result = PlanGeneration(
                    plan_action="new",
                    type="execute_steps",
                    execution_mode="parallel",
                    reasoning="Initial execution to gather evidence for goal assessment",
                    steps=step_actions_to_plan_generate_steps(
                        _default_agent_decision(goal, state.iteration).steps
                    ),
                    next_action=f"I'll proceed with analyzing: {preview_first(goal, 80)}",
                )

        # RFC-214: Record plan-generate pair in ledger (not injected into CoreAgent)
        human_msg = None
        for msg in reversed(generate_messages):
            if isinstance(msg, LoopHumanMessage):
                human_msg = msg
                break

        if human_msg is not None and ai_response is not None:
            from soothe.foundation.loop.planning.ledger_compaction import (
                compact_planning_human_content,
            )
            from soothe.foundation.loop.utils.messages import LoopAIMessage, _record_ledger_message

            # Compact the recorded human so cache stays warm and the goal is
            # not duplicated as a directive (C1 + D1). The AI dump for
            # plan-generate is kept verbatim — its `steps` list IS the value
            # of the recording, and there is no equivalent of `assessment_reasoning`
            # to drop without losing schema fidelity.
            recorded_human = human_msg.model_copy(
                update={"content": compact_planning_human_content(str(human_msg.content))}
            )
            ai_msg = LoopAIMessage(
                content=str(ai_response.model_dump())
                if hasattr(ai_response, "model_dump")
                else str(ai_response),
                thread_id=state.thread_id,
                iteration=state.iteration,
                phase="plan_generate",
            )
            _record_ledger_message(
                context_engine,
                recorded_human,
                "plan_generate",
            )
            _record_ledger_message(
                context_engine,
                ai_msg,
                "plan_generate",
            )
            logger.debug(
                "Recorded plan-generate ledger pair: human=%d chars, ai=%d chars",
                len(str(recorded_human.content)),
                len(str(ai_msg.content)),
            )

        result = self._combine_results(assessment, plan_result)
        return self._finalize_generated_plan_result(
            result=result,
            state=state,
            context=context,
            goal=goal,
        )

    async def generate_lightweight(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: Any,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
    ) -> Any:
        """Cheaper plan-generate for the ``simple`` intake branch (RFC-630).

        Same ``PlanGeneration`` schema as ``generate_from_assessment``, but with
        a reduced context: only the last 2 step results and no DAG prior-state
        context. Runs the same LLM call with a smaller prompt. Used for
        single-focused-step goals that don't need the full evidence ledger.

        The ``context_engine`` is forwarded so the plan-generate ledger pair is
        still recorded (RFC-624 Phase 4 requires a non-None CE for ledger
        writes); only ``plan_manager`` is dropped to skip DAG context.
        """
        # Trim step results to the last 2 to shrink the prompt.
        trimmed_state = state.model_copy(update={"step_results": state.step_results[-2:]})
        return await self.generate_from_assessment(
            goal=goal,
            state=trimmed_state,
            context=context,
            assessment=assessment,
            plan_manager=None,
            context_engine=context_engine,
        )

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
    ) -> Any:
        """Plan execution using two-call architecture (RFC-604).

        StatusAssessment call: lightweight status check (compact assess-only system prompt, IG-372)
        PlanGeneration call: conditional plan generation (execution policies + plan-generate instructions, IG-329)

        Returns combined PlanResult with evidence-based metrics applied.
        """
        from soothe.foundation.loop.state.schemas import PlanResult, StatusAssessment

        max_retries = 3
        result = None

        # RFC-624: Build ContextBundle from ContextEngine when available
        context_bundle = None
        if context_engine is not None:
            try:
                context_bundle = await context_engine.project()
            except Exception:
                logger.debug("ContextEngine.project() failed, proceeding without bundle")

        for attempt in range(max_retries):
            assess_messages = self._prompt_builder.build_plan_messages(
                goal,
                state,
                context,
                plan_phase="assess",
                context_bundle=context_bundle,
            )
            messages_for_retry = assess_messages
            generate_messages: list[Any] = []

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

                # Guard: always reject premature 'done' at iteration 0 with no execution
                if assessment.status == "done":
                    if state.iteration == 0 and len(state.step_results) == 0:
                        logger.warning("[Guard] Reject 'done' at iter=0 no execution")
                        assessment.status = "replan"
                        assessment.goal_progress = "none"

                # Early completion: apply goal-completion policy (IG-298)
                if assessment.status == "done":
                    from soothe.foundation.context.planning.completion import (
                        determine_goal_completion_needs,
                    )

                    gc_mode = (
                        self._config.agent.loop.goal_completion_mode
                        if self._config is not None
                        else "llm_only"
                    )
                    logger.debug("Plan early-complete: goal_completion_mode=%s", gc_mode)

                    require_completion = determine_goal_completion_needs(
                        llm_decision=assessment.require_goal_completion,
                        mode=gc_mode,
                        dag_failed_steps=sum(1 for r in state.step_results if not r.success),
                        dag_completed_steps=sum(1 for r in state.step_results if r.success),
                        last_execute_wave_parallel_multi_step=state.last_execute_wave_parallel_multi_step,
                        last_wave_hit_subagent_cap=state.last_wave_hit_subagent_cap,
                        current_decision_steps=(
                            state.current_decision.steps if state.current_decision else None
                        ),
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
                        assessment_reasoning="",
                        plan_reasoning="",
                        plan_action="keep",
                        decision=None,
                        next_action="Goal achieved successfully",
                        require_goal_completion=require_completion,
                        full_output=state.last_execute_assistant_text,
                    )
                else:
                    # RFC-630: the legacy simple-query bypass (prefixed 1-step
                    # plan) is removed. Single-step goals are handled by the
                    # ``trivial`` intake label via ``build_trivial_plan`` in
                    # init_or_resume; the ``simple`` label uses
                    # ``generate_lightweight``. Neither produces the
                    # "I will complete this goal directly:" prefix.
                    # Build DAG context for progressive planning (IG-400)
                    dag_context = None
                    if plan_manager is not None:
                        dag_ctx = plan_manager.get_planning_context()
                        if dag_ctx.has_prior_state:
                            from soothe.foundation.loop.prompts.builder import (
                                _format_dag_context,
                            )

                            dag_context = _format_dag_context(dag_ctx)

                    generate_messages = self._prompt_builder.build_plan_messages(
                        goal,
                        state,
                        context,
                        plan_phase="generate",
                        dag_context=dag_context,
                        context_bundle=context_bundle,
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
                    "Plan result: status=%s plan=%s prog=%s%s",
                    result.status,
                    result.plan_action,
                    result.goal_progress,
                    decision_info,
                )
                prompt_chars = sum(
                    estimate_content_chars(getattr(m, "content", None)) for m in assess_messages
                )
                if generate_messages:
                    prompt_chars += sum(
                        estimate_content_chars(getattr(m, "content", None))
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

        return self._finalize_generated_plan_result(
            result=result,
            state=state,
            context=context,
            goal=goal,
        )
