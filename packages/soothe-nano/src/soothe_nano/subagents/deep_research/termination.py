"""Early termination logic for Deep Research research loops.

Provides heuristics to determine when sufficient information has been
gathered to terminate the research loop early, reducing latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soothe_nano.subagents.deep_research.protocol import SourceResult


@dataclass
class TerminationDecision:
    """Result of early termination check."""

    should_terminate: bool
    reason: str
    confidence: float = 0.0


class LoopTerminationChecker:
    """Checks if research loop should terminate early based on gathered results."""

    def __init__(
        self,
        min_results: int = 3,
        min_source_diversity: int = 2,
        max_duplicate_ratio: float = 0.5,
        min_content_length: int = 200,
    ):
        """Initialize termination checker.

        Args:
            min_results: Minimum total results needed before considering termination.
            min_source_diversity: Minimum number of different sources required.
            max_duplicate_ratio: Maximum ratio of duplicate results (0.0-1.0).
            min_content_length: Minimum average content length per result.
        """
        self.min_results = min_results
        self.min_source_diversity = min_source_diversity
        self.max_duplicate_ratio = max_duplicate_ratio
        self.min_content_length = min_content_length

    def check_termination(
        self,
        state: dict[str, Any],
        iteration: int,
        current_results: list[SourceResult],
    ) -> TerminationDecision:
        """Check if research should terminate early.

        Args:
            state: Current graph state with accumulated results.
            iteration: Current loop iteration (0-indexed).
            current_results: Results from the current iteration.

        Returns:
            TerminationDecision with should_terminate flag and reason.
        """
        # Get accumulated references from state
        accumulated = state.get("references_gathered", [])

        # Combine current and accumulated for total count
        total_results = len(accumulated) + len(current_results)

        # Don't terminate too early
        if iteration < 1:
            return TerminationDecision(
                should_terminate=False,
                reason="insufficient_iterations",
                confidence=0.0,
            )

        # Check minimum results threshold
        if total_results < self.min_results:
            return TerminationDecision(
                should_terminate=False,
                reason=f"below_min_results ({total_results}/{self.min_results})",
                confidence=0.0,
            )

        # Check source diversity
        source_names = self._extract_source_names(accumulated, current_results)
        if len(source_names) < self.min_source_diversity:
            return TerminationDecision(
                should_terminate=False,
                reason=f"insufficient_diversity ({len(source_names)}/{self.min_source_diversity} sources)",
                confidence=0.0,
            )

        # Check for diminishing returns (no new sources in last iteration)
        prev_sources = self._extract_source_names_from_refs(accumulated)
        current_sources = {r.source_name for r in current_results}
        new_sources = current_sources - prev_sources

        if iteration >= 2 and not new_sources:
            return TerminationDecision(
                should_terminate=True,
                reason="no_new_sources",
                confidence=0.7,
            )

        # Check content quality
        avg_content_length = self._compute_avg_content_length(current_results)
        if avg_content_length < self.min_content_length:
            return TerminationDecision(
                should_terminate=False,
                reason=f"low_content_quality ({avg_content_length:.0f} chars)",
                confidence=0.0,
            )

        # Check if we have diverse, high-quality results
        if total_results >= self.min_results * 2 and len(source_names) >= self.min_source_diversity:
            return TerminationDecision(
                should_terminate=True,
                reason="sufficient_diverse_results",
                confidence=0.8,
            )

        return TerminationDecision(
            should_terminate=False,
            reason="continue_research",
            confidence=0.0,
        )

    def _extract_source_names(
        self,
        accumulated: list[Any],
        current: list[SourceResult],
    ) -> set[str]:
        """Extract unique source names from accumulated and current results."""
        names: set[str] = set()

        # From accumulated references (dicts)
        for ref in accumulated:
            if isinstance(ref, dict):
                name = ref.get("source_name")
                if name:
                    names.add(name)
            elif hasattr(ref, "source_name"):
                names.add(ref.source_name)

        # From current results
        for result in current:
            names.add(result.source_name)

        return names

    def _extract_source_names_from_refs(self, refs: list[Any]) -> set[str]:
        """Extract source names from reference list."""
        names: set[str] = set()
        for ref in refs:
            if isinstance(ref, dict):
                name = ref.get("source_name")
                if name:
                    names.add(name)
            elif hasattr(ref, "source_name"):
                names.add(ref.source_name)
        return names

    def _compute_avg_content_length(self, results: list[SourceResult]) -> float:
        """Compute average content length from results."""
        if not results:
            return 0.0
        total = sum(len(r.content) for r in results)
        return total / len(results)


def should_terminate_early(
    state: dict[str, Any],
    iteration: int,
    current_results: list[SourceResult],
    config: Any | None = None,
) -> TerminationDecision:
    """Convenience function for early termination check.

    Args:
        state: Current graph state.
        iteration: Current loop iteration.
        current_results: Results from current iteration.
        config: Optional DeepResearchConfig for thresholds.

    Returns:
        TerminationDecision with termination recommendation.
    """
    # Extract thresholds from config if available
    min_results = 3
    min_diversity = 2

    if config:
        min_results = getattr(config, "min_results_for_termination", 3)
        min_diversity = getattr(config, "min_source_diversity", 2)

    checker = LoopTerminationChecker(
        min_results=min_results,
        min_source_diversity=min_diversity,
    )

    return checker.check_termination(state, iteration, current_results)
