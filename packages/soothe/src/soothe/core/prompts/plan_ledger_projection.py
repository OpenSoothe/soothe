"""Project AgentLoop ledger messages for plan-assess / plan-generate (IG-380, RFC-214).

RFC-214: The complete ledger includes all phases (plan_assess, plan_generate,
execute_step). Plan prompts see the full ledger for cache maximization.
CoreAgent execution sees only execute_step messages (plan-phase reasoning
not injected into CoreAgent thread).

When ``PlanPromptLedgerConfig`` limits are all zero/unset behavior, the caller
receives the same message object references as ``state.loop_messages`` (shallow
list copy). When any limit is positive, messages are deep-copied and trimmed
without mutating persisted ledger state.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from soothe.core.agent_loop.utils.stream_normalize import extract_text_from_message_content

if TYPE_CHECKING:
    from soothe.config.models import PlanPromptLedgerConfig

logger = logging.getLogger(__name__)

_LEDGER_OMITTED_MARKER = "[Earlier ledger content omitted for plan prompt size]\n\n"
_TRUNC_PER_MSG = "\n…[truncated for plan prompt]\n"


def _deep_copy_message(msg: BaseMessage) -> BaseMessage:
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(deep=True)
    return copy.deepcopy(msg)


def _message_text_len(msg: BaseMessage) -> int:
    return len(extract_text_from_message_content(getattr(msg, "content", "")))


def _set_message_content(msg: BaseMessage, text: str) -> BaseMessage:
    copier = getattr(msg, "model_copy", None)
    if callable(copier):
        return copier(update={"content": text})
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=text)
    if isinstance(msg, AIMessage):
        return AIMessage(content=text)
    return msg


def _cap_single_message_content(msg: BaseMessage, max_chars: int) -> BaseMessage:
    if max_chars <= 0:
        return msg
    text = extract_text_from_message_content(getattr(msg, "content", ""))
    if len(text) <= max_chars:
        return msg
    clipped = text[: max(0, max_chars - len(_TRUNC_PER_MSG))] + _TRUNC_PER_MSG
    return _set_message_content(msg, clipped)


def _trim_total_chars_front(
    messages: list[BaseMessage], max_chars: int
) -> tuple[list[BaseMessage], bool]:
    """Drop oldest messages until total extracted text <= max_chars (or one truncated body).

    Returns:
        (trimmed_messages, True) if any leading messages were dropped or body was hard-clipped.
    """
    if max_chars <= 0 or not messages:
        return messages, False

    def total_len(ms: list[BaseMessage]) -> int:
        return sum(_message_text_len(m) for m in ms)

    out = list(messages)
    shrunk = False
    while out and total_len(out) > max_chars:
        if len(out) == 1:
            m0 = out[0]
            text = extract_text_from_message_content(getattr(m0, "content", ""))
            if len(text) <= max_chars:
                break
            marker = "\n…[truncated for plan prompt]\n"
            clipped = text[: max(0, max_chars - len(marker))] + marker
            out[0] = _set_message_content(m0, clipped)
            shrunk = True
            break
        out.pop(0)
        shrunk = True
    return out, shrunk


def project_loop_messages_for_plan(
    loop_messages: list[BaseMessage],
    ledger_cfg: PlanPromptLedgerConfig | None,
) -> list[BaseMessage]:
    """Return ledger messages for plan LLM prompts (IG-380).

    Args:
        loop_messages: RFC-214 ledger from ``LoopState.loop_messages``.
        ledger_cfg: Optional caps; ``None`` treated as all limits disabled.

    Returns:
        Same references as input when no limits apply (shallow list copy).
        Deep-trimmed copies when any limit is positive.
    """
    if ledger_cfg is None:
        return list(loop_messages)

    max_msg = int(ledger_cfg.plan_ledger_max_messages)
    max_total = int(ledger_cfg.plan_ledger_max_total_chars)
    max_per = int(ledger_cfg.plan_ledger_max_message_chars)

    if max_msg <= 0 and max_total <= 0 and max_per <= 0:
        return list(loop_messages)

    copies = [_deep_copy_message(m) for m in loop_messages]
    omitted_prefix = False

    if max_msg > 0 and len(copies) > max_msg:
        dropped = len(copies) - max_msg
        copies = copies[-max_msg:]
        omitted_prefix = dropped > 0
        logger.debug(
            "Plan ledger projection: tail messages=%d (dropped oldest=%d)",
            len(copies),
            dropped,
        )

    if max_per > 0:
        copies = [_cap_single_message_content(m, max_per) for m in copies]

    if max_total > 0:
        copies, shrunk_total = _trim_total_chars_front(copies, max_total)
        omitted_prefix = omitted_prefix or shrunk_total

    if omitted_prefix and copies:
        first = copies[0]
        text = extract_text_from_message_content(getattr(first, "content", ""))
        if not text.startswith(_LEDGER_OMITTED_MARKER.strip()):
            copies[0] = _set_message_content(first, _LEDGER_OMITTED_MARKER + text)

    logger.debug(
        "Plan ledger projection: out_msgs=%d approx_chars=%d caps(msg=%s total=%s per=%s)",
        len(copies),
        sum(_message_text_len(m) for m in copies),
        max_msg or "off",
        max_total or "off",
        max_per or "off",
    )
    return copies


def project_loop_messages_for_core_agent(
    loop_messages: list[BaseMessage],
) -> list[BaseMessage]:
    """Return ledger messages for CoreAgent thread (RFC-214).

    Filters to only execute_step phase messages. Plan-phase messages
    (plan_assess, plan_generate) are NOT injected into CoreAgent thread,
    keeping CoreAgent's history focused on tool execution.

    Args:
        loop_messages: RFC-214 complete ledger from ``LoopState.loop_messages``.

    Returns:
        Filtered list with only execute_step Human/AI message pairs.
    """
    from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage

    out: list[BaseMessage] = []
    for msg in loop_messages:
        phase = getattr(msg, "phase", None)
        if isinstance(msg, (LoopHumanMessage, LoopAIMessage)):
            if phase == "execute_step":
                out.append(msg)
        # Also include any non-loop messages (plain HumanMessage/AIMessage from early phases)
        elif isinstance(msg, (HumanMessage, AIMessage)) and phase is None:
            out.append(msg)

    logger.debug(
        "CoreAgent ledger projection: %d execute_step messages (filtered from %d total)",
        len(out),
        len(loop_messages),
    )
    return out
