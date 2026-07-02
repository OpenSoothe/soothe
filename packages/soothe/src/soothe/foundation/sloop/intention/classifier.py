"""Intent classifier implementation (RFC-225, RFC-630, IG-540).

4-class LLM intake classification (``quiz`` | ``trivial`` | ``simple`` |
``complex``) via ``classify_intake``, driving ``route_by_intent`` branch
routing. Loop continuation is derived structurally inside ``StrangeLoop``
from the loaded checkpoint and is not a classifier concern.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.utils.llm.invoke_policy import (
    await_with_llm_call_policy,
    llm_rate_limit_config_from,
)
from soothe.utils.llm.structured import invoke_structured_chat

from .intake_messages import build_intake_human_message, build_intake_system_message
from .models import (
    IntakeClassificationLLMResult,
    IntakeLabel,
    IntentClassification,
    derive_task_complexity_from_intake,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class IntentClassifier:
    """LLM-driven intent classification (RFC-225, RFC-630).

    - 4-class intake label via a single structured LLM call.
    - No structural / continuation logic — that is owned by ``StrangeLoop``.
    - Robust fallback to ``complex`` on failure (fail-safe: full pipeline runs).

    Args:
        model: Fast LLM for classification (e.g., gpt-4o-mini).
        assistant_name: Name used in quiz fallback replies.
        soothe_config: Optional config for Langfuse tracing.
    """

    def __init__(
        self,
        model: BaseChatModel | None,
        assistant_name: str = "Soothe",
        soothe_config: SootheConfig | None = None,
    ) -> None:
        self._fast_model = model
        self._assistant_name = assistant_name
        self._soothe_config = soothe_config

        if model:
            logger.info("[IntentClassifier] Initialized with structured output model")
        else:
            logger.warning("[IntentClassifier] No model provided, classification disabled")

    # -- Public API --------------------------------------------------------

    async def classify_intake(
        self,
        query: str,
        *,
        loop_messages: list[BaseMessage] | None = None,
        thread_id: str | None = None,
        context_engine: Any | None = None,
        observability_metadata: dict[str, str] | None = None,
        langfuse_bootstrap: dict[str, Any] | None = None,
    ) -> IntentClassification:
        """Classify the query into a 4-class intake label (RFC-630).

        One structured LLM call with retry; fallback to ``complex`` so the full
        pipeline runs (fail-safe, RFC-630 §9.3).

        Args:
            query: User input text.
            loop_messages: Optional persisted ledger for prior-goal projection.
            thread_id: Thread id for ledger metadata (optional).
            context_engine: Optional CE instance for intent-classify ledger writes.
            observability_metadata: Optional metadata for observability.
            langfuse_bootstrap: Shared Langfuse config from ``build_goal_loop_langfuse_bootstrap``
                so intent-classify nests under the same trace as ``strange-loop-graph``.

        Returns:
            IntentClassification with ``intake_label`` ∈
            {``quiz``, ``trivial``, ``simple``, ``complex``} and ``intent_type``
            derived from it (``quiz`` → ``quiz``, else ``agentic``).
        """
        if not self._fast_model:
            return self._fallback(query)

        result: IntentClassification | None = None
        last_error: Exception | None = None
        last_human_content: str | None = None
        last_llm_dict: dict[str, Any] | None = None

        for retry_mode in (False, True):
            try:
                result, last_human_content, last_llm_dict = await self._classify_intake_llm(
                    query,
                    retry_mode=retry_mode,
                    loop_messages=loop_messages,
                    observability_metadata=observability_metadata,
                    langfuse_bootstrap=langfuse_bootstrap,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Intake classification failed (%s), retrying...",
                    "retry" if retry_mode else "primary",
                )
                logger.debug("Intake classification error: %s", exc, exc_info=True)

        if result is None:
            logger.warning(
                "Intake classification failed after retry, using fallback (error: %s)",
                type(last_error).__name__ if last_error else "unknown",
            )
            return self._fallback(query, error_context=last_error)

        result = self._patch_missing_fields(result, query)

        if last_human_content is not None and last_llm_dict is not None:
            await self._record_intake_ledger(
                human_content=last_human_content,
                llm_result=last_llm_dict,
                thread_id=thread_id,
                context_engine=context_engine,
            )

        logger.debug(
            "Intake classified: intake_label=%s complexity=%s",
            result.intake_label,
            result.task_complexity,
        )

        return result

    # -- Internal LLM calls ------------------------------------------------

    async def _classify_intake_llm(
        self,
        query: str,
        *,
        retry_mode: bool = False,
        loop_messages: list[BaseMessage] | None = None,
        observability_metadata: dict[str, str] | None = None,
        langfuse_bootstrap: dict[str, Any] | None = None,
    ) -> tuple[IntentClassification, str, dict[str, Any]]:
        """4-class intake LLM call with structured output (RFC-630)."""
        from soothe.foundation.sloop.prompts.plan_ledger_projection import (
            project_prior_goal_completion_for_intake,
        )

        system_content = build_intake_system_message(self._assistant_name, retry=retry_mode)
        human_content = build_intake_human_message(query=query, retry=retry_mode)

        ledger_cfg = (
            self._soothe_config.agent.loop.plan_prompt_ledger if self._soothe_config else None
        )
        projected = project_prior_goal_completion_for_intake(loop_messages or [], ledger_cfg)

        config = self._build_invoke_config(
            "classify_intake",
            "intake.primary",
            observability_metadata=observability_metadata,
            langfuse_bootstrap=langfuse_bootstrap,
        )

        messages: list[BaseMessage] = [SystemMessage(content=system_content)]
        messages.extend(projected)
        messages.append(HumanMessage(content=human_content))

        schema = IntakeClassificationLLMResult.model_json_schema()
        try:

            async def _invoke() -> dict[str, Any]:
                return await invoke_structured_chat(
                    self._fast_model,
                    messages,
                    json_schema=schema,
                    schema_name="IntakeClassificationLLMResult",
                    strict=True,
                    config=config,
                )

            result_dict = await await_with_llm_call_policy(
                _invoke,
                config=llm_rate_limit_config_from(self._soothe_config),
            )
        except Exception:
            logger.exception("LLM intake classification call failed")
            raise

        if result_dict is None:
            raise ValueError("LLM returned None - structured output parsing failed")

        if result_dict.get("intake_label") not in (
            IntakeLabel.QUIZ,
            IntakeLabel.TRIVIAL,
            IntakeLabel.SIMPLE,
            IntakeLabel.COMPLEX,
        ):
            raise ValueError(f"Invalid intake_label from LLM: {result_dict.get('intake_label')!r}")

        llm_result = IntakeClassificationLLMResult(**result_dict)
        return llm_result.to_intent_classification(), human_content, result_dict

    async def _record_intake_ledger(
        self,
        *,
        human_content: str,
        llm_result: dict[str, Any],
        thread_id: str | None,
        context_engine: Any | None,
    ) -> None:
        """Append intent-classify Human/AI pair to the CE ledger (RFC-214, IG-540)."""
        if context_engine is None:
            return
        from soothe.foundation.sloop.utils.messages import (
            LoopAIMessage,
            LoopHumanMessage,
            _record_ledger_message,
        )

        tid = (thread_id or "").strip()
        human_msg = LoopHumanMessage(
            content=human_content,
            thread_id=tid or None,
            iteration=0,
            phase="intent_classify",
        )
        ai_msg = LoopAIMessage(
            content=json.dumps(llm_result, ensure_ascii=False),
            thread_id=tid or None,
            iteration=0,
            phase="intent_classify",
        )
        try:
            _record_ledger_message(context_engine, human_msg, "intent_classify")
            _record_ledger_message(context_engine, ai_msg, "intent_classify")
            await context_engine.save()
            logger.debug(
                "Recorded intent-classify ledger pair: human=%d chars, ai=%d chars",
                len(human_content),
                len(ai_msg.content),
            )
        except Exception:
            logger.warning("Failed to record intent-classify ledger pair", exc_info=True)

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _build_quiz_intent() -> IntentClassification:
        """Build a quiz IntentClassification (fast-path hint bypass)."""
        return IntentClassification(
            intent_type="quiz",
            intake_label=IntakeLabel.QUIZ,
            reasoning=None,
            goal_description=None,
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.QUIZ),
            quiz_response=None,
        )

    def _fallback(
        self,
        query: str,
        *,
        error_context: Exception | None = None,
    ) -> IntentClassification:
        """Safe fallback to ``complex`` (RFC-630 §9.3): run the full pipeline."""
        reason = type(error_context).__name__ if error_context else "classification_disabled"
        logger.debug("Intake fallback to complex (%s)", reason)
        return IntentClassification(
            intent_type="agentic",
            intake_label=IntakeLabel.COMPLEX,
            reasoning="Let me run the full agent loop to work through this goal.",
            goal_description=query,
            task_complexity=derive_task_complexity_from_intake(IntakeLabel.COMPLEX),
            quiz_response=None,
        )

    def _patch_missing_fields(
        self,
        intent: IntentClassification,
        query: str,
    ) -> IntentClassification:
        """Patch missing goal_description and reasoning on agentic results (IG-518)."""
        if intent.intent_type == "agentic":
            if not intent.goal_description:
                intent.goal_description = query
                logger.debug("Patched missing goal_description")
            if not intent.reasoning:
                intent.reasoning = "I'll use tools to work through this goal."
                logger.debug("Patched missing reasoning")
        return intent

    def _build_invoke_config(
        self,
        purpose: str,
        component: str,
        *,
        observability_metadata: dict[str, str] | None = None,
        langfuse_bootstrap: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build RunnableConfig with Langfuse tracing and call metadata."""
        from soothe.middleware._utils import create_llm_call_metadata

        if (
            langfuse_bootstrap is not None
            and self._soothe_config is not None
            and self._soothe_config.observability.langfuse.enabled
        ):
            try:
                from soothe.utils.observability.langfuse import build_intake_langfuse_invoke_config

                return build_intake_langfuse_invoke_config(
                    self._soothe_config,
                    langfuse_bootstrap=langfuse_bootstrap,
                    purpose=purpose,
                    component=f"classifier.{component}",
                    phase="pre-stream",
                    extra_metadata=observability_metadata,
                )
            except Exception:
                logger.debug("Langfuse intake invoke config build failed", exc_info=True)

        try:
            from soothe.utils.observability.langfuse import (
                build_traced_config,
                intent_classify_langfuse_run_display_name,
            )

            trace_name = (
                (self._soothe_config.observability.langfuse.trace_name or "").strip()
                if self._soothe_config
                else ""
            )
            return build_traced_config(
                self._soothe_config,
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
                run_name=intent_classify_langfuse_run_display_name(trace_name or None),
                extra_metadata=observability_metadata,
                independent_trace=False,
            )
        except Exception:
            metadata = create_llm_call_metadata(
                purpose=purpose,
                component=f"classifier.{component}",
                phase="pre-stream",
            )
            if observability_metadata:
                metadata.update(observability_metadata)
            return {"metadata": metadata}
