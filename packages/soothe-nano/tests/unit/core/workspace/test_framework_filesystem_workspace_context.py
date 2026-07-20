"""Tests for workspace ContextVar lifecycle (RFC-103)."""

from __future__ import annotations

import asyncio

import pytest

from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem


@pytest.mark.asyncio
async def test_clear_workspace_falls_back_when_token_from_other_task() -> None:
    """Middleware hooks may run in different asyncio Contexts; reset must not raise."""
    token_holder: dict[str, object] = {}

    async def setter() -> None:
        token_holder["token"] = FrameworkFilesystem.set_current_workspace("/tmp/soothe_ws_ctx_test")

    async def clearer() -> None:
        FrameworkFilesystem.clear_current_workspace(token_holder["token"])  # type: ignore[arg-type]

    await asyncio.create_task(setter())
    await asyncio.create_task(clearer())
