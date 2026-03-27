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
    from soothe.ux.core.display_policy import DisplayPolicy

    policy = DisplayPolicy(verbosity="normal")

    if policy.should_show_event(event_type, data):
        render_event(data)

    if policy.should_show_assistant_text(text, is_main=True):
        display_text(policy.filter_content(text))
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Literal

# =============================================================================
# Type Definitions
# =============================================================================

VerbosityLevel = Literal["minimal", "normal", "detailed", "debug"]


class EventCategory(Enum):
    """Categories for event filtering decisions."""

    ASSISTANT_TEXT = auto()  # Main assistant responses
    PROTOCOL = auto()  # Protocol/lifecycle events
    TOOL_ACTIVITY = auto()  # Tool calls and results
    SUBAGENT_PROGRESS = auto()  # Subagent progress updates
    SUBAGENT_CUSTOM = auto()  # Custom subagent events
    THINKING = auto()  # Internal thinking/heartbeat
    ERROR = auto()  # Error events
    DEBUG = auto()  # Debug-level events
    INTERNAL = auto()  # Internal events - NEVER shown


# =============================================================================
# Policy Configuration Constants
# =============================================================================

# Internal JSON keys that indicate research/inquiry engine responses
INTERNAL_JSON_KEYS = frozenset(
    {
        "sub_questions",
        "queries",
        "is_sufficient",
        "knowledge_gap",
        "follow_up_queries",
    }
)

# Event types that should NEVER be shown (internal implementation details)
INTERNAL_EVENT_TYPES = frozenset(
    {
        "soothe.subagent.research.internal_llm",
    }
)

# Event types to skip in progress display (handled by plan update mechanism)
SKIP_EVENT_TYPES = frozenset(
    {
        "soothe.cognition.plan.batch_started",
        "soothe.cognition.plan.step_started",
        "soothe.cognition.plan.step_completed",
        "soothe.cognition.plan.step_failed",
    }
)

# Keywords that indicate confused LLM meta-responses
CONFUSED_RESPONSE_INDICATORS = [
    ("sub-questions", ["provide", "share", "empty", "not provided", "actually provided"]),
    ("sub_questions", ["provide", "share", "empty", "not provided", "actually provided"]),
    ("section appears to be empty", []),
    ("once you share them", ["json format"]),
]


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
        category = self._classify_event(event_type, namespace)
        return self._should_show_category(category)

    def _classify_event(
        self,
        event_type: str,
        namespace: tuple[str, ...] = (),
    ) -> EventCategory:
        """Classify an event into a category for filtering."""
        # Non-soothe events
        if not event_type.startswith("soothe."):
            if namespace:
                if "thinking" in event_type or "heartbeat" in event_type:
                    return EventCategory.THINKING
                return EventCategory.SUBAGENT_CUSTOM
            if "thinking" in event_type or "heartbeat" in event_type:
                return EventCategory.THINKING
            return EventCategory.DEBUG

        # Extract domain from event type
        segments = event_type.split(".")
        domain = segments[1] if len(segments) >= 2 else "unknown"  # noqa: PLR2004

        if domain == "error":
            return EventCategory.ERROR
        if domain == "output":
            return EventCategory.ASSISTANT_TEXT
        if domain == "tool":
            # Check if it's an internal research event
            if "internal" in event_type:
                return EventCategory.INTERNAL
            return EventCategory.TOOL_ACTIVITY
        if domain == "subagent":
            if "thinking" in event_type or "heartbeat" in event_type:
                return EventCategory.THINKING
            return EventCategory.SUBAGENT_CUSTOM
        if domain in ("lifecycle", "protocol"):
            return EventCategory.PROTOCOL

        return EventCategory.PROTOCOL

    def _should_show_category(self, category: EventCategory) -> bool:
        """Check if a category should be shown at current verbosity."""
        # Internal category is NEVER shown
        if category == EventCategory.INTERNAL:
            return False

        if self.verbosity == "debug":
            return True

        if self.verbosity == "detailed":
            return category in {
                EventCategory.ASSISTANT_TEXT,
                EventCategory.PROTOCOL,
                EventCategory.SUBAGENT_PROGRESS,
                EventCategory.SUBAGENT_CUSTOM,
                EventCategory.TOOL_ACTIVITY,
                EventCategory.ERROR,
            }

        if self.verbosity == "normal":
            return category in {
                EventCategory.ASSISTANT_TEXT,
                EventCategory.PROTOCOL,
                EventCategory.SUBAGENT_PROGRESS,
                EventCategory.ERROR,
            }

        # minimal
        return category in {
            EventCategory.ASSISTANT_TEXT,
            EventCategory.ERROR,
        }

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

    # ==========================================================================
    # Assistant Text Filtering
    # ==========================================================================

    def should_show_assistant_text(
        self,
        text: str,  # noqa: ARG002
        *,
        is_main: bool,
        is_multi_step_active: bool = False,
    ) -> bool:
        """Determine if assistant text should be displayed.

        Args:
            text: The text content
            is_main: True if from main agent
            is_multi_step_active: True if in multi-step plan execution

        Returns:
            True if the text should be shown
        """
        # During internal context, suppress non-main agent text
        if self.internal_context_active and not is_main:
            return False

        # During multi-step plans, suppress intermediate main agent text
        if is_multi_step_active and is_main:
            return False

        # Check verbosity
        return self._should_show_category(EventCategory.ASSISTANT_TEXT)

    def filter_content(self, text: str) -> str:
        """Filter internal content from text for display.

        This method removes:
        - Internal JSON responses (sub_questions, etc.)
        - Search data tags
        - Synthesis instructions
        - Confused LLM meta-responses

        Args:
            text: Raw text content

        Returns:
            Filtered text safe for display
        """
        # Filter JSON code blocks with internal keys
        text = self._filter_json_code_blocks(text)

        # Filter plain JSON objects with internal keys
        text = self._filter_plain_json(text)

        # Filter confused LLM meta-responses
        text = self._filter_confused_responses(text)

        # Filter search data tags
        text = self._filter_search_data_tags(text)

        # Clean up whitespace
        text = self._normalize_whitespace(text)

        return text.strip() if text.strip() == "" else text

    def _filter_json_code_blocks(self, text: str) -> str:
        """Remove JSON code blocks containing internal keys."""
        result_parts = []
        i = 0

        while i < len(text):
            # Find ```json marker
            json_start = text.find("```json", i)
            if json_start == -1:
                result_parts.append(text[i:])
                break

            result_parts.append(text[i:json_start])

            # Find closing ```
            content_start = json_start + 7
            json_end = text.find("```", content_start)

            if json_end == -1:
                result_parts.append(text[json_start:])
                break

            # Try to parse and check if internal
            json_content = text[content_start:json_end].strip()
            should_remove = self._is_internal_json_content(json_content)

            if should_remove:
                i = json_end + 3
            else:
                result_parts.append(text[json_start : json_end + 3])
                i = json_end + 3

        return "".join(result_parts)

    def _filter_plain_json(self, text: str) -> str:
        """Remove plain JSON objects containing internal keys."""
        result_parts = []
        i = 0

        while i < len(text):
            # Find opening brace at line start or after whitespace
            brace_pos = -1
            for j in range(i, len(text)):
                if text[j] == "{" and (j == 0 or text[j - 1] in " \t\n\r"):
                    brace_pos = j
                    break

            if brace_pos == -1:
                result_parts.append(text[i:])
                break

            result_parts.append(text[i:brace_pos])

            # Find matching closing brace
            json_end = self._find_matching_brace(text, brace_pos)

            if json_end == -1:
                result_parts.append(text[brace_pos:])
                break

            json_text = text[brace_pos:json_end]
            should_remove = self._is_internal_json_content(json_text)

            if should_remove:
                i = json_end
            else:
                result_parts.append(json_text)
                i = json_end

        return "".join(result_parts)

    def _find_matching_brace(self, text: str, start: int) -> int:
        """Find the position after the matching closing brace."""
        brace_count = 0
        for j in range(start, len(text)):
            if text[j] == "{":
                brace_count += 1
            elif text[j] == "}":
                brace_count -= 1
                if brace_count == 0:
                    return j + 1
        return -1

    def _is_internal_json_content(self, content: str) -> bool:
        """Check if JSON content contains internal keys."""
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return bool(INTERNAL_JSON_KEYS & set(parsed.keys()))
        except json.JSONDecodeError:
            pass
        return False

    def _filter_confused_responses(self, text: str) -> str:
        """Remove confused LLM meta-responses about missing data."""
        text_lower = text.lower()

        for primary_indicator, secondary_indicators in CONFUSED_RESPONSE_INDICATORS:
            if primary_indicator in text_lower and (
                not secondary_indicators or any(s in text_lower for s in secondary_indicators)
            ):
                # Filter line by line
                lines = text.split("\n")
                filtered = [line for line in lines if primary_indicator not in line.lower()]
                text = "\n".join(filtered)

        return text

    def _filter_search_data_tags(self, text: str) -> str:
        """Remove <search_data> blocks and synthesis instructions."""
        # Remove search_data blocks
        while "<search_data>" in text and "</search_data>" in text:
            start = text.find("<search_data>")
            end = text.find("</search_data>") + len("</search_data>")
            text = text[:start] + text[end:]

        # Remove leftover tags
        text = text.replace("<search_data>", "").replace("</search_data>", "")

        # Remove synthesis instructions
        synthesis_markers = [
            "Synthesize the search data into a clear answer.",
            "Do NOT reproduce raw results, source listings, or URLs.",
        ]
        for marker in synthesis_markers:
            text = text.replace(marker, "")

        return text

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize excessive whitespace."""
        # Normalize multiple spaces (2+ -> 1)
        text = re.sub(r" {2,}", " ", text)
        # Normalize multiple newlines
        return re.sub(r"\n{3,}", "\n\n", text)

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
    "EventCategory",
    "VerbosityLevel",
    "create_display_policy",
]
