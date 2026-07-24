"""Host aliases for shared environment resolution helpers.

Thin re-export wrapper — canonical implementations live in
``soothe_nano.config.env``.  Do not duplicate or modify the
re-exported symbols here; fix them in nano.
"""

# Re-export facade — canonical source: soothe_nano.config.env
from soothe_nano.config.env import (
    _ENV_VAR_RE,
    SOOTHE_HOME,
    _expand_env_in_config,
    _resolve_env,
    _resolve_provider_env,
)

__all__ = [
    "SOOTHE_HOME",
    "_ENV_VAR_RE",
    "_expand_env_in_config",
    "_resolve_env",
    "_resolve_provider_env",
]
