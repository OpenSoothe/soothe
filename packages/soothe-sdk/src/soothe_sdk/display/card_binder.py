"""Pure event → ``MessageData`` binding logic (RFC-413).

The functions here have **no Textual / widget / rendering dependencies** so
the same logic can run from the TUI and from the daemon-resident card
ledger without source changes.

Inputs are LangChain checkpoint messages or persisted activity-event rows
from the daemon conversation log. Outputs are lightweight ``MessageData``
objects suitable for ``MessageStore.bulk_load`` (TUI) or ``card.*`` frame
emission (daemon).
"""

from __future__ import annotations

import logging
import time as _time
from ast import literal_eval
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from soothe_sdk.display.message_processing import (
    extract_tool_args_dict,
    normalize_tool_calls_list,
)
from soothe_sdk.display.text_extract import (
    extract_ai_text_for_display,
    extract_user_text_for_display,
    normalize_stream_message,
)
from soothe_sdk.display.tool_result import extract_tool_result_payload
from soothe_sdk.display.transcript_types import MessageData, MessageType, ToolStatus

logger = logging.getLogger(__name__)

# Phases persisted on loop checkpoint messages that the live TUI aggregates into
# cognition cards (plan / step / task rows) rather than standalone assistant
# and tool widgets.
_LOOP_INTERNAL_CHECKPOINT_PHASES: frozenset[str] = frozenset(
    {"plan_assess", "plan_generate", "execute_step", "execute_wave"}
)


def is_loop_internal_checkpoint_message(msg: Any) -> bool:
    """True when this checkpoint message is loop-orchestration internals only."""
    if not isinstance(msg, (HumanMessage, AIMessage)):
        return False
    phase = getattr(msg, "phase", None)
    return isinstance(phase, str) and phase in _LOOP_INTERNAL_CHECKPOINT_PHASES


def merge_visible_messages_with_cognition_cards(
    visible: list[MessageData],
    cognition: list[MessageData],
) -> list[MessageData]:
    """Interleave visible checkpoint cards with cognition replay by time.

    Visible messages have unreliable wall times; cognition rows carry parsed
    event timestamps. Spread visible items across ``[0, 1]`` in order and map
    cognition timestamps into the same range so the transcript reads naturally
    (user → plan/step cards → final assistant).

    Args:
        visible: ``MessageData`` from checkpoint after internal phases were
            stripped.
        cognition: Cognition card replay from the conversation log.

    Returns:
        Merged list for bulk load.
    """
    if not cognition:
        return visible
    if not visible:
        return list(cognition)

    n = len(visible)
    vis_spread = max(1, n - 1)
    vis_entries: list[tuple[float, MessageData]] = [
        (i / vis_spread, m) for i, m in enumerate(visible)
    ]
    sorted_cog = sorted(cognition, key=lambda m: m.timestamp)
    ts0 = sorted_cog[0].timestamp
    ts1 = sorted_cog[-1].timestamp
    span = ts1 - ts0 or 1.0
    cog_entries: list[tuple[float, MessageData]] = []
    for m in sorted_cog:
        # Keep inside (0, 1) so tie-break ordering stays stable vs endpoints.
        frac = (m.timestamp - ts0) / span
        mapped = 0.05 + 0.9 * frac
        cog_entries.append((mapped, m))
    merged = sorted([*vis_entries, *cog_entries], key=lambda x: x[0])
    return [m for _, m in merged]


def convert_messages_to_data(
    messages: list[Any],
    *,
    cognition_card_replay: list[MessageData] | None = None,
) -> list[MessageData]:
    """Convert LangChain messages into lightweight ``MessageData`` objects.

    This is a pure function with zero DOM operations. Tool call matching
    happens here: ``ToolMessage`` results are matched by ``tool_call_id`` and
    stored directly on the corresponding ``MessageData``.

    Args:
        messages: LangChain message objects from a LangGraph checkpoint.
        cognition_card_replay: When non-empty, strip checkpoint messages
            tagged with internal loop phases and merge these cognition cards
            (plan / goal / step) so resume matches live streaming.

    Returns:
        Ordered list of ``MessageData`` ready for ``MessageStore.bulk_load``.
    """
    hide_internals = bool(cognition_card_replay)
    result: list[MessageData] = []
    # Maps tool_call_id -> index into result list
    pending_tool_indices: dict[str, int] = {}

    for msg in messages:
        msg = normalize_stream_message(msg)
        if hide_internals and is_loop_internal_checkpoint_message(msg):
            continue
        user_text = extract_user_text_for_display(msg)
        if user_text is not None:
            # Detect skill invocations persisted via additional_kwargs
            skill_meta = (msg.additional_kwargs or {}).get("__skill")
            if isinstance(skill_meta, dict) and skill_meta.get("name"):
                result.append(
                    MessageData(
                        type=MessageType.SKILL,
                        content="",
                        skill_name=skill_meta["name"],
                        skill_description=str(skill_meta.get("description", "")),
                        skill_source=str(skill_meta.get("source", "")),
                        skill_args=str(skill_meta.get("args", "")),
                        skill_body=user_text,
                    )
                )
            else:
                result.append(MessageData(type=MessageType.USER, content=user_text))

        elif isinstance(msg, AIMessage):
            text = extract_ai_text_for_display(msg)
            if text:
                result.append(MessageData(type=MessageType.ASSISTANT, content=text))

            # Track tool calls for later matching
            for tc in normalize_tool_calls_list(getattr(msg, "tool_calls", [])):
                tc_id = tc.get("id")
                name = tc.get("name", "unknown")
                args = extract_tool_args_dict(tc)
                data = MessageData(
                    type=MessageType.TOOL,
                    content="",
                    tool_name=name,
                    tool_args=args,
                    tool_status=ToolStatus.PENDING,
                )
                result.append(data)
                if tc_id:
                    pending_tool_indices[tc_id] = len(result) - 1
                else:
                    data.tool_status = ToolStatus.REJECTED

        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id in pending_tool_indices:
                idx = pending_tool_indices.pop(tc_id)
                data = result[idx]
                payload = extract_tool_result_payload(msg)
                if payload is not None:
                    data.tool_status = ToolStatus.ERROR if payload.is_error else ToolStatus.SUCCESS
                    data.tool_output = payload.output_display
                else:
                    status = getattr(msg, "status", "success")
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if status == "success":
                        data.tool_status = ToolStatus.SUCCESS
                    else:
                        data.tool_status = ToolStatus.ERROR
                    data.tool_output = content
            else:
                logger.debug(
                    "ToolMessage with tool_call_id=%r could not be matched to a pending tool call",
                    tc_id,
                )

        else:
            logger.debug(
                "Skipping unsupported message type %s during history conversion",
                type(msg).__name__,
            )

    # Mark unmatched tool calls as rejected
    for idx in pending_tool_indices.values():
        result[idx].tool_status = ToolStatus.REJECTED

    if cognition_card_replay:
        return merge_visible_messages_with_cognition_cards(
            result,
            cognition_card_replay,
        )
    return result


def conversation_rows_to_langchain_messages(rows: list[dict[str, Any]]) -> list[Any]:
    """Convert persisted conversation rows to LangChain message objects."""
    messages: list[Any] = []
    for row in rows:
        if str(row.get("kind") or "").strip() != "conversation":
            continue
        metadata = row.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        role = str(row.get("role") or metadata_dict.get("role") or "").strip().lower()
        content = str(row.get("content") or metadata_dict.get("text") or "").strip()
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def parse_loop_event_timestamp(timestamp: Any) -> datetime | None:
    """Parse an event timestamp into a UTC-aware datetime.

    Args:
        timestamp: Raw timestamp string from a persisted event row.

    Returns:
        Parsed UTC-aware datetime, or ``None`` when parsing fails.
    """
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def convert_event_to_message_data(event: dict[str, Any]) -> MessageData | None:
    """Convert one persisted activity-event row to ``MessageData``.

    Args:
        event: Conversation-log row with optional metadata payload.

    Returns:
        ``MessageData`` when a displayable card can be built, else ``None``.
    """
    kind = str(event.get("kind") or "").strip()
    metadata_raw = event.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    parsed_ts = parse_loop_event_timestamp(event.get("timestamp"))

    event_timestamp = parsed_ts.timestamp() if parsed_ts is not None else _time.time()

    if kind == "conversation":
        role = str(event.get("role") or metadata.get("role") or "").strip().lower()
        content = str(event.get("content") or metadata.get("text") or "").strip()
        if not content:
            return None
        if role == "user":
            return MessageData(
                type=MessageType.USER,
                content=content,
                timestamp=event_timestamp,
            )
        if role == "assistant":
            return MessageData(
                type=MessageType.ASSISTANT,
                content=content,
                timestamp=event_timestamp,
            )
        return None

    if kind == "tool_call":
        tool_name = str(event.get("tool_name") or metadata.get("tool_name") or "unknown")
        args_preview = str(
            event.get("args_preview") or metadata.get("args_preview") or event.get("content") or ""
        ).strip()
        parsed_args: dict[str, Any] | None = None
        if args_preview:
            with suppress(ValueError, SyntaxError):
                parsed = literal_eval(args_preview)
                if isinstance(parsed, dict):
                    parsed_args = parsed
        return MessageData(
            type=MessageType.TOOL,
            content="",
            tool_name=tool_name,
            tool_args=parsed_args,
            tool_status=ToolStatus.RUNNING,
            timestamp=event_timestamp,
        )

    if kind == "tool_result":
        tool_name = str(event.get("tool_name") or metadata.get("tool_name") or "unknown")
        content = str(event.get("content") or metadata.get("content") or "")
        return MessageData(
            type=MessageType.TOOL,
            content="",
            tool_name=tool_name,
            tool_status=ToolStatus.SUCCESS,
            tool_output=content,
            timestamp=event_timestamp,
        )

    if kind == "event":
        event_data = event.get("data")
        if not isinstance(event_data, dict):
            nested_data = metadata.get("data")
            if isinstance(nested_data, dict):
                event_data = nested_data
            else:
                return None

        if isinstance(event_data, dict):
            event_type = str(event_data.get("type") or "").strip()
            if event_type == "soothe.cognition.agent_loop.completed":
                # Render a concise completion report so resumed transcripts
                # have a clear endpoint marker (the live transcript reads
                # this from streamed progress; replay needs an explicit
                # row). The final assistant text is still recovered
                # separately from the checkpoint ``phase=goal_completion``
                # AIMessage.
                status = str(event_data.get("status") or "").strip() or "completed"
                goal_progress = str(event_data.get("goal_progress") or "").strip()
                total_steps = int(event_data.get("total_steps") or 0)
                completion_summary = str(event_data.get("completion_summary") or "").strip()
                parts = [f"Goal {status}"]
                if goal_progress:
                    parts.append(f"progress={goal_progress}")
                if total_steps:
                    parts.append(f"{total_steps} step{'s' if total_steps != 1 else ''}")
                line = " · ".join(parts)
                if completion_summary:
                    line = f"{line} — {completion_summary}"
                return MessageData(
                    type=MessageType.APP,
                    content=line,
                    timestamp=event_timestamp,
                )
            if event_type == "soothe.cognition.agent_loop.reasoned":
                assessment = str(event_data.get("assessment_reasoning") or "").strip()
                plan_reasoning = str(event_data.get("plan_reasoning") or "").strip()
                if not assessment and not plan_reasoning:
                    return None
                plan_action_raw = str(event_data.get("plan_action") or "").strip()
                plan_action = plan_action_raw if plan_action_raw in {"keep", "new"} else ""
                return MessageData(
                    type=MessageType.COGNITION_REASON,
                    content="",
                    timestamp=event_timestamp,
                    cognition_plan_next_action="",
                    cognition_plan_status=str(event_data.get("status") or ""),
                    cognition_plan_iteration=int(event_data.get("iteration") or 0),
                    cognition_plan_action=plan_action,
                    cognition_plan_assessment=assessment,
                    cognition_plan_strategy=plan_reasoning,
                )
            if event_type == "soothe.cognition.agent_loop.started":
                # The goal-tree pin (📍 goal · iter<=N) is suppressed on
                # history replay: it only adds value while the loop is
                # actively planning. Replayed transcripts already show the
                # user prompt, step cards, and the completion summary.
                return None
            if event_type == "soothe.cognition.agent_loop.step.started":
                step_id = str(event_data.get("step_id") or "").strip()
                if not step_id:
                    return None
                return MessageData(
                    type=MessageType.STEP_PROGRESS,
                    content="",
                    timestamp=event_timestamp,
                    step_progress_id=step_id,
                    step_progress_description=str(event_data.get("description") or "(step)"),
                    step_progress_phase="running",
                )
            if event_type == "soothe.cognition.agent_loop.step.completed":
                step_id = str(event_data.get("step_id") or "").strip()
                if not step_id:
                    return None
                success = bool(event_data.get("success", True))
                summary_text = str(
                    event_data.get("summary") or event_data.get("output_preview") or ""
                ).strip()
                if not summary_text:
                    summary_text = "Done" if success else "Failed"
                return MessageData(
                    type=MessageType.STEP_PROGRESS,
                    content="",
                    timestamp=event_timestamp,
                    step_progress_id=step_id,
                    step_progress_description=str(event_data.get("description") or "(step)"),
                    step_progress_phase="success" if success else "error",
                    step_success=success,
                    step_duration_ms=int(event_data.get("duration_ms") or 0),
                    step_tool_call_count=int(event_data.get("tool_call_count") or 0),
                    step_summary=summary_text,
                )

        # Unrecognized event type — drop it (matches live UX which silently
        # filters non-cognition stream events). The previous "Event: <type>"
        # catch-all leaked intermediate plan-decision and tool-call.update
        # rows into resumed transcripts.
        return None

    return None


def collect_cognition_card_replay(events: list[dict[str, Any]]) -> list[MessageData]:
    """Build cognition card replay rows for TUI parity with live streaming.

    Live streaming mutates a single ``CognitionStepMessage`` widget per
    ``step_id`` (started → completed transitions the same card in place),
    so the replay must collapse the started/completed event pair to one
    card too. We keep the latest state per ``step_id`` — completed when
    present (it carries duration, summary, tool-count), otherwise the
    started card so the step still appears in the transcript.

    Args:
        events: Raw conversation-log rows (``kind=event`` with cognition payloads).

    Returns:
        Ordered cognition ``MessageData`` (goal tree, plan, step cards).
    """
    sorted_events = sorted(
        events,
        key=lambda event: (
            parse_loop_event_timestamp(event.get("timestamp")) or datetime.min.replace(tzinfo=UTC)
        ),
    )
    cards: list[MessageData] = []
    step_card_position: dict[str, int] = {}
    for event in sorted_events:
        if str(event.get("kind") or "").strip() != "event":
            continue
        msg_data = convert_event_to_message_data(event)
        if msg_data is None:
            continue
        if msg_data.type not in (
            MessageType.COGNITION_REASON,
            MessageType.COGNITION_GOAL_TREE,
            MessageType.STEP_PROGRESS,
        ):
            continue
        if msg_data.type == MessageType.STEP_PROGRESS and msg_data.step_progress_id:
            step_id = msg_data.step_progress_id
            existing = step_card_position.get(step_id)
            if existing is not None:
                # Mirror live in-place mutation of CognitionStepMessage:
                # transition phase/duration/tools to the later event but
                # preserve the description (the schema for
                # AgenticStepCompletedEvent omits ``description`` — only
                # ``step.started`` carries it).
                cards[existing] = merge_step_progress(cards[existing], msg_data)
                continue
            step_card_position[step_id] = len(cards)
        cards.append(msg_data)
    return cards


def merge_step_progress(prior: MessageData, later: MessageData) -> MessageData:
    """Combine two ``STEP_PROGRESS`` cards (typically started → completed)."""
    # Prefer the later event's status / metrics / summary, but keep the
    # description from whichever card has one (started has it; completed
    # doesn't and falls back to the placeholder "(step)").
    prior_desc = (prior.step_progress_description or "").strip()
    later_desc = (later.step_progress_description or "").strip()
    description = (
        later_desc
        if later_desc and later_desc != "(step)"
        else (prior_desc if prior_desc and prior_desc != "(step)" else later_desc or prior_desc)
    )
    return MessageData(
        type=MessageType.STEP_PROGRESS,
        content=later.content,
        timestamp=later.timestamp,
        step_progress_id=later.step_progress_id or prior.step_progress_id,
        step_progress_description=description or "(step)",
        step_progress_phase=later.step_progress_phase or prior.step_progress_phase,
        step_success=later.step_success if later.step_success is not None else prior.step_success,
        step_duration_ms=later.step_duration_ms or prior.step_duration_ms,
        step_tool_call_count=later.step_tool_call_count or prior.step_tool_call_count,
        step_summary=later.step_summary or prior.step_summary,
    )


def convert_loop_events_to_data(events: list[dict[str, Any]]) -> list[MessageData]:
    """Convert persisted activity-event rows into stable TUI cards.

    This fallback is used only when checkpoint messages are unavailable.
    """
    data: list[MessageData] = []
    pending_tool_indices: dict[str, list[int]] = {}
    # Track step_progress card index per step_id so a later `completed`
    # event mutates the same card instead of mounting a second one — see
    # collect_cognition_card_replay for the same rationale.
    step_card_position: dict[str, int] = {}

    sorted_events = sorted(
        events,
        key=lambda event: (
            parse_loop_event_timestamp(event.get("timestamp")) or datetime.min.replace(tzinfo=UTC)
        ),
    )
    for event in sorted_events:
        kind = str(event.get("kind") or "").strip()
        msg_data = convert_event_to_message_data(event)
        if msg_data is None:
            continue

        if kind == "tool_call" and msg_data.type == MessageType.TOOL and msg_data.tool_name:
            pending_tool_indices.setdefault(msg_data.tool_name, []).append(len(data))
            data.append(msg_data)
            continue

        if kind == "tool_result" and msg_data.type == MessageType.TOOL and msg_data.tool_name:
            tool_name = msg_data.tool_name
            pending = pending_tool_indices.get(tool_name, [])
            if pending:
                call_idx = pending.pop(0)
                data[call_idx].tool_status = ToolStatus.SUCCESS
                data[call_idx].tool_output = msg_data.tool_output
            else:
                data.append(msg_data)
            continue

        if msg_data.type == MessageType.STEP_PROGRESS and msg_data.step_progress_id:
            step_id = msg_data.step_progress_id
            existing = step_card_position.get(step_id)
            if existing is not None:
                data[existing] = merge_step_progress(data[existing], msg_data)
                continue
            step_card_position[step_id] = len(data)

        data.append(msg_data)

    return data


def merge_history_sources(
    checkpoint_messages: list[Any],
    activity_events: list[dict[str, Any]],
) -> list[tuple[str, Any]]:
    """Merge checkpoint messages and persisted activity events chronologically.

    Args:
        checkpoint_messages: LangChain message objects from checkpoint.
        activity_events: Event rows from the daemon conversation log.

    Returns:
        List of ``(source_type, data)`` tuples sorted by timestamp:
            * ``source_type``: ``"message"`` or ``"event"``
            * ``data``: LangChain message or ``MessageData``
    """
    timeline: list[tuple[datetime, str, Any]] = []
    min_timestamp = datetime.min.replace(tzinfo=UTC)

    # Extract timestamps from checkpoint messages
    for msg in checkpoint_messages:
        # LangChain messages don't have explicit timestamps in checkpoint
        # Use message sequence as proxy (they're already ordered)
        # We'll place them relative to events based on tool call matching
        timeline.append((min_timestamp, "message", msg))

    # Activity events carry explicit timestamps for ordering
    for event in activity_events:
        ts = parse_loop_event_timestamp(event.get("timestamp")) or min_timestamp

        # Convert event to MessageData
        msg_data = convert_event_to_message_data(event)
        if msg_data:
            timeline.append((ts, "event", msg_data))

    # Sort by timestamp (messages without timestamps get datetime.min)
    # This interleaves events chronologically with messages
    timeline.sort(key=lambda x: x[0])

    # Return as (source_type, data) list
    return [(item[1], item[2]) for item in timeline]


def convert_combined_to_data(combined: list[tuple[str, Any]]) -> list[MessageData]:
    """Convert merged timeline to ``MessageData`` widgets.

    Args:
        combined: List of ``(source_type, data)`` from ``merge_history_sources``.

    Returns:
        List of ``MessageData`` widgets for UI rendering.
    """
    data: list[MessageData] = []
    pending_checkpoint_messages: list[Any] = []

    def flush_checkpoint_messages() -> None:
        if not pending_checkpoint_messages:
            return
        data.extend(convert_messages_to_data(pending_checkpoint_messages))
        pending_checkpoint_messages.clear()

    for source_type, item in combined:
        if source_type == "message":
            pending_checkpoint_messages.append(item)
            continue

        flush_checkpoint_messages()
        if source_type == "event" and isinstance(item, MessageData):
            data.append(item)

    flush_checkpoint_messages()
    return data


__all__ = [
    "collect_cognition_card_replay",
    "convert_combined_to_data",
    "convert_event_to_message_data",
    "convert_loop_events_to_data",
    "convert_messages_to_data",
    "conversation_rows_to_langchain_messages",
    "is_loop_internal_checkpoint_message",
    "merge_history_sources",
    "merge_step_progress",
    "merge_visible_messages_with_cognition_cards",
    "parse_loop_event_timestamp",
]
