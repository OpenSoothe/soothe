"""Model configuration utilities for TUI (adapted from Soothe).

This module provides TUI-specific configuration utilities that bridge between
SootheConfig and TUI preferences. Note: This is a minimal stub to enable TUI
functionality - full migration needed in future.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)

# Default config path for Soothe
DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"

# Environment variable prefix (Soothe uses SOOTHE_ instead of DEEPAGENTS_)
_ENV_PREFIX = "SOOTHE_"


# Model configuration error (stub for now)
class ModelConfigError(Exception):
    """Error in model configuration."""

    pass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Parsed ``provider:model`` specification for TUI helpers."""

    provider: str
    model: str

    @classmethod
    def try_parse(cls, model_spec: str) -> ModelSpec | None:
        """Parse explicit ``provider:model`` when both parts are non-empty."""
        if not model_spec or ":" not in model_spec:
            return None
        prov, _, rest = model_spec.partition(":")
        prov = prov.strip()
        mod = rest.strip()
        if not prov or not mod:
            return None
        return cls(provider=prov, model=mod)


def _load_soothe_config() -> Any:
    """Load ``SootheConfig`` using the same path rules as the CLI/daemon."""
    try:
        from soothe.ux.shared.config_loader import load_config

        return load_config(None)
    except Exception:
        logger.debug("Could not load SootheConfig for TUI model helpers", exc_info=True)
        return None


class ModelConfig:
    """TUI-facing view over ``SootheConfig`` providers and router (``config.yml``)."""

    @classmethod
    def load(cls) -> ModelConfig:
        """Load from ``SootheConfig`` (cached via ``load_config``)."""
        return cls(_cfg=_load_soothe_config())

    def __init__(self, *, _cfg: Any = None) -> None:
        """Initialize from an optional pre-loaded ``SootheConfig``."""
        self._cfg = _cfg
        self.default_model: str | None = None
        self.recent_model: str | None = None
        if _cfg is not None:
            try:
                self.default_model = _cfg.resolve_model("default")
            except Exception:
                logger.debug("Could not resolve default model from SootheConfig", exc_info=True)
                self.default_model = None

    def get_kwargs(self, provider: str, model_name: str | None = None) -> dict[str, Any]:
        """Return kwargs for ``init_chat_model`` for this provider (from ``SootheConfig``)."""
        if not self._cfg or not provider:
            return {}
        try:
            _, kwargs = self._cfg._provider_kwargs(provider)  # noqa: SLF001
        except Exception:
            logger.debug("provider_kwargs failed for %r", provider, exc_info=True)
            return {}
        return dict(kwargs)

    def get_base_url(self, provider: str) -> str | None:
        """Resolved ``api_base_url`` for the named provider, if any."""
        if not self._cfg or not provider:
            return None
        p = self._cfg._find_provider(provider)  # noqa: SLF001
        if not p or not p.api_base_url:
            return None
        try:
            from soothe.config.env import _resolve_provider_env

            resolved = _resolve_provider_env(
                p.api_base_url,
                provider_name=p.name,
                field_name="api_base_url",
            )
        except Exception:
            logger.debug("Could not resolve api_base_url for %r", provider, exc_info=True)
            return None
        return str(resolved).strip() or None

    def get_api_key_env(self, provider: str) -> str | None:
        """Infer env var name from provider ``api_key`` or fall back to static map."""
        if self._cfg and provider:
            p = self._cfg._find_provider(provider)  # noqa: SLF001
            if p and p.api_key:
                m = re.match(r"^\$\{([^}]+)\}\s*$", str(p.api_key).strip())
                if m:
                    return m.group(1)
        return PROVIDER_API_KEY_ENV.get(provider)

    def get_class_path(self, provider: str) -> str | None:
        """Optional custom ``BaseChatModel`` import path (not used in Soothe YAML today)."""
        return None

    def get_profile_overrides(self, provider: str, model_name: str | None = None) -> dict[str, Any]:
        """Profile overrides from config for the given provider/model."""
        return {}


def resolve_env_var(var_name: str) -> str:
    """Resolve environment variable with SOOTHE_ prefix support.

    This function handles two scenarios:
    1. Direct env var lookup: resolve_env_var("LANGSMITH_API_KEY")
       - First checks SOOTHE_LANGSMITH_API_KEY
       - Falls back to LANGSMITH_API_KEY
    2. Pattern resolution: resolve_env_var("${LANGSMITH_API_KEY}")
       - Resolves ${VAR} patterns within strings

    Args:
        var_name: Environment variable name (e.g., "LANGSMITH_API_KEY")
                  or pattern string (e.g., "${LANGSMITH_API_KEY}")

    Returns:
        Resolved value from environment, or empty string if not found.
    """
    import os
    import re

    # Case 1: Pattern resolution (${VAR} syntax)
    pattern = r"\$\{([^}]+)\}"
    if re.search(pattern, var_name):

        def replace_env_var(match):
            env_var = match.group(1)
            # Try SOOTHE_ prefix first, then canonical
            prefixed = f"{_ENV_PREFIX}{env_var}"
            if prefixed in os.environ:
                return os.environ[prefixed]
            if env_var in os.environ:
                return os.environ[env_var]
            # Keep original pattern if not found
            return match.group(0)

        return re.sub(pattern, replace_env_var, var_name)

    # Case 2: Direct env var lookup (no ${...} pattern)
    # Try SOOTHE_ prefix first, then canonical name
    prefixed = f"{_ENV_PREFIX}{var_name}"
    if prefixed in os.environ:
        return os.environ[prefixed]
    return os.getenv(var_name, "")


# Provider API key environment variables mapping
PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google": "GOOGLE_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "COHERE_API_KEY",
}

# Providers where a single API-key env var is not a reliable auth signal
# (ADC, local runtime, etc.) — matches early-credential skip in ``create_model``.
IMPLICIT_AUTH_PROVIDERS: frozenset[str] = frozenset(
    {
        "google_vertexai",
        "ollama",
    }
)


def get_credential_env_var(provider: str) -> str | None:
    """Return the primary API-key env var name for ``provider``, if known."""
    cfg = _load_soothe_config()
    if cfg is not None and provider:
        p = cfg._find_provider(provider)  # noqa: SLF001
        if p and p.api_key:
            m = re.match(r"^\$\{([^}]+)\}\s*$", str(p.api_key).strip())
            if m:
                return m.group(1)
    return PROVIDER_API_KEY_ENV.get(provider)


# Stub functions for thread config (TUI preferences)
# These should be migrated to use SootheConfig properly


def load_thread_config(thread_id: str | None = None) -> dict:
    """Load thread-specific TUI preferences.

    Stub implementation - returns empty dict.
    Full implementation should use SootheConfig's persistence.

    Args:
        thread_id: Thread identifier. Can be None for default config.

    Returns:
        Thread configuration dictionary.
    """
    return {}


def save_thread_relative_time(thread_id: str, relative_time: str) -> None:
    """Save thread's relative time display preference.

    Args:
        thread_id: Thread identifier.
        relative_time: Relative time format.
    """
    # Stub - implement with SootheConfig persistence
    pass


def save_thread_columns(thread_id: str, columns: list) -> None:
    """Save thread's column display preferences.

    Args:
        thread_id: Thread identifier.
        columns: Column configuration list.
    """
    # Stub - implement with SootheConfig persistence
    pass


def save_thread_sort_order(sort_order: str) -> None:
    """Save thread list sort order preference.

    Args:
        sort_order: Sort order specification.
    """
    # Stub - implement with SootheConfig persistence
    pass


def load_thread_sort_order() -> str:
    """Return persisted thread list sort key (stub: most recently updated first)."""
    return "updated_at"


def load_thread_relative_time() -> bool:
    """Return whether thread list uses relative timestamps (stub: on)."""
    return True


def suppress_warning(warning_type: str) -> bool:
    """Persist suppressed notification preference (stub: no-op success)."""
    return True


def unsuppress_warning(warning_type: str) -> bool:
    """Clear suppressed notification preference (stub: no-op success)."""
    return True


def save_default_model(model_spec: ModelSpec) -> None:
    """Save default model preference.

    Args:
        model_spec: Model specification to save as default.
    """
    # Stub - should integrate with SootheConfig providers mapping
    pass


def save_recent_model(model_spec: ModelSpec) -> None:
    """Save model to recent models list.

    Args:
        model_spec: Model specification to add to recent models.
    """
    # Stub - should maintain recent models list in SootheConfig
    pass


def clear_default_model() -> None:
    """Clear saved default model preference."""
    # Stub
    pass


def clear_caches() -> None:
    """Clear cached ``SootheConfig`` so the next ``ModelConfig.load()`` re-reads disk."""
    try:
        import soothe.ux.shared.config_loader as _cl

        _cl._config_cache.clear()
    except Exception:
        logger.debug("Could not clear config_loader cache", exc_info=True)


def is_warning_suppressed(warning_type: str) -> bool:
    """Check if a warning type is suppressed in user preferences.

    Args:
        warning_type: Warning type identifier.

    Returns:
        True if warning should be suppressed.
    """
    # Stub - should check SootheConfig user preferences
    return False


# Additional stub classes and functions for model_selector compatibility


class ModelProfileEntry:
    """Stub for model profile entry - used in model selector.

    Full implementation should integrate with SootheConfig's provider profiles.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        display_name: str | None = None,
        description: str | None = None,
        context_limit: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.provider = provider
        self.model = model
        self.display_name = display_name or f"{provider}:{model}"
        self.description = description or ""
        self.context_limit = context_limit
        self.kwargs = kwargs


def get_available_models() -> list[ModelProfileEntry]:
    """List models declared on ``SootheConfig.providers`` (for ``/model`` UI)."""
    cfg = _load_soothe_config()
    if not cfg or not cfg.providers:
        return []
    out: list[ModelProfileEntry] = []
    for p in cfg.providers:
        if p.models:
            for m in p.models:
                out.append(ModelProfileEntry(p.name, m))
        else:
            out.append(
                ModelProfileEntry(
                    p.name,
                    "",
                    display_name=f"{p.name} ({p.provider_type})",
                    description="Configure models: list under this provider in config.yml",
                )
            )
    return out


def get_model_profiles(cli_override: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Map ``provider:model`` keys to footer-shaped profile rows (minimal until YAML profiles exist).

    Args:
        cli_override: Reserved for CLI profile merge (unused in minimal catalog).

    Returns:
        Mapping of spec string to ``{"profile": {...}, "overridden_keys": set()}``.
    """
    del cli_override  # reserved for future profile merge from CLI flags
    profiles: dict[str, dict[str, Any]] = {}
    for entry in get_available_models():
        if not entry.model:
            continue
        key = f"{entry.provider}:{entry.model}"
        profiles[key] = {"profile": {}, "overridden_keys": set()}
    return profiles


def has_provider_credentials(provider: str) -> bool | None:
    """Check credentials using ``SootheConfig`` providers when available."""
    if not provider:
        return None
    if provider in IMPLICIT_AUTH_PROVIDERS:
        if provider == "google_vertexai":
            proj = resolve_env_var("GOOGLE_CLOUD_PROJECT")
            return bool(proj and proj.strip())
        return None

    cfg = _load_soothe_config()
    if cfg is not None:
        p = cfg._find_provider(provider)  # noqa: SLF001
        if p is not None:
            if p.provider_type in IMPLICIT_AUTH_PROVIDERS or p.provider_type == "ollama":
                return None
            if p.api_key:
                try:
                    from soothe.config.env import _resolve_provider_env

                    v = _resolve_provider_env(p.api_key, provider_name=p.name, field_name="api_key")
                except Exception:
                    logger.debug("resolve api_key failed for provider %r", provider, exc_info=True)
                    return None
                return bool(v and str(v).strip())
            return False

    env_name = PROVIDER_API_KEY_ENV.get(provider)
    if not env_name:
        return None
    val = resolve_env_var(env_name)
    return bool(val and val.strip())
