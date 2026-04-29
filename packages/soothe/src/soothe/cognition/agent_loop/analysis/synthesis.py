"""Synthesis execution logic for comprehensive final report generation (RFC-603, RFC-616, IG-300).

Consolidated execution module:
- Scenario classification (Phase 1 via ScenarioClassifier)
- Synthesis generation (Phase 2 via CoreAgent streaming)

Separation of concerns (IG-300):
- policies/goal_completion_policy.py: Decision logic ("should we synthesize?")
- analysis/scenario_classifier.py: Classification logic ("what scenario?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")

Checkpoint isolation (IG-302): synthesis uses a fresh LangGraph ``thread_id`` so the
checkpointer does not replay the full AgentLoop message history; only system + the
synthesis human turn are loaded.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from soothe.cognition.agent_loop.analysis.scenario_classifier import (
    ScenarioClassification,
    classify_synthesis_scenario,
)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.utils.messages import (
    LoopHumanMessage,
    tag_messages_stream_chunk_for_goal_completion,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)

_DEFAULT_SYNTHESIS_EVIDENCE_MAX = 120_000

_SYNTH_GC_MARKER = "__synth_gc__"


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

    Two-phase synthesis system:
    - Phase 1: ScenarioClassifier determines scenario + structure
    - Phase 2: CoreAgent generates synthesis following scenario template

    Removed legacy components (IG-300):
    - Keyword-based goal_type classification
    - Response length categorization
    - Length-based guidance
    """

    def __init__(
        self,
        llm_client: BaseChatModel,
        core_agent: CoreAgent,
        soothe_config: SootheConfig | None = None,
    ) -> None:
        """Initialize synthesis generator with LLM client and CoreAgent.

        Args:
            llm_client: Fast model for scenario classification (Phase 1).
            core_agent: CoreAgent for synthesis execution with streaming (Phase 2).
            soothe_config: Optional daemon config for evidence budgeting (IG-317).
        """
        self.llm = llm_client
        self.core_agent = core_agent
        self._soothe_config = soothe_config

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
            return await classify_synthesis_scenario(goal, state, self.llm)
        except Exception:
            logger.warning("Classifier failed, using fallback", exc_info=True)
            from soothe.cognition.agent_loop.analysis.scenario_classifier import BUILTIN_SCENARIOS

            return ScenarioClassification(
                scenario="general_summary",
                sections=BUILTIN_SCENARIOS["general_summary"],
                contextual_focus=["Provide concise summary of goal completion"],
                evidence_emphasis="Use any available tool results or AI responses",
            )

    async def generate_synthesis(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
    ) -> AsyncGenerator:
        """Generate synthesis via CoreAgent streaming (RFC-616, IG-300).

        Two-phase flow:
        1. Classify scenario from goal + intent + execution
        2. Build synthesis prompt using classification
        3. Stream via CoreAgent

        Yields LangGraph ``messages``-mode stream tuples tagged with ``phase=goal_completion``
        for RFC-614 / IG-317 (AgentLoop wraps as ``stream_event``).

        Args:
            goal: Goal description.
            state: Loop state with thread context and execution history.
            plan_result: Plan result (reserved for future hints).

        Yields:
            ``(namespace, mode, data)`` stream chunks (same shape as CoreAgent ``astream``).
        """
        _ = plan_result  # Reserved for future use

        # Extract evidence
        evidence = self._extract_evidence(state)

        # Phase 1: Classify scenario
        classification = await self._classify_scenario(goal, state)

        # Phase 2: Build synthesis prompt from classification
        prompt = self._build_synthesis_prompt(goal, evidence, classification)

        # Create human message
        human_msg = LoopHumanMessage(
            content=prompt,
            thread_id=state.thread_id,
            iteration=state.iteration,
            goal_summary=state.goal[:200] if state.goal else None,
            phase="goal_completion",
        )

        logger.info(
            "Synthesis generator: scenario=%s sections=%d evidence_chars=%d",
            classification.scenario,
            len(classification.sections),
            len(evidence),
        )

        # IG-302: Fresh checkpoint thread so LangGraph does not replay full AgentLoop history.
        checkpoint_thread_id = synthesis_checkpoint_thread_id(state.thread_id)
        configurable: dict[str, str] = {"thread_id": checkpoint_thread_id}
        if state.workspace:
            configurable["workspace"] = state.workspace
        logger.info(
            "Synthesis isolated checkpoint thread=%s parent_thread=%s",
            checkpoint_thread_id,
            state.thread_id,
        )

        async for chunk in self.core_agent.astream(
            {"messages": [human_msg]},
            config={"configurable": configurable},
            stream_mode=["messages"],
            subgraphs=False,
        ):
            yield tag_messages_stream_chunk_for_goal_completion(
                chunk,
                thread_id=state.thread_id,
                iteration=state.iteration,
            )

    def _extract_evidence(self, state: LoopState) -> str:
        """Build bounded detailed evidence for synthesis (IG-317)."""
        evidence_parts: list[str] = []
        for result in state.step_results:
            if result.success:
                evidence_parts.append(result.get_detailed_evidence_string())

        if not evidence_parts:
            return "No execution evidence available (goal completed without tools)"

        raw = "\n\n".join(evidence_parts)
        max_chars = _DEFAULT_SYNTHESIS_EVIDENCE_MAX
        if self._soothe_config is not None:
            cap = self._soothe_config.agentic.report_output.synthesis_max_chars
            if cap > 0:
                max_chars = cap
        if len(raw) > max_chars:
            marker = "\n\n[evidence truncated for synthesis prompt]\n"
            return raw[: max_chars - len(marker)] + marker
        return raw

    def _build_synthesis_prompt(
        self,
        goal: str,
        evidence: str,
        classification: ScenarioClassification,
    ) -> str:
        """Build synthesis prompt from scenario classification (RFC-616, IG-300).

        Args:
            goal: Goal description.
            evidence: Concatenated evidence from successful steps.
            classification: Scenario classification from Phase 1.

        Returns:
            Complete synthesis prompt text with scenario structure and focus.
        """
        focus_items = "\n".join(f"- {focus}" for focus in classification.contextual_focus)

        return f"""Generate a {classification.scenario} synthesis for the goal: {goal}

SCENARIO STRUCTURE:
Sections: {", ".join(classification.sections)}

CONTEXTUAL FOCUS:
{focus_items}

EVIDENCE EMPHASIS:
{classification.evidence_emphasis}

EXECUTION EVIDENCE:
{evidence}

INSTRUCTIONS:
1. Follow the scenario structure - address each section purposefully
2. Focus on the contextual areas identified above
3. Judge appropriate depth and detail level based on the goal and evidence
4. Extract and present actual content from tool results (file contents, search results, etc.)
   - ToolMessage.content contains the actual file content, search results, etc.
   - For file reading: show the actual file content (with line numbers if applicable)
   - For web/research: show actual search results or fetched content
5. Be concrete and actionable - show findings, not just confirmations
6. Use the full execution history available in the conversation context"""
