"""Synthesis execution logic for comprehensive final report generation (RFC-603, RFC-616, IG-300).

Consolidated execution module:
- Scenario classification (Phase 1 via ScenarioClassifier)
- Synthesis generation (Phase 2 via CoreAgent streaming)

Separation of concerns (IG-300):
- policies/goal_completion_policy.py: Decision logic ("should we synthesize?")
- analysis/scenario_classifier.py: Classification logic ("what scenario?")
- analysis/synthesis.py: Execution logic ("how to synthesize?")

Checkpoint isolation (IG-302): synthesis uses a fresh LangGraph ``thread_id`` so the
checkpointer does not replay the parent thread. The model receives copies of the
AgentLoop ledger (``loop_messages``) plus a final goal-completion instruction turn.
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.core.agent_loop.analysis.scenario_classifier import (
    ScenarioClassification,
    classify_synthesis_scenario,
)
from soothe.core.agent_loop.state.schemas import LoopState, PlanResult
from soothe.core.agent_loop.utils.messages import (
    LoopHumanMessage,
    tag_messages_stream_chunk_for_goal_completion,
)
from soothe.core.agent_loop.utils.stream_normalize import extract_text_from_message_content
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
from soothe.utils.similarity import semantic_similarity

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.config import SootheConfig
    from soothe.core.agent import CoreAgent

logger = logging.getLogger(__name__)

_DEFAULT_SYNTHESIS_EVIDENCE_MAX = 120_000
_DEFAULT_LOOP_MESSAGE_MIN_SIMILARITY = 0.35
_DEFAULT_LOOP_MESSAGE_MIN_AI_COUNT = 5

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

    Two-phase synthesis: scenario classification, then CoreAgent generation (IG-300).
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
            from soothe.core.agent_loop.analysis.scenario_classifier import BUILTIN_SCENARIOS

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
        2. Assemble ``messages``: copies of ``state.loop_messages`` (plus a final instruction turn)
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

        # Phase 1: Classify scenario
        classification = await self._classify_scenario(goal, state)

        # Phase 2: Ledger copies + final instruction (no flattened EXECUTION EVIDENCE string)
        instruction = self._build_synthesis_instruction(goal, classification)
        max_total = self._synthesis_max_chars()
        ledger_budget = max(0, max_total - len(instruction) - 256)
        ledger_messages = self._ledger_messages_for_synthesis(state, ledger_budget, goal=goal)
        messages = [
            *ledger_messages,
            self._synthesis_instruction_message(state, instruction),
        ]
        # Hard cap: drop oldest ledger turns if instruction + ledger exceeds configured maximum.
        while len(messages) > 1:
            approx = sum(
                len(extract_text_from_message_content(getattr(m, "content", ""))) for m in messages
            )
            if approx <= max_total:
                break
            messages.pop(0)

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

        graph_config: dict[str, Any] = {"configurable": configurable}
        if self._soothe_config is not None:
            graph_config = merge_langfuse_runnable_config(
                graph_config,
                self._soothe_config,
                session_id=state.thread_id,
            )

        async for chunk in self.core_agent.astream(
            {"messages": messages},
            config=graph_config,
            stream_mode=["messages"],
            subgraphs=False,
        ):
            yield tag_messages_stream_chunk_for_goal_completion(
                chunk,
                thread_id=state.thread_id,
                iteration=state.iteration,
            )

    def _synthesis_max_chars(self) -> int:
        """Return max total extracted text for ledger + instruction (IG-317)."""
        max_chars = _DEFAULT_SYNTHESIS_EVIDENCE_MAX
        if self._soothe_config is not None:
            cap = self._soothe_config.agentic.report_output.synthesis_max_chars
            if cap > 0:
                max_chars = cap
        return max_chars

    @staticmethod
    def _copy_message_for_synthesis(msg: BaseMessage) -> BaseMessage:
        """Deep-copy a ledger message so CoreAgent cannot mutate AgentLoop state."""
        copier = getattr(msg, "model_copy", None)
        if callable(copier):
            return copier(deep=True)
        return copy.deepcopy(msg)

    def _filter_messages_by_goal_relevance(
        self,
        messages: list[BaseMessage],
        goal: str,
        *,
        min_similarity: float = _DEFAULT_LOOP_MESSAGE_MIN_SIMILARITY,
        min_ai_count: int = _DEFAULT_LOOP_MESSAGE_MIN_AI_COUNT,
    ) -> list[BaseMessage]:
        """Filter messages by relevance to the synthesis goal.

        Only filters when there are >= min_ai_count AI messages to avoid overhead on small contexts.
        Uses semantic_similarity only (no keyword fallback).
        If filtering removes too many messages (< 2 remaining), synthesizes ALL messages.
        """
        # Only filter when >= min_ai_count AI messages
        ai_message_count = sum(1 for m in messages if isinstance(m, AIMessage))
        if ai_message_count < min_ai_count:
            return messages

        goal_text = (goal or "").strip()
        if not goal_text:
            return messages

        # Score each message by semantic similarity to goal
        scored_messages = []
        for msg in messages:
            content = extract_text_from_message_content(getattr(msg, "content", ""))
            if not content or not content.strip():
                scored_messages.append((0.0, msg))
                continue

            score = semantic_similarity(content, goal_text)
            scored_messages.append((score, msg))

        # Filter by threshold
        filtered = [msg for score, msg in scored_messages if score >= min_similarity]

        # Fallback: if filtering too aggressive, synthesize ALL messages
        if len(filtered) < 2:
            logger.debug(
                "Filtering too aggressive: %d/%d retained, using all messages",
                len(filtered),
                len(messages),
            )
            return messages

        removed = len(messages) - len(filtered)
        if removed > 0:
            logger.info(
                "Filtered %d/%d messages below relevance threshold %.2f",
                removed,
                len(messages),
                min_similarity,
            )

        return filtered

    def _ledger_messages_for_synthesis(
        self,
        state: LoopState,
        ledger_char_budget: int,
        goal: str | None = None,
    ) -> list[BaseMessage]:
        """Return bounded ledger copies, optionally filtered by goal relevance."""
        budget = max(0, ledger_char_budget)

        if state.loop_messages:
            copies = [self._copy_message_for_synthesis(m) for m in state.loop_messages]

            # Filter by goal relevance if goal provided
            if goal:
                copies = self._filter_messages_by_goal_relevance(copies, goal)

            return self._trim_messages_by_extracted_chars(copies, budget)

        evidence_parts = [
            r.to_evidence_string(truncate=False) for r in state.step_results if r.success
        ]
        body = (
            "\n\n".join(evidence_parts)
            if evidence_parts
            else "No execution evidence available (goal completed without tools)"
        )
        if budget > 0 and len(body) > budget:
            marker = "\n\n[execution summary truncated for synthesis]\n"
            body = body[: max(0, budget - len(marker))] + marker
        return [
            HumanMessage(
                content=(
                    "AgentLoop execution ledger was unavailable. "
                    "Use the following compact step summaries as execution context:\n\n" + body
                )
            )
        ]

    def _trim_messages_by_extracted_chars(
        self,
        messages: list[BaseMessage],
        max_chars: int,
    ) -> list[BaseMessage]:
        """Drop oldest messages (or truncate a single oversized body) to respect ``max_chars``."""
        if max_chars <= 0 or not messages:
            return []

        def total_len(ms: list[BaseMessage]) -> int:
            return sum(
                len(extract_text_from_message_content(getattr(m, "content", ""))) for m in ms
            )

        out = list(messages)
        while out and total_len(out) > max_chars:
            if len(out) == 1:
                m0 = out[0]
                text = extract_text_from_message_content(m0.content)
                if len(text) <= max_chars:
                    break
                marker = "\n…[truncated for synthesis]\n"
                clipped = text[: max_chars - len(marker)] + marker
                copier = getattr(m0, "model_copy", None)
                if callable(copier):
                    out[0] = m0.model_copy(update={"content": clipped})
                else:
                    out[0] = HumanMessage(content=clipped)
                break
            out.pop(0)

        return out

    def _synthesis_instruction_message(
        self, state: LoopState, instruction: str
    ) -> LoopHumanMessage:
        """Final human turn: scenario template only; execution context is prior messages."""
        return LoopHumanMessage(
            content=instruction,
            thread_id=state.thread_id,
            iteration=state.iteration,
            goal_summary=state.goal[:200] if state.goal else None,
            phase="goal_completion",
        )

    def _build_synthesis_instruction(
        self,
        goal: str,
        classification: ScenarioClassification,
    ) -> str:
        """Build the closing synthesis instruction (scenario template; no embedded evidence).

        Prior messages in the same request carry the AgentLoop ledger (RFC-214).

        Args:
            goal: Goal description.
            classification: Scenario classification from Phase 1.

        Returns:
            Instruction text for the final ``LoopHumanMessage``.
        """
        focus_items = "\n".join(f"- {focus}" for focus in classification.contextual_focus)

        return f"""Generate a {classification.scenario} synthesis for the goal: {goal}

SCENARIO STRUCTURE:
Sections: {", ".join(classification.sections)}

CONTEXTUAL FOCUS:
{focus_items}

EVIDENCE EMPHASIS:
{classification.evidence_emphasis}

INSTRUCTIONS:
1. Use the AgentLoop execution messages above (human execute prompts and assistant outcomes) as primary evidence.
2. Follow the scenario structure - address each section purposefully.
3. Focus on the contextual areas identified above.
4. Extract and present actual content reflected in that history (file contents, search results, tool outcomes, etc.).
5. Be concrete and actionable - show findings, not just confirmations.
6. If prior turns are missing or sparse, state what is unknown rather than inventing execution detail."""
