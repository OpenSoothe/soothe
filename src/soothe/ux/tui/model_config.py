"""Model configuration utilities for TUI (adapted from Soothe).

This module provides TUI-specific configuration utilities that bridge between
SootheConfig and TUI preferences. Note: This is a minimal stub to enable TUI
functionality - full migration needed in future.
"""

from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

# Default config path for Soothe
DEFAULT_CONFIG_PATH = Path(SOOTHE_HOME) / "config" / "config.yml"

# Environment variable prefix (Soothe uses SOOTHE_ instead of DEEPAGENTS_)
_ENV_PREFIX = "SOOTHE_"


# Model configuration error (stub for now)
class ModelConfigError(Exception):
    """Error in model configuration."""

    pass


# ModelSpec stub - Soothe uses different model resolution
class ModelSpec:
    """Stub for model specification - Soothe uses provider:model format."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model


class ModelConfig:
    """Stub for model configuration - Soothe uses SootheConfig instead.

    This class provides stub methods for compatibility with Soothe TUI code.
    Full implementation should integrate with SootheConfig properly.
    """

    @classmethod
    def load(cls) -> "ModelConfig":
        """Load model configuration.

        Stub - returns instance with defaults.
        Full implementation should load from SootheConfig.

        Returns:
            ModelConfig instance.
        """
        return cls()

    def __init__(self) -> None:
        """Initialize with default values."""
        self.default_model: str | None = None
        self.recent_model: str | None = None

    def get_kwargs(self, provider: str, model_name: str | None = None) -> dict[str, Any]:
        """Get provider-specific kwargs.

        Stub - returns empty dict.
        Full implementation should return provider-specific configuration.

        Args:
            provider: Provider name (e.g., 'openai', 'anthropic').
            model_name: Optional model name for per-model overrides.

        Returns:
            Dictionary of provider kwargs.
        """
        return {}

    def get_base_url(self, provider: str) -> str | None:
        """Get base URL for provider.

        Stub - returns None.
        Full implementation should return custom base URL if configured.

        Args:
            provider: Provider name.

        Returns:
            Base URL or None.
        """
        return None

    def get_api_key_env(self, provider: str) -> str | None:
        """Get API key environment variable name for provider.

        Stub - returns None.
        Full implementation should return configured env var name.

        Args:
            provider: Provider name.

        Returns:
            Environment variable name or None.
        """
        return None


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
}


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
    """Clear all configuration caches."""
    # Stub - integrate with config_loader cache clearing
    pass


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
    """Get list of available models from configured providers.

    Stub - returns empty list.
    Full implementation should query SootheConfig providers.

    Returns:
        List of ModelProfileEntry instances.
    """
    return []


def get_model_profiles(cli_override: str | None = None) -> dict[str, ModelProfileEntry]:
    """Get dictionary of model profiles.

    Stub - returns empty dict.
    Full implementation should load profiles from SootheConfig.

    Args:
        cli_override: Optional CLI override parameter (ignored in stub).

    Returns:
        Dictionary mapping model keys to ModelProfileEntry.
    """
    return {}


def has_provider_credentials(provider: str) -> bool:
    """Check if provider has credentials configured.

    Stub - returns False.
    Full implementation should check SootheConfig for API keys.

    Args:
        provider: Provider name to check.

    Returns:
        True if provider has credentials.
    """
    return False
