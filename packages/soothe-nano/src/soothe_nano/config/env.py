"""Environment variable resolution and home directory for Soothe."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

SOOTHE_HOME: Path = Path(os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))).expanduser()
"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""

# Matches ${VAR_NAME} anywhere in a string (not anchored)
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

_logger = logging.getLogger(__name__)


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values.

    Supports env vars anywhere in the string, including:
    - Exact match: ``${HOME}`` → ``/Users/alice``
    - Embedded: ``${HOME}/workspaces`` → ``/Users/alice/workspaces``
    - Multiple: ``${VAR1}/${VAR2}`` → ``value1/value2``
    - Unresolved vars are left as-is (e.g., ``${MISSING_VAR}`` stays unchanged).

    Args:
        value: String potentially containing ``${ENV_VAR}`` placeholders.

    Returns:
        String with all resolvable env vars substituted.
    """

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is not None:
            return resolved
        # Leave unresolved placeholder intact
        return match.group(0)

    return _ENV_VAR_RE.sub(replacer, value)


def _expand_env_in_config(
    config: dict[str, Any] | list[Any] | str | Any,
) -> dict[str, Any] | list[Any] | str | Any:
    """Recursively expand ``${ENV_VAR}`` placeholders throughout config tree.

    Walks through dicts, lists, and strings, applying ``_resolve_env`` to all
    string values. Non-string values (ints, booleans, None) are left unchanged.

    Args:
        config: Configuration value (dict, list, string, or scalar).

    Returns:
        Configuration with all string env placeholders resolved.
    """
    if isinstance(config, dict):
        return {k: _expand_env_in_config(v) for k, v in config.items()}
    if isinstance(config, list):
        return [_expand_env_in_config(item) for item in config]
    if isinstance(config, str):
        return _resolve_env(config)
    # Scalars (int, bool, None, etc.) pass through unchanged
    return config


def _resolve_provider_env(value: str, *, provider_name: str, field_name: str) -> str | None:
    """Resolve provider field env placeholders and warn if missing.

    Args:
        value: Raw configured field value.
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
