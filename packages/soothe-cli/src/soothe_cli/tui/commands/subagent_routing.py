"""Subagent display names and input routing (shared by CLI and TUI)."""

from __future__ import annotations

# Display names for known soothe core subagents (IG-517).
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "planner": "Planner",
    "deep_research": "Deep Research",
    "academic_research": "Academic Research",
    "browser_use": "Browser",
}

# Lowercase slash tokens matched after ``/`` for preferred_subagent routing (core only).
# Longest-first so a shorter id never shadows a longer prefix match.
# Intake-only specialists (IG-600/601) must stay here so slash sets preferred_subagent.
# ``plan`` is the UX slash for wire id ``planner`` (RFC-454 /plan routing).
SUBAGENT_SLASH_ROUTE_IDS: tuple[str, ...] = (
    "academic_research",
    "deep_research",
    "browser_use",
    "planner",
    "plan",
)

# Slash token → wire preferred_subagent id when they differ.
_SUBAGENT_SLASH_TO_WIRE: dict[str, str] = {
    "plan": "planner",
}


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

    Detects subagent routing commands (e.g. ``/deep_research``, ``/browser_use``,
    ``/plan``) and extracts the wire subagent name along with the cleaned input
    text (slash token removed so display cards do not show the prefix).

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_name, cleaned_text)``.
        ``subagent_name`` is ``None`` if no valid subcommand found.
        The subcommand is removed from ``cleaned_text``.

    Examples:
        ``"/deep_research check this"`` -> ``("deep_research", "check this")``
        ``"/browser_use open example.com"`` -> ``("browser_use", "open example.com")``
        ``"/plan draft a migration"`` -> ``("planner", "draft a migration")``
        ``"hello world"`` -> ``(None, "hello world")``
    """
    first_match: tuple[int, str] | None = None
    lowered = user_input.lower()

    for slash_token in SUBAGENT_SLASH_ROUTE_IDS:
        subcommand = f"/{slash_token}"
        idx = lowered.find(subcommand)
        if idx == -1:
            continue
        end = idx + len(subcommand)
        # Require end-of-string or whitespace so ``/browser`` does not match ``/browser_use``.
        if end < len(lowered) and not lowered[end].isspace():
            continue
        if first_match is None or idx < first_match[0]:
            first_match = (idx, slash_token)

    if first_match:
        idx, slash_token = first_match
        subcommand = f"/{slash_token}"
        cleaned = user_input[:idx] + user_input[idx + len(subcommand) :]
        cleaned = " ".join(cleaned.split())
        wire_name = _SUBAGENT_SLASH_TO_WIRE.get(slash_token, slash_token)
        return (wire_name, cleaned)

    return (None, user_input)
