"""Attach per-turn model and router-profile overlays for a loop run."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from soothe.middleware._model_override import (
    attach_stream_model_override,
    reset_stream_model_override,
)
from soothe.middleware._router_profile_override import (
    attach_stream_router_profile,
    reset_stream_router_profile,
)


@contextmanager
def stream_turn_overrides(
    *,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    router_profile: str | None = None,
) -> Iterator[None]:
    """Attach stream overlays for one agent turn; always reset on exit.

    Args:
        model: Optional ``provider:model`` stream override (``/model``).
        model_params: Extra kwargs for the stream model override.
        router_profile: Optional ``router_profiles`` name for chat roles.
    """
    model_token = attach_stream_model_override(model, model_params)
    profile_token = attach_stream_router_profile(router_profile)
    try:
        yield
    finally:
        reset_stream_router_profile(profile_token)
        reset_stream_model_override(model_token)
