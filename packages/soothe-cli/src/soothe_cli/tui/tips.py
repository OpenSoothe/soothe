"""Rotating session tips for the status bar below the chat input."""

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
]


def pick_session_tip() -> str:
    """Return one tip string for this session."""
    return random.choice(SESSION_TIPS)  # noqa: S311
