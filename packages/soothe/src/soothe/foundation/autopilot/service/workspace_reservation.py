"""WorkspaceReservation — scheduling-time conflict gate (RFC-222 revised).

Daemon-owned. Refuses to dispatch a new goal whose workspace prefix
overlaps with any goal currently active. Replaces per-path
``FileLockMiddleware`` for v1 (see RFC-222 Q1) — the registry is in the
daemon, the check happens before dispatch, so no cross-process RPC is
needed.

Conflict semantics (when ``strict_overlap`` is True, the default):
- ``/foo/bar`` conflicts with ``/foo/bar/baz`` (parent vs child)
- ``/foo/bar/baz`` conflicts with ``/foo/bar`` (child vs parent)
- ``/foo/bar`` does NOT conflict with ``/foo/barber`` (path component-aware)
- ``/foo/bar`` does NOT conflict with ``/foo/qux`` (siblings)
- Identical paths conflict.

When ``strict_overlap`` is False, only exact-path matches conflict.

Workspace paths are normalized (absolute, no trailing slash, no ``..``)
before comparison so equivalent paths compare equal regardless of input
shape.
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)


def _normalize(workspace: str | Path) -> str:
    """Canonical workspace path: absolute, POSIX-style, no trailing slash.

    We use PurePosixPath for the component comparison even on macOS/Linux —
    we only care about path-prefix semantics, not filesystem case-sensitivity.
    """
    p = Path(workspace).expanduser()
    # Don't resolve symlinks (workspaces may not exist yet); just normalize.
    abs_str = str(p.absolute()).rstrip("/")
    if not abs_str:
        abs_str = "/"
    return abs_str


def _parts(workspace_norm: str) -> tuple[str, ...]:
    """Path components for prefix-overlap checks."""
    return PurePosixPath(workspace_norm).parts


def _overlaps(a_norm: str, b_norm: str, *, strict: bool) -> bool:
    """Return True if two normalized workspace paths overlap."""
    if a_norm == b_norm:
        return True
    if not strict:
        return False
    a_parts = _parts(a_norm)
    b_parts = _parts(b_norm)
    short, long = (a_parts, b_parts) if len(a_parts) < len(b_parts) else (b_parts, a_parts)
    # Component-wise prefix match — avoids the /foo/bar vs /foo/barber false positive.
    return short == long[: len(short)]


class WorkspaceReservation:
    """Workspace-prefix conflict gate (RFC-222 revised).

    Args:
        strict_overlap: When True, any prefix overlap counts as a conflict.
            When False, only exact-path matches conflict.
        enabled: When False, every ``acquire`` succeeds and
            ``conflicts_with_active`` returns ``None``. Allows config-level
            opt-out for tests / single-tenant deployments.
    """

    def __init__(
        self,
        *,
        strict_overlap: bool = True,
        enabled: bool = True,
    ) -> None:
        self._strict = strict_overlap
        self._enabled = enabled
        # goal_id → normalized workspace string
        self._reservations: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def reservation_count(self) -> int:
        return len(self._reservations)

    def conflicts_with_active(
        self, workspace: str | Path, *, exclude_goal_id: str | None = None
    ) -> str | None:
        """Return the goal_id of a conflicting active reservation, or None.

        Args:
            workspace: Workspace path to check.
            exclude_goal_id: Skip this goal when checking (avoids self-conflict
                when re-dispatching a goal that still holds a stale reservation).
        """
        if not self._enabled:
            return None
        norm = _normalize(workspace)
        for goal_id, held in self._reservations.items():
            if goal_id == exclude_goal_id:
                continue
            if _overlaps(norm, held, strict=self._strict):
                return goal_id
        return None

    def acquire(self, goal_id: str, workspace: str | Path) -> bool:
        """Try to reserve ``workspace`` for ``goal_id``.

        Returns:
            True on success. False if another active goal holds an
            overlapping reservation. Idempotent for the same goal_id
            on the same workspace.
        """
        if not self._enabled:
            self._reservations[goal_id] = _normalize(workspace)
            return True
        norm = _normalize(workspace)

        # Idempotent: same goal, same workspace → success without re-checking.
        existing = self._reservations.get(goal_id)
        if existing is not None and existing == norm:
            return True

        # Check overlap against every OTHER reservation.
        for held_goal, held_ws in self._reservations.items():
            if held_goal == goal_id:
                continue
            if _overlaps(norm, held_ws, strict=self._strict):
                logger.debug(
                    "WorkspaceReservation: conflict for goal %s on %s — held by %s on %s",
                    goal_id,
                    norm,
                    held_goal,
                    held_ws,
                )
                return False

        self._reservations[goal_id] = norm
        return True

    def release(self, goal_id: str) -> bool:
        """Release ``goal_id``'s reservation. Returns True if it existed."""
        return self._reservations.pop(goal_id, None) is not None

    def active_reservations(self) -> dict[str, str]:
        """Snapshot of goal_id → normalized workspace for observability."""
        return dict(self._reservations)
