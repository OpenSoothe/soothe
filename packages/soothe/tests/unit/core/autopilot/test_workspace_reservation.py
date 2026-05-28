"""Tests for WorkspaceReservation (RFC-222 revised)."""

from __future__ import annotations

from pathlib import Path

from soothe.core.autopilot.workspace_reservation import WorkspaceReservation


class TestBasicAcquireRelease:
    def test_fresh_acquire_succeeds(self) -> None:
        r = WorkspaceReservation()
        assert r.acquire("g1", "/proj/a") is True
        assert r.reservation_count() == 1

    def test_release_existing_returns_true(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.release("g1") is True
        assert r.reservation_count() == 0

    def test_release_unknown_returns_false(self) -> None:
        r = WorkspaceReservation()
        assert r.release("ghost") is False

    def test_idempotent_acquire_same_workspace(self) -> None:
        r = WorkspaceReservation()
        assert r.acquire("g1", "/proj/a") is True
        # Same goal re-claiming same workspace should succeed without conflict
        assert r.acquire("g1", "/proj/a") is True
        assert r.reservation_count() == 1


class TestExactConflict:
    def test_same_path_different_goal_conflicts(self) -> None:
        r = WorkspaceReservation()
        assert r.acquire("g1", "/proj/a") is True
        assert r.acquire("g2", "/proj/a") is False
        assert r.reservation_count() == 1

    def test_conflicts_with_active_returns_holder(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.conflicts_with_active("/proj/a") == "g1"

    def test_no_conflict_returns_none(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.conflicts_with_active("/proj/b") is None


class TestPrefixOverlap:
    def test_child_path_conflicts_with_parent_holder(self) -> None:
        r = WorkspaceReservation()
        r.acquire("parent", "/proj/a")
        assert r.acquire("child", "/proj/a/sub") is False

    def test_parent_path_conflicts_with_child_holder(self) -> None:
        r = WorkspaceReservation()
        r.acquire("child", "/proj/a/sub")
        assert r.acquire("parent", "/proj/a") is False

    def test_component_aware_no_false_positive(self) -> None:
        """/proj/bar must NOT conflict with /proj/barber (prefix string but
        not prefix component)."""
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/bar")
        assert r.acquire("g2", "/proj/barber") is True
        assert r.reservation_count() == 2

    def test_sibling_paths_no_conflict(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.acquire("g2", "/proj/b") is True

    def test_deep_prefix_overlap(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a/b/c")
        assert r.acquire("g2", "/proj/a") is False


class TestStrictDisabled:
    def test_only_exact_matches_conflict_when_strict_off(self) -> None:
        r = WorkspaceReservation(strict_overlap=False)
        r.acquire("g1", "/proj/a")
        assert r.acquire("g2", "/proj/a/sub") is True  # child OK when not strict
        assert r.acquire("g3", "/proj/a") is False  # exact still conflicts


class TestEnabledFalse:
    def test_disabled_pool_never_conflicts(self) -> None:
        r = WorkspaceReservation(enabled=False)
        r.acquire("g1", "/proj/a")
        assert r.acquire("g2", "/proj/a") is True
        assert r.conflicts_with_active("/proj/a") is None
        assert r.enabled is False


class TestPathNormalization:
    def test_trailing_slash_normalized(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a/")
        assert r.acquire("g2", "/proj/a") is False  # same after normalization

    def test_accepts_path_object(self) -> None:
        r = WorkspaceReservation()
        assert r.acquire("g1", Path("/proj/a")) is True
        assert r.acquire("g2", "/proj/a") is False

    def test_tilde_expansion(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        r = WorkspaceReservation()
        r.acquire("g1", "~/work")
        # Same expansion → conflict
        assert r.acquire("g2", str(tmp_path / "work")) is False


class TestObservability:
    def test_active_reservations_snapshot_is_copy(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/a")
        r.acquire("g2", "/b")
        snap = r.active_reservations()
        assert set(snap.keys()) == {"g1", "g2"}
        snap["g3"] = "/c"  # mutating snapshot must not affect internal state
        assert r.reservation_count() == 2


class TestReuseAfterRelease:
    def test_path_becomes_available_after_release(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.acquire("g2", "/proj/a") is False
        r.release("g1")
        assert r.acquire("g2", "/proj/a") is True

    def test_release_idempotent(self) -> None:
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.release("g1") is True
        assert r.release("g1") is False  # second release no-op
