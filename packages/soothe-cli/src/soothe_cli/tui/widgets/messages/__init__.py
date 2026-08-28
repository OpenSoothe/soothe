"""Message widgets for Soothe TUI."""

from soothe_cli.tui.widgets.messages._helpers import (
    _assemble_card_header,
    _is_widget_animation_visible,
    _mode_color,
    _should_refresh_now,
    _strip_success_exit_line,
    flush_deferred_tools_refreshes,
    request_deferred_tools_refresh,
    reset_turn_tool_refresh_state,
)
from soothe_cli.tui.widgets.messages.app import AppMessage, SummarizationMessage
from soothe_cli.tui.widgets.messages.assistant import (
    AssistantMessage,
    _rich_style_with_textual_selection,
    _SelectableMarkdownBody,
)
from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage
from soothe_cli.tui.widgets.messages.cognition_reason import CognitionReasonMessage
from soothe_cli.tui.widgets.messages.cognition_step import (
    CognitionStepMessage,
    create_subagent_card,
)
from soothe_cli.tui.widgets.messages.cognition_step_activity import StepToolRow as _StepToolRow
from soothe_cli.tui.widgets.messages.diff_message import DiffMessage
from soothe_cli.tui.widgets.messages.error import ErrorMessage
from soothe_cli.tui.widgets.messages.skill import (
    SkillMessage,
    _build_skill_description_preview,
    _SkillToggle,
    _strip_frontmatter,
)
from soothe_cli.tui.widgets.messages.structured_ask_user import StructuredAskUserWidget
from soothe_cli.tui.widgets.messages.user import (
    QueuedUserMessage,
    UserMessage,
)

__all__ = [
    # Helpers
    "_assemble_card_header",
    "_is_widget_animation_visible",
    "_mode_color",
    "_should_refresh_now",
    "_strip_success_exit_line",
    "flush_deferred_tools_refreshes",
    "request_deferred_tools_refresh",
    "reset_turn_tool_refresh_state",
    # Assistant
    "AssistantMessage",
    "_SelectableMarkdownBody",
    "_rich_style_with_textual_selection",
    # App / system
    "AppMessage",
    "SummarizationMessage",
    # Clarification
    "StructuredAskUserWidget",
    # Cognition
    "CognitionGoalTreeMessage",
    "CognitionReasonMessage",
    "CognitionStepMessage",
    "_StepToolRow",
    "create_subagent_card",
    # Diff
    "DiffMessage",
    # Error
    "ErrorMessage",
    # Skill
    "SkillMessage",
    "_SkillToggle",
    "_build_skill_description_preview",
    "_strip_frontmatter",
    # User
    "UserMessage",
    "QueuedUserMessage",
]
