"""Environment variable resolution and home directory for Soothe."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

SOOTHE_HOME: Path = Path(os.environ.get("SOOTHE_HOME", str(Path.home() / ".soothe"))).expanduser()
"""Default Soothe home directory. Overridable via ``SOOTHE_HOME`` env var."""


def default_soothe_workspace_dir() -> str:
    """Default install workspace directory (``$SOOTHE_HOME/Workspace``).

    Used for ``SootheConfig.workspace_dir`` and daemon resolution when no
    explicit path is configured (IG-327).

    Returns:
        Absolute path string (not necessarily created on disk yet).
    """
    # Tests patch ``SOOTHE_HOME`` to ``str`` via monkeypatch; normalize to Path.
    return str(Path(SOOTHE_HOME).expanduser() / "Workspace")


_ENV_VAR_RE = re.compile(r"^\$\{(\w+)\}$")

_logger = logging.getLogger(__name__)


def _resolve_env(value: str) -> str:
    """Resolve ``${ENV_VAR}`` references in config values."""
    m = _ENV_VAR_RE.match(value)
    if m:
        return os.environ.get(m.group(1), value)
    return value


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
