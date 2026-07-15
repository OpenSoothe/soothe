"""Subagent display names and input routing (shared by CLI and TUI)."""

from __future__ import annotations

# Display names for known soothe core subagents (IG-517).
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Planner",
    "deep_research": "Deep Research",
    "academic_research": "Academic Research",
    "browser_use": "Browser",
}

# Lowercase ids matched after ``/`` for preferred_subagent routing (core only).
# Longest-first so a shorter id never shadows a longer prefix match.
# Intake-only specialists (IG-600/601) must stay here so slash sets preferred_subagent.
SUBAGENT_SLASH_ROUTE_IDS: tuple[str, ...] = (
    "academic_research",
    "deep_research",
    "browser_use",
)


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

    Detects subagent routing commands (e.g. ``/deep_research``, ``/browser_use``)
    and extracts the subagent name along with the cleaned input text.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_name, cleaned_text)``.
        ``subagent_name`` is ``None`` if no valid subcommand found.
        The subcommand is removed from ``cleaned_text``.

    Examples:
        ``"/deep_research check this"`` -> ``("deep_research", "check this")``
        ``"/browser_use open example.com"`` -> ``("browser_use", "open example.com")``
        ``"hello world"`` -> ``(None, "hello world")``
    """
    first_match: tuple[int, str] | None = None
    lowered = user_input.lower()

    for subagent_name in SUBAGENT_SLASH_ROUTE_IDS:
        subcommand = f"/{subagent_name}"
        idx = lowered.find(subcommand)
        if idx == -1:
            continue
        end = idx + len(subcommand)
        # Require end-of-string or whitespace so ``/browser`` does not match ``/browser_use``.
        if end < len(lowered) and not lowered[end].isspace():
            continue
        if first_match is None or idx < first_match[0]:
            first_match = (idx, subagent_name)

    if first_match:
        idx, subagent_name = first_match
        subcommand = f"/{subagent_name}"
        cleaned = user_input[:idx] + user_input[idx + len(subcommand) :]
        cleaned = " ".join(cleaned.split())
        return (subagent_name, cleaned)

    return (None, user_input)
