"""Subagent display names and routing helpers."""

from __future__ import annotations

SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "scout": "Scout",
    "research": "Research",
    "browser": "Browser",
    "claude": "Claude",
    "skillify": "Skillify",
    "weaver": "Weaver",
}

BUILTIN_SUBAGENT_NAMES: list[str] = list(SUBAGENT_DISPLAY_NAMES.keys())

_FIRST_SUBAGENT_INDEX = 2


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


def parse_subagent_prefix_from_input(user_input: str) -> tuple[list[str], str]:
    """Parse leading numeric selector from input.

    .. deprecated::
        Numeric prefix routing is deprecated and not used in Soothe.
        The LLM naturally routes to appropriate subagents via the `task` tool.
        This function is retained for backward compatibility with external code
        but should not be used in new implementations.

    Numeric prefixes select subagents:
    ``1`` = Main, ``2`` = Scout, ``3`` = Research, ``4`` = Browser,
    ``5`` = Claude, ``6`` = Skillify, ``7`` = Weaver.

    Args:
        user_input: Raw user input string.

    Returns:
        Tuple of ``(subagent_names, message)``.  Empty list means main agent.

    Examples:
        ``"4 quantum papers"`` -> ``(["research"], "quantum papers")``
        ``"hello world"`` -> ``([], "hello world")``
    """
    tokens = user_input.strip().split()
    i = 0
    while i < len(tokens) and tokens[i].replace(",", "").strip().isdigit():
        i += 1
    if i == 0:
        return ([], user_input.strip())

    prefix_str = " ".join(tokens[:i])
    message = " ".join(tokens[i:]).strip()
    names: list[str] = []
    for token in prefix_str.replace(",", " ").split():
        cleaned = token.strip()
        if not cleaned.isdigit():
            continue
        idx = int(cleaned)
        if idx == 1:
            continue
        if _FIRST_SUBAGENT_INDEX <= idx <= len(BUILTIN_SUBAGENT_NAMES) + 1:
            name = BUILTIN_SUBAGENT_NAMES[idx - _FIRST_SUBAGENT_INDEX]
            if name not in names:
                names.append(name)
    return (names, message)
