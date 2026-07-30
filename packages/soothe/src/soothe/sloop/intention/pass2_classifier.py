"""Pass 2 classifier: scope classification (RFC-630 IG-554).

3-class scope (trivial|simple|complex) for work requests. Prior-goal projection
is included for reference resolution. Runs only when Pass 1 returns is_task=True.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from soothe_nano.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe_nano.utils.llm.structured import invoke_structured_chat

from .models import IntakePass2LLMResult, IntakeScope
from .prompts import INTAKE_PASS2_HUMAN_TASK, INTAKE_PASS2_SYSTEM_PROMPT
from .structured_methods import INTAKE_JSON_FIRST_METHODS

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

# Mid-loop prior goal_completion dumps can be multi-k tokens; Pass 2 only needs
# enough context for reference resolution ("apply it"), not the full report.
_PASS2_PRIOR_MAX_CHARS = 2400


def clip_pass2_prior_projection(prior_projection: str | None) -> str | None:
    """Bound prior-goal text for Pass 2 (keep the tail for next-action cues)."""
    if prior_projection is None:
        return None
    text = prior_projection.strip()
    if not text:
        return None
    if len(text) <= _PASS2_PRIOR_MAX_CHARS:
        return text
    return "…\n" + text[-_PASS2_PRIOR_MAX_CHARS:]


class IntakePass2Classifier:
    """Pass 2: scope classification for work requests (RFC-630 IG-554).

    Classifies as trivial, simple, or complex. Prior-goal projection included
    for reference resolution ("apply it"). On structured-output failure,
    fail-safe to simple (lightweight plan) so CoreAgent can finish in one
    execute rather than forcing a full complex spine.

    Args:
        model: Fast LLM for classification.
        soothe_config: Optional config for rate limiting and tracing.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        soothe_config: SootheConfig | None = None,
    ) -> None:
        self._fast_model = model
        self._soothe_config = soothe_config

        if model:
            logger.debug("[IntakePass2] Initialized")
        else:
            logger.warning("[IntakePass2] No model provided, classifier disabled")

    async def classify(
        self,
        query: str,
        *,
        prior_projection: str | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass2LLMResult:
        """Classify work scope as trivial, simple, or complex.

        Args:
            query: User input text.
            prior_projection: Prior-goal summary for reference resolution (optional).
            observability_metadata: Optional metadata for observability.
            goal_trace: Optional Langfuse trace context.

        Returns:
            IntakePass2LLMResult with scope classification.
        """
        if not self._fast_model:
            return self._fallback(query)

        try:
            result = await self._classify_llm(
                query,
                prior_projection=prior_projection,
                observability_metadata=observability_metadata,
                goal_trace=goal_trace,
            )
            logger.debug(
                "Pass2 classified: scope=%s goal=%s",
                result.scope,
                preview_goal(query),
            )
            return result
        except Exception as exc:
            logger.warning(
                "Pass2 classification failed, fail-safe to simple: %s",
                type(exc).__name__,
            )
            logger.debug("Pass2 error: %s", exc, exc_info=True)
            return self._fallback(query, error_context=exc)

    async def _classify_llm(
        self,
        query: str,
        *,
        prior_projection: str | None = None,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> IntakePass2LLMResult:
        """Single LLM call for Pass 2 scope classification."""
        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(content=INTAKE_PASS2_SYSTEM_PROMPT),
        ]

        clipped_prior = clip_pass2_prior_projection(prior_projection)
        if clipped_prior:
            messages.append(SystemMessage(content=f"PRIOR_GOAL_SUMMARY:\n{clipped_prior}"))

        messages.append(HumanMessage(content=f"CURRENT_GOAL: {query}\n\n{INTAKE_PASS2_HUMAN_TASK}"))

        config = self._build_invoke_config(
            "classify_pass2",
            "intake.pass2",
            observability_metadata=observability_metadata,
            goal_trace=goal_trace,
        )

        schema = IntakePass2LLMResult.model_json_schema()

        async def _invoke() -> dict[str, Any]:
            return await invoke_structured_chat(
                self._fast_model,
                messages,
                json_schema=schema,
                schema_name="IntakePass2LLMResult",
                strict=True,
                config=config,
                methods=INTAKE_JSON_FIRST_METHODS,
            )

        result_dict = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(self._soothe_config),
        )

        if result_dict is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        # Validate scope
        if result_dict.get("scope") not in (
            IntakeScope.TRIVIAL,
            IntakeScope.SIMPLE,
            IntakeScope.COMPLEX,
        ):
            raise ValueError(f"Invalid scope from LLM: {result_dict.get('scope')!r}")

        if result_dict.get("multi_phase") not in (True, False):
            result_dict["multi_phase"] = False

        if result_dict.get("requires_tool_use") not in (True, False):
            result_dict["requires_tool_use"] = False

        wire = result_dict.get("wire_subagent")
        if wire is not None:
            from soothe.sloop.state.schemas import resolve_wire_subagent

            resolved = resolve_wire_subagent(wire_subagent=str(wire).strip() or None)
            result_dict["wire_subagent"] = resolved

        return IntakePass2LLMResult(**result_dict)

    def _fallback(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntakePass2LLMResult:
        """Fail-safe: simple so one CoreAgent execute can finish the deliverable."""
        reason = type(error_context).__name__ if error_context else "no_model"
        logger.debug("Pass2 fallback to simple (%s)", reason)
        return IntakePass2LLMResult(
            scope=IntakeScope.SIMPLE,
            reasoning="Let me handle this as a focused single-execute task.",
            multi_phase=False,
            wire_subagent=None,
            requires_tool_use=False,
        )

    def _build_invoke_config(
        self,
        purpose: str,
        component: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        goal_trace: Any | None = None,
    ) -> dict[str, Any]:
        """Build RunnableConfig with Langfuse tracing."""
        from soothe_nano.utils.llm.observability import create_llm_call_metadata

        if goal_trace is not None:
            return goal_trace.intake_invoke_config(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="intake_pass2",
                extra_metadata=observability_metadata,
            )

        if self._soothe_config is not None:
            from soothe_sdk.observability.langfuse import SootheLangfuse

            trace_name = (self._soothe_config.observability.langfuse.trace_name or "").strip()
            return SootheLangfuse(self._soothe_config).traced_llm(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="intake_pass2",
                run_name=f"intake-pass2:{trace_name or 'query'}",
                extra_metadata=observability_metadata,
            )

        metadata = create_llm_call_metadata(
            purpose=purpose,
            component=f"classifier.{component}",
            phase="intake_pass2",
        )
        if observability_metadata:
            metadata.update(observability_metadata)
        return {"metadata": metadata}


def preview_goal(goal: str, max_len: int = 50) -> str:
    """Truncate goal description for logging."""
    if len(goal) <= max_len:
        return goal
    return goal[: max_len - 3] + "..."


__all__ = ["IntakePass2Classifier", "clip_pass2_prior_projection"]
