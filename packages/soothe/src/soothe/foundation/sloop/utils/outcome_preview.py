"""Planner-facing outcome preview helpers (RFC-211, IG-357)."""

from __future__ import annotations

from typing import Any


def planner_outcome_text_preview(outcome: dict[str, Any]) -> str | None:
    """Resolve bounded planner-facing text from an RFC-211 outcome dict (IG-357).

    Precedence:

    1. ``wave_join_preview`` — Execute wave join excerpt on wave-level ``StepResult``.
    2. ``task_return_preview`` — single ``task`` tool return excerpt from metadata registry.
    3. ``output_summary`` — generic truncated summary.

    Returns:
        First non-empty string, or ``None``.
    """
    for key in ("wave_join_preview", "task_return_preview", "output_summary"):
        val = outcome.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None
