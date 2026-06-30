"""Unit tests for streaming configuration in SootheConfig."""

from support_config import config_with_router_profile as config_with_router

from soothe.config.models import ModelProviderConfig, ModelRouter


def test_create_chat_model_with_streaming_enabled():
    """Verify models are created with streaming=True by default."""
    config = config_with_router(
        ModelRouter(default="test-provider:gpt-4o-mini"),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    model = config.create_chat_model("default")

    # Check streaming parameter is enabled
    assert hasattr(model, "streaming")
    assert model.streaming is True


def test_create_chat_model_for_spec_with_streaming():
    """Verify models created with explicit spec also have streaming=True."""
    config = config_with_router(
        ModelRouter(default="test-provider:gpt-4o-mini"),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    model = config.create_chat_model_for_spec("test-provider:gpt-4o-mini")

    # Check streaming parameter is enabled
    assert hasattr(model, "streaming")
    assert model.streaming is True


def test_create_chat_model_for_spec_with_params_streaming():
    """Verify streaming=True is not overridden by model_params."""
    config = config_with_router(
        ModelRouter(default="test-provider:gpt-4o-mini"),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    # Even if user tries to disable streaming in params, it should remain enabled
    model = config.create_chat_model_for_spec(
        "test-provider:gpt-4o-mini",
        model_params={"temperature": 0.7},
    )

    assert hasattr(model, "streaming")
    assert model.streaming is True


def test_model_cache_includes_streaming_key():
    """Verify cache keys include streaming parameter for proper invalidation."""
    config = config_with_router(
        ModelRouter(default="test-provider:gpt-4o-mini"),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    # Create model twice - should use cache
    model1 = config.create_chat_model("default")
    model2 = config.create_chat_model("default")

    # Should be the same cached instance
    assert model1 is model2

    # Check cache key format includes streaming (now in llm_factory._cache)
    cache_keys = list(config.llm_factory._cache.keys())
    assert len(cache_keys) == 1
    assert "streaming" in cache_keys[0]


def test_create_chat_model_for_spec_cache_key_streaming():
    """Verify spec model cache keys include streaming parameter."""
    config = config_with_router(
        ModelRouter(default="test-provider:gpt-4o-mini"),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    # Create models with same spec but different params
    model1 = config.create_chat_model_for_spec("test-provider:gpt-4o-mini")
    model2 = config.create_chat_model_for_spec(
        "test-provider:gpt-4o-mini", model_params={"temperature": 0.5}
    )
    model3 = config.create_chat_model_for_spec(
        "test-provider:gpt-4o-mini", model_params={"temperature": 0.7}
    )

    # Should be different instances due to different params
    assert model1 is not model2
    assert model2 is not model3

    # Same params should return cached instance
    model4 = config.create_chat_model_for_spec(
        "test-provider:gpt-4o-mini", model_params={"temperature": 0.5}
    )
    assert model2 is model4

    # Check all cache keys include streaming (now in llm_factory._cache)
    for cache_key in config.llm_factory._cache.keys():
        assert "streaming" in cache_key


def test_multiple_roles_all_streaming():
    """Verify all model roles (default, think, fast) have streaming enabled."""
    config = config_with_router(
        ModelRouter(
            default="test-provider:gpt-4o-mini",
            think="test-provider:gpt-4o",
            fast="test-provider:gpt-4o-mini",
        ),
        providers=[
            ModelProviderConfig(
                name="test-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    for role in ["default", "think", "fast"]:
        model = config.create_chat_model(role)
        assert hasattr(model, "streaming")
        assert model.streaming is True


def test_streaming_with_provider_wrapper():
    """Verify streaming works with provider compatibility wrappers."""
    config = config_with_router(
        ModelRouter(default="limited-provider:local-model"),
        providers=[
            ModelProviderConfig(
                name="limited-provider",
                provider_type="openai",
                api_key="${OPENAI_API_KEY}",
            )
        ],
    )

    model = config.create_chat_model("default")

    # Model should have streaming enabled
    assert hasattr(model, "streaming")
    assert model.streaming is True
