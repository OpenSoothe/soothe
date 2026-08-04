"""Rotating session tips for the status bar below the chat input.

Tips render only in the status footer (see :class:`~soothe_cli.tui.widgets.status.StatusBar`).
The welcome banner no longer holds a tip, so there is a single tip surface.
:class:`TipRotator` cycles through the pool so the footer rotates tips on an
interval instead of showing one fixed string for the whole session.
"""

from __future__ import annotations

import random

SESSION_TIPS: list[str] = [
    "Use @ to reference files and / for commands",
    "Try /resume to pick up a previous StrangeLoop instance",
    "Type exit, quit, or /quit to exit TUI; use /resume to continue a previous loop",
    "Use /context to check token usage and goal status",
    "Use /mcp to see your loaded tools and servers",
    "Use /model to switch models mid-conversation",
    "Use /model-router to switch role presets for this loop",
    "Press ctrl+x to compose prompts in your external editor",
    "Press ctrl+u to delete to the start of the line in the chat input",
    "Use /skill:<name> to invoke a skill directly",
    "Type /update to check for and install updates",
    "Use /theme to customize the CLI colors and style",
    "Use /skill:skill-creator to build reusable agent skills",
    "Use /auto-update to toggle automatic CLI updates",
    "Press ctrl+t to peek at the live plan while the agent is working",
    "Press shift+tab to switch into Plan mode (or use /plan)",
    "Use /plan to draft a goal without executing it right away",
]


def pick_session_tip() -> str:
    """Return one random tip string (one-shot selection)."""
    return random.choice(SESSION_TIPS)  # noqa: S311


class TipRotator:
    """Cycle through the tip pool, yielding a different tip each call.

    The rotator walks a shuffled copy of :data:`SESSION_TIPS` and reshuffles
    when exhausted, so repeated calls avoid returning the same tip twice in a
    row (unless the pool has only one entry). Each instance keeps its own
    position, so multiple rotators do not interfere with each other.
    """

    def __init__(self, tips: list[str] | None = None) -> None:
        self._tips = list(tips) if tips is not None else list(SESSION_TIPS)
        self._order: list[int] = []
        self._pos = 0
        self._last_index: int | None = None
        self._shuffle()

    def _shuffle(self) -> None:
        """Build a fresh shuffled index order, avoiding a repeat of the last tip."""
        n = len(self._tips)
        if n == 0:
            self._order = []
            self._pos = 0
            return
        order = list(range(n))
        random.shuffle(order)  # noqa: S311
        # Avoid repeating the last yielded tip at the wrap-around.
        if n > 1 and self._last_index is not None and order[0] == self._last_index:
            order[0], order[1] = order[1], order[0]
        self._order = order
        self._pos = 0

    def next_tip(self) -> str:
        """Return the next tip in the rotation.

        Returns:
            A tip string from the pool. Returns an empty string when the pool
            is empty.
        """
        if not self._tips:
            return ""
        if self._pos >= len(self._order):
            self._shuffle()
        idx = self._order[self._pos]
        self._pos += 1
        self._last_index = idx
        return self._tips[idx]
