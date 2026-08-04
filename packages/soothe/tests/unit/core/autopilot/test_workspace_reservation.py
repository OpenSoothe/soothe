"""Tests for WorkspaceReservation (RFC-222 revised)."""

from __future__ import annotations

from pathlib import Path

from soothe.autopilot.workspace_reservation import WorkspaceReservation


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

    def test_absolute_path_ok_when_cwd_missing(self, monkeypatch) -> None:
        """Scheduling must not crash if the process cwd was deleted."""
        monkeypatch.setattr(
            "soothe.autopilot.workspace_reservation.os.getcwd",
            lambda: (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory")),
        )
        r = WorkspaceReservation()
        assert r.acquire("g1", "/proj/a") is True
        assert r.conflicts_with_active("/proj/a") == "g1"

    def test_relative_sentinel_ok_when_cwd_missing(self, monkeypatch) -> None:
        """Autopilot fallback workspaces are relative (``$autopilot/goal/...``)."""
        monkeypatch.setattr(
            "soothe.autopilot.workspace_reservation.os.getcwd",
            lambda: (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory")),
        )
        r = WorkspaceReservation()
        assert r.acquire("g1", "$autopilot/goal/abc") is True
        assert r.conflicts_with_active("$autopilot/goal/abc") == "g1"
        assert r.acquire("g2", "$autopilot/goal/def") is True


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


class TestTOCTOUMitigation:
    """Verify that check-and-set is atomic — no double-acquire under
    concurrent access to the same overlapping workspace."""

    def test_concurrent_acquire_same_path_only_one_wins(self) -> None:
        """Two threads acquire the same path for different goals
        simultaneously — exactly one must succeed."""
        import threading

        r = WorkspaceReservation()
        results: list[bool] = []
        barrier = threading.Barrier(2)

        def _acquire(goal_id: str) -> None:
            barrier.wait()
            results.append(r.acquire(goal_id, "/proj/shared"))

        t1 = threading.Thread(target=_acquire, args=("g1",))
        t2 = threading.Thread(target=_acquire, args=("g2",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Exactly one should have acquired
        assert results.count(True) == 1
        assert results.count(False) == 1
        assert r.reservation_count() == 1

    def test_concurrent_acquire_overlapping_paths(self) -> None:
        """Parent path and child path acquired concurrently — one must fail."""
        import threading

        r = WorkspaceReservation()
        results: list[bool] = []
        barrier = threading.Barrier(2)

        def _acquire(goal_id: str, ws: str) -> None:
            barrier.wait()
            results.append(r.acquire(goal_id, ws))

        t1 = threading.Thread(target=_acquire, args=("g1", "/proj/a"))
        t2 = threading.Thread(target=_acquire, args=("g2", "/proj/a/sub"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results.count(True) == 1
        assert results.count(False) == 1

    def test_acquire_then_conflicts_with_active_is_consistent(self) -> None:
        """After acquire succeeds, conflicts_with_active must immediately
        see the reservation (no stale read)."""
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        # Immediately checking from another "thread" must see the hold
        assert r.conflicts_with_active("/proj/a") == "g1"

    def test_release_then_acquire_is_atomic(self) -> None:
        """Release followed by acquire from another goal must not leave
        a window where both or neither hold the reservation."""
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        assert r.release("g1") is True
        # Immediately re-acquiring for a different goal must succeed
        assert r.acquire("g2", "/proj/a") is True
        assert r.reservation_count() == 1

    def test_snapshot_isolation_under_mutation(self) -> None:
        """active_reservations() returns a copy that is safe to mutate
        even if the internal dict is being modified."""
        r = WorkspaceReservation()
        r.acquire("g1", "/proj/a")
        snap = r.active_reservations()
        # Mutate snapshot — must not affect internal state
        snap.clear()
        assert r.reservation_count() == 1
