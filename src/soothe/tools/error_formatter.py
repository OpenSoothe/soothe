"""Format tool errors for user display (RFC-0016 Phase 4)."""

from typing import Any


def format_tool_error(error_dict: dict[str, Any]) -> str:
    """Format structured error for user-friendly display.

    Args:
        error_dict: Error response from tool

    Returns:
        Formatted error string
    """
    lines = []

    # Main error
    lines.append(f"❌ Error: {error_dict.get('error', 'Unknown error')}")

    # Details
    details = error_dict.get("details", {})
    if details:
        lines.append("\nDetails:")
        for key, value in details.items():
            lines.append(f"  • {key}: {value}")

    # Suggestions
    suggestions = error_dict.get("suggestions", [])
    if suggestions:
        lines.append("\n💡 Suggestions:")
        for i, suggestion in enumerate(suggestions, 1):
            lines.append(f"  {i}. {suggestion}")

    # Auto-retry hint
    auto_retry = error_dict.get("auto_retry_hint")
    if auto_retry:
        lines.append(f"\n🔄 Try: {auto_retry}")

    return "\n".join(lines)


# Example usage
if __name__ == "__main__":
    error = {
        "error": "File already exists",
        "details": {"path": "/path/to/file.py"},
        "suggestions": [
            "Use read_file first to check current contents",
            "Use edit_file_lines to modify specific sections",
        ],
        "recoverable": True,
        "auto_retry_hint": "read_file(path='/path/to/file.py')",
    }

    print(format_tool_error(error))
    # Output:
    # ❌ Error: File already exists
    #
    # Details:
    #   • path: /path/to/file.py
    #
    # 💡 Suggestions:
    #   1. Use read_file first to check current contents
    #   2. Use edit_file_lines to modify specific sections
    #
    # 🔄 Try: read_file(path='/path/to/file.py')
