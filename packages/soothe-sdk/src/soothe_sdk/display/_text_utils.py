"""Internal text utilities for tool formatting (not part of public API)."""


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
