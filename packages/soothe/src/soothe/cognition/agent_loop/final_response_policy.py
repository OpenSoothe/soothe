"""Adaptive final user response policy when AgentLoop reaches goal completion (IG-199)."""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from soothe.cognition.agent_loop.response_length_policy import ResponseLengthCategory
from soothe.cognition.agent_loop.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.synthesis import evidence_requires_final_synthesis

# Keep in sync with ``AgenticFinalResponseMode`` in ``soothe.config.models`` (avoid circular import).
FinalResponseMode = Literal["adaptive", "always_synthesize", "always_last_execute"]

# Structural fallbacks below the word-count floor (IG-273).
_STRUCTURED_PAYLOAD_MIN_LINES = 6


def _word_count(text: str) -> int:
    """Return whitespace-separated word count; cheap proxy aligned with IG-268 targets."""
    return len(re.findall(r"\S+", text))


def _min_word_floor(category: str | None) -> int:
    """Map IG-268 category to its minimum word count, with a default for unknown inputs."""
    try:
        return ResponseLengthCategory(category).min_words if category else 150
    except ValueError:
        return 150


def assemble_assistant_text_from_stream_messages(messages: list[BaseMessage]) -> str:
    """Extract assistant-visible text from CoreAgent stream message list.

    Matches the selection rules used for AgentLoop final-report streaming: prefer
    concatenated ``AIMessageChunk`` text over a trailing non-chunk ``AIMessage``.

    Args:
        messages: Messages collected from ``_stream_and_collect`` (AI entries only).

    Returns:
        Stripped assistant text, or empty string if none.
    """
    accumulated_chunks = ""
    final_ai_message_text = ""
    for msg in messages:
        if not isinstance(msg, (AIMessage, AIMessageChunk)):
            continue
        content = msg.content
        extracted_text = ""
        if isinstance(content, str):
            extracted_text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            extracted_text = "".join(parts)

        if isinstance(msg, AIMessageChunk) and extracted_text:
            accumulated_chunks += extracted_text
        elif isinstance(msg, AIMessage) and extracted_text:
            final_ai_message_text = extracted_text

    last_ai_text = (
        accumulated_chunks
        if len(accumulated_chunks) >= len(final_ai_message_text)
        else final_ai_message_text
    )
    return last_ai_text.strip()


def needs_final_thread_synthesis(
    state: LoopState,
    plan_result: PlanResult,
    mode: FinalResponseMode,
) -> bool:
    """Decide whether to run the extra CoreAgent final-report turn on goal completion.

    Args:
        state: AgentLoop state after Execute phases (includes last assistant capture).
        plan_result: Plan phase result with ``status == "done"``.
        mode: Config override or ``adaptive`` heuristics.

    Returns:
        True to run thread-level final report synthesis; False to prefer last Execute text.
    """
    if mode == "always_synthesize":
        return True
    if mode == "always_last_execute":
        return False

    if state.last_execute_wave_parallel_multi_step:
        return True
    if state.last_wave_hit_subagent_cap:
        return True
    if evidence_requires_final_synthesis(state, plan_result):
        return True

    assistant = (state.last_execute_assistant_text or "").strip()
    if not assistant:
        return True
    return False


def should_return_goal_completion_directly(
    state: LoopState,
    plan_result: PlanResult,
    mode: FinalResponseMode,
    *,
    response_length_category: str | None = None,
) -> bool:
    """Check whether Execute-phase assistant output can be returned directly.

    This optimization avoids a second synthesis turn when the latest Execute
    response is already user-ready for the completed goal.

    Decision rules:
    - ``plan_result.status != "done"`` → never direct-return.
    - ``always_synthesize`` → never direct-return.
    - ``always_last_execute`` → direct-return whenever Execute text exists.
    - Adaptive mode honors wave-level vetoes (parallel multi-step, subagent cap).
      When evidence heuristics request synthesis, the Execute text must also
      satisfy IG-268 richness (word-count floor aligned with the category, or
      structured content such as code fences / multi-line payloads) AND overlap
      with the planner's ``full_output`` to avoid returning unrelated chatter.

    Args:
        state: AgentLoop state after Execute phases.
        plan_result: Plan result at completion.
        mode: Final-response mode from config.
        response_length_category: IG-268 category string (``brief``, ``concise``,
            ``standard``, ``comprehensive``) used for dynamic richness thresholds.

    Returns:
        ``True`` when Execute output should be returned as goal completion.
    """
    if plan_result.status != "done":
        return False

    assistant = (state.last_execute_assistant_text or "").strip()

    if mode == "always_synthesize":
        return False
    if mode == "always_last_execute":
        # Honor the mode strictly: if there is no Execute text, the caller falls
        # back to the user-friendly summary; synthesis must not kick in.
        return bool(assistant)

    if not assistant:
        return False

    if state.last_execute_wave_parallel_multi_step:
        return False
    if state.last_wave_hit_subagent_cap:
        return False

    # In adaptive mode, evidence heuristics can request synthesis; allow bypass
    # only when Execute output is rich enough AND aligned with planner output.
    if evidence_requires_final_synthesis(state, plan_result):
        return _looks_like_complete_goal_answer(
            assistant,
            response_length_category=response_length_category,
        ) and _overlaps_with_plan_output(assistant, plan_result)

    return True


def _looks_like_complete_goal_answer(
    assistant_text: str,
    *,
    response_length_category: str | None,
) -> bool:
    """Heuristic guard for rich, user-facing completion content (IG-268, IG-273).

    Thresholds are expressed in words to stay aligned with
    :class:`ResponseLengthCategory` minimums. Short-but-structured payloads
    (code fences, multi-line lists) are accepted as an escape hatch when the
    Execute phase produced a deliberate compact answer.
    """
    text = assistant_text.strip()
    if not text:
        return False

    min_words = _min_word_floor(response_length_category)
    if _word_count(text) >= min_words:
        return True

    # Shorter responses may still be complete when they carry structured payloads.
    if "```" in text:
        return True
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    return len(non_empty_lines) >= _STRUCTURED_PAYLOAD_MIN_LINES


def _overlaps_with_plan_output(assistant_text: str, plan_result: PlanResult) -> bool:
    """Return True when Execute text appears to reflect the planner's ``full_output``.

    Used only as an adaptive-mode veto signal: if the planner captured a distinct
    ``full_output`` and the Execute assistant text shares no common substring
    with it, we assume Execute did not actually answer the goal and require
    synthesis. Absent or empty planner output leaves the decision untouched.
    """
    plan_out = (plan_result.full_output or "").strip()
    if not plan_out:
        # No planner reference available; do not veto on this signal.
        return True

    assistant_lower = assistant_text.lower()
    # Sample the first chunk of plan output for a lightweight overlap probe.
    probe = plan_out[:160].lower()
    if not probe.strip():
        return True

    # Split on whitespace and keep substantive tokens (avoid stopwords-ish noise).
    tokens = [t for t in re.split(r"\W+", probe) if len(t) >= 4]
    if not tokens:
        return True

    hits = sum(1 for t in tokens if t in assistant_lower)
    # Require at least 25% token overlap to accept direct return.
    return hits * 4 >= len(tokens)
