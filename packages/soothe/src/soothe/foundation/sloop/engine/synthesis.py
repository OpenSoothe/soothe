"""Synthesis execution logic for comprehensive final report generation (RFC-603, RFC-616, IG-300).

Consolidated execution module:
- Scenario classification (Phase 1 via ScenarioClassifier)
- Synthesis generation (Phase 2 via CoreAgent streaming)

Separation of concerns (IG-300):
- policies/goal_completion_policy.py: Decision logic ("should we synthesize?")
- analysis/scenario_classifier.py: Classification logic ("what scenario?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")

Checkpoint isolation (IG-302): synthesis uses a fresh LangGraph ``thread_id`` so the
checkpointer does not replay the parent thread. The model receives execute-step ledger
messages plus a context human envelope and system report instructions.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from soothe_nano.utils.observability.langfuse import merge_langfuse_runnable_config

from soothe.foundation.sloop.engine.scenario_classifier import (
    ScenarioClassification,
    classify_synthesis_scenario,
)
from soothe.foundation.sloop.engine.synthesis_projection import build_synthesis_messages
from soothe.foundation.sloop.state.schemas import LoopState
from soothe.foundation.sloop.utils.messages import tag_messages_stream_chunk_for_goal_completion
from soothe.foundation.sloop.utils.plan_action_text import resolve_plan_action_text
from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.language_models.chat_models import BaseChatModel
    from soothe_nano.protocols.core_agent import CoreAgentProtocol

    from soothe.config import SootheConfig
    from soothe.foundation.sloop.state.schemas import PlanResult

logger = logging.getLogger(__name__)

_DEFAULT_SYNTHESIS_EVIDENCE_MAX = 120_000

_SYNTH_GC_MARKER = "__synth_gc__"
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"


def synthesis_checkpoint_thread_id(parent_thread_id: str) -> str:
    """Return an ephemeral LangGraph thread id for goal-completion synthesis (IG-302).

    Using a dedicated id prevents the SQLite checkpointer from loading the parent
    thread's full conversation into the synthesis model call.

    Args:
        parent_thread_id: StrangeLoop / user thread identifier.

    Returns:
        Unique checkpoint thread key (stable prefix for log grep).
    """
    return f"{parent_thread_id}{_SYNTH_GC_MARKER}{uuid.uuid4().hex}"


class SynthesisGenerator:
    """Generate synthesis reports from execution evidence (RFC-616, IG-300).

    Two-phase synthesis: scenario classification, then CoreAgent generation (IG-300).
    """

    def __init__(
        self,
        llm_client: BaseChatModel,
        core_agent: CoreAgentProtocol,
        soothe_config: SootheConfig | None = None,
        *,
        loop_id: str | None = None,
        fast_llm_client: BaseChatModel | None = None,
    ) -> None:
        """Initialize synthesis generator with LLM client and CoreAgent.

        Args:
            llm_client: Model for synthesis streaming (Phase 2).
            core_agent: CoreAgent for synthesis execution with streaming (Phase 2).
            soothe_config: Optional daemon config for evidence budgeting (IG-317).
            loop_id: Optional loop identifier for Langfuse trace correlation.
            fast_llm_client: Fast model for scenario classification (Phase 1).
                Falls back to ``llm_client`` when not provided.
        """
        self.llm = llm_client
        self._classify_llm = fast_llm_client or llm_client
        self.core_agent = core_agent
        self._soothe_config = soothe_config
        self._loop_id = loop_id

    async def _classify_scenario(self, goal: str, state: LoopState) -> ScenarioClassification:
        """Wrap classifier with error handling (IG-300).

        Args:
            goal: User's goal description.
            state: Loop state with intent and execution history.

        Returns:
            ScenarioClassification with scenario + sections + focus + emphasis.
            Fallback to general_summary on classification failure.
        """
        try:
            return await classify_synthesis_scenario(
                goal, state, self._classify_llm, soothe_config=self._soothe_config
            )
        except Exception:
            logger.warning("Classifier failed, using fallback", exc_info=True)
            from soothe.foundation.sloop.engine.scenario_classifier import BUILTIN_SCENARIOS

            return ScenarioClassification(
                scenario="general_summary",
                sections=BUILTIN_SCENARIOS["general_summary"],
                contextual_focus=["Summarize major actions and outcomes for the request"],
                evidence_emphasis=(
                    "Group evidence by concern or outcome; do not replay turns chronologically"
                ),
            )

    async def generate_synthesis(
        self,
        goal: str,
        state: LoopState,
    ) -> AsyncGenerator:
        """Generate synthesis via CoreAgent streaming.

        Two-phase: classify scenario, then project evidence and stream via CoreAgent.
        Uses isolated checkpoint thread to prevent replay of parent StrangeLoop history.

        Args:
            goal: Goal description.
            state: Loop state with thread context and execution ledger (`loop_messages`).

        Yields:
            LangGraph ``messages``-mode stream tuples tagged with ``phase=goal_completion``.
        """

        classify_start = time.perf_counter()
        classification = await self._classify_scenario(goal, state)
        classify_elapsed_ms = int((time.perf_counter() - classify_start) * 1000)
        logger.info(
            "Synthesis Phase 1 (classify): scenario=%s elapsed_ms=%d",
            classification.scenario,
            classify_elapsed_ms,
        )

        max_total = self._synthesis_max_chars()
        ledger_cfg = None
        agent_instructions_max_chars = 8000
        if self._soothe_config is not None:
            ledger_cfg = self._soothe_config.agent.loop.plan_prompt_ledger
            agent_instructions_max_chars = int(
                self._soothe_config.agent.agent_instructions_max_chars
            )
        messages = build_synthesis_messages(
            state,
            classification,
            user_query=goal,
            max_chars=max_total,
            ledger_cfg=ledger_cfg,
            agent_instructions_max_chars=agent_instructions_max_chars,
        )

        approx_chars = sum(
            len(extract_text_from_message_content(getattr(m, "content", ""))) for m in messages
        )
        execute_ledger_count = max(0, len(messages) - 2)
        logger.info(
            "Synthesis generator: scenario=%s sections=%d execute_ledger_msgs=%d prompt_msgs=%d approx_chars=%d",
            classification.scenario,
            len(classification.sections),
            execute_ledger_count,
            len(messages),
            approx_chars,
        )

        checkpoint_thread_id = synthesis_checkpoint_thread_id(state.thread_id)
        configurable: dict[str, Any] = {
            "thread_id": checkpoint_thread_id,
            SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY: True,
        }
        if state.workspace:
            configurable["workspace"] = state.workspace
        logger.info(
            "Synthesis isolated checkpoint thread=%s parent_thread=%s",
            checkpoint_thread_id,
            state.thread_id,
        )

        graph_config: dict[str, Any] = {"configurable": configurable}
        parent_runnable_config: dict[str, Any] | None = None
        try:
            from langgraph.config import get_config as _lg_get_config

            parent_runnable_config = _lg_get_config()
        except RuntimeError:
            parent_runnable_config = None

        if self._soothe_config is not None:
            tn = (self._soothe_config.observability.langfuse.trace_name or "").strip()
            run_name = f"{tn}:goal-synthesis" if tn else "goal-synthesis"
            graph_config = merge_langfuse_runnable_config(
                graph_config,
                self._soothe_config,
                session_id=state.thread_id,
                run_name=run_name,
                loop_id=self._loop_id,
                inherit_callbacks_from=parent_runnable_config,
            )

        if parent_runnable_config is not None:
            from langchain_core.runnables.config import merge_configs

            graph_config = merge_configs(parent_runnable_config, graph_config)

        # IG-477: Stream via LLM directly — avoids CoreAgent graph checkpointer
        # during goal-completion synthesis (same class of leak as execute streaming).
        synthesis_start = time.perf_counter()
        logger.info(
            "Synthesis Phase 2 (generate): starting stream scenario=%s approx_chars=%d",
            classification.scenario,
            approx_chars,
        )
        from soothe.foundation.sloop.utils.token_usage import direct_llm_token_call_scope

        with direct_llm_token_call_scope():
            async for chunk in self.llm.astream(messages, config=graph_config):
                yield tag_messages_stream_chunk_for_goal_completion(
                    ((), "messages", (chunk, {})),
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                )
        synthesis_elapsed_ms = int((time.perf_counter() - synthesis_start) * 1000)
        logger.info(
            "Synthesis Phase 2 (generate): completed elapsed_ms=%d",
            synthesis_elapsed_ms,
        )

    def _synthesis_max_chars(self) -> int:
        """Return max total extracted text for system + evidence payload (IG-317)."""
        max_chars = _DEFAULT_SYNTHESIS_EVIDENCE_MAX
        if self._soothe_config is not None:
            cap = self._soothe_config.agent.loop.report_output.synthesis_max_chars
            if cap > 0:
                max_chars = cap
        return max_chars


def generate_user_fallback_summary(
    state: LoopState,
    plan_result: PlanResult,
) -> str:
    """Generate user-friendly fallback summary (RFC-211 / IG-199 / IG-299).

    NEVER leak internal evidence_summary to users.
    Generate user-friendly completion summary instead.

    Args:
        state: Loop state with step_results.
        plan_result: Plan result with full_output or next_action.

    Returns:
        User-friendly summary text.
    """
    # Use planner's full_output if available
    if plan_result.full_output:
        final_output = plan_result.full_output
        logger.info("Fallback summary: use full_output chars=%d", len(final_output))
        return final_output

    action_text = resolve_plan_action_text(plan_result)

    # Generate from step results if available
    if state.step_results:
        successful_count = sum(1 for r in state.step_results if r.success)
        total_count = len(state.step_results)
        final_output = (
            f"Completed {successful_count}/{total_count} steps successfully. {action_text}"
        )
        logger.info(
            "Fallback summary: generated from steps success=%d/%d",
            successful_count,
            total_count,
        )
        return final_output

    # No steps executed, use internal action text as summary
    final_output = action_text or "Goal achieved successfully"
    logger.info("Fallback summary: use plan action text chars=%d", len(final_output))
    return final_output
