"""Unified presentation decisions for CLI/TUI surfaces.

This module centralizes display-time suppression and summarization rules so
renderers stay focused on output transport (stdout/stderr or widgets).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from soothe_sdk import log_preview
from soothe_sdk.verbosity import VerbosityTier, should_show

from soothe_cli.shared.display_policy import VerbosityLevel


@dataclass
class PresentationState:
    """Stateful suppression metadata for presentation decisions."""

    last_reason_key: str = ""
    last_reason_at_s: float = 0.0
    last_reason_by_step: dict[str, float] | None = None
    final_answer_locked: bool = False

    # Action deduplication tracking (IG-143)
    last_action_text: str = ""
    last_action_time: float = 0.0

    def __post_init__(self) -> None:
        """Initialize mutable map defaults safely."""
        if self.last_reason_by_step is None:
            self.last_reason_by_step = {}


class PresentationEngine:
    """Small policy engine for presentation-specific decisions."""

    _REASON_DEDUP_WINDOW_S = 8.0
    _REASON_STEP_RATE_LIMIT_S = 5.0
    _TOOL_RESULT_MAX_CHARS = 180
    _ACTION_DEDUP_WINDOW_S = 5.0

    def __init__(self) -> None:
        """Initialize presentation state."""
        self._state = PresentationState()

    @property
    def final_answer_locked(self) -> bool:
        """True after a custom final/chitchat response was emitted for this turn."""
        return self._state.final_answer_locked

    def mark_final_answer_locked(self) -> None:
        """Record that the final user-visible answer was already emitted (e.g. custom event)."""
        self._state.final_answer_locked = True

    def reset_turn(self) -> None:
        """Clear per-turn presentation state (reason dedup, final lock, action dedup)."""
        self._state.last_reason_key = ""
        self._state.last_reason_at_s = 0.0
        self._state.last_reason_by_step.clear()
        self._state.final_answer_locked = False
        self._state.last_action_text = ""
        self._state.last_action_time = 0.0

    def reset_session(self) -> None:
        """Clear presentation state for a new session (e.g. thread change)."""
        self.reset_turn()

    def tier_visible(self, tier: VerbosityTier, verbosity: VerbosityLevel) -> bool:
        """Return whether content at the given verbosity tier should display."""
        return should_show(tier, verbosity)

    def should_emit_reason(
        self,
        *,
        content: str,
        step_id: str | None = None,
        now_s: float | None = None,
    ) -> bool:
        """Decide whether a reason line should be emitted.

        Applies short-window de-duplication and per-step rate limiting.
        """
        now = now_s if now_s is not None else time.monotonic()
        normalized = self._normalize_reason(content)
        if not normalized:
            return False

        # Global dedup window for near-identical reason updates.
        if (
            normalized == self._state.last_reason_key
            and (now - self._state.last_reason_at_s) < self._REASON_DEDUP_WINDOW_S
        ):
            return False

        # Per-step rate limit for noisy repeated updates.
        if step_id:
            last_step_at = self._state.last_reason_by_step.get(step_id, 0.0)
            if (now - last_step_at) < self._REASON_STEP_RATE_LIMIT_S:
                return False
            self._state.last_reason_by_step[step_id] = now

        self._state.last_reason_key = normalized
        self._state.last_reason_at_s = now
        return True

    def summarize_tool_result(self, text: str) -> str:
        """Convert noisy tool results into concise one-line summaries."""
        compact = " ".join(text.split())
        if not compact:
            return compact

        # If payload looks like a huge list/dict dump, replace with a compact marker.
        if (compact.startswith("[") and compact.endswith("]")) or (
            compact.startswith("{") and compact.endswith("}")
        ):
            return "Tool result received (structured payload)."

        return log_preview(compact, self._TOOL_RESULT_MAX_CHARS)

    @staticmethod
    def _normalize_reason(content: str) -> str:
        lowered = content.lower().strip()
        lowered = re.sub(r"\(\d+%\s+sure\)", "", lowered)
        return re.sub(r"\s+", " ", lowered)

    def should_emit_action(
        self,
        *,
        action_text: str,
        now_s: float | None = None,
    ) -> bool:
        """Deduplicate repeated action summaries within 5s window.

        Args:
            action_text: Action summary text (may include confidence).
            now_s: Optional timestamp (defaults to monotonic time).

        Returns:
            True if action should be emitted, False if duplicate.
        """
        normalized = self._normalize_action(action_text)
        now = now_s if now_s is not None else time.monotonic()

        # Dedup identical actions within window
        if (
            normalized == self._state.last_action_text
            and (now - self._state.last_action_time) < self._ACTION_DEDUP_WINDOW_S
        ):
            return False

        # Update state
        self._state.last_action_text = normalized
        self._state.last_action_time = now
        return True

    @staticmethod
    def _normalize_action(text: str) -> str:
        """Strip confidence and whitespace for action comparison.

        Args:
            text: Action text to normalize.

        Returns:
            Normalized text for deduplication comparison.
        """
        lowered = text.lower().strip()
        # Remove "(XX% sure)" or "(XX% confident)" suffix
        lowered = re.sub(r"\(\d+%\s+(?:sure|confident)\)", "", lowered)
        return re.sub(r"\s+", " ", lowered)
