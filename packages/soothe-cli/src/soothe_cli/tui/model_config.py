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

from soothe_sdk.client.config import SOOTHE_HOME

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


async def _fetch_provider_config(provider_name: str) -> dict[str, Any] | None:
    """Fetch provider config from daemon via WebSocket RPC.

    Args:
        provider_name: Provider name to fetch.

    Returns:
        Provider config dict or None if not found.
    """
    try:
        from soothe_sdk.client import WebSocketClient, fetch_config_section

        from soothe_cli.config.cli_config import CLIConfig

        cli_cfg = CLIConfig.from_config_file()
        ws_url = cli_cfg.websocket_url()

        client = WebSocketClient(url=ws_url)
        await client.connect()
        try:
            providers_data = await fetch_config_section(client, "providers", timeout=5.0)
            return providers_data.get(provider_name)
        finally:
            await client.close()
    except Exception:
        logger.debug("Could not fetch provider config from daemon", exc_info=True)
        return None


class ModelConfig:
    """TUI-facing view over daemon config providers and router.

    Per IG-174/IG-175 architectural separation, this class is transitioning to
    fetch config from daemon via WebSocket RPC instead of local SootheConfig.
    Currently in transition period - gracefully degrades when daemon not reachable.
    """

    @classmethod
    def load(cls) -> ModelConfig:
        """Load config from daemon (TODO: IG-175 Phase 2).

        During transition, returns empty instance when daemon not reachable.
        Full implementation will fetch defaults/providers from daemon RPC.
        """
        # TODO(IG-175): Replace with async daemon RPC fetch
        # Currently returns empty instance for graceful degradation
        logger.debug("ModelConfig.load() returning empty instance during IG-175 transition")
        return cls(_cfg=None)

    def __init__(self, *, _cfg: Any = None) -> None:
        """Initialize from an optional pre-loaded config.

        Args:
            _cfg: Config instance (None during IG-175 transition).
        """
        self._cfg = _cfg
        self.default_model: str | None = None
        self.recent_model: str | None = None
        # TODO(IG-175): Fetch default model from daemon RPC

    def get_kwargs(self, provider: str, model_name: str | None = None) -> dict[str, Any]:
        """Return kwargs for ``init_chat_model`` for this provider.

        TODO(IG-175): Fetch from daemon RPC.
        Currently returns empty dict during transition.
        """
        if not provider:
            return {}
        # TODO(IG-175): Implement daemon RPC fetch
        logger.debug("get_kwargs returning empty dict during IG-175 transition")
        return {}

    def get_base_url(self, provider: str) -> str | None:
        """Resolved ``api_base_url`` for the named provider.

        TODO(IG-175): Fetch from daemon RPC.
        Currently returns None during transition.
        """
        if not provider:
            return None
        # TODO(IG-175): Implement daemon RPC fetch
        logger.debug("get_base_url returning None during IG-175 transition")
        return None

    def get_api_key_env(self, provider: str) -> str | None:
        """Infer env var name from provider ``api_key``.

        TODO(IG-175): Fetch from daemon RPC.
        Currently falls back to static map during transition.
        """
        if not provider:
            return None
        # TODO(IG-175): Implement daemon RPC fetch
        # Fallback to static map during transition
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
    """Return the primary API-key env var name for ``provider``, if known.

    Per IG-174, fetches provider config from daemon via RPC.
    Falls back to hardcoded env var mapping if daemon not reachable.
    """
    if provider:
        # Try to fetch from daemon
        try:
            import asyncio

            provider_data = asyncio.run(_fetch_provider_config(provider))
            if provider_data and provider_data.get("api_key"):
                api_key = provider_data["api_key"]
                # Extract env var from ${ENV_VAR} syntax
                m = re.match(r"^\$\{([^}]+)\}\s*$", str(api_key).strip())
                if m:
                    return m.group(1)
        except Exception:
            logger.debug("Could not fetch provider config from daemon", exc_info=True)

    # Fallback to hardcoded mapping
    return PROVIDER_API_KEY_ENV.get(provider)


# Thread configuration for TUI preferences


@dataclass(frozen=True, slots=True)
class ThreadConfig:
    """Thread list display preferences for TUI.

    Attributes:
        columns: Column visibility settings keyed by column name.
        relative_time: Whether to show relative timestamps.
        sort_order: Sort order for thread list ("updated_at" or "created_at").
    """

    columns: dict[str, bool]
    relative_time: bool
    sort_order: str


# Default column visibility (all columns visible by default)
_DEFAULT_COLUMNS = {
    "thread_id": True,
    "agent_name": True,
    "messages": True,
    "created_at": True,
    "updated_at": True,
    "git_branch": True,
    "cwd": True,
    "initial_prompt": True,
}


def load_thread_config(thread_id: str | None = None) -> ThreadConfig:
    """Load thread-specific TUI preferences.

    Stub implementation - returns default configuration.
    Full implementation should use SootheConfig's persistence.

    Args:
        thread_id: Thread identifier. Can be None for default config.

    Returns:
        Thread configuration object.
    """
    # Use existing stub functions for defaults
    return ThreadConfig(
        columns=dict(_DEFAULT_COLUMNS),
        relative_time=load_thread_relative_time(),
        sort_order=load_thread_sort_order(),
    )


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
        import soothe_cli.shared.config_loader as _cl

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
    """List models declared on daemon config (for ``/model`` UI).

    Per IG-174 architectural separation, CLI fetches providers from daemon via RPC.
    Returns empty list if daemon not reachable.
    """
    try:
        import asyncio

        from soothe_sdk.client import WebSocketClient, fetch_config_section

        # Use CLIConfig to get WebSocket URL
        from soothe_cli.config.cli_config import CLIConfig

        cli_cfg = CLIConfig.from_config_file()
        ws_url = cli_cfg.websocket_url()

        # Fetch providers section from daemon
        client = WebSocketClient(url=ws_url)

        async def _fetch_providers() -> dict:
            await client.connect()
            try:
                return await fetch_config_section(client, "providers", timeout=5.0)
            finally:
                await client.close()

        providers_data = asyncio.run(_fetch_providers())

        if not providers_data:
            return []

        out: list[ModelProfileEntry] = []
        for p_name, p_data in providers_data.items():
            models = p_data.get("models", [])
            if models:
                for m in models:
                    out.append(ModelProfileEntry(p_name, m))
            else:
                provider_type = p_data.get("provider_type", "unknown")
                out.append(
                    ModelProfileEntry(
                        p_name,
                        "",
                        display_name=f"{p_name} ({provider_type})",
                        description="Configure models: list under this provider in config.yml",
                    )
                )
        return out
    except Exception:
        logger.debug("Could not fetch providers from daemon", exc_info=True)
        return []


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
    """Check credentials using daemon config when available.

    Per IG-174, fetches provider config from daemon via RPC.
    Falls back to environment variables if daemon not reachable.
    """
    if not provider:
        return None
    if provider in IMPLICIT_AUTH_PROVIDERS:
        if provider == "google_vertexai":
            proj = resolve_env_var("GOOGLE_CLOUD_PROJECT")
            return bool(proj and proj.strip())
        return None

    # Try to fetch from daemon
    try:
        import asyncio

        provider_data = asyncio.run(_fetch_provider_config(provider))
        if provider_data is not None:
            provider_type = provider_data.get("provider_type", "")
            if provider_type in IMPLICIT_AUTH_PROVIDERS or provider_type == "ollama":
                return None
            if provider_data.get("api_key"):
                try:
                    from soothe_sdk.utils import resolve_provider_env

                    v = resolve_provider_env(
                        provider_data["api_key"], provider_name=provider, field_name="api_key"
                    )
                except Exception:
                    logger.debug("resolve api_key failed for provider %r", provider, exc_info=True)
                    return None
                return bool(v and str(v).strip())
            return False
    except Exception:
        logger.debug("Could not fetch provider config from daemon", exc_info=True)

    # Fallback to environment variable check
    env_name = PROVIDER_API_KEY_ENV.get(provider)
    if not env_name:
        return None
    val = resolve_env_var(env_name)
    return bool(val and val.strip())
