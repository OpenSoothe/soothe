"""Shared NanoConfig / SootheConfig builders for soothe-nano tests."""

from __future__ import annotations

from typing import Any

from soothe_nano.config.models import ModelRouter, RouterProfile
from soothe_nano.config.settings import SootheConfig


def config_with_router_profile(
    router: ModelRouter | dict[str, Any] | None = None,
    *,
    profile_name: str = "test",
    embedding_dims: int = 1536,
    **kwargs: Any,
) -> SootheConfig:
    """Build ``SootheConfig`` (NanoConfig) with a single router profile."""
    if not router:
        return SootheConfig(**kwargs)
    if isinstance(router, dict):
        router = ModelRouter(**router)
    embedding_profile = kwargs.pop(
        "embedding_profile",
        [{"model_role": "openai:text-embedding-3-small", "embedding_dims": embedding_dims}],
    )
    return SootheConfig(
        router_profiles=[
            RouterProfile(
                name=profile_name,
                router=router,
            )
        ],
        embedding_profile=embedding_profile,
        active_router_profile=profile_name,
        **kwargs,
    )
