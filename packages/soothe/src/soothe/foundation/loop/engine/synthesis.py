"""Synthesis execution logic for comprehensive final report generation (RFC-603, RFC-616, IG-300).

Consolidated execution module:
- Scenario classification (Phase 1 via ScenarioClassifier)
- Synthesis generation (Phase 2 via CoreAgent streaming)

Separation of concerns (IG-300):
- policies/goal_completion_policy.py: Decision logic ("should we synthesize?")
- analysis/scenario_classifier.py: Classification logic ("what scenario?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")

Checkpoint isolation (IG-302): synthesis uses a fresh LangGraph ``thread_id`` so the
checkpointer does not replay the parent thread. The model receives a projected
user-safe evidence payload plus system report instructions (``synthesis_projection``).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from soothe.foundation.loop.engine.scenario_classifier import (
    ScenarioClassification,
    classify_synthesis_scenario,
)
from soothe.foundation.loop.engine.synthesis_projection import build_synthesis_messages
from soothe.foundation.loop.state.schemas import LoopState
from soothe.foundation.loop.utils.messages import tag_messages_stream_chunk_for_goal_completion
from soothe.foundation.loop.utils.stream_normalize import extract_text_from_message_content
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.foundation.core.agent import CoreAgent

logger = logging.getLogger(__name__)

_DEFAULT_SYNTHESIS_EVIDENCE_MAX = 120_000

_SYNTH_GC_MARKER = "__synth_gc__"
SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY = "soothe_goal_synthesis"


def synthesis_checkpoint_thread_id(parent_thread_id: str) -> str:
    """Return an ephemeral LangGraph thread id for goal-completion synthesis (IG-302).

    Using a dedicated id prevents the SQLite checkpointer from loading the parent
    thread's full conversation into the synthesis model call.

    Args:
        parent_thread_id: AgentLoop / user thread identifier.

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
        core_agent: CoreAgent,
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
            from soothe.foundation.loop.engine.scenario_classifier import BUILTIN_SCENARIOS

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
        Uses isolated checkpoint thread to prevent replay of parent AgentLoop history.

        Args:
            goal: Goal description.
            state: Loop state with thread context and execution ledger (`loop_messages`).

        Yields:
            LangGraph ``messages``-mode stream tuples tagged with ``phase=goal_completion``.
        """

        classification = await self._classify_scenario(goal, state)
        max_total = self._synthesis_max_chars()
        messages = build_synthesis_messages(
            state,
            classification,
            user_query=goal,
            max_chars=max_total,
        )

        approx_chars = sum(
            len(extract_text_from_message_content(getattr(m, "content", ""))) for m in messages
        )
        logger.info(
            "Synthesis generator: scenario=%s sections=%d ledger_msgs=%d prompt_msgs=%d approx_chars=%d",
            classification.scenario,
            len(classification.sections),
            len(state.loop_messages),
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
        async for chunk in self.llm.astream(messages, config=graph_config):
            yield tag_messages_stream_chunk_for_goal_completion(
                ((), "messages", (chunk, {})),
                thread_id=state.thread_id,
                iteration=state.iteration,
            )

    def _synthesis_max_chars(self) -> int:
        """Return max total extracted text for system + evidence payload (IG-317)."""
        max_chars = _DEFAULT_SYNTHESIS_EVIDENCE_MAX
        if self._soothe_config is not None:
            cap = self._soothe_config.agent.loop.report_output.synthesis_max_chars
            if cap > 0:
                max_chars = cap
        return max_chars
