"""Tests for VerbosityTier classification (RFC-0024)."""

from soothe.core.verbosity_tier import (
    VerbosityTier,
    classify_event_to_tier,
    should_show,
)


class TestVerbosityTier:
    def test_tier_ordering(self) -> None:
        """Tier values are ordered for comparison."""
        assert VerbosityTier.QUIET < VerbosityTier.NORMAL
        assert VerbosityTier.NORMAL < VerbosityTier.DETAILED
        assert VerbosityTier.DETAILED < VerbosityTier.DEBUG
        assert VerbosityTier.INTERNAL > VerbosityTier.DEBUG

    def test_tier_values(self) -> None:
        """Tier values are as specified in RFC-0024."""
        assert VerbosityTier.QUIET == 0
        assert VerbosityTier.NORMAL == 1
        assert VerbosityTier.DETAILED == 2
        assert VerbosityTier.DEBUG == 3
        assert VerbosityTier.INTERNAL == 99


class TestShouldShow:
    def test_should_show_quiet(self) -> None:
        """QUIET tier is visible at all levels."""
        assert should_show(VerbosityTier.QUIET, "quiet")
        assert should_show(VerbosityTier.QUIET, "normal")
        assert should_show(VerbosityTier.QUIET, "detailed")
        assert should_show(VerbosityTier.QUIET, "debug")

    def test_should_show_normal(self) -> None:
        """NORMAL tier is visible at normal and above."""
        assert not should_show(VerbosityTier.NORMAL, "quiet")
        assert should_show(VerbosityTier.NORMAL, "normal")
        assert should_show(VerbosityTier.NORMAL, "detailed")
        assert should_show(VerbosityTier.NORMAL, "debug")

    def test_should_show_detailed(self) -> None:
        """DETAILED tier is visible at detailed and above."""
        assert not should_show(VerbosityTier.DETAILED, "quiet")
        assert not should_show(VerbosityTier.DETAILED, "normal")
        assert should_show(VerbosityTier.DETAILED, "detailed")
        assert should_show(VerbosityTier.DETAILED, "debug")

    def test_should_show_debug(self) -> None:
        """DEBUG tier is only visible at debug level."""
        assert not should_show(VerbosityTier.DEBUG, "quiet")
        assert not should_show(VerbosityTier.DEBUG, "normal")
        assert not should_show(VerbosityTier.DEBUG, "detailed")
        assert should_show(VerbosityTier.DEBUG, "debug")

    def test_should_show_internal_never(self) -> None:
        """INTERNAL tier is never shown at any verbosity."""
        assert not should_show(VerbosityTier.INTERNAL, "quiet")
        assert not should_show(VerbosityTier.INTERNAL, "normal")
        assert not should_show(VerbosityTier.INTERNAL, "detailed")
        assert not should_show(VerbosityTier.INTERNAL, "debug")


class TestClassifyEventToTier:
    def test_classify_agentic_events(self) -> None:
        """Agentic loop events classify to correct tiers."""
        assert classify_event_to_tier("soothe.agentic.loop.started") == VerbosityTier.NORMAL
        assert classify_event_to_tier("soothe.agentic.loop.completed") == VerbosityTier.QUIET
        # Step descriptions and completion both visible at NORMAL for progress visibility
        assert classify_event_to_tier("soothe.agentic.step.started") == VerbosityTier.NORMAL
        assert classify_event_to_tier("soothe.agentic.step.completed") == VerbosityTier.NORMAL

    def test_classify_lifecycle_events(self) -> None:
        """Lifecycle events classify to DETAILED by default."""
        assert classify_event_to_tier("soothe.lifecycle.thread.created") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.lifecycle.daemon.heartbeat") == VerbosityTier.DEBUG

    def test_classify_protocol_events(self) -> None:
        """Protocol events classify to correct tiers."""
        assert classify_event_to_tier("soothe.protocol.context.projected") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.cognition.plan.created") == VerbosityTier.NORMAL

    def test_classify_tool_events(self) -> None:
        """Tool events classify to INTERNAL (RFC-0020).

        Tool calls are displayed via LangChain's on_tool_call/on_tool_result at NORMAL.
        Internal tool events (soothe.tool.*) are for logging/metrics only, not display.
        """
        # All tool events should be INTERNAL (invisible) to avoid duplicate display
        assert classify_event_to_tier("soothe.tool.execution.result") == VerbosityTier.INTERNAL
        assert classify_event_to_tier("soothe.tool.websearch.search_started") == VerbosityTier.INTERNAL
        assert classify_event_to_tier("soothe.tool.file_ops.read") == VerbosityTier.INTERNAL
        assert classify_event_to_tier("soothe.tool.data.inspection_started") == VerbosityTier.INTERNAL

    def test_classify_output_events(self) -> None:
        """Output events classify to QUIET (always visible)."""
        assert classify_event_to_tier("soothe.output.chitchat.response") == VerbosityTier.QUIET
        assert classify_event_to_tier("soothe.output.autonomous.final_report") == VerbosityTier.QUIET
        assert classify_event_to_tier("soothe.output.chitchat.started") == VerbosityTier.INTERNAL

    def test_classify_error_events(self) -> None:
        """Error events classify to QUIET (always visible)."""
        assert classify_event_to_tier("soothe.error.general") == VerbosityTier.QUIET

    def test_classify_non_soothe_events(self) -> None:
        """Non-soothe events classify to DEBUG or DETAILED."""
        assert classify_event_to_tier("thinking.heartbeat", namespace=()) == VerbosityTier.DEBUG
        assert classify_event_to_tier("some_event", namespace=("tools:abc",)) == VerbosityTier.DETAILED
        assert classify_event_to_tier("unknown_event", namespace=()) == VerbosityTier.DEBUG

    def test_classify_subagent_events(self) -> None:
        """Subagent events classify to DETAILED (IG-089: hidden at normal).

        Dispatch/completed events are NORMAL, but internal steps are DETAILED.
        """
        # Internal steps hidden at normal
        assert classify_event_to_tier("soothe.subagent.browser.step") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.subagent.claude.tool_use") == VerbosityTier.DETAILED
        # Dispatch and completed visible at normal
        assert classify_event_to_tier("soothe.subagent.browser.dispatched") == VerbosityTier.NORMAL
        assert classify_event_to_tier("soothe.subagent.research.completed") == VerbosityTier.NORMAL

    def test_classify_loop_agent_events(self) -> None:
        """Loop agent judgment events classify to NORMAL (user-visible progress)."""
        # Judgment events show agent reasoning about goal progress
        assert classify_event_to_tier("soothe.cognition.loop_agent.judgment") == VerbosityTier.NORMAL
