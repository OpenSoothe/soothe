"""Internal text utilities for tool formatting (not part of public API)."""


def normalize_tool_name(tool_name: str) -> str:
    """Normalize tool name to snake_case for comparison and lookup.

    Args:
        tool_name: Raw tool name (may contain dashes or spaces).

    Returns:
        Lowercase snake_case name.
    """
    return tool_name.lower().replace("-", "_").replace(" ", "_")


def text_looks_like_error(text: str) -> bool:
    """Return True if text content suggests a tool failure.

    Checks for common error indicator substrings.

    Args:
        text: Tool output text to inspect.

    Returns:
        True if any error indicator is found.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(indicator in lowered for indicator in ("error", "failed", "exception", "traceback"))
