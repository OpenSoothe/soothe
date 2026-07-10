"""Daemon-owned loop metadata preserved across StrangeLoop checkpoint writes."""

from __future__ import annotations

from typing import Any

DAEMON_LOOP_METADATA_KEYS = frozenset(
    {
        "current_workspace",
        "client_workspace",
        "client_workspace_id",
        "user_id",
        "workspace_mapping",
        "is_ephemeral",
    }
)


def extract_daemon_loop_metadata(data: dict[str, Any] | None) -> dict[str, Any]:
    """Extract daemon-owned fields from a loop metadata dict."""
    if not data:
        return {}
    return {
        key: data[key]
        for key in DAEMON_LOOP_METADATA_KEYS
        if key in data and data[key] is not None
    }


def merge_daemon_loop_metadata(
    checkpoint_data: dict[str, Any],
    preserved: dict[str, Any],
) -> dict[str, Any]:
    """Overlay daemon-owned fields onto StrangeLoop checkpoint JSON."""
    if not preserved:
        return checkpoint_data
    merged = dict(checkpoint_data)
    merged.update(preserved)
    return merged


async def load_preserved_daemon_metadata(cur: Any, loop_id: str) -> dict[str, Any]:
    """Load daemon metadata for ``loop_id`` from ``agentloop_checkpoints``."""
    await cur.execute(
        """
        SELECT checkpoint_data, client_workspace
        FROM agentloop_checkpoints WHERE loop_id = %s
        """,
        (loop_id,),
    )
    row = await cur.fetchone()
    if not row:
        return {}
    existing = dict(row["checkpoint_data"]) if row.get("checkpoint_data") else {}
    preserved = extract_daemon_loop_metadata(existing)
    client_ws = row.get("client_workspace")
    if client_ws is not None:
        preserved.setdefault("client_workspace", client_ws)
    return preserved


__all__ = [
    "DAEMON_LOOP_METADATA_KEYS",
    "extract_daemon_loop_metadata",
    "load_preserved_daemon_metadata",
    "merge_daemon_loop_metadata",
]
