"""Tests for the daemon-side ``goal_interrupted`` ledger marker writer.

Covers ``mark_cancelled_goal_interrupted``: it loads the CE ledger, appends a
``phase="goal_interrupted"`` Human+AI pair whose AI body is a deterministic
digest of the cancelled goal's partial ``execute_step`` work, and persists it.
Failures are swallowed; no marker is written when no execute evidence exists.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from soothe.foundation.context.persistence.sqlite_backend import (
    SqliteContextPersistence,
)

# Initialize the daemon package graph (events/config) before importing from
# the query subpackage, mirroring how test_engine_cancel.py orders its imports.
from soothe_daemon.config import SootheDaemonConfig  # noqa: F401  (side-effect import)
from soothe_daemon.query.goal_interrupt_persistence import (
    _build_cancelled_digest,
    _new_ledger_entry,
    mark_cancelled_goal_interrupted,
)


def _sqlite_config() -> Any:
    """Minimal config stub: ``resolve_context_engine_persistence`` only reads
    ``config.persistence.default_backend`` for the sqlite branch.
    """

    return SimpleNamespace(
        persistence=SimpleNamespace(
            default_backend="sqlite",
            postgres_base_dsn=None,
            soothe_postgres_dsn=None,
            postgres_databases={},
        )
    )


def _execute_ai_entry(content: str, thread_id: str = "t1") -> dict[str, Any]:
    return {
        "type": "AIMessage",
        "content": content,
        "additional_kwargs": {"phase": "execute_step"},
        "metadata": {"phase": "execute_step", "thread_id": thread_id, "iteration": 3},
    }


def test_digest_collects_execute_evidence_latest_first() -> None:
    ledger = [
        _execute_ai_entry("first wave finding: parser.py line 42"),
        _execute_ai_entry("second wave finding: wrote repro test"),
    ]
    digest = _build_cancelled_digest(ledger, reason="user_cancelled")
    assert "user_cancelled" in digest
    # Oldest-first ordering: first wave appears before second wave.
    assert digest.index("first wave finding") < digest.index("second wave finding")


def test_digest_empty_when_no_execute_evidence() -> None:
    ledger = [
        {
            "type": "AIMessage",
            "content": "plan text",
            "additional_kwargs": {"phase": "plan_generate"},
        },
    ]
    assert _build_cancelled_digest(ledger, reason="fatal_error") == ""


def test_new_ledger_entry_shape() -> None:
    entry = _new_ledger_entry(
        role="ai",
        content="digest body",
        phase="goal_interrupted",
        thread_id="t1",
        iteration=2,
    )
    assert entry["type"] == "ai"
    assert entry["content"] == "digest body"
    assert entry["additional_kwargs"]["phase"] == "goal_interrupted"
    assert entry["metadata"]["phase"] == "goal_interrupted"
    assert entry["metadata"]["thread_id"] == "t1"


@pytest.mark.asyncio
async def test_mark_cancelled_writes_pair_to_persistence(tmp_path: Path) -> None:
    """End-to-end: marker pair is persisted and reloadable from the ledger."""
    # Seed the persistence with an execute_step AI row so the digest is non-empty.
    persistence = SqliteContextPersistence(loop_id="loop-1", db_path=tmp_path / "ce.db")
    seed = [_execute_ai_entry("partial work: located the bug")]
    await persistence.save_ledger(seed)
    await persistence.close()

    # The helper uses resolve_context_engine_persistence(config, loop_id) which
    # for the sqlite branch builds its own backend at the runtime DB path. To
    # keep this test hermetic we patch the factory to return our tmp-path backend.
    import soothe.foundation.context.persistence.factory as factory

    import soothe_daemon.query.goal_interrupt_persistence as mod

    original = factory.resolve_context_engine_persistence
    factory.resolve_context_engine_persistence = lambda cfg, lid: SqliteContextPersistence(
        loop_id=lid, db_path=tmp_path / "ce.db"
    )
    mod.resolve_context_engine_persistence = factory.resolve_context_engine_persistence
    try:
        appended = await mark_cancelled_goal_interrupted(
            _sqlite_config(), "loop-1", reason="user_cancelled"
        )
        assert appended == 2

        # Reload and assert the marker pair is present.
        p2 = SqliteContextPersistence(loop_id="loop-1", db_path=tmp_path / "ce.db")
        ledger = await p2.load_ledger()
        await p2.close()
        interrupted = [
            e
            for e in ledger
            if (e.get("additional_kwargs") or {}).get("phase") == "goal_interrupted"
        ]
        assert len(interrupted) == 2
        ai_body = next(str(e.get("content")) for e in interrupted if e.get("type") == "ai")
        assert "user_cancelled" in ai_body
        assert "located the bug" in ai_body
    finally:
        factory.resolve_context_engine_persistence = original
        mod.resolve_context_engine_persistence = original


@pytest.mark.asyncio
async def test_mark_cancelled_noop_without_evidence(tmp_path: Path) -> None:
    import soothe.foundation.context.persistence.factory as factory

    import soothe_daemon.query.goal_interrupt_persistence as mod

    persistence = SqliteContextPersistence(loop_id="loop-2", db_path=tmp_path / "ce2.db")
    await persistence.save_ledger([])
    await persistence.close()

    original = factory.resolve_context_engine_persistence
    factory.resolve_context_engine_persistence = lambda cfg, lid: SqliteContextPersistence(
        loop_id=lid, db_path=tmp_path / "ce2.db"
    )
    mod.resolve_context_engine_persistence = factory.resolve_context_engine_persistence
    try:
        appended = await mark_cancelled_goal_interrupted(
            _sqlite_config(), "loop-2", reason="user_cancelled"
        )
        assert appended == 0
    finally:
        factory.resolve_context_engine_persistence = original
        mod.resolve_context_engine_persistence = original
