"""Ground operator-approved intake plans onto the decompose DISPATCH path."""

from __future__ import annotations

import logging
from typing import Any

from soothe.prompts import APPROVED_PLAN_EXECUTE_HINT

logger = logging.getLogger(__name__)

_APPROVED_PLAN_MARKER = "<!-- soothe:approved-plan -->"


def approved_plan_section_body(
    *,
    approved_plan_markdown: str,
    approved_plan_path: str | None = None,
) -> str:
    """Render the APPROVED PLAN section body for execute / plan envelopes."""
    body = (approved_plan_markdown or "").strip()
    if not body:
        return ""
    lines: list[str] = []
    path = (approved_plan_path or "").strip()
    if path:
        lines.append(f"path: {path}")
    lines.append(APPROVED_PLAN_EXECUTE_HINT)
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def compose_root_full_description(
    goal_text: str,
    *,
    approved_plan_markdown: str,
    approved_plan_path: str | None = None,
) -> str:
    """Compose root ``full_description`` that carries the approved plan into THREAD."""
    goal = (goal_text or "").strip() or "Execute task"
    section = approved_plan_section_body(
        approved_plan_markdown=approved_plan_markdown,
        approved_plan_path=approved_plan_path,
    )
    return f"{goal}\n\n{_APPROVED_PLAN_MARKER}\n## APPROVED PLAN\n\n{section}"


def root_already_grounded(full_description: str | None) -> bool:
    """True when the root description already embeds an approved plan."""
    return _APPROVED_PLAN_MARKER in (full_description or "")


def consume_approved_plan_from_state(loop_state: Any) -> tuple[str | None, str | None]:
    """Read and clear one-shot approved plan fields from ``LoopState``."""
    if loop_state is None:
        return None, None
    body = (getattr(loop_state, "approved_plan_markdown", None) or "").strip() or None
    path = (getattr(loop_state, "approved_plan_path", None) or "").strip() or None
    if hasattr(loop_state, "approved_plan_markdown"):
        loop_state.approved_plan_markdown = None
    if hasattr(loop_state, "approved_plan_path"):
        loop_state.approved_plan_path = None
    return body, path


def peek_approved_plan_from_state(loop_state: Any) -> tuple[str | None, str | None]:
    """Read approved plan fields without clearing.

    When the plan body is not cached on ``loop_state`` (e.g. the plan-mode
    approve exec-goal carries only ``approved_plan_path``), reload the body
    from the artifact on disk so DISPATCH can ground it onto the exec root.
    """
    if loop_state is None:
        return None, None
    body = (getattr(loop_state, "approved_plan_markdown", None) or "").strip() or None
    path = (getattr(loop_state, "approved_plan_path", None) or "").strip() or None
    if not body and path:
        try:
            from pathlib import Path

            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            logger.debug("[grounding] could not reload approved plan from %s", path, exc_info=True)
        else:
            from soothe.sloop.plans.artifact import strip_plan_frontmatter

            body = strip_plan_frontmatter(text).strip() or text.strip() or None
    return body, path


__all__ = [
    "approved_plan_section_body",
    "compose_root_full_description",
    "consume_approved_plan_from_state",
    "peek_approved_plan_from_state",
    "root_already_grounded",
]
