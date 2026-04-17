"""Test that message widgets support text selection for copy functionality."""

from __future__ import annotations

from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    DiffMessage,
    ErrorMessage,
    QueuedUserMessage,
    SkillMessage,
    ToolCallMessage,
    UserMessage,
)


def test_all_message_widgets_have_can_select_enabled() -> None:
    """Verify all message widgets support text selection for clipboard copy.

    This ensures users can select and copy text from message widgets in the TUI.
    The can_select attribute must be True for the copy_selection_to_clipboard()
    function in widgets/clipboard.py to work correctly.
    """
    # Static-based widgets
    assert UserMessage.can_select is True, "UserMessage must support text selection"
    assert QueuedUserMessage.can_select is True, "QueuedUserMessage must support text selection"
    assert DiffMessage.can_select is True, "DiffMessage must support text selection"
    assert ErrorMessage.can_select is True, "ErrorMessage must support text selection"
    assert AppMessage.can_select is True, "AppMessage must support text selection"

    # Vertical-based widgets
    assert AssistantMessage.can_select is True, "AssistantMessage must support text selection"
    assert SkillMessage.can_select is True, "SkillMessage must support text selection"
    assert ToolCallMessage.can_select is True, "ToolCallMessage must support text selection"


def test_widget_instances_preserve_can_select() -> None:
    """Verify widget instances inherit can_select from class attribute."""
    # Create instances and verify they have the attribute
    user_msg = UserMessage("test content")
    assert hasattr(user_msg, "can_select"), "UserMessage instance must have can_select attribute"

    # Verify it's inherited from class, not instance-level override
    assert UserMessage.can_select is True
    assert user_msg.__class__.can_select is True

    # Test one Vertical-based widget
    assistant_msg = AssistantMessage("test")
    assert hasattr(assistant_msg, "can_select"), "AssistantMessage instance must have can_select"
    assert AssistantMessage.can_select is True
