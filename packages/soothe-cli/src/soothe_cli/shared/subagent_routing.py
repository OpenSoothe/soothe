"""Subagent display names and input routing (shared by CLI and TUI)."""

from __future__ import annotations

SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "browser": "Browser",
    "claude": "Claude",
    "research": "Research",
    "explore": "Explore",
}

BUILTIN_SUBAGENT_NAMES: list[str] = list(SUBAGENT_DISPLAY_NAMES.keys())


def get_subagent_display_name(technical_name: str) -> str:
    """Get display name for a subagent.

    Args:
        technical_name: Internal subagent name.

    Returns:
        PascalCase display name.
    """
    return SUBAGENT_DISPLAY_NAMES.get(
        technical_name,
        technical_name.replace("_", " ").title().replace(" ", ""),
    )


def parse_subagent_from_input(user_input: str) -> tuple[str | None, str]:
    """Parse subagent subcommand from user input.

    Detects subagent subcommands (e.g., /browser, /claude) anywhere in the text
    and extracts the subagent name along with the cleaned input text.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_name, cleaned_text)``.
        ``subagent_name`` is ``None`` if no valid subcommand found.
        The subcommand is removed from ``cleaned_text``.

    Examples:
        ``"/browser check this"`` -> ``("browser", "check this")``
        ``"Can you /claude analyze this"`` -> ``("claude", "Can you analyze this")``
        ``"hello world"`` -> ``(None, "hello world")``
    """
    first_match: tuple[int, str] | None = None

    for subagent_name in BUILTIN_SUBAGENT_NAMES:
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
