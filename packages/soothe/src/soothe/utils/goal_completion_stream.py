"""Goal-completion stream accumulation helpers (StrangeLoop synthesis paths)."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from soothe.utils.messages import extract_text_from_message_content


@dataclass
class GoalCompletionAccumState:
    """Mutable accumulators for adaptive goal-completion streaming."""

    accumulated_chunks: str = ""
    final_ai_message_text: str = ""
    ai_msg_count: int = 0


def update_goal_completion_from_message(state: GoalCompletionAccumState, msg: BaseMessage) -> None:
    """Update goal-completion accumulators from one streamed AI message."""
    if not isinstance(msg, (AIMessage, AIMessageChunk)):
        return

    state.ai_msg_count += 1
    extracted = extract_text_from_message_content(msg.content)

    if isinstance(msg, AIMessageChunk):
        if extracted:
            state.accumulated_chunks += extracted
        return

    if isinstance(msg, AIMessage) and extracted:
        state.final_ai_message_text = extracted


def resolve_goal_completion_text(state: GoalCompletionAccumState) -> str:
    """Choose longer of accumulated chunk text vs final non-chunk AI text."""
    if len(state.accumulated_chunks) >= len(state.final_ai_message_text):
        text = state.accumulated_chunks
    else:
        text = state.final_ai_message_text

    if not text:
        return ""

    lines = text.split("\n")
    result: list[str] = []
    empty_count = 0
    have_content = False

    for line in lines:
        if line == "":
            empty_count += 1
        else:
            if empty_count > 0:
                if not have_content:
                    result.append("")
                    result.append("")
                else:
                    result.append("")
            empty_count = 0
            have_content = True
            result.append(line)

    if empty_count > 0:
        result.append("")
        result.append("")

    return "\n".join(result)


__all__ = [
    "GoalCompletionAccumState",
    "resolve_goal_completion_text",
    "update_goal_completion_from_message",
]
