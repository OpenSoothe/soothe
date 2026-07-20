"""Provider configuration lookup and credential resolution.

ProviderRegistry holds provider configs from SootheConfig and provides:
- Provider lookup by name
- Provider type detection (mapping config string to ProviderType enum)
- Credential resolution with ${ENV_VAR} expansion for init_chat_model kwargs
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_nano.config.env import _resolve_provider_env
from soothe_nano.config.models import ModelProviderConfig
from soothe_nano.utils.llm.types import ProviderType

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Provider configuration lookup and type detection.

    Holds provider configs and resolves credentials with ``${ENV_VAR}`` expansion.
    Used by LLMFactory to determine wrapper chain and build ``init_chat_model`` kwargs.

    Args:
        providers: List of ``ModelProviderConfig`` from ``SootheConfig.providers``.
    """

    def __init__(self, providers: list[ModelProviderConfig]) -> None:
        """Initialize registry with provider configs.

        Args:
            providers: List of ModelProviderConfig from SootheConfig.
        """
        self._providers: dict[str, ModelProviderConfig] = {p.name: p for p in providers}

    def get_provider(self, name: str) -> ModelProviderConfig | None:
        """Lookup provider config by name.

        Args:
            name: Provider name from config.

        Returns:
            Provider config or None if not found.
        """
        return self._providers.get(name)

    def resolve_provider_type(self, name: str) -> ProviderType:
        """Detect provider type from config.

        Args:
            name: Provider name from config.

        Returns:
            ProviderType enum. Returns ``CUSTOM`` if provider not found or type unknown.
        """
        provider = self.get_provider(name)
        if provider is None:
            return ProviderType.CUSTOM
        type_str = provider.provider_type
        try:
            return ProviderType(type_str)
        except ValueError:
            logger.warning(
                "Unknown provider_type '%s' for provider '%s', treating as CUSTOM",
                type_str,
                name,
            )
            return ProviderType.CUSTOM

    @staticmethod
    def _is_standard_openai_endpoint(api_base_url: str | None) -> bool:
        """Return True when the URL is unset or points at the official OpenAI API."""
        if not api_base_url:
            return True
        normalized = api_base_url.rstrip("/")
        return normalized.startswith("https://api.openai.com")

    def requires_openai_compat_wrapper(self, name: str) -> bool:
        """Whether to apply ``OpenAICompatModelWrapper`` for this provider.

        Local OpenAI-compatible servers (oMLX, LMStudio, vLLM) often return
        structured output in ``reasoning_content`` and reject object-form
        ``tool_choice``. We auto-detect them via ``provider_type: openai`` plus
        a non-standard ``api_base_url``.

        Args:
            name: Provider name from config.

        Returns:
            True when compatibility wrappers should be applied.
        """
        provider = self.get_provider(name)
        if provider is None or provider.provider_type != "openai":
            return False

        if not provider.api_base_url:
            return False

        resolved = _resolve_provider_env(
            provider.api_base_url,
            provider_name=provider.name,
            field_name="api_base_url",
        )
        if not resolved:
            return False

        return not self._is_standard_openai_endpoint(resolved)

    def get_provider_kwargs(self, name: str) -> tuple[str, dict[str, Any]]:
        """Build ``init_chat_model`` kwargs for a provider.

        Resolves ``${ENV_VAR}`` in ``api_base_url`` and ``api_key``.

        Args:
            name: Provider name from config.

        Returns:
            Tuple of ``(provider_type_for_langchain, kwargs_dict)``.
            ``kwargs_dict`` contains ``base_url``, ``api_key``, ``use_responses_api=False``
            if custom ``base_url`` is set.
        """
        provider = self.get_provider(name)
        kwargs: dict[str, Any] = {}
        provider_type_str = name  # Default to provider name for unknown providers

        if provider:
            provider_type_str = provider.provider_type
            actual_type = provider_type_str

            if provider.api_base_url:
                resolved = _resolve_provider_env(
                    provider.api_base_url,
                    provider_name=provider.name,
                    field_name="api_base_url",
                )
                if resolved:
                    kwargs["base_url"] = resolved
                    # Disable responses API for custom OpenAI-compatible endpoints
                    if actual_type == "openai":
                        kwargs["use_responses_api"] = False

            if provider.api_key:
                resolved = _resolve_provider_env(
                    provider.api_key,
                    provider_name=provider.name,
                    field_name="api_key",
                )
                if resolved:
                    kwargs["api_key"] = resolved

            return actual_type, kwargs

        return provider_type_str, kwargs


__all__ = [
    "ProviderRegistry",
]
