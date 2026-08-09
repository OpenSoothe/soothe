"""Shared envelope helpers for Autopilot prompts (IG-736)."""

from __future__ import annotations

UNTRUSTED_OPEN = "<untrusted_data>"
UNTRUSTED_CLOSE = "</untrusted_data>"


def wrap_untrusted(body: str) -> str:
    """Wrap untrusted operator/agent text for guard evaluation.

    Args:
        body: Condition text, goal summaries, or other untrusted content.

    Returns:
        Body enclosed in ``<untrusted_data>`` markers.
    """
    cleaned = body if body.endswith("\n") else f"{body}\n"
    return f"{UNTRUSTED_OPEN}\n{cleaned}{UNTRUSTED_CLOSE}"


__all__ = [
    "UNTRUSTED_CLOSE",
    "UNTRUSTED_OPEN",
    "wrap_untrusted",
]
