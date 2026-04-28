"""Unified Display Policy Module for CLI and TUI.

This module centralizes all event filtering, content processing, and display
policy decisions in one place. Both CLI and TUI renderers use this policy
to determine:

1. Which events to show/hide based on verbosity
2. Which content to filter from assistant text
3. Which message types are internal vs user-facing
4. How to handle different event categories

Design Principles:
- Event-based filtering over content-based filtering
- Explicit policy rules over implicit pattern matching
- Centralized configuration for consistency
- Easy to extend without modifying multiple files

Usage:
    from soothe_cli.shared.display_policy import DisplayPolicy

    policy = DisplayPolicy(verbosity="normal")

    if policy.should_show_event(event_type, data):
        render_event(data)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from soothe_sdk.core.verbosity import VerbosityLevel, VerbosityTier, should_show
from soothe_sdk.ux import classify_event_to_tier
from soothe_sdk.ux.internal import (
    INTERNAL_JSON_KEYS,
    filter_confused_responses,
    filter_json_code_blocks,
    filter_plain_json,
    filter_search_data_tags,
    normalize_internal_whitespace,
)

# =============================================================================
# Type Definitions
# =============================================================================


def normalize_verbosity(verbosity: str) -> VerbosityLevel:
    """Normalize external verbosity values to canonical internal names."""
    if verbosity == "minimal":
        return "normal"
    if verbosity in {"quiet", "normal", "detailed", "debug"}:
        return verbosity
    return "normal"


def should_show_tool_call_ui(verbosity: str | VerbosityLevel) -> bool:
    """Whether the TUI should mount tool-call rows (``ToolCallMessage`` / tool output).

    Controlled only by ``logging.verbosity`` in the CLI client config
    (``~/.soothe/config/cli_config.yml``), same scale as CLI progress — not by
    LangGraph namespace or event type. ``quiet`` hides tool UI; other levels show it.

    Args:
        verbosity: Raw or normalized verbosity string (e.g. from ``cli_config.yml``).

    Returns:
        False when verbosity is ``quiet``; True for ``normal``, ``detailed``, and ``debug``.
    """
    v = normalize_verbosity(verbosity) if isinstance(verbosity, str) else verbosity
    return v != "quiet"


# =============================================================================
# Policy Configuration Constants
# =============================================================================

# Event types that should NEVER be shown (internal implementation details)
INTERNAL_EVENT_TYPES = frozenset(
    {
        "soothe.capability.research.internal_llm.run",
    }
)

# Event types to skip in progress display (handled by plan update mechanism or not rendered)
SKIP_EVENT_TYPES = frozenset(
    {
        # Plan events handled by renderer's plan update mechanism
        "soothe.cognition.plan.batch.started",
        "soothe.cognition.plan.step.started",
        "soothe.cognition.plan.step.completed",
        "soothe.cognition.plan.step.failed",
        # Policy events not rendered (RFC-0019)
        "soothe.protocol.policy.checked",
        "soothe.protocol.policy.denied",
    }
)

PLAN_EVENT_TYPES = frozenset(
    {
        "soothe.cognition.plan.created",
        "soothe.cognition.plan.reflected",
        "soothe.cognition.plan.step.started",
        "soothe.cognition.plan.step.completed",
        "soothe.cognition.plan.step.failed",
    }
)

MILESTONE_EVENT_TYPES = frozenset(
    {
        "soothe.cognition.plan.step.completed",
        "soothe.cognition.plan.step.failed",
    }
)

QUIET_SENTENCE_MAX_LEN = 120
QUIET_FALLBACK_MAX_LEN = 160
QUIET_TRUNCATED_MAX_LEN = 157
TRAILING_EMBELLISHMENT_WORDS = frozenset(
    {
        "beautiful",
        "historic",
        "wonderful",
        "amazing",
        "great",
        "lovely",
        "fantastic",
        "famous",
        "vibrant",
    }
)

DECORATIVE_FILLER_PATTERNS = (
    r"\n?\s*Let me know if you(?:'d| would)? like .*?$",
    r"\n?\s*If you(?:'d| would) like, I can .*?$",
    r"\n?\s*Feel free to ask if .*?$",
    r"\n?\s*I(?:'m| am) happy to help you with .*?$",
)


# =============================================================================
# Display Policy Class
# =============================================================================


@dataclass
class DisplayPolicy:
    """Unified display policy for CLI and TUI.

    This class centralizes all decisions about what to show/hide,
    what content to filter, and how to process events for display.
    """

    verbosity: VerbosityLevel = "normal"

    def __post_init__(self) -> None:
        """Normalize compatibility aliases after initialization."""
        self.verbosity = normalize_verbosity(self.verbosity)

    # Track internal context state
    internal_context_active: bool = field(default=False, repr=False)
    internal_context_types: set[str] = field(default_factory=set, repr=False)

    # ==========================================================================
    # Event Filtering
    # ==========================================================================

    def should_show_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,  # noqa: ARG002
        namespace: tuple[str, ...] = (),
    ) -> bool:
        """Determine if an event should be displayed.

        Args:
            event_type: The event type string (e.g., "soothe.tool.research.analyze")
            data: Optional event data dict
            namespace: Subagent namespace tuple

        Returns:
            True if the event should be shown, False otherwise
        """
        # Internal events are NEVER shown
        if event_type in INTERNAL_EVENT_TYPES:
            return False

        # Skip certain event types (handled by plan update mechanism)
        if event_type in SKIP_EVENT_TYPES:
            return False

        # Classify and check verbosity
        tier = self._classify_event(event_type, namespace)
        return self._should_show_tier(tier)

    def _classify_event(
        self,
        event_type: str,
        namespace: tuple[str, ...] = (),
    ) -> VerbosityTier:
        """Classify an event directly to a VerbosityTier."""
        return classify_event_to_tier(event_type, namespace)

    def _should_show_tier(self, tier: VerbosityTier) -> bool:
        """Check if a tier should be shown at current verbosity."""
        return should_show(tier, self.verbosity)

    # ==========================================================================
    # Internal Context Tracking
    # ==========================================================================

    def enter_internal_context(self, context_type: str) -> None:
        """Mark entry into an internal processing context.

        Call this when starting internal LLM calls (e.g., research analysis).
        """
        self.internal_context_active = True
        self.internal_context_types.add(context_type)

    def exit_internal_context(self) -> None:
        """Mark exit from internal processing context."""
        self.internal_context_active = False
        self.internal_context_types.clear()

    def is_in_internal_context(self) -> bool:
        """Check if currently in an internal processing context."""
        return self.internal_context_active

    def filter_content(self, text: str, *, preserve_boundary_whitespace: bool = False) -> str:
        """Filter internal content from text for display.

        Args:
            text: Text to filter.
            preserve_boundary_whitespace: If True, preserve leading/trailing whitespace
                for proper streaming chunk concatenation.
        """
        # Preserve leading/trailing whitespace for streaming chunks
        if preserve_boundary_whitespace:
            leading_ws = len(text) - len(text.lstrip())
            trailing_ws = len(text) - len(text.rstrip())
            lead = text[:leading_ws]
            trail = text[len(text) - trailing_ws :] if trailing_ws > 0 else ""

        text = filter_json_code_blocks(text)
        text = filter_plain_json(text)
        text = filter_confused_responses(text)
        text = filter_search_data_tags(text)
        text = self._filter_decorative_filler(text)
        text = normalize_internal_whitespace(text)
        text = self._strip_sentence_embellishment(text)
        text = self._normalize_factual_ending(text)

        if preserve_boundary_whitespace:
            # Restore boundary whitespace for streaming concatenation
            return lead + text.strip() + trail
        return text.strip()

    def _filter_decorative_filler(self, text: str) -> str:
        """Remove polite trailing filler that adds no user value."""
        for pattern in DECORATIVE_FILLER_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
        return text

    def extract_quiet_answer(self, text: str) -> str:
        """Extract a compact answer for quiet mode with safe fallback."""
        cleaned = self.filter_content(text)
        if not cleaned:
            return ""

        single_line = re.sub(r"\s+", " ", cleaned).strip()
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", single_line):
            return single_line

        if re.fullmatch(
            r"[-+]?\d+(?:\.\d+)?\s*[+\-*/]\s*[-+]?\d+(?:\.\d+)?\s*=\s*([-+]?\d+(?:\.\d+)?)",
            single_line,
        ):
            equation_match = re.search(r"=\s*([-+]?\d+(?:\.\d+)?)$", single_line)
            if equation_match:
                return equation_match.group(1)

        numeric_match = re.search(
            r"\b(?:that(?:'s| is)|it(?:'s| is)|answer(?: is)?|result(?: is)?)\s+([-+]?\d+(?:\.\d+)?)\b",
            single_line,
            re.IGNORECASE,
        )
        if numeric_match:
            return numeric_match.group(1)

        sentences = [
            part.strip() for part in re.split(r"(?<=[.!?])\s+", single_line) if part.strip()
        ]
        if sentences:
            first = self._strip_sentence_embellishment(sentences[0])
            if len(first) <= QUIET_SENTENCE_MAX_LEN:
                return first

        if len(single_line) <= QUIET_FALLBACK_MAX_LEN:
            return self._strip_sentence_embellishment(single_line)
        return (
            self._strip_sentence_embellishment(
                single_line[:QUIET_TRUNCATED_MAX_LEN].rsplit(" ", 1)[0]
            )
            + "..."
        )

    def _strip_sentence_embellishment(self, text: str) -> str:
        """Remove lightweight trailing flourish from otherwise factual answers."""
        text = re.sub(r"\s*[🇦-🇿✨🎉👍😊😄😃😀😉🙌]+$", "", text).strip()

        inline_match = re.match(r"^(.*?),\s+(?:a|an)\s+(.+?)([.!?])$", text, flags=re.IGNORECASE)
        if inline_match:
            descriptor_words = re.findall(r"[A-Za-z']+", inline_match.group(2).lower())
            if descriptor_words and any(
                word in TRAILING_EMBELLISHMENT_WORDS for word in descriptor_words
            ):
                return inline_match.group(1) + inline_match.group(3)

        sentence_match = re.match(r"^(.*?\.)\s+(?:a|an)\s+(.+)$", text, flags=re.IGNORECASE)
        if not sentence_match:
            return text

        descriptor_words = re.findall(r"[A-Za-z']+", sentence_match.group(2).lower())
        if descriptor_words and any(
            word in TRAILING_EMBELLISHMENT_WORDS for word in descriptor_words
        ):
            return sentence_match.group(1)
        return text

    def _normalize_factual_ending(self, text: str) -> str:
        """Convert lightweight factual exclamation endings to periods."""
        if re.search(
            r"\b(?:capital|answer|result|sum|total|equals|is)\b", text, flags=re.IGNORECASE
        ):
            return re.sub(r"!$", ".", text)
        return text

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize excessive whitespace."""
        return normalize_internal_whitespace(text)

    # ==========================================================================
    # Event Type Helpers
    # ==========================================================================

    def is_plan_event(self, event_type: str) -> bool:
        """Check if this is a plan-related event."""
        return event_type.startswith("soothe.cognition.plan.")

    def is_research_event(self, event_type: str) -> bool:
        """Check if this is a research subagent event."""
        return event_type.startswith("soothe.subagent.research.")

    def is_internal_event(self, event_type: str) -> bool:
        """Check if this is an internal (never-shown) event."""
        return event_type in INTERNAL_EVENT_TYPES or "internal" in event_type


# =============================================================================
# Factory Function
# =============================================================================


def create_display_policy(
    verbosity: VerbosityLevel = "normal",
) -> DisplayPolicy:
    """Create a display policy with the given verbosity level.

    Args:
        verbosity: Verbosity level for filtering

    Returns:
        Configured DisplayPolicy instance
    """
    return DisplayPolicy(verbosity=verbosity)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "INTERNAL_EVENT_TYPES",
    "INTERNAL_JSON_KEYS",
    "SKIP_EVENT_TYPES",
    "DisplayPolicy",
    "VerbosityLevel",
    "VerbosityTier",
    "create_display_policy",
    "normalize_verbosity",
    "should_show_tool_call_ui",
]
