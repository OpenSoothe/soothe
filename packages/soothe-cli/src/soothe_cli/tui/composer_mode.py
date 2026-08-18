"""Sticky TUI composer modes: Auto / Manual / Plan.

``auto`` / ``manual`` map to the RFC-622 ``clarification_mode`` wire field.
``plan`` is a sticky planner-routing mode that sets ``preferred_subagent=planner``
so operators need not type ``/plan`` on every turn.

Default composer mode is ``manual`` so interactive TUI sessions relay
clarification questions to the operator unless they opt into Auto or Plan.
"""

from __future__ import annotations

COMPOSER_MODE_AUTO = "auto"
COMPOSER_MODE_MANUAL = "manual"
COMPOSER_MODE_PLAN = "plan"

COMPOSER_MODE_ORDER: tuple[str, ...] = (
    COMPOSER_MODE_AUTO,
    COMPOSER_MODE_MANUAL,
    COMPOSER_MODE_PLAN,
)
VALID_COMPOSER_MODES: frozenset[str] = frozenset(COMPOSER_MODE_ORDER)


def normalize_composer_mode(mode: str | None) -> str:
    """Clamp an arbitrary value to a valid composer mode (default ``manual``)."""
    if mode in VALID_COMPOSER_MODES:
        return mode
    return COMPOSER_MODE_MANUAL


def next_composer_mode(current: str) -> str:
    """Advance Auto → Manual → Plan → Auto.

    Unknown values normalize to ``manual`` (same as a first Shift+Tab from a
    garbage seed), without advancing past Manual in that step.
    """
    if current not in VALID_COMPOSER_MODES:
        return COMPOSER_MODE_MANUAL
    idx = COMPOSER_MODE_ORDER.index(current)
    return COMPOSER_MODE_ORDER[(idx + 1) % len(COMPOSER_MODE_ORDER)]


def resolve_composer_wire_fields(mode: str) -> tuple[str, str | None]:
    """Map composer mode to wire ``clarification_mode`` and sticky subagent.

    Args:
        mode: Composer mode (``auto``, ``manual``, or ``plan``).

    Returns:
        ``(clarification_mode, sticky_preferred_subagent)``. Plan mode sends
        ``clarification_mode=auto`` plus sticky ``planner``; slash routing in
        the message still wins over the sticky hint at send time.
    """
    normalized = normalize_composer_mode(mode)
    if normalized == COMPOSER_MODE_PLAN:
        return COMPOSER_MODE_AUTO, "planner"
    if normalized == COMPOSER_MODE_MANUAL:
        return COMPOSER_MODE_MANUAL, None
    return COMPOSER_MODE_AUTO, None
