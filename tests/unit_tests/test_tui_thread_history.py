"""Tests for TUI thread history recovery behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.core.events import CHITCHAT_RESPONSE
from soothe.ux.tui.app import SootheApp


def test_load_thread_history_recovers_assistant_from_output_events() -> None:
    """Recover assistant history from output events when conversation has only user turns."""
    app = SootheApp()

    logger_instance = MagicMock()
    logger_instance.recent_conversation.return_value = [{"role": "user", "text": "hello"}]
    logger_instance.recent_actions.return_value = [
        {"kind": "event", "namespace": [], "data": {"type": CHITCHAT_RESPONSE, "content": "hi from assistant"}}
    ]

    with (
        patch("soothe.ux.tui.app.ThreadLogger", return_value=logger_instance),
        patch(
            "soothe.ux.tui.app.SootheApp._load_conversation_from_checkpoint",
            return_value=[],
        ),
        patch("soothe.ux.tui.renderers._handle_generic_custom_activity", return_value=None),
    ):
        app._load_thread_history("thread-abc")

    assert any(m["role"] == "assistant" and "hi from assistant" in m["content"] for m in app._message_history)
