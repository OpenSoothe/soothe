"""Tests for progress verbosity filtering helpers."""

from soothe.cli.progress_verbosity import (
    _SUBAGENT_PREFIXES,
    classify_custom_event,
    should_show,
)


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
        assert classify_custom_event((), {"type": "soothe.context.projected"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.policy.checked"}) == "protocol"

    def test_classify_custom_event_error(self):
        assert classify_custom_event((), {"type": "soothe.error"}) == "error"

    def test_classify_custom_event_subagent_from_namespace(self):
        assert classify_custom_event(("tools:abc",), {"type": "some_event"}) == "subagent_custom"

    def test_classify_custom_event_subagent_from_soothe_prefix(self):
        assert classify_custom_event((), {"type": "soothe.browser.step"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.research.web_search"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.claude.text"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.claude.tool_use"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.claude.result"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.skillify.search"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.weaver.generate"}) == "subagent_custom"

    def test_classify_custom_event_thinking(self):
        assert classify_custom_event((), {"type": "soothe.thinking.heartbeat"}) == "thinking"

    def test_subagent_prefixes_complete(self):
        expected = {
            "soothe.research.",
            "soothe.browser.",
            "soothe.claude.",
            "soothe.skillify.",
            "soothe.weaver.",
        }
        assert expected == _SUBAGENT_PREFIXES
