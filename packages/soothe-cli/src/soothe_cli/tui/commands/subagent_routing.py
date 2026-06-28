"""Subagent display names and input routing (shared by CLI and TUI)."""

from __future__ import annotations

# Display names for known soothe core subagents (IG-517).
# Only include subagents that actually exist in soothe core:
# - Built-in: explore, plan, tacitus (registered in SUBAGENT_FACTORIES)
# - Plugin-based: browser_use (registered via @plugin decorator)
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "explore": "Explore",
    "plan": "Plan",
    "tacitus": "Tacitus",
    "browser_use": "Browser",
}

# Lowercase ids matched after ``/`` for preferred_subagent routing (core only).
SUBAGENT_SLASH_ROUTE_IDS: tuple[str, ...] = ("tacitus", "explore")

BUILTIN_SUBAGENT_NAMES: list[str] = list(SUBAGENT_SLASH_ROUTE_IDS)


def get_subagent_display_name(technical_name: str) -> str:
    """Get display name for a subagent.

    Args:
        technical_name: Internal subagent name.

    Returns:
        Title-cased label for first-party ids; otherwise the raw id string.
    """
    key = (technical_name or "").strip()
    if key.lower() in SUBAGENT_DISPLAY_NAMES:
        return SUBAGENT_DISPLAY_NAMES[key.lower()]
    return key


def parse_subagent_from_input(user_input: str) -> tuple[str | None, str]:
    """Parse subagent subcommand from user input.

    Detects subagent routing commands (e.g. ``/tacitus``, ``/explore``)
    and extracts the subagent name along with the cleaned input text.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_name, cleaned_text)``.
        ``subagent_name`` is ``None`` if no valid subcommand found.
        The subcommand is removed from ``cleaned_text``.

    Examples:
        ``"/tacitus check this"`` -> ``("tacitus", "check this")``
        ``"/explore map the repo"`` -> ``("explore", "map the repo")``
        ``"hello world"`` -> ``(None, "hello world")``
    """
    first_match: tuple[int, str] | None = None

    for subagent_name in SUBAGENT_SLASH_ROUTE_IDS:
        subcommand = f"/{subagent_name}"
        idx = user_input.lower().find(subcommand)
        if idx != -1 and (first_match is None or idx < first_match[0]):
            first_match = (idx, subagent_name)

    if first_match:
        idx, subagent_name = first_match
        subcommand = f"/{subagent_name}"
        cleaned = user_input[:idx] + user_input[idx + len(subcommand) :]
        cleaned = " ".join(cleaned.split())
        return (subagent_name, cleaned)

    return (None, user_input)
