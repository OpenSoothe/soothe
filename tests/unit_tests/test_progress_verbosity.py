"""Tests for progress verbosity filtering helpers."""

from soothe.cli.progress_verbosity import (
    _SUBAGENT_PREFIXES,
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

    def test_classify_custom_event_protocol(self) -> None:
        assert classify_custom_event((), {"type": "soothe.plan.created"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.context.projected"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.policy.checked"}) == "protocol"

    def test_classify_custom_event_error(self) -> None:
        assert classify_custom_event((), {"type": "soothe.error"}) == "error"

    def test_classify_custom_event_subagent_from_namespace(self) -> None:
        assert classify_custom_event(("tools:abc",), {"type": "some_event"}) == "subagent_custom"

    def test_classify_custom_event_subagent_from_soothe_prefix(self) -> None:
        # Key progress events are classified as subagent_progress
        assert classify_custom_event((), {"type": "soothe.browser.step"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.browser.cdp"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.research.web_search"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.research.search_done"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.research.queries_generated"}) == "subagent_progress"
        assert classify_custom_event((), {"type": "soothe.research.complete"}) == "subagent_progress"

        # Other subagent events are classified as subagent_custom
        assert classify_custom_event((), {"type": "soothe.research.reflect"}) == "subagent_custom"
        # Text output events are now classified as protocol for visibility
        assert classify_custom_event((), {"type": "soothe.claude.text"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.claude.tool_use"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.claude.result"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.skillify.search"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.weaver.generate"}) == "subagent_custom"
        assert classify_custom_event((), {"type": "soothe.chitchat.response"}) == "protocol"
        assert classify_custom_event((), {"type": "soothe.autonomous.final_report"}) == "protocol"

    def test_classify_custom_event_thinking(self) -> None:
        assert classify_custom_event((), {"type": "soothe.thinking.heartbeat"}) == "thinking"

    def test_subagent_prefixes_complete(self) -> None:
        expected = frozenset(
            {
                "soothe.research.",
                "soothe.browser.",
                "soothe.skillify.",
                "soothe.weaver.",
                "soothe.planner.",
                "soothe.scout.",
                "soothe.claude.",
            }
        )
        assert expected == _SUBAGENT_PREFIXES
