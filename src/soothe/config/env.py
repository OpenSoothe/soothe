"""Environment variable resolution and home directory for Soothe."""

from __future__ import annotations

import os
import re
from pathlib import Path

SOOTHE_HOME: str = os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))
"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""

_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values."""
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


def _resolve_provider_env(value: str, *, provider_name: str, field_name: str) -> str:
    """Resolve provider field env placeholders and fail fast if missing.

    Args:
        value: Raw configured field value.
        provider_name: Provider name (for error messages).
        field_name: Field name on provider config.

    Returns:
        Resolved value.

    Raises:
        ValueError: If the value is a ``${ENV_VAR}`` placeholder that could not
            be resolved from the environment.
    """
    resolved = _resolve_env(value)
    m = _ENV_VAR_RE.match(resolved)
    if m:
        env_name = m.group(1)
        msg = (
            f"Provider '{provider_name}' has unresolved env var '{env_name}' in "
            f"providers[].{field_name}. Set {env_name} or replace it with a literal value."
        )
        raise ValueError(msg)
    return resolved
