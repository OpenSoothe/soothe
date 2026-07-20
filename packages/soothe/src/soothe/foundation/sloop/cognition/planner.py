"""LLMPlanner -- RFC-604 Plan-phase planner (sequential structured LLM calls)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from pydantic import ValidationError
from soothe_nano.utils.llm.invoke_policy import await_with_llm_call_policy
from soothe_nano.utils.llm.structured import StructuredOutputError, invoke_structured_chat_typed
from soothe_nano.utils.network_errors import calculate_network_backoff, is_transient_network_error
from soothe_nano.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe_nano.utils.text_preview import create_output_summary, preview_first
from soothe_nano.utils.token_counting import estimate_content_chars
from soothe_sdk.protocols.planner import PlanContext

from soothe.config.models import LLMRateLimitConfig
from soothe.foundation.sloop.cognition.plan_gap_wire import (
    coerce_plan_gap_analysis_wire_dict,
)
from soothe.foundation.sloop.cognition.plan_generation_wire import (
    capped_plan_generation_wire_model,
    coerce_plan_generation_wire_dict,
    plan_generation_wire_to_model,
)
from soothe.foundation.sloop.cognition.plan_step_safety import (
    derive_goal_progress_from_status,
    filter_filler_plan_steps,
    intake_label_from_state,
    normalize_status_assessment,
    simple_intake_should_force_done,
    terminal_assess_may_complete,
)
from soothe.foundation.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.foundation.sloop.state.schemas import (
    DEFAULT_MAX_PLAN_STEPS_PER_WAVE,
    AgentDecision,
    LoopState,
    PlanGeneration,
    StepAction,
    plan_generate_steps_to_step_actions,
    renumber_decision_local_step_ids_for_goal_continuation,
    step_actions_to_plan_generate_steps,
    strip_unrequested_step_delegates,
)
from soothe.foundation.sloop.utils.json_parsing import (
    _extract_balanced_json_object,
    _repair_truncated_json,
    _strip_markdown_json_fence,
    _try_parse_json_dict,
)
from soothe.foundation.sloop.utils.messages import LoopHumanMessage, last_ledger_ai_content
from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text
from soothe.foundation.sloop.utils.reflection import (
    _default_agent_decision,
    _extract_text_content,
)

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


def _parse_status_assessment_from_raw_message(response: Any) -> Any:
    """Parse ``StatusAssessment`` from a raw AIMessage when tool JSON is null.

    Thinking models (e.g. qwen via coding-plan) often emit valid assessment JSON
    in ``content`` or ``additional_kwargs["reasoning_content"]`` while LangChain's
    function-calling parser surfaces ``json: null`` in traces.
    """
    from soothe_nano.utils.llm.wrappers import _extract_json_str_from_response

    from soothe.foundation.sloop.state.schemas import StatusAssessment
    from soothe.foundation.sloop.utils.json_parsing import _load_llm_json_dict

    parsed = _load_llm_json_dict(_extract_json_str_from_response(response))
    return StatusAssessment(**parsed)


def _detect_stuck_loop(state: LoopState) -> str | None:
    """IG-454: Detect if the loop is stuck and should be terminated or replanned.

    Checks for:
    1. Repeated identical actions (same internal action line N times consecutively)
    2. Consecutive execution failures (``success=False`` from crashes/timeouts)

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


def _apply_continuation_intake_guardrails(result: Any, state: LoopState) -> Any:
    """Override bootstrap when intake complexity or empty reasoning forbids it."""
    from soothe.foundation.sloop.intention.models import IntakeLabel

    if getattr(result, "action", None) != "bootstrap":
        return result

    intake = intake_label_from_state(state)
    if intake in (IntakeLabel.SIMPLE, IntakeLabel.COMPLEX):
        logger.info(
            "[Plan] continuation guardrail: intake=%s forced plan_generate",
            intake.value,
        )
        return result.model_copy(
            update={
                "action": "plan_generate",
                "reasoning": "Intake complexity requires full planning.",
            }
        )

    if not (getattr(result, "reasoning", None) or "").strip():
        return result.model_copy(
            update={
                "action": "plan_generate",
                "reasoning": "I'll use the full planner because assess output was empty.",
            }
        )

    multi_phase = getattr(state.intent, "multi_phase", None) if state.intent else None
    if multi_phase:
        return result.model_copy(
            update={
                "action": "plan_generate",
                "reasoning": "Multi-step goal requires full planning.",
            }
        )

    return result


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
        plan_assess_model: Any | None = None,
        plan_generate_model: Any | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Initialize LLMPlanner.

        Args:
            model: Langchain BaseChatModel supporting structured output.
            config: Optional configuration for shared context XML in prompts.
            plan_assess_model: Model for plan-assess and continuation-assess calls.
            plan_generate_model: Model for plan-generate calls.
            loop_id: Optional loop identifier for Langfuse trace correlation.
        """
        from soothe.foundation.sloop.prompts import PromptBuilder

        self._model = model
        self._plan_assess_model = plan_assess_model or model
        self._plan_generate_model = plan_generate_model or model
        self._config = config
        self._loop_id = loop_id
        self._prompt_builder = PromptBuilder(config)

    def _max_plan_steps_per_wave(self) -> int:
        """Configured cap on plan-generate steps per wave."""
        if self._config is None:
            return DEFAULT_MAX_PLAN_STEPS_PER_WAVE
        return self._config.agent.loop.max_plan_steps_per_wave

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

    def _llm_rate_limit_config(self) -> LLMRateLimitConfig:
        """Timeout/retry policy for direct planner LLM calls (bypasses middleware stack)."""
        if self._config is not None:
            return self._config.agent.loop.llm_rate_limit
        return LLMRateLimitConfig()

    async def _invoke_structured(
        self,
        model: Any,
        messages: list[Any],
        schema: type[Any],
        *,
        config: dict[str, Any] | None = None,
        thread_id: str | None = None,
        normalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> Any:
        """Structured planner output with bounded timeout and retry."""

        async def _call() -> Any:
            return await invoke_structured_chat_typed(
                model,
                messages,
                schema,
                config=config,
                normalize=normalize,
            )

        return await await_with_llm_call_policy(
            _call,
            config=self._llm_rate_limit_config(),
            thread_id=thread_id,
        )

    async def _ainvoke_bounded(
        self,
        model: Any,
        input: str | list[Any],
        *,
        config: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> Any:
        """Raw ``ainvoke`` with bounded timeout and retry."""

        async def _call() -> Any:
            if config is not None:
                return await model.ainvoke(input, config=config)
            return await model.ainvoke(input)

        return await await_with_llm_call_policy(
            _call,
            config=self._llm_rate_limit_config(),
            thread_id=thread_id,
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
            response = await self._ainvoke_bounded(self._model, messages, thread_id=None)
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
            response = await self._ainvoke_bounded(self._model, [human_msg], thread_id=None)
            content = getattr(response, "content", str(response))
            return _extract_text_content(content)
        except Exception as e:
            logger.warning("LLMPlanner._invoke failed: %s", e)
            return ""

    @staticmethod
    def _preferred_subagent_step_description(description: str, subagent_name: str) -> str:
        """User-facing step text when wiring an explicit subagent (IG-349, shared with Plan path)."""
        desc = (description or "").strip()
        if not desc:
            return f"Using the {subagent_name} subagent."
        lowered = f"{desc[0].lower()}{desc[1:]}"
        return f"Using the {subagent_name} subagent, {lowered}"

    @staticmethod
    def _apply_preferred_subagent_to_decision(
        decision: AgentDecision,
        subagent_name: str,
    ) -> AgentDecision:
        """Apply wire ``preferred_subagent`` to ``AgentDecision`` step descriptions (IG-349).

        Intake-only specialists are skipped here (IG-600); they never reach plan-generate
        under the wired-subagent route (IG-599).
        """
        from soothe.foundation.sloop.state.schemas import is_intake_only_wire_subagent

        if not decision.steps or is_intake_only_wire_subagent(subagent_name):
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

    async def _assess_status_with_response(
        self,
        messages: list[Any],
        goal: str,
        iteration: int,
        *,
        thread_id: str | None,
    ) -> tuple[Any, Any]:
        """StatusAssessment call with raw response for CE audit (IG-557).

        Returns both the parsed assessment and the raw LLM response object.
        Assess pairs are not recorded in the CE ledger.

        Args:
            messages: Assess-phase messages from ``build_plan_messages(..., plan_phase=\"assess\")``
            goal: Goal description for fallback decision
            iteration: Current iteration for varied fallback
            thread_id: Thread id for Langfuse session correlation.

        Returns:
            Tuple of (StatusAssessment, raw_response) or (StatusAssessment, None) on fallback.
        """
        from soothe.foundation.sloop.state.schemas import StatusAssessment

        model = _plan_phase_chat_model(self._plan_assess_model)
        lf_cfg = self._planner_langfuse_run_config(thread_id=thread_id, phase="plan-assess")

        # IG-503: Retry loop for transient network errors
        network_attempts = 0
        last_error: Exception | None = None

        while network_attempts < _NETWORK_RETRY_MAX_ATTEMPTS:
            try:
                assessment = await self._invoke_structured(
                    model,
                    messages,
                    StatusAssessment,
                    config=lf_cfg,
                    thread_id=thread_id,
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
            raw = await self._ainvoke_bounded(model, messages, config=lf_cfg, thread_id=thread_id)
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
        state: LoopState,
        context: PlanContext,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        context_bundle: Any | None = None,
    ) -> Any:
        """RFC-226: discriminator via unified planner assembly (RFC-214 §4, IG-538).

        Routes a follow-up agentic query to bootstrap or plan_generate using the
        same system + projected ledger + task envelope shape as plan-assess.
        """
        from soothe.foundation.sloop.engine.continuation_context import (
            polish_continuation_assess_reasoning,
        )
        from soothe.foundation.sloop.state.schemas import ContinuationAssessment

        messages = self._prompt_builder.build_plan_messages(
            state.goal,
            state,
            context,
            call_kind="continuation",
            context_bundle=context_bundle,
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
        )
        model = _plan_phase_chat_model(self._plan_assess_model)
        try:
            lf_cfg = self._planner_langfuse_run_config(
                thread_id=state.thread_id, phase="continuation-assess"
            )
            result = await self._invoke_structured(
                model,
                messages,
                ContinuationAssessment,
                config=lf_cfg,
                thread_id=state.thread_id,
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
                reasoning="I'll fall back to the full planner because the assess call failed.",
                goal_progress="none",
            )

        if result is None or getattr(result, "action", None) not in ("bootstrap", "plan_generate"):
            logger.warning(
                "[LLMPlanner] ContinuationAssessment returned invalid action; "
                "fallback to plan_generate"
            )
            return ContinuationAssessment(
                action="plan_generate",
                reasoning="I'll use the full planner because the assess output was invalid.",
                goal_progress="none",
            )

        polished = polish_continuation_assess_reasoning(getattr(result, "reasoning", "") or "")
        if polished != (result.reasoning or ""):
            result = result.model_copy(update={"reasoning": polished})

        result = _apply_continuation_intake_guardrails(result, state)

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
            PlanGeneration with top-level decision fields and first-person reasoning.
        """
        plan_result, _ = await self._generate_plan_with_response(
            messages,
            assessment,
            goal,
            iteration,
            thread_id=thread_id,
        )
        from soothe.foundation.sloop.cognition.plan_step_briefs import (
            populate_plan_generate_full_descriptions,
        )

        return populate_plan_generate_full_descriptions(plan_result)

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
        plan_wire_schema = capped_plan_generation_wire_model(
            max_steps=self._max_plan_steps_per_wave()
        )

        model = _plan_phase_chat_model(self._plan_generate_model)

        # Retry structured output up to 2 times when None returned (IG-xxx)
        max_retries = 2
        last_error: Exception | None = None
        attempt_messages = list(messages)

        for attempt in range(max_retries + 1):
            try:
                lf_cfg = self._planner_langfuse_run_config(
                    thread_id=thread_id, phase="plan-generate"
                )
                plan_wire = await self._invoke_structured(
                    model,
                    attempt_messages,
                    plan_wire_schema,
                    config=lf_cfg,
                    thread_id=thread_id,
                    normalize=coerce_plan_generation_wire_dict,
                )
                plan_result = plan_generation_wire_to_model(plan_wire)
                if plan_result.type == "final" and assessment.status != "done":
                    raise ValueError(
                        "plan returned final without terminal assessment; "
                        "provide execute steps when status is not done"
                    )

                logger.debug(
                    "[Plan] steps=%d next=%s",
                    len(plan_result.steps) if isinstance(plan_result.steps, list) else 0,
                    preview_first(resolve_plan_action_text(plan_result), chars=80),
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
                    if "steps" in detail and "object" in detail:
                        attempt_messages = [
                            *attempt_messages,
                            HumanMessage(
                                content=(
                                    "steps[] must contain only step objects with description and "
                                    "dependencies (use [] when none). Do not put field names like "
                                    "reasoning or execution_mode inside steps[]."
                                )
                            ),
                        ]
                    elif "returned final without terminal assessment" in detail:
                        attempt_messages = [
                            *attempt_messages,
                            HumanMessage(
                                content=(
                                    "Use empty steps only when goal is fully complete. "
                                    "Otherwise return non-empty execute steps."
                                )
                            ),
                        ]
                    continue
            except StructuredOutputError as e:
                detail = str(e)
                logger.warning(
                    "[LLMPlanner] PlanGeneration structured output failed: %s", detail[:240]
                )
                last_error = e
                if attempt < max_retries:
                    logger.debug(
                        "[LLMPlanner] Retrying after structured output error (attempt %d/%d)",
                        attempt + 1,
                        max_retries,
                    )
                    if "steps" in detail and "object" in detail:
                        attempt_messages = [
                            *attempt_messages,
                            HumanMessage(
                                content=(
                                    "steps[] must contain only step objects (description, "
                                    "dependencies). Top-level fields are reasoning, steps, and "
                                    "optional clarify only."
                                )
                            ),
                        ]
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
                            plan_wire = await self._invoke_structured(
                                model,
                                messages,
                                plan_wire_schema,
                                config=lf_cfg_retry,
                                thread_id=thread_id,
                                normalize=coerce_plan_generation_wire_dict,
                            )
                            if plan_wire is not None:
                                plan_result = plan_generation_wire_to_model(plan_wire)
                                logger.debug(
                                    "[Plan] steps=%d next=%s (after network retry)",
                                    len(plan_result.steps)
                                    if isinstance(plan_result.steps, list)
                                    else 0,
                                    preview_first(resolve_plan_action_text(plan_result), chars=80),
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
            type="execute_steps",
            execution_mode="parallel",
            reasoning="I'll proceed with a default plan after plan generation failed.",
            steps=step_actions_to_plan_generate_steps(
                _default_agent_decision(goal, iteration).steps
            ),
        ), None

    @staticmethod
    def _plan_generation_to_decision(plan_result: Any) -> AgentDecision | None:
        """Rebuild `AgentDecision` from flattened `PlanGeneration` fields."""
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

        Keeps derived ``next_action`` on ``PlanResult`` for internal orchestration;
        ``plan_reasoning`` carries plan-generate ``reasoning`` for user-facing cognition cards.

        Args:
            assessment: StatusAssessment result
            plan_result: PlanGeneration result

        Returns:
            PlanResult with combined reasoning and action fields
        """
        from soothe_nano.utils.text_preview import preview_first

        from soothe.foundation.sloop.state.schemas import PlanResult

        action_text = resolve_plan_action_text(plan_result)
        plan_reasoning = (plan_result.reasoning or "").strip()

        logger.debug("[PlanAction] %s", preview_first(action_text, chars=80))
        decision = self._plan_generation_to_decision(plan_result)

        # Build final PlanResult
        return PlanResult(
            status=assessment.status,
            goal_progress=assessment.goal_progress,
            assessment_reasoning="",
            plan_reasoning=plan_reasoning,
            plan_action="new",
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
            from soothe.foundation.sloop.cognition.plan_dag_normalizer import normalize_plan_dag

            normalized = normalize_plan_dag(
                result.decision,
                completed_ids=state.dependency_completion_ids(),
            )
            if normalized is not result.decision:
                result = result.model_copy(update={"decision": normalized})

            filtered_steps = filter_filler_plan_steps(result.decision.steps)
            if len(filtered_steps) != len(result.decision.steps):
                logger.warning(
                    "[PlanGen] Dropped %d filler step(s) from plan",
                    len(result.decision.steps) - len(filtered_steps),
                )
                result = result.model_copy(
                    update={
                        "decision": result.decision.model_copy(update={"steps": filtered_steps}),
                    }
                )

            max_steps = self._max_plan_steps_per_wave()
            if len(result.decision.steps) > max_steps:
                logger.warning(
                    "[PlanGen] Truncated plan steps from %d to %d",
                    len(result.decision.steps),
                    max_steps,
                )
                result = result.model_copy(
                    update={
                        "decision": result.decision.model_copy(
                            update={
                                "steps": result.decision.steps[:max_steps],
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
            user_wire = resolve_user_requested_wire_subagent(
                routing_classification=context.routing_classification,
                intent=getattr(state, "intent", None),
            )
            stripped_steps = strip_unrequested_step_delegates(
                result.decision.steps,
                user_wire_subagent=user_wire,
            )
            if stripped_steps is not result.decision.steps:
                result = result.model_copy(
                    update={
                        "decision": result.decision.model_copy(update={"steps": stripped_steps}),
                    }
                )

            from soothe.foundation.sloop.state.schemas import apply_step_wire_subagents

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
        plan_gap: Any | None = None,
        context_bundle: Any | None = None,
    ) -> Any:
        """Assess-only planner call used by split graph flow (RFC-214).

        Persists ``StatusAssessment`` on the CE goal node (IG-557); does not
        append ``plan_assess`` ledger pairs.
        """
        if context_bundle is None and context_engine is not None:
            try:
                goal_id = getattr(state, "_ce_goal_id", None)
                context_bundle = await context_engine.project(goal_id=goal_id)
            except Exception:
                logger.debug("[Plan] assess_status: ContextEngine.project() failed", exc_info=True)
        assess_messages = self._prompt_builder.build_plan_messages(
            goal,
            state,
            context,
            plan_phase="assess",
            call_kind="assess",
            context_bundle=context_bundle,
            plan_gap=plan_gap,
        )
        assessment, ai_response = await self._assess_status_with_response(
            assess_messages,
            goal,
            state.iteration,
            thread_id=state.thread_id,
        )
        assessment = normalize_status_assessment(assessment, plan_gap)
        assessment.goal_progress = derive_goal_progress_from_status(state, assessment, plan_gap)

        if ai_response is not None and context_engine is not None:
            goal_id = getattr(state, "_ce_goal_id", None)
            if goal_id:
                context_engine.set_last_assessment(
                    goal_id,
                    assessment,
                    iteration=state.iteration,
                )
                logger.info(
                    "[Plan] CE last_assessment iter=%d status=%s progress=%s",
                    state.iteration,
                    assessment.status,
                    assessment.goal_progress,
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
        elif simple_intake_should_force_done(state, assessment):
            logger.info(
                "[Plan] simple intake: forcing done after sufficient evidence (steps=%d, hint=%s)",
                len(state.step_results),
                state.prior_progress.derived_progress_hint
                if state.prior_progress is not None
                else "n/a",
            )
            assessment.status = "done"
            if assessment.goal_progress == "none":
                assessment.goal_progress = "high"
            assessment.require_goal_completion = True
        return assessment

    async def analyze_plan_gap(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        context_engine: Any | None = None,
    ) -> Any:
        """Read-only gap analysis before plan-assess (IG-557)."""
        from soothe.foundation.sloop.state.schemas import PlanGapAnalysis

        context_bundle = None
        if context_engine is not None:
            try:
                goal_id = getattr(state, "_ce_goal_id", None)
                context_bundle = await context_engine.project(goal_id=goal_id)
            except Exception:
                logger.debug(
                    "[Plan] analyze_plan_gap: ContextEngine.project() failed", exc_info=True
                )
        gap_messages = self._prompt_builder.build_plan_messages(
            goal,
            state,
            context,
            plan_phase="assess",
            call_kind="gap",
            context_bundle=context_bundle,
        )
        model = _plan_phase_chat_model(self._plan_assess_model)
        lf_cfg = self._planner_langfuse_run_config(
            thread_id=state.thread_id,
            phase="plan-gap-analysis",
        )
        gap = await self._invoke_structured(
            model,
            gap_messages,
            PlanGapAnalysis,
            config=lf_cfg,
            thread_id=state.thread_id,
            normalize=coerce_plan_gap_analysis_wire_dict,
        )
        if gap is None:
            raise ValueError("PlanGapAnalysis returned None")
        if context_engine is not None:
            goal_id = getattr(state, "_ce_goal_id", None)
            if goal_id:
                context_engine.set_last_gap_analysis(goal_id, gap, iteration=state.iteration)
                logger.info(
                    "[Plan] gap distance=%s open_components=%d",
                    gap.distance_from_goal,
                    sum(
                        1
                        for c in gap.components
                        if c.status in ("not_started", "partial", "blocked")
                    ),
                )
        return gap

    async def generate_from_assessment(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        assessment: Any,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        plan_gap: Any | None = None,
    ) -> Any:
        """Generate plan after an existing assess result (split graph flow, RFC-214).

        Records the plan-generate user/AI pair in the ledger after the LLM call.
        These messages are NOT injected into CoreAgent thread.
        """
        from soothe.foundation.context.planning.completion import (
            determine_goal_completion_needs,
        )
        from soothe.foundation.sloop.state.schemas import PlanResult, derive_plan_action

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
                full_output=last_ledger_ai_content(state) or None,
            )

        if (
            derive_plan_action(
                assessment_status=assessment.status,
                has_remaining_steps=state.has_remaining_steps(),
            )
            == "keep"
        ):
            logger.info(
                "[PlanGen] Reusing in-flight plan (%d step(s) remain)",
                len(state.current_decision.steps) - len(state.dependency_completion_ids())
                if state.current_decision
                else 0,
            )
            return PlanResult(
                status=assessment.status,
                goal_progress=assessment.goal_progress,
                assessment_reasoning="",
                plan_reasoning="",
                plan_action="keep",
                decision=None,
                next_action="I'll continue with the remaining steps in the current plan.",
                require_goal_completion=assessment.require_goal_completion,
            )

        # RFC-630: trivial intake uses ``build_trivial_plan`` in init_or_resume;
        # the ``simple`` label uses ``generate_lightweight``. Neither produces
        # the "I will complete this goal directly:" prefix.

        # Build DAG context for progressive planning (IG-400)
        dag_context = None
        if plan_manager is not None:
            dag_ctx = plan_manager.get_planning_context()
            if dag_ctx.has_prior_state:
                from soothe.foundation.sloop.prompts.builder import _format_dag_context

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
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
            inline_assessment=assessment,
            plan_gap=plan_gap,
        )
        plan_result, ai_response = await self._generate_plan_with_response(
            generate_messages,
            assessment,
            goal,
            state.iteration,
            thread_id=state.thread_id,
        )

        from soothe.foundation.sloop.cognition.plan_step_briefs import (
            populate_plan_generate_full_descriptions,
        )

        plan_result = populate_plan_generate_full_descriptions(plan_result)
        if ai_response is plan_result or (
            hasattr(ai_response, "model_dump") and hasattr(plan_result, "model_dump")
        ):
            ai_response = plan_result

        # RFC-214: Record plan-generate pair in ledger (not injected into CoreAgent)
        human_msg = None
        for msg in reversed(generate_messages):
            if isinstance(msg, LoopHumanMessage):
                human_msg = msg
                break

        if human_msg is not None and ai_response is not None:
            from soothe.foundation.sloop.cognition.ledger_compaction import (
                compact_planning_human_content,
            )
            from soothe.foundation.sloop.utils.messages import LoopAIMessage, _record_ledger_message

            # Compact the recorded human so cache stays warm and the goal is
            # not duplicated as a directive (D1). The AI dump for
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
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        plan_gap: Any | None = None,
    ) -> Any:
        """Cheaper plan-generate for the ``simple`` intake branch (RFC-630).

        Same wire schema as ``generate_from_assessment``, but with
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
            checkpoint=checkpoint,
            exclude_goal_id=exclude_goal_id,
            plan_gap=plan_gap,
        )

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
        context_engine: Any | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
    ) -> Any:
        """Plan execution using two-call architecture (RFC-604).

        StatusAssessment call: lightweight status check (compact assess-only system prompt, IG-372)
        Plan wire call: conditional plan generation (execution policies + plan-generate instructions)

        Returns combined PlanResult with evidence-based metrics applied.
        """
        from soothe.foundation.sloop.state.schemas import PlanResult, StatusAssessment

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
                assessment = normalize_status_assessment(assessment)
                assessment.goal_progress = derive_goal_progress_from_status(state, assessment, None)
                assess_ms = (time.perf_counter() - t_assess) * 1000
                plan_gen_ms = 0.0
                llm_calls = 1

                # Guard: always reject premature 'done' at iteration 0 with no execution
                if assessment.status == "done":
                    if state.iteration == 0 and len(state.step_results) == 0:
                        logger.warning("[Guard] Reject 'done' at iter=0 no execution")
                        assessment.status = "replan"
                        assessment.goal_progress = "none"

                can_complete_early = False
                if assessment.status == "done":
                    intake_label = intake_label_from_state(state)
                    can_complete_early = terminal_assess_may_complete(
                        state,
                        assessment,
                        None,
                        intake_label=intake_label,
                    )
                    if not can_complete_early:
                        logger.warning(
                            "[Plan] Reject terminal assess in one-shot plan: structural gates failed "
                            "(status=%s progress=%s iter=%d)",
                            assessment.status,
                            assessment.goal_progress,
                            state.iteration,
                        )

                # Early completion: apply goal-completion policy (IG-298)
                if can_complete_early:
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
                        full_output=last_ledger_ai_content(state) or None,
                    )
                else:
                    # RFC-630: trivial intake uses ``build_trivial_plan`` in
                    # init_or_resume; the ``simple`` label uses
                    # ``generate_lightweight``.
                    # Build DAG context for progressive planning (IG-400)
                    dag_context = None
                    if plan_manager is not None:
                        dag_ctx = plan_manager.get_planning_context()
                        if dag_ctx.has_prior_state:
                            from soothe.foundation.sloop.prompts.builder import (
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
                        checkpoint=checkpoint,
                        exclude_goal_id=exclude_goal_id,
                        inline_assessment=assessment,
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
                            retry_model = _plan_phase_chat_model(self._plan_generate_model)
                            if lf_retry is not None:
                                response = await self._ainvoke_bounded(
                                    retry_model,
                                    messages_for_retry,
                                    config=lf_retry,
                                    thread_id=state.thread_id,
                                )
                            else:
                                response = await self._ainvoke_bounded(
                                    retry_model,
                                    messages_for_retry,
                                    thread_id=state.thread_id,
                                )
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
