"""Tests for progress verbosity filtering helpers."""

from soothe.ux.core.progress_verbosity import (
    classify_custom_event,
    should_show,
)


class TestProgressVerbosity:
    def test_should_show_minimal(self) -> None:
        assert should_show("assistant_text", "minimal")
        assert should_show("error", "minimal")
        assert not should_show("protocol", "minimal")
        assert not should_show("tool_activity", "minimal")
        assert not should_show("subagent_custom", "minimal")

    def test_should_show_normal(self) -> None:
        assert should_show("assistant_text", "normal")
        assert should_show("protocol", "normal")
        assert should_show("error", "normal")
        assert should_show("subagent_progress", "normal")
        assert not should_show("tool_activity", "normal")
        assert not should_show("subagent_custom", "normal")

    def test_should_show_detailed(self) -> None:
        assert should_show("assistant_text", "detailed")
        assert should_show("protocol", "detailed")
        assert should_show("error", "detailed")
        assert should_show("tool_activity", "detailed")
        assert should_show("subagent_custom", "detailed")
        assert not should_show("thinking", "detailed")

    def test_should_show_debug(self) -> None:
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

    def test_classify_protocol_events(self) -> None:
        assert classify_custom_event((), {"type": "soothe.protocol.plan.created"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.protocol.context.projected"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.protocol.policy.checked"}) == "protocol"

    def test_classify_lifecycle_events(self) -> None:
        assert classify_custom_event((), {"type": "soothe.lifecycle.thread.created"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.lifecycle.iteration.started"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.lifecycle.checkpoint.saved"}) == "protocol"

    def test_classify_error_events(self) -> None:
        assert classify_custom_event((), {"type": "soothe.error.general"}) == "error"

    def test_classify_output_events(self) -> None:
        assert classify_custom_event((), {"type": "soothe.output.chitchat.response"}) == "assistant_text"
        assert classify_custom_event((), {"type": "soothe.output.autonomous.final_report"}) == "assistant_text"
        assert classify_custom_event((), {"type": "soothe.output.chitchat.started"}) == "assistant_text"

    def test_classify_tool_events(self) -> None:
        # Registered tool events get tool_activity from registry
        assert classify_custom_event((), {"type": "soothe.tool.websearch.search_started"}) == "tool_activity"
        assert classify_custom_event((), {"type": "soothe.tool.websearch.crawl_completed"}) == "tool_activity"
        # Unregistered tool events fall back to protocol (structural classification)
        assert classify_custom_event((), {"type": "soothe.tool.workspace.read_started"}) == "protocol"

    def test_classify_subagent_events(self) -> None:
        assert classify_custom_event((), {"type": "soothe.subagent.browser.step"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.subagent.browser.cdp"}) == "subagent_progress"

        assert classify_custom_event((), {"type": "soothe.subagent.claude.text"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.subagent.claude.result"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.subagent.claude.tool_use"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.subagent.skillify.retrieve_started"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.subagent.weaver.generate_started"}) == "subagent_custom"

    def test_classify_subagent_from_namespace(self) -> None:
        assert classify_custom_event(("tools:abc",), {"type": "some_event"}) == "subagent_custom"

    def test_classify_thinking(self) -> None:
        assert classify_custom_event((), {"type": "soothe.thinking.heartbeat"}) == "thinking"
        assert classify_custom_event(("ns",), {"type": "thinking.heartbeat"}) == "thinking"

    def test_classify_unknown_soothe_prefix(self) -> None:
        assert classify_custom_event((), {"type": "soothe.unknown.something"}) == "protocol"

    def test_classify_non_soothe_events(self) -> None:
        assert classify_custom_event((), {"type": "something_else"}) == "debug"
