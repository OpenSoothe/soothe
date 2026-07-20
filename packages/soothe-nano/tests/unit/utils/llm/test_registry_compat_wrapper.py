"""Tests for auto-detection of OpenAI compatibility wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.config.models import ModelProviderConfig
from soothe_nano.config.settings import SootheConfig
from soothe_nano.utils.llm.registry import ProviderRegistry
from soothe_nano.utils.llm.wrappers import OpenAICompatModelWrapper


@pytest.mark.parametrize(
    ("api_base_url", "expected"),
    [
        (None, False),
        ("https://api.openai.com/v1", False),
        ("http://100.75.70.86:9642/v1", True),
        ("http://localhost:1234/v1", True),
    ],
)
def test_requires_openai_compat_wrapper(api_base_url: str | None, expected: bool) -> None:
    registry = ProviderRegistry(
        [
            ModelProviderConfig(
                name="local",
                provider_type="openai",
                api_base_url=api_base_url,
                api_key="test",
            )
        ]
    )
    assert registry.requires_openai_compat_wrapper("local") is expected


def test_requires_openai_compat_wrapper_anthropic_never() -> None:
    registry = ProviderRegistry(
        [
            ModelProviderConfig(
                name="anthropic",
                provider_type="anthropic",
                api_base_url="http://localhost:9999/v1",
                api_key="test",
            )
        ]
    )
    assert registry.requires_openai_compat_wrapper("anthropic") is False


def test_factory_applies_compat_wrapper_for_custom_openai_endpoint() -> None:
    config = SootheConfig(
        providers=[
            ModelProviderConfig(
                name="omlx",
                provider_type="openai",
                api_base_url="http://127.0.0.1:9642/v1",
                api_key="test",
            )
        ],
        router_profiles=[
            {
                "name": "test",
                "router": {"default": "omlx:test-model"},
            }
        ],
        embedding_profile=[{"model_role": "openai:text-embedding-3-small", "embedding_dims": 1536}],
        active_router_profile="test",
    )

    raw_model = MagicMock()
    with patch("soothe_nano.utils.llm.factory.init_chat_model", return_value=raw_model):
        model = config.create_chat_model("default")

    assert isinstance(model._model, OpenAICompatModelWrapper)  # noqa: SLF001
