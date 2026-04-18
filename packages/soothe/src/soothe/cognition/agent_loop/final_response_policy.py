"""Adaptive final user response policy when AgentLoop reaches goal completion (IG-199)."""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from soothe.cognition.agent_loop.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.synthesis import evidence_requires_final_synthesis

# Keep in sync with ``AgenticFinalResponseMode`` in ``soothe.config.models`` (avoid circular import).
FinalResponseMode = Literal["adaptive", "always_synthesize", "always_last_execute"]


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
