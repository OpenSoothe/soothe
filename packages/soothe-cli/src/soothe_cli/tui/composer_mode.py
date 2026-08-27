"""Sticky TUI composer modes: Auto / Manual / Plan / Ask.

``auto`` / ``manual`` map to the RFC-622 ``clarification_mode`` wire field.
``plan`` is a sticky plan-mode that sets ``interaction_mode=plan`` (read-only
plan graph) so operators need not type ``/plan`` on every turn.
``ask`` is a read-only mode enforced via ``interaction_mode=ask``.

The initial badge falls back to ``auto`` until the daemon is ready, at which
point ``on_soothe_app_daemon_ready`` re-seeds it from the daemon's configured
``agent.clarification.default_mode`` (e.g. ``manual``) when ``--mode`` was not
passed. ``auto`` routes clarifications to the veritas auto-answerer; ``manual``
relays them to the operator via the interactive TUI relay.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPOSER_MODE_AUTO = "auto"
COMPOSER_MODE_MANUAL = "manual"
COMPOSER_MODE_PLAN = "plan"
COMPOSER_MODE_ASK = "ask"

COMPOSER_MODE_ORDER: tuple[str, ...] = (
    COMPOSER_MODE_AUTO,
    COMPOSER_MODE_MANUAL,
    COMPOSER_MODE_PLAN,
    COMPOSER_MODE_ASK,
)
VALID_COMPOSER_MODES: frozenset[str] = frozenset(COMPOSER_MODE_ORDER)


@dataclass(frozen=True)
class ComposerWireFields:
    """Wire fields derived from a composer mode."""

    clarification_mode: str
    preferred_subagent: str | None
    interaction_mode: str | None


def normalize_composer_mode(mode: str | None) -> str:
    """Clamp an arbitrary value to a valid composer mode (default ``auto``)."""
    if mode in VALID_COMPOSER_MODES:
        return mode
    return COMPOSER_MODE_AUTO


def next_composer_mode(current: str) -> str:
    """Advance Auto → Manual → Plan → Ask → Auto.

    Unknown values normalize to ``auto`` (the default, same as a first
    Shift+Tab from a garbage seed), without advancing past Auto in that step.
    """
    if current not in VALID_COMPOSER_MODES:
        return COMPOSER_MODE_AUTO
    idx = COMPOSER_MODE_ORDER.index(current)
    return COMPOSER_MODE_ORDER[(idx + 1) % len(COMPOSER_MODE_ORDER)]


def resolve_composer_wire_fields(mode: str) -> ComposerWireFields:
    """Map composer mode to wire ``clarification_mode``, sticky subagent, and
    ``interaction_mode``.

    Args:
        mode: Composer mode (``auto``, ``manual``, ``plan``, or ``ask``).

    Returns:
        A :class:`ComposerWireFields`. Plan mode sends ``clarification_mode=auto``
        plus ``interaction_mode=plan`` (read-only plan graph); ask mode sends
        ``clarification_mode=auto`` plus ``interaction_mode=ask``. Slash routing
        in the message still wins over the sticky hint at send time.
    """
    normalized = normalize_composer_mode(mode)
    if normalized == COMPOSER_MODE_PLAN:
        return ComposerWireFields(COMPOSER_MODE_AUTO, None, "plan")
    if normalized == COMPOSER_MODE_ASK:
        return ComposerWireFields(COMPOSER_MODE_AUTO, None, COMPOSER_MODE_ASK)
    if normalized == COMPOSER_MODE_MANUAL:
        return ComposerWireFields(COMPOSER_MODE_MANUAL, None, None)
    return ComposerWireFields(COMPOSER_MODE_AUTO, None, None)
