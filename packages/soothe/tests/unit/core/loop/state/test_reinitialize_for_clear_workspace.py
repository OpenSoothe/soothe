"""Tests for workspace metadata inheritance on /clear reinitialize."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.foundation.sloop.state.sloop_manager import StrangeLoopStateManager


@pytest.mark.asyncio
async def test_reinitialize_for_clear_applies_inherited_workspace_metadata() -> None:
    manager = StrangeLoopStateManager(loop_id="old-loop")
    manager._backend_type = "postgresql"
    manager._postgres_backend = MagicMock()
    manager._postgres_backend.get_loop_metadata = AsyncMock(
        return_value={
            "current_workspace": "/var/lib/soothe/workspaces/demo",
            "client_workspace": "/Users/me/demo",
            "workspace_mapping": {
                "host_root": "/Users/me",
                "container_root": "/var/lib/soothe/workspaces",
            },
        }
    )
    manager._postgres_backend.update_loop_metadata = AsyncMock()
    manager._save_checkpoint_to_db = AsyncMock()

    with patch.object(
        manager,
        "_ensure_backend_initialized",
        new=AsyncMock(),
    ):
        new_loop_id, _checkpoint = await manager.reinitialize_for_clear("thread-1")

    assert new_loop_id != "old-loop"
    manager._save_checkpoint_to_db.assert_awaited_once()
    manager._postgres_backend.update_loop_metadata.assert_awaited_once()
    call_args = manager._postgres_backend.update_loop_metadata.await_args
    assert call_args is not None
    assert call_args.args[0] == new_loop_id
    assert call_args.kwargs["current_workspace"] == "/var/lib/soothe/workspaces/demo"
    assert call_args.kwargs["client_workspace"] == "/Users/me/demo"
    assert call_args.kwargs["workspace_mapping"]["host_root"] == "/Users/me"
