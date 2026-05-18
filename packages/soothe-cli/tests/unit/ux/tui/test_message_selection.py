"""Test that message widgets support text selection for copy functionality."""

from __future__ import annotations

from soothe_cli.tui.widgets.message_store import MessageData, MessageType
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    CognitionStepMessage,
    DiffMessage,
    ErrorMessage,
    QueuedUserMessage,
    SkillMessage,
    ToolCallMessage,
    UserMessage,
)


def test_all_message_widgets_allow_select() -> None:
    """Verify message widgets opt in to Textual text selection."""
    assert UserMessage.ALLOW_SELECT is True
    assert QueuedUserMessage.ALLOW_SELECT is True
    assert DiffMessage.ALLOW_SELECT is True
    assert ErrorMessage.ALLOW_SELECT is True
    assert AppMessage.ALLOW_SELECT is True
    assert AssistantMessage.ALLOW_SELECT is True
    assert SkillMessage.ALLOW_SELECT is True
    assert ToolCallMessage.ALLOW_SELECT is True
    assert CognitionStepMessage.ALLOW_SELECT is True


def test_widget_instances_inherit_allow_select() -> None:
    """Widget instances use the class-level ALLOW_SELECT flag."""
    user_msg = UserMessage("test content")
    assert user_msg.ALLOW_SELECT is True

    assistant_msg = AssistantMessage("test")
    assert assistant_msg.ALLOW_SELECT is True


def test_queued_user_message_store_roundtrip() -> None:
    """Virtualized chat must serialize QueuedUserMessage without falling back to APP."""
    w = QueuedUserMessage("hello queue", id="msg-fixed-id")
    data = MessageData.from_widget(w)
    assert data.type == MessageType.QUEUED_USER
    assert data.content == "hello queue"
    assert data.id == "msg-fixed-id"
    restored = data.to_widget()
    assert isinstance(restored, QueuedUserMessage)
    assert restored._content == "hello queue"
    assert restored.id == "msg-fixed-id"
