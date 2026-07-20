"""Tests for loop-scoped router profile overlay (RFC-632 / IG-592)."""

from __future__ import annotations

from soothe_nano.config.settings import SootheConfig
from soothe_nano.utils.runtime import (
    attach_stream_router_profile,
    get_stream_router_profile,
    reset_stream_router_profile,
    stream_turn_overrides,
)


def _config_with_two_profiles() -> SootheConfig:
    return SootheConfig(
        router_profiles=[
            {
                "name": "production",
                "router": {
                    "default": "dashscope:prod-default",
                    "fast": "dashscope:prod-fast",
                    "think": "dashscope:prod-think",
                },
            },
            {
                "name": "local",
                "router": {
                    "default": "omlx:local-default",
                    "fast": "omlx:local-fast",
                    "think": "omlx:local-think",
                },
            },
        ],
        embedding_profile=[{"model_role": "dashscope:prod-embed", "embedding_dims": 768}],
        active_router_profile="production",
    )


def test_resolve_model_honors_stream_router_profile_for_chat_roles() -> None:
    cfg = _config_with_two_profiles()
    assert cfg.resolve_model("default") == "dashscope:prod-default"
    assert cfg.resolve_model("fast") == "dashscope:prod-fast"
    assert cfg.embedding_dims == 768

    token = attach_stream_router_profile("local")
    try:
        assert get_stream_router_profile() == "local"
        assert cfg.resolve_model("default") == "omlx:local-default"
        assert cfg.resolve_model("fast") == "omlx:local-fast"
        assert cfg.resolve_model("think") == "omlx:local-think"
        # Embedding stays on process active profile.
        assert cfg.resolve_model("embedding") == "dashscope:prod-embed"
        assert cfg.embedding_dims == 768
    finally:
        reset_stream_router_profile(token)

    assert cfg.resolve_model("default") == "dashscope:prod-default"


def test_stream_turn_overrides_sets_model_and_profile() -> None:
    cfg = _config_with_two_profiles()
    with stream_turn_overrides(model="openai:gpt-test", router_profile="local"):
        assert cfg.resolve_model("think") == "omlx:local-think"
        from soothe_nano.utils.runtime import get_stream_model_override

        assert get_stream_model_override() is not None
        assert get_stream_model_override()[0] == "openai:gpt-test"
    assert get_stream_router_profile() is None
    from soothe_nano.utils.runtime import get_stream_model_override

    assert get_stream_model_override() is None


def test_unknown_overlay_name_falls_back_to_process_router() -> None:
    cfg = _config_with_two_profiles()
    token = attach_stream_router_profile("missing-profile")
    try:
        assert cfg.resolve_model("default") == "dashscope:prod-default"
    finally:
        reset_stream_router_profile(token)
