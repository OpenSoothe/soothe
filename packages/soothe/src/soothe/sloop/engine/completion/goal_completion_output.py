"""Goal-completion user-visible text reconciliation (display quality)."""

from __future__ import annotations

import re
from typing import Any

from soothe.sloop.utils.stream_normalize import extract_text_from_message_content


def _numeric_tokens(text: str) -> set[str]:
    return {match.group(0) for match in re.finditer(r"\b\d+\b", text or "")}


def collect_execute_step_deliverable_text(loop_messages: list[Any]) -> str:
    """Return concatenated execute-step assistant bodies from the loop ledger."""
    parts: list[str] = []
    for msg in loop_messages:
        if getattr(msg, "phase", None) != "execute_step":
            continue
        content = extract_text_from_message_content(getattr(msg, "content", None)).strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts).strip()


def synthesis_reflects_step_deliverables(synthesis: str, step_deliverable: str) -> bool:
    """Return True when synthesis incorporates step deliverable evidence.

    Uses structural checks only: required numeric tokens from the step body must
    appear in synthesis when the step body contains numbers.
    """
    synth = (synthesis or "").strip()
    deliverable = (step_deliverable or "").strip()
    if not synth or not deliverable:
        return bool(synth)

    step_numbers = _numeric_tokens(deliverable)
    if step_numbers:
        synth_numbers = _numeric_tokens(synth)
        if not step_numbers.issubset(synth_numbers):
            return False

    return True


def reconcile_synthesis_with_step_ledger(
    synthesis_text: str,
    *,
    loop_messages: list[Any],
) -> str:
    """Prefer execute-step deliverables when synthesis drifts from step evidence."""
    synth = (synthesis_text or "").strip()
    deliverable = collect_execute_step_deliverable_text(loop_messages)
    if not deliverable:
        return synth
    if not synth:
        return deliverable
    if synthesis_reflects_step_deliverables(synth, deliverable):
        return synth
    return deliverable


__all__ = [
    "collect_execute_step_deliverable_text",
    "reconcile_synthesis_with_step_ledger",
    "synthesis_reflects_step_deliverables",
]
