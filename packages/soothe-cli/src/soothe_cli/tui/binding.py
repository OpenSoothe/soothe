"""Map runtime transcript models to Textual widgets (TUI-only)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from soothe_cli.runtime.state.transcript import MessageData, MessageType

if TYPE_CHECKING:
    from textual.widget import Widget

logger = logging.getLogger(__name__)


def message_to_widget(data: MessageData) -> Widget:
    """Recreate a widget from this message data.

    Returns:
        The appropriate message widget for this data.
    """
    # Import here to avoid circular imports
    from soothe_cli.tui.widgets.messages import (
        AppMessage,
        AssistantMessage,
        CognitionGoalTreeMessage,
        CognitionReasonMessage,
        CognitionStepMessage,
        DiffMessage,
        ErrorMessage,
        QueuedUserMessage,
        SkillMessage,
        SummarizationMessage,
        UserMessage,
    )
    from soothe_cli.tui.widgets.messages.cognition_step import _DeferredStepComplete

    match data.type:
        case MessageType.USER:
            return UserMessage(data.content, id=data.id)

        case MessageType.QUEUED_USER:
            return QueuedUserMessage(data.content, id=data.id)

        case MessageType.ASSISTANT:
            return AssistantMessage(data.content, id=data.id)

        case MessageType.TOOL:
            name = data.tool_name or "tool"
            return AppMessage(f"[{name}]", id=data.id)

        case MessageType.SKILL:
            widget = SkillMessage(
                skill_name=data.skill_name or "unknown",
                description=data.skill_description or "",
                source=data.skill_source or "",
                body=data.skill_body or "",
                args=data.skill_args or "",
                id=data.id,
            )
            widget._deferred_expanded = data.skill_expanded
            return widget

        case MessageType.ERROR:
            return ErrorMessage(data.content, id=data.id)

        case MessageType.APP:
            return AppMessage(data.content, id=data.id)

        case MessageType.SUMMARIZATION:
            return SummarizationMessage(data.content, id=data.id)

        case MessageType.DIFF:
            return DiffMessage(
                data.content,
                file_path=data.diff_file_path or "",
                id=data.id,
            )

        case MessageType.STEP_PROGRESS:
            w = CognitionStepMessage(
                step_id=data.step_progress_id or "",
                description=data.step_progress_description or "",
                id=data.id,
            )
            if data.step_tool_calls_json:
                try:
                    raw_rows = json.loads(data.step_tool_calls_json)
                    if isinstance(raw_rows, list) and raw_rows:
                        w.apply_tool_rows_snapshot(raw_rows)
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid step_tool_calls_json for %s",
                        data.id,
                    )
            phase = data.step_progress_phase or "pending"
            if phase == "running":
                w._deferred_running = True
            elif phase == "interrupted":
                w._deferred_interrupted = data.step_summary or "Interrupted"
            elif phase in ("success", "error") and data.step_success is not None:
                w._deferred_complete = _DeferredStepComplete(
                    bool(data.step_success),
                    int(data.step_duration_ms or 0),
                    int(data.step_tool_call_count or 0),
                    str(data.step_summary or ""),
                )
            return w

        case MessageType.COGNITION_REASON:
            return CognitionReasonMessage(
                next_action=data.cognition_plan_next_action or "",
                status=data.cognition_plan_status or "",
                iteration=int(data.cognition_plan_iteration or 0),
                plan_action=data.cognition_plan_action or "",
                assessment_reasoning=data.cognition_plan_assessment or "",
                plan_reasoning=data.cognition_plan_strategy or "",
                id=data.id,
            )

        case MessageType.COGNITION_GOAL_TREE:
            snap: dict[str, Any] = {}
            if data.cognition_goal_snapshot_json:
                try:
                    raw = json.loads(data.cognition_goal_snapshot_json)
                    if isinstance(raw, dict):
                        snap = raw
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid cognition_goal_snapshot_json for %s",
                        data.id,
                    )
            goal = str(snap.get("goal", "")).strip()
            w = CognitionGoalTreeMessage(
                goal=goal or " ",
                max_iterations=int(snap.get("max_iterations", 0)),
                id=data.id,
            )
            if snap:
                w._apply_snapshot(snap)
            return w

        case _:
            logger.warning(
                "Unknown MessageType %r for message %s, falling back to AppMessage",
                data.type,
                data.id,
            )
            return AppMessage(data.content, id=data.id)


def message_from_widget(widget: Widget) -> MessageData:
    """Create MessageData from an existing widget.

    Args:
        widget: The message widget to serialize.

    Returns:
        MessageData containing all the widget's state.
    """
    # Deferred: prevents import-order issue — both modules live in the
    # widgets package, and messages is re-exported from widgets/__init__.
    from soothe_cli.tui.widgets.messages import (
        AppMessage,
        AssistantMessage,
        CognitionGoalTreeMessage,
        CognitionReasonMessage,
        CognitionStepMessage,
        DiffMessage,
        ErrorMessage,
        QueuedUserMessage,
        SkillMessage,
        SummarizationMessage,
        UserMessage,
    )

    widget_id = widget.id or f"msg-{uuid.uuid4().hex[:8]}"

    if isinstance(widget, QueuedUserMessage):
        return MessageData(
            type=MessageType.QUEUED_USER,
            content=widget._content,
            id=widget_id,
        )

    if isinstance(widget, CognitionGoalTreeMessage):
        return MessageData(
            type=MessageType.COGNITION_GOAL_TREE,
            content="",
            id=widget_id,
            cognition_goal_snapshot_json=json.dumps(widget.snapshot_dict()),
        )

    if isinstance(widget, CognitionReasonMessage):
        return MessageData(
            type=MessageType.COGNITION_REASON,
            content="",
            id=widget_id,
            cognition_plan_next_action=widget._next_action,
            cognition_plan_status=widget._status,
            cognition_plan_iteration=widget._iteration,
            cognition_plan_action=widget._plan_action,
            cognition_plan_assessment=widget._assessment_reasoning,
            cognition_plan_strategy=widget._plan_reasoning,
        )

    if isinstance(widget, CognitionStepMessage):
        phase = widget._status
        if widget._interrupt_message:
            phase = "interrupted"
        return MessageData(
            type=MessageType.STEP_PROGRESS,
            content="",
            id=widget_id,
            step_progress_id=widget._step_id,
            step_progress_description=widget._description,
            step_progress_phase=phase,
            step_success=widget._last_success,
            step_duration_ms=widget._last_duration_ms,
            step_tool_call_count=widget._last_tool_call_count,
            step_summary=(
                widget._interrupt_message if widget._interrupt_message else widget._last_summary
            ),
            step_tool_calls_json=json.dumps(widget.snapshot_tool_rows()),
        )

    if isinstance(widget, SkillMessage):
        return MessageData(
            type=MessageType.SKILL,
            content="",
            id=widget_id,
            skill_name=widget._skill_name,
            skill_description=widget._description,
            skill_source=widget._source,
            skill_body=widget._body,
            skill_args=widget._args,
            skill_expanded=widget._expanded,
        )

    if isinstance(widget, UserMessage):
        return MessageData(
            type=MessageType.USER,
            content=widget._content,
            id=widget_id,
        )

    if isinstance(widget, AssistantMessage):
        return MessageData(
            type=MessageType.ASSISTANT,
            content=widget._content,
            id=widget_id,
            is_streaming=widget._streaming_active,
        )

    if isinstance(widget, ErrorMessage):
        return MessageData(
            type=MessageType.ERROR,
            content=widget._content,
            id=widget_id,
        )

    # Check specialized subclasses before AppMessage so we keep their type
    # when serializing and can restore their specific styling later.
    if isinstance(widget, DiffMessage):
        return MessageData(
            type=MessageType.DIFF,
            content=widget._diff_content,
            id=widget_id,
            diff_file_path=widget._file_path,
        )

    from soothe_cli.tui.widgets.file_change_preview import FileChangePreviewWidget

    if isinstance(widget, FileChangePreviewWidget):
        path = str(widget.data.get("file_path") or widget.data.get("path") or "")
        summary = f"{widget._action_label}: {path}" if path else widget._action_label
        return MessageData(type=MessageType.APP, content=summary or "File change", id=widget_id)

    if isinstance(widget, SummarizationMessage):
        return MessageData(
            type=MessageType.SUMMARIZATION,
            content=str(widget._content),
            id=widget_id,
        )

    if isinstance(widget, AppMessage):
        return MessageData(
            type=MessageType.APP,
            content=str(widget._content),
            id=widget_id,
        )

    logger.warning(
        "Unknown widget type %s (id=%s), storing as APP message",
        type(widget).__name__,
        widget_id,
    )
    return MessageData(
        type=MessageType.APP,
        content=f"[Unknown widget: {type(widget).__name__}]",
        id=widget_id,
    )
