"""Unit tests for Deep Research early termination logic."""

from __future__ import annotations

import pytest

from soothe_nano.subagents.deep_research.protocol import ResearchReference, SourceResult
from soothe_nano.subagents.deep_research.termination import (
    LoopTerminationChecker,
    should_terminate_early,
)


@pytest.fixture
def termination_checker() -> LoopTerminationChecker:
    """Default termination checker for tests."""
    return LoopTerminationChecker(
        min_results=3,
        min_source_diversity=2,
        max_duplicate_ratio=0.5,
        min_content_length=200,
    )


class TestLoopTerminationChecker:
    """Tests for LoopTerminationChecker."""

    def test_no_termination_on_first_iteration(self, termination_checker: LoopTerminationChecker):
        """Should not terminate on iteration 0."""
        state = {"references_gathered": []}
        results = [SourceResult(content="test", source_ref="ref1", source_name="web")]

        decision = termination_checker.check_termination(state, 0, results)

        assert not decision.should_terminate
        assert decision.reason == "insufficient_iterations"

    def test_termination_with_sufficient_results(self, termination_checker: LoopTerminationChecker):
        """Should terminate when sufficient diverse results gathered."""
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
            SourceResult(content="b" * 300, source_ref="ref2", source_name="academic"),
            SourceResult(content="c" * 300, source_ref="ref3", source_name="web"),
            SourceResult(content="d" * 300, source_ref="ref4", source_name="academic"),
            SourceResult(content="e" * 300, source_ref="ref5", source_name="url"),
            SourceResult(content="f" * 300, source_ref="ref6", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        assert decision.should_terminate
        assert decision.reason == "sufficient_diverse_results"
        assert decision.confidence == 0.8

    def test_no_termination_below_min_results(self, termination_checker: LoopTerminationChecker):
        """Should not terminate below minimum results threshold."""
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        assert not decision.should_terminate
        assert "below_min_results" in decision.reason

    def test_no_termination_with_single_source(self, termination_checker: LoopTerminationChecker):
        """Should not terminate with insufficient source diversity."""
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
            SourceResult(content="b" * 300, source_ref="ref2", source_name="web"),
            SourceResult(content="c" * 300, source_ref="ref3", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        assert not decision.should_terminate
        assert "insufficient_diversity" in decision.reason

    def test_termination_on_no_new_sources(self, termination_checker: LoopTerminationChecker):
        """Should terminate when iteration adds no new sources."""
        # Previous results from web and academic
        state = {
            "references_gathered": [
                {"source_name": "web", "source_ref": "ref1"},
                {"source_name": "academic", "source_ref": "ref2"},
            ]
        }
        # Current results only from web (no new sources)
        results = [
            SourceResult(content="a" * 300, source_ref="ref3", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 2, results)

        assert decision.should_terminate
        assert decision.reason == "no_new_sources"
        assert decision.confidence == 0.7

    def test_no_termination_with_new_sources(self, termination_checker: LoopTerminationChecker):
        """Should not terminate when new sources are discovered."""
        state = {
            "references_gathered": [
                {"source_name": "web", "source_ref": "ref1"},
            ]
        }
        results = [
            SourceResult(content="a" * 300, source_ref="ref2", source_name="academic"),
        ]

        decision = termination_checker.check_termination(state, 2, results)

        # Should not terminate due to no_new_sources
        assert not decision.should_terminate or decision.reason != "no_new_sources"

    def test_termination_with_accumulated_results(
        self, termination_checker: LoopTerminationChecker
    ):
        """Should consider accumulated results from state."""
        state = {
            "references_gathered": [
                {"source_name": "web", "source_ref": "ref1"},
                {"source_name": "academic", "source_ref": "ref2"},
                {"source_name": "web", "source_ref": "ref3"},
            ]
        }
        results = [
            SourceResult(content="a" * 300, source_ref="ref4", source_name="academic"),
            SourceResult(content="b" * 300, source_ref="ref5", source_name="url"),
            SourceResult(content="c" * 300, source_ref="ref6", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        assert decision.should_terminate
        assert decision.reason == "sufficient_diverse_results"


class TestSourceDiversity:
    """Tests for source diversity calculation."""

    def test_diversity_with_mixed_sources(self):
        """Should count unique source names."""
        checker = LoopTerminationChecker(min_source_diversity=2)
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a", source_ref="ref1", source_name="web"),
            SourceResult(content="b", source_ref="ref2", source_name="web"),
            SourceResult(content="c", source_ref="ref3", source_name="academic"),
        ]

        decision = checker.check_termination(state, 1, results)

        # Should have 2 unique sources (web, academic)
        assert "insufficient_diversity" not in decision.reason

    def test_diversity_with_research_reference_objects(self):
        """Should handle ResearchReference objects in state."""
        checker = LoopTerminationChecker(min_source_diversity=2)
        refs = [
            ResearchReference(source_name="web", source_ref="ref1"),
            ResearchReference(source_name="academic", source_ref="ref2"),
        ]
        state = {"references_gathered": refs}
        results = [
            SourceResult(content="a" * 300, source_ref="ref3", source_name="web"),
        ]

        decision = checker.check_termination(state, 1, results)

        # Should have 2 unique sources from refs
        assert "insufficient_diversity" not in decision.reason


class TestContentQuality:
    """Tests for content quality heuristics."""

    def test_low_content_quality_blocks_termination(self):
        """Should not terminate with low-quality (short) content."""
        checker = LoopTerminationChecker(
            min_results=3,
            min_content_length=200,
        )
        state = {"references_gathered": []}
        results = [
            SourceResult(content="short", source_ref="ref1", source_name="web"),
            SourceResult(content="also short", source_ref="ref2", source_name="academic"),
            SourceResult(content="tiny", source_ref="ref3", source_name="url"),
        ]

        decision = checker.check_termination(state, 1, results)

        assert not decision.should_terminate
        assert "low_content_quality" in decision.reason

    def test_sufficient_content_quality_allows_termination(self):
        """Should allow termination with high-quality content."""
        checker = LoopTerminationChecker(
            min_results=3,
            min_content_length=200,
        )
        state = {"references_gathered": []}
        results = [
            SourceResult(content="x" * 300, source_ref="ref1", source_name="web"),
            SourceResult(content="y" * 300, source_ref="ref2", source_name="academic"),
            SourceResult(content="z" * 300, source_ref="ref3", source_name="url"),
        ]

        decision = checker.check_termination(state, 1, results)

        assert "low_content_quality" not in decision.reason


class TestShouldTerminateEarly:
    """Tests for the convenience function."""

    def test_with_config(self):
        """Should use config thresholds when provided."""

        class MockConfig:
            min_results_for_termination = 5
            min_source_diversity = 3

        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
            SourceResult(content="b" * 300, source_ref="ref2", source_name="academic"),
        ]

        decision = should_terminate_early(state, 1, results, MockConfig())

        # Should not terminate - below config thresholds
        assert not decision.should_terminate
        assert "below_min_results" in decision.reason

    def test_without_config(self):
        """Should use defaults when no config provided."""
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
        ]

        decision = should_terminate_early(state, 1, results, None)

        # Should use defaults (min_results=3)
        assert not decision.should_terminate


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_results(self, termination_checker: LoopTerminationChecker):
        """Should handle empty results gracefully."""
        state = {"references_gathered": []}
        results: list[SourceResult] = []

        decision = termination_checker.check_termination(state, 1, results)

        assert not decision.should_terminate
        assert "below_min_results" in decision.reason

    def test_empty_state(self, termination_checker: LoopTerminationChecker):
        """Should handle missing references_gathered key."""
        state: dict = {}
        results = [
            SourceResult(content="a" * 300, source_ref="ref1", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        # Should not crash, just treat as empty
        assert not decision.should_terminate

    def test_single_source_result(self, termination_checker: LoopTerminationChecker):
        """Should handle single result."""
        state = {"references_gathered": []}
        results = [
            SourceResult(content="a" * 500, source_ref="ref1", source_name="web"),
        ]

        decision = termination_checker.check_termination(state, 1, results)

        assert not decision.should_terminate
        assert "below_min_results" in decision.reason
