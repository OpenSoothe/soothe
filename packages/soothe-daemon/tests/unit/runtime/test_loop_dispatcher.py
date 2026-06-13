"""Tests for resume-time thread binding in ``bind_execution_thread_for_loop`` (IG-455).

Per RFC-223 the main StrangeLoop checkpoint thread id equals the ``loop_id``:
the runtime in ``soothe.core.loop.engine.strange_loop`` normalizes any
caller-supplied id back to ``loop_id`` before saving the checkpoint, so the
daemon must read from that same id on resume. Earlier code minted a separate
UUID, causing ``loop_state_get`` and ``loop_messages`` to read an empty
checkpoint and the TUI to show no history.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import soothe.config as soothe_config
from soothe.foundation.loop.state.persistence.manager import (
    StrangeLoopCheckpointPersistenceManager,
)

from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop


class _CapturingDaemon:
    def __init__(self, config: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self._config = config
        self._persistence_manager = StrangeLoopCheckpointPersistenceManager(config=config)

    async def _send_client_message(self, _client_id: Any, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        await self._persistence_manager.close()


def _make_bind_daemon(daemon: _CapturingDaemon, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        _persistence_manager=daemon._persistence_manager,
        _thread_registry=SimpleNamespace(
            ensure=lambda *_a, **_k: None,
            set_workspace=lambda *_a, **_k: None,
            set_thread_loop=lambda *_a, **_k: None,
        ),
        _daemon_workspace=str(tmp_path / "fallback"),
    )


@pytest.mark.asyncio
async def test_resume_returns_loop_id_when_metadata_already_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Continue on a loop whose previous run wrote ``current_thread_id == loop_id``."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _CapturingDaemon(config=config)
    try:
        loop_id = "loop-resume-normalized"
        await daemon._persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=[loop_id],
            current_thread_id=loop_id,
            status="idle",
        )

        bound = await bind_execution_thread_for_loop(_make_bind_daemon(daemon, tmp_path), loop_id)

        assert bound == loop_id
        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("current_thread_id") == loop_id
        assert metadata.get("thread_ids") == [loop_id]
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_resume_returns_loop_id_when_metadata_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First bind on a freshly registered loop must adopt loop_id, not mint a UUID."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _CapturingDaemon(config=config)
    try:
        loop_id = "loop-resume-firstbind"
        await daemon._persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=[],
            current_thread_id="",
            status="created",
        )

        bound = await bind_execution_thread_for_loop(_make_bind_daemon(daemon, tmp_path), loop_id)

        assert bound == loop_id
        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("current_thread_id") == loop_id
        assert loop_id in (metadata.get("thread_ids") or [])
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_resume_preserves_existing_fork_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-223 step-fork thread ids stay in ``thread_ids`` after re-bind."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _CapturingDaemon(config=config)
    try:
        loop_id = "loop-resume-with-forks"
        fork_one = f"{loop_id}__step_S_1"
        fork_two = f"{loop_id}__step_S_2"
        await daemon._persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=[loop_id, fork_one, fork_two],
            current_thread_id=loop_id,
            status="idle",
        )

        bound = await bind_execution_thread_for_loop(_make_bind_daemon(daemon, tmp_path), loop_id)

        assert bound == loop_id
        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("thread_ids") == [loop_id, fork_one, fork_two]
        assert metadata.get("current_thread_id") == loop_id
    finally:
        await daemon.close()


@pytest.mark.asyncio
async def test_resume_repairs_stale_alien_thread_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-RFC-223 metadata pointing at a random UUID is repaired to loop_id on continue."""
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", str(tmp_path / "soothe-home"))

    from soothe.config import SootheConfig

    config = SootheConfig()
    daemon = _CapturingDaemon(config=config)
    try:
        loop_id = "loop-resume-repair"
        stale = "019e0000-0000-7000-8000-000000000001"
        await daemon._persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=[stale],
            current_thread_id=stale,
            status="idle",
        )

        bound = await bind_execution_thread_for_loop(_make_bind_daemon(daemon, tmp_path), loop_id)

        assert bound == loop_id
        metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
        assert metadata is not None
        assert metadata.get("current_thread_id") == loop_id
        thread_ids = metadata.get("thread_ids") or []
        assert loop_id in thread_ids
        # Stale entry is preserved so the historical checkpoint remains addressable
        # for diagnostics / forensic recovery.
        assert stale in thread_ids
    finally:
        await daemon.close()
