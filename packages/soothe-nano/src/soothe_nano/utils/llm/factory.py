"""LLM factory with automatic provider adaptation.

LLMFactory decouples model instantiation from SootheConfig, providing:
- Model caching by spec + params
- Automatic wrapper chain based on provider type
- Thread-safe concurrent access
- Embedding model creation with DashScope special handling

Usage:
    factory = LLMFactory(config)
    model = factory.create_chat_model("default")
    model = factory.create_chat_model_for_spec("anthropic:claude-sonnet-4-5")
"""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from soothe_nano.utils.llm.observability import SootheTokenUsageChatModel
from soothe_nano.utils.llm.registry import ProviderRegistry
from soothe_nano.utils.llm.types import ModelRole, ProviderType
from soothe_nano.utils.llm.wrappers import OpenAICompatModelWrapper

if TYPE_CHECKING:
    from soothe_nano.config.settings import SootheConfig

logger = logging.getLogger(__name__)

_model_cache_lock = threading.Lock()


class LLMFactory:
    """Model creation with automatic provider adaptation.

    Decouples model instantiation from SootheConfig, providing:
    - Model caching by spec + params (thread-safe)
    - Automatic wrapper chain based on provider type
    - Embedding model creation with DashScope special handling

    Args:
        config: SootheConfig instance holding providers, router, embedding model, and dims.
    """

    def __init__(self, config: SootheConfig) -> None:
        """Initialize factory with config reference.

        Args:
            config: SootheConfig instance (typed as Any to avoid circular import).
        """
        self._config = config
        self._registry = ProviderRegistry(config.providers)
        self._cache: dict[str, BaseChatModel] = {}
        self._embedding_cache: dict[str, Embeddings] = {}

    def resolve_model(self, role: ModelRole = "default") -> str:
        """Resolve model spec for a role via config router.

        Args:
            role: Purpose role (default, fast, think, image, embedding).

        Returns:
            provider:model string.
        """
        return self._config.resolve_model(role)

    def create_chat_model(
        self,
        role: ModelRole = "default",
        *,
        fallback_role: ModelRole | None = None,
    ) -> BaseChatModel:
        """Create model for router role with caching and wrappers.

        When ``fallback_role`` is omitted and ``role`` is not ``default``, a failed
        resolve or instantiation for ``role`` retries ``default`` if that maps to a
        different ``provider:model`` spec.

        Args:
            role: Purpose role.
            fallback_role: Optional fallback role after primary failure. ``None``
                enables automatic ``default`` fallback for non-``default`` roles.

        Returns:
            Wrapped BaseChatModel instance.

        Raises:
            Exception: Re-raises the primary error when fallback is disabled,
                specs are identical, or the fallback attempt also fails.
        """
        effective_fallback = fallback_role
        if effective_fallback is None and role != "default":
            effective_fallback = "default"

        primary_spec = self.resolve_model(role)
        try:
            return self._create_from_spec(primary_spec, {})
        except Exception:
            if not effective_fallback or effective_fallback == role:
                raise
            fallback_spec = self.resolve_model(effective_fallback)
            if fallback_spec == primary_spec:
                raise
            logger.warning(
                "Chat model creation failed for role %r (spec=%r); falling back to role %r",
                role,
                primary_spec,
                effective_fallback,
            )
            return self._create_from_spec(fallback_spec, {})

    def create_chat_model_for_spec(
        self,
        spec: str,
        params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Create model from explicit provider:model spec.

        Unlike `create_chat_model(role=...)`, this bypasses router role resolution
        and creates a model from an explicit spec string. Useful for per-turn
        overrides and subagent-specific model selection.

        Args:
            spec: provider:model string (e.g., ``anthropic:claude-sonnet-4-5``).
            params: Extra kwargs for ``init_chat_model`` (caller-validated).

        Returns:
            Wrapped BaseChatModel instance.

        Raises:
            ValueError: If ``spec`` is empty after stripping.
        """
        return self._create_from_spec(spec, params or {})

    def _parse_spec(self, spec: str) -> tuple[str, str]:
        """Parse provider:model spec into components.

        Args:
            spec: provider:model or just model string.

        Returns:
            Tuple of (provider_name, model_name). provider_name empty if not prefixed.
        """
        provider_name, _, model_name = spec.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""
        return provider_name, model_name

    def _cache_key(self, spec: str, params: dict[str, Any]) -> str:
        """Build cache key from spec and params.

        Args:
            spec: provider:model string.
            params: Extra kwargs.

        Returns:
            Cache key string with sorted JSON for deterministic ordering.
        """
        return f"{spec}:streaming:{json.dumps(params, sort_keys=True, default=str)}"

    def _create_from_spec(self, spec: str, params: dict[str, Any]) -> BaseChatModel:
        """Internal: parse spec, resolve provider, create, wrap, cache.

        Args:
            spec: provider:model string.
            params: Extra kwargs for init_chat_model.

        Returns:
            Wrapped BaseChatModel instance.

        Raises:
            ValueError: If spec is empty.
        """
        spec_str = (spec or "").strip()
        if not spec_str:
            raise ValueError("model_spec is required for create_chat_model_for_spec")

        merged_params = dict(params)
        cache_key = self._cache_key(spec_str, merged_params)

        with _model_cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

            provider_name, model_name = self._parse_spec(spec_str)
            provider_type = self._registry.resolve_provider_type(provider_name)
            provider_type_str, kwargs = self._registry.get_provider_kwargs(provider_name)
            merged_kwargs = {**kwargs, **merged_params}

            init_str = f"{provider_type_str}:{model_name}" if provider_name else spec_str
            model = init_chat_model(init_str, streaming=True, stream_usage=True, **merged_kwargs)

            model = self._apply_wrapper_chain(model, provider_type, provider_name)

            self._cache[cache_key] = model
            logger.debug("Created and cached model for spec '%s'", spec_str)

        return model

    def _apply_wrapper_chain(
        self,
        model: BaseChatModel,
        provider_type: ProviderType,
        provider_name: str,
    ) -> BaseChatModel:
        """Apply provider-specific wrappers in order.

        Wrapper chain:
        - Custom OpenAI-compatible endpoints: OpenAICompatModelWrapper → SootheTokenUsageChatModel
        - All others: SootheTokenUsageChatModel only

        Args:
            model: Raw model from init_chat_model.
            provider_type: Detected provider type from registry.
            provider_name: Provider name for logging.

        Returns:
            Wrapped model ready for use.
        """
        if self._registry.requires_openai_compat_wrapper(provider_name):
            logger.info(
                "Provider '%s' uses a custom OpenAI-compatible endpoint, applying compatibility wrapper",
                provider_name,
            )
            model = OpenAICompatModelWrapper(model, provider_name)

        # Always apply token observability for consistent Langfuse integration
        model = SootheTokenUsageChatModel(model)

        return model

    def create_embedding_model(self, role: ModelRole = "embedding") -> Embeddings:
        """Create embedding model using the requested router role.

        Handles DashScope special cases:
        - OpenAI-compatible endpoint: DashScopeOpenAIEmbeddings
        - Native DashScope SDK: DashScopeEmbeddings

        Results are cached by spec string.

        Returns:
            Embeddings instance.
        """
        from langchain.embeddings import init_embeddings

        spec = self.resolve_model(role)
        provider_name, _, model_name = spec.partition(":")
        if not model_name:
            model_name = provider_name
            provider_name = ""

        cache_key = spec
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        provider_type_str, kwargs = self._registry.get_provider_kwargs(provider_name)
        # Remove use_responses_api for embeddings (not applicable)
        kwargs.pop("use_responses_api", None)

        # Disable tokenization for OpenAI SDK v2+ compatibility.
        # OpenAI SDK v2+ requires string input, not token arrays (list[int]).
        # When check_embedding_ctx_length=True (default) + tiktoken_enabled=True (default),
        # langchain_openai tokenizes text and sends token arrays to the API,
        # causing 422 UnprocessableEntityError. Disabling context length checking
        # bypasses tokenization entirely and sends raw strings directly.
        kwargs["check_embedding_ctx_length"] = False

        # DashScope special handling (OpenAI-compatible vs native)
        if provider_name == "dashscope":
            base_url = kwargs.get("base_url", "")
            if "compatible-mode" in base_url:
                logger.debug("DashScope using OpenAI-compatible endpoint for embeddings")
                from soothe_nano.utils.embeddings_dashscope_openai import DashScopeOpenAIEmbeddings

                embedding_kwargs = {k: v for k, v in kwargs.items() if k != "base_url"}
                embeddings = DashScopeOpenAIEmbeddings(
                    model=model_name,
                    dimension=self._config.embedding_dims,
                    base_url=base_url,
                    **embedding_kwargs,
                )
            else:
                logger.debug("DashScope using native SDK for embeddings")
                from soothe_nano.utils.embeddings_dashscope import DashScopeEmbeddings

                embeddings = DashScopeEmbeddings(
                    model=model_name,
                    dimension=self._config.embedding_dims,
                    **kwargs,
                )
            self._embedding_cache[cache_key] = embeddings
            logger.debug("Created DashScope embedding model for '%s'", spec)
            return embeddings

        init_str = f"{provider_type_str}:{model_name}" if provider_name else spec
        embeddings = init_embeddings(init_str, **kwargs)
        self._embedding_cache[cache_key] = embeddings
        logger.debug("Created embedding model for '%s'", spec)

        return embeddings


__all__ = [
    "LLMFactory",
]
