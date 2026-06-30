"""Shared SootheConfig builders for unit and integration tests."""

from __future__ import annotations

from typing import Any

from soothe.config.models import ModelRouter, RouterProfile
from soothe.config.settings import SootheConfig


def config_with_router_profile(
    router: ModelRouter | dict[str, Any] | None = None,
    *,
    profile_name: str = "test",
    embedding_dims: int = 1536,
    **kwargs: Any,
) -> SootheConfig:
    """Build ``SootheConfig`` with a single router profile."""
    if not router:
        return SootheConfig(**kwargs)
    if isinstance(router, dict):
        router = ModelRouter(**router)
    return SootheConfig(
        router_profiles=[
            RouterProfile(
                name=profile_name,
                router=router,
                embedding_dims=embedding_dims,
            )
        ],
        active_router_profile=profile_name,
        **kwargs,
    )
