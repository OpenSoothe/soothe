"""Transcript message models shared between TUI rendering and server-side card binding.

Lightweight dataclasses for chat history. The previous home was a CLI-side
transcript module; that path is now a re-export shim so existing CLI
imports continue to work.

These types intentionally have **no Textual / widget / rendering
dependencies** so the binder module can run inside the server runtime.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from time import time
from typing import Any

# Fields on MessageData that callers are allowed to update via update_message().
# Prevents accidental overwriting of identity fields like id/type/timestamp.
UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "content",
        "tool_status",
        "tool_output",
        "tool_expanded",
        "tool_rows_json",
        "skill_expanded",
        "is_streaming",
        "height_hint",
        "step_tool_calls_json",
    }
)


class MessageType(StrEnum):
    """Types of messages in the chat."""

    USER = "user"
    QUEUED_USER = "queued_user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SKILL = "skill"
    ERROR = "error"
    APP = "app"
    SUMMARIZATION = "summarization"
    STEP_PROGRESS = "step_progress"
    COGNITION_REASON = "cognition_reason"
    COGNITION_GOAL_TREE = "cognition_goal_tree"
    DIFF = "diff"


class ToolStatus(StrEnum):
    """Status of a tool call."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass
class MessageData:
    """In-memory message data for virtualization.

    This dataclass holds all information needed to recreate a message widget.
    It is designed to be lightweight so that thousands of messages can be
    stored without meaningful memory overhead.
    """

    type: MessageType
    """The kind of message (user, assistant, tool, etc.)."""

    content: str
    """Primary text content of the message.

    For most message types this is the display text. For TOOL messages it is
    typically empty because the tool's identity comes from `tool_name` /
    `tool_args` instead.
    """

    id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    """Unique identifier used to match the dataclass to its DOM widget."""

    timestamp: float = field(default_factory=time)
    """Unix epoch timestamp of when the message was created."""

    # TOOL message fields - only populated for TOOL messages
    tool_name: str | None = None
    """Name of the tool that was called."""

    tool_args: dict[str, Any] | None = None
    """Arguments passed to the tool call."""

    tool_status: ToolStatus | None = None
    """Current execution status of the tool call."""

    tool_output: str | None = None
    """Output returned by the tool after execution."""

    tool_expanded: bool = False
    """Whether the tool output section is expanded in the UI."""

    tool_rows_json: str | None = None
    """JSON list of tool rows from ``ToolCallMessage.snapshot_tool_rows()``."""

    # ---

    diff_file_path: str | None = None
    """File path associated with the diff (DIFF messages only)."""

    # SKILL message fields - only populated for SKILL messages
    skill_name: str | None = None
    """Name of the skill that was invoked."""

    skill_description: str | None = None
    """Short description of the skill."""

    skill_source: str | None = None
    """Origin of the skill (e.g., `'built-in'`, `'user'`, `'project'`)."""

    skill_args: str | None = None
    """User-provided arguments to the skill invocation."""

    skill_body: str | None = None
    """Full SKILL.md content sent to the agent."""

    skill_expanded: bool = False
    """Whether the skill body is expanded in the UI."""

    step_progress_id: str | None = None
    """Agent-loop act step id (STEP_PROGRESS only)."""

    step_progress_description: str | None = None
    """Step description line (STEP_PROGRESS only)."""

    step_progress_phase: str | None = None
    """Lifecycle: pending, running, success, error, interrupted (STEP_PROGRESS only)."""

    step_success: bool | None = None
    """Whether the step completed successfully (STEP_PROGRESS only)."""

    step_duration_ms: int | None = None
    """Step duration in ms (STEP_PROGRESS only)."""

    step_tool_call_count: int | None = None
    """Tool calls during the step (STEP_PROGRESS only)."""

    step_summary: str | None = None
    """Result or error summary text (STEP_PROGRESS only)."""

    step_tool_calls_json: str | None = None
    """JSON list of tool rows from ``CognitionStepMessage.snapshot_tool_rows()``."""

    cognition_plan_status: str | None = None
    """Plan status: continue, replan, done (COGNITION_REASON only)."""

    cognition_plan_iteration: int | None = None
    """Agent-loop iteration (COGNITION_REASON only)."""

    cognition_plan_action: str | None = None
    """``keep`` or ``new`` (COGNITION_REASON only)."""

    cognition_plan_assessment: str | None = None
    """Phase-1 assessment text (COGNITION_REASON only)."""

    cognition_plan_strategy: str | None = None
    """Phase-2 plan reasoning (COGNITION_REASON only)."""

    cognition_goal_snapshot_json: str | None = None
    """JSON blob from ``CognitionGoalTreeMessage.snapshot_dict()`` (COGNITION_GOAL_TREE only)."""

    loop_output_phase: str | None = None
    """Assistant output phase (``goal_completion``, ``plan_direct``, etc.)."""

    is_streaming: bool = False
    """Whether the message is still being streamed.

    While `True`, the corresponding widget is actively receiving content
    chunks and should not be pruned or re-hydrated.
    """

    height_hint: int | None = None
    """Cached widget height in terminal rows for scroll position estimation.

    When `_hydrate_messages_above` inserts widgets above the viewport it needs
    to adjust the scroll offset so the user's view doesn't jump. Currently this
    uses a fixed estimate (5 rows per message). Caching the actual rendered
    height here after first mount would make that estimate accurate, especially
    for tall messages like diffs or long assistant responses.

    Not yet populated — see `_hydrate_messages_above` in `app.py`.
    """

    def __post_init__(self) -> None:
        """Validate type-field coherence after construction.

        Raises:
            ValueError: If a TOOL message is missing `tool_name` or a SKILL
                message is missing `skill_name`.
        """
        if self.type == MessageType.TOOL and not self.tool_name:
            msg = "TOOL messages must have a tool_name"
            raise ValueError(msg)
        if self.type == MessageType.SKILL and not self.skill_name:
            msg = "SKILL messages must have a skill_name"
            raise ValueError(msg)
