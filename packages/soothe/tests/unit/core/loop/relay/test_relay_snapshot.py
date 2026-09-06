"""Tests for the relay snapshot predicates (IG-775)."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.sloop.relay.snapshot import (
    snapshot_has_resumable_interrupt,
    snapshot_has_unanswered_pending,
)


class TestSnapshotHasResumableInterrupt:
    def test_top_level_interrupt(self) -> None:
        snap = SimpleNamespace(interrupts=(object(),), tasks=())
        assert snapshot_has_resumable_interrupt(snap) is True

    def test_task_level_interrupt(self) -> None:
        snap = SimpleNamespace(
            interrupts=(),
            tasks=(SimpleNamespace(interrupts=(object(),)),),
        )
        assert snapshot_has_resumable_interrupt(snap) is True

    def test_absent(self) -> None:
        snap = SimpleNamespace(interrupts=(), tasks=(SimpleNamespace(interrupts=()),))
        assert snapshot_has_resumable_interrupt(snap) is False

    def test_none_interrupts_tolerant(self) -> None:
        snap = SimpleNamespace(interrupts=None, tasks=None)
        assert snapshot_has_resumable_interrupt(snap) is False


class TestSnapshotHasUnansweredPending:
    def test_relay_state_inbox_with_no_answer(self) -> None:
        snap = SimpleNamespace(values={"relay_state": {"inbox": [{"request": {}}], "answer": None}})
        assert snapshot_has_unanswered_pending(snap) is True

    def test_relay_state_inbox_with_answer(self) -> None:
        snap = SimpleNamespace(
            values={"relay_state": {"inbox": [{"request": {}}], "answer": {"answers": ["y"]}}}
        )
        assert snapshot_has_unanswered_pending(snap) is False

    def test_relay_state_empty_inbox(self) -> None:
        snap = SimpleNamespace(values={"relay_state": {"inbox": [], "answer": None}})
        assert snapshot_has_unanswered_pending(snap) is False

    def test_no_pending(self) -> None:
        snap = SimpleNamespace(values={})
        assert snapshot_has_unanswered_pending(snap) is False

    def test_relay_state_present_but_empty_inbox_is_false(self) -> None:
        snap = SimpleNamespace(values={"relay_state": {"inbox": [], "answer": None}})
        assert snapshot_has_unanswered_pending(snap) is False
