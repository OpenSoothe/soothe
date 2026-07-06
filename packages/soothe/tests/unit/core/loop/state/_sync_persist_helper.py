"""Test helpers for immediate SQLite checkpoint persistence."""

from __future__ import annotations

from typing import Any


def bind_sync_persist_writes(state_manager: Any) -> None:
    """Wrap ``save`` / ``initialize`` so tests can reload from disk without toggling production flags."""
    original_save = state_manager.save
    original_initialize = state_manager.initialize

    async def save_with_flush(checkpoint: Any) -> None:
        await original_save(checkpoint)
        await state_manager.force_flush()

    async def initialize_with_flush(*args: Any, **kwargs: Any) -> Any:
        checkpoint = await original_initialize(*args, **kwargs)
        await state_manager.force_flush()
        return checkpoint

    state_manager.save = save_with_flush  # type: ignore[method-assign]
    state_manager.initialize = initialize_with_flush  # type: ignore[method-assign]
