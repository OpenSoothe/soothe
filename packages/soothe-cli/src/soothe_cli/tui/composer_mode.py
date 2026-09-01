"""TUI composer modes — working-mode hierarchy.

Agent sub-modes (auto, manual, bypass) grouped first, then plan and ask.
Shift+Tab cycle: Auto → Manual → Bypass → Plan → Ask → Auto.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPOSER_MODE_AUTO = "auto"
COMPOSER_MODE_MANUAL = "manual"
COMPOSER_MODE_PLAN = "plan"
COMPOSER_MODE_ASK = "ask"
COMPOSER_MODE_BYPASS = "bypass"

# Agent sub-modes grouped first, then standalone working modes.
COMPOSER_MODE_ORDER: tuple[str, ...] = (
    COMPOSER_MODE_AUTO,
    COMPOSER_MODE_MANUAL,
    COMPOSER_MODE_BYPASS,
    COMPOSER_MODE_PLAN,
    COMPOSER_MODE_ASK,
)
VALID_COMPOSER_MODES: frozenset[str] = frozenset(COMPOSER_MODE_ORDER)

# Agent working mode sub-modes (full mutating tool surface).
AGENT_SUB_MODES: frozenset[str] = frozenset(
    {COMPOSER_MODE_AUTO, COMPOSER_MODE_MANUAL, COMPOSER_MODE_BYPASS}
)
# Standalone working modes (not agent sub-modes).
STANDALONE_WORKING_MODES: frozenset[str] = frozenset({COMPOSER_MODE_PLAN, COMPOSER_MODE_ASK})


@dataclass(frozen=True)
class ComposerWireFields:
    """Wire fields derived from a composer mode."""

    clarification_mode: str
    preferred_subagent: str | None
    interaction_mode: str | None


def normalize_composer_mode(mode: str | None) -> str:
    """Clamp an arbitrary value to a valid composer mode (default `auto`)."""
    if mode in VALID_COMPOSER_MODES:
        return mode
    return COMPOSER_MODE_AUTO


def next_composer_mode(current: str) -> str:
    """Advance to the next mode in the cycle. Unknown values reset to `auto`."""
    if current not in VALID_COMPOSER_MODES:
        return COMPOSER_MODE_AUTO
    idx = COMPOSER_MODE_ORDER.index(current)
    return COMPOSER_MODE_ORDER[(idx + 1) % len(COMPOSER_MODE_ORDER)]


def resolve_composer_wire_fields(mode: str) -> ComposerWireFields:
    """Map composer mode to wire fields.

    auto → clarification=auto, interaction=None; manual → clarification=manual;
    bypass → clarification=auto, interaction=bypass; plan → interaction=plan;
    ask → interaction=ask. Slash routing in the message wins over the sticky hint.
    """
    normalized = normalize_composer_mode(mode)
    if normalized == COMPOSER_MODE_PLAN:
        return ComposerWireFields(COMPOSER_MODE_AUTO, None, "plan")
    if normalized == COMPOSER_MODE_ASK:
        return ComposerWireFields(COMPOSER_MODE_AUTO, None, COMPOSER_MODE_ASK)
    if normalized == COMPOSER_MODE_BYPASS:
        return ComposerWireFields(COMPOSER_MODE_AUTO, None, COMPOSER_MODE_BYPASS)
    if normalized == COMPOSER_MODE_MANUAL:
        return ComposerWireFields(COMPOSER_MODE_MANUAL, None, None)
    return ComposerWireFields(COMPOSER_MODE_AUTO, None, None)
