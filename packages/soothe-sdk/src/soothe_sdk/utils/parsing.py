"""Parsing utilities for goal and plan text processing.

Utility functions for parsing goals, plans, and other text-based structures
used by both daemon and CLI.

Part of RFC-610 SDK module structure refactoring (IG-185).
"""

import logging
import os
import re

_logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")


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


# Task name regex pattern for plan step matching
_TASK_NAME_RE = re.compile(r"^\s*(?:Task\s*:\s*|Step\s*:\s*)(.+)$", re.MULTILINE)

"""Regex pattern for matching task/step names in plan text."""


def _resolve_env(value: str) -> str:
    """Resolve `${ENV_VAR}` references in config values.

    Args:
        value: Raw value possibly containing `${VAR}` placeholder.

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
        value: Raw configured field value (e.g., `${OPENAI_API_KEY}`).
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


PATH_ARG_PATTERN = re.compile(r"^(file_path|path|directory|dir|folder|cwd)\b", re.IGNORECASE)
"""Regex pattern for detecting path-like argument names in tool calls.

Renamed from is_path_argument in IG-XXX (SDK refactoring).
The original name was misleading - this is a pattern, not a function.
"""


__all__ = [
    "parse_autopilot_goals",
    "_TASK_NAME_RE",
    "resolve_provider_env",
    "PATH_ARG_PATTERN",
]
