"""Shared utilities for SDK and CLI packages.

Utility functions used by both daemon and CLI are provided in SDK to avoid
CLI importing daemon runtime.

This module is part of Phase 1 of IG-174: CLI import violations fix.
"""

import logging
import os
import re
from pathlib import Path

_logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")


def strip_internal_tags(text: str) -> str:
    """Strip internal thinking tags from text.

    Removes internal reasoning tags that should not be shown to users.

    Args:
        text: Text possibly containing internal tags.

    Returns:
        Cleaned text without internal tags.
    """
    # Pattern for internal tags like <thinking>, <internal>, etc.
    internal_pattern = re.compile(r"<(thinking|internal|reasoning)>.*?</\1>", re.DOTALL)
    return internal_pattern.sub("", text).strip()


def format_cli_error(error: Exception) -> str:
    """Format exception for CLI display.

    Creates user-friendly error message for terminal display.

    Args:
        error: Exception to format.

    Returns:
        Formatted error string suitable for CLI output.
    """
    error_type = type(error).__name__
    error_msg = str(error)

    # Truncate very long error messages
    if len(error_msg) > 500:
        error_msg = error_msg[:500] + "..."

    return f"{error_type}: {error_msg}"


def log_preview(text: str, max_length: int = 100) -> str:
    """Create preview of text for logging.

    Args:
        text: Full text to preview.
        max_length: Maximum preview length.

    Returns:
        Preview string, truncated if necessary.
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - 3] + "..."


def convert_and_abbreviate_path(path: str, base_dir: str | None = None) -> str:
    """Convert and abbreviate path for display.

    Makes paths more readable by abbreviating home directory and base dir.

    Args:
        path: Full path to abbreviate.
        base_dir: Optional base directory to abbreviate.

    Returns:
        Abbreviated path suitable for display.
    """
    if not path:
        return path

    # Convert to Path object
    p = Path(path)

    # Try to abbreviate relative to home
    home = Path.home()
    try:
        if p.is_absolute() and str(p).startswith(str(home)):
            abbrev = "~" + str(p.relative_to(home))
            return abbrev
    except ValueError:
        pass

    # Try to abbreviate relative to base_dir
    if base_dir:
        try:
            base = Path(base_dir)
            if str(p).startswith(str(base)):
                abbrev = "." + str(p.relative_to(base))
                return abbrev
        except ValueError:
            pass

    # Return original if no abbreviation possible
    return str(p)


def parse_autopilot_goals(text: str) -> list[str]:
    """Parse autopilot goals from text.

    Extracts goal statements from autopilot input text.

    Args:
        text: Text containing goal definitions.

    Returns:
        List of parsed goal strings.
    """
    # Pattern for goals like "Goal: ..." or numbered goals
    goal_pattern = re.compile(r"^(?:Goal\s*:\s*|\d+\.\s*)(.+)$", re.MULTILINE)
    matches = goal_pattern.findall(text)

    # If no explicit goal markers, treat each line as a goal
    if not matches:
        goals = [line.strip() for line in text.split("\n") if line.strip()]
        return goals

    return [goal.strip() for goal in matches]


def get_tool_display_name(tool_name: str) -> str:
    """Get user-friendly display name for tool.

    Maps internal tool names to readable display names.

    Args:
        tool_name: Internal tool name.

    Returns:
        User-friendly display name.
    """
    # Tool name mapping
    display_names = {
        "execute": "Shell Execute",
        "ls": "List Files",
        "read_file": "Read File",
        "write_file": "Write File",
        "edit_file": "Edit File",
        "glob": "Search Files",
        "grep": "Search Content",
        "web_search": "Web Search",
        "tavily_search": "Web Search (Tavily)",
        "research": "Research",
    }

    # Return mapped name or original if no mapping
    return display_names.get(tool_name, tool_name.replace("_", " ").title())


# Task name regex pattern for plan step matching
_TASK_NAME_RE = re.compile(r"^\s*(?:Task\s*:\s*|Step\s*:\s*)(.+)$", re.MULTILINE)

"""Regex pattern for matching task/step names in plan text."""


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values.

    Args:
        value: Raw value possibly containing ``${VAR}`` placeholder.

    Returns:
        Resolved value with env var substituted, or original if not a pattern.
    """
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


def resolve_provider_env(value: str, *, provider_name: str, field_name: str) -> str | None:
    """Resolve provider field env placeholders and warn if missing.

    Args:
        value: Raw configured field value (e.g., ``${OPENAI_API_KEY}``).
        provider_name: Provider name (for warning messages).
        field_name: Field name on provider config.

    Returns:
        Resolved value, or None if the env var could not be resolved.
    """
    resolved = _resolve_env(value)
    m = _ENV_VAR_RE.match(resolved)
    if m:
        env_name = m.group(1)
        _logger.warning(
            "Provider '%s' has unresolved env var '%s' in "
            "providers[].%s. Set %s or replace it with a literal value. "
            "Skipping provider configuration.",
            provider_name,
            env_name,
            field_name,
            env_name,
        )
        return None
    return resolved


is_path_argument = re.compile(r"^(file_path|path|directory|dir|folder|cwd)\b", re.IGNORECASE)
"""Regex for detecting path-like argument names in tool calls."""

__all__ = [
    "strip_internal_tags",
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "parse_autopilot_goals",
    "get_tool_display_name",
    "_TASK_NAME_RE",
    "resolve_provider_env",
    "is_path_argument",
]
