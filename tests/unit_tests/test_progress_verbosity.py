"""Tests for progress verbosity filtering helpers."""

from soothe.cli.progress_verbosity import classify_custom_event, should_show


class TestProgressVerbosity:
    def test_should_show_minimal(self):
        assert should_show("assistant_text", "minimal")
        assert should_show("error", "minimal")
        assert not should_show("protocol", "minimal")
        assert not should_show("tool_activity", "minimal")
        assert not should_show("subagent_custom", "minimal")

    def test_should_show_normal(self):
        assert should_show("assistant_text", "normal")
        assert should_show("protocol", "normal")
        assert should_show("error", "normal")
        assert not should_show("tool_activity", "normal")
        assert not should_show("subagent_custom", "normal")

    def test_should_show_detailed(self):
        assert should_show("assistant_text", "detailed")
        assert should_show("protocol", "detailed")
        assert should_show("error", "detailed")
        assert should_show("tool_activity", "detailed")
        assert should_show("subagent_custom", "detailed")
        assert not should_show("thinking", "detailed")

    def test_should_show_debug(self):
        for category in (
            "assistant_text",
            "protocol",
            "subagent_custom",
            "tool_activity",
            "thinking",
            "error",
            "debug",
        ):
            assert should_show(category, "debug")

    def test_classify_custom_event_protocol(self):
        assert classify_custom_event((), {"type": "soothe.plan.created"}) == "protocol"

    def test_classify_custom_event_error(self):
        assert classify_custom_event((), {"type": "soothe.error"}) == "error"

    def test_classify_custom_event_subagent(self):
        assert classify_custom_event(("tools:abc",), {"type": "browser_step"}) == "subagent_custom"

    def test_classify_custom_event_thinking(self):
        assert classify_custom_event((), {"type": "soothe.thinking.heartbeat"}) == "thinking"
