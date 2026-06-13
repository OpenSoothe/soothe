"""Loop management using LangGraph's built-in checkpoint persistence."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_sdk.client.config import SOOTHE_HOME
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import aiosqlite

logger = logging.getLogger(__name__)

_aiosqlite_patched = False


def _patch_aiosqlite() -> None:
    """Patch aiosqlite.Connection with `is_alive()` if missing.

    Required by langgraph-checkpoint>=2.1.0.
    See: https://github.com/langchain-ai/langgraph/issues/6583
    """
    global _aiosqlite_patched  # noqa: PLW0603  # Module-level flag requires global statement
    if _aiosqlite_patched:
        return

    import aiosqlite as _aiosqlite

    if not hasattr(_aiosqlite.Connection, "is_alive"):

        def _is_alive(self: _aiosqlite.Connection) -> bool:
            """Check if the connection is still alive.

            Returns:
                True if connection is alive, False otherwise.
            """
            return bool(self._running and self._connection is not None)

        # Dynamically adding a method to aiosqlite.Connection at runtime.
        # Type checkers can't understand this monkey-patch, so we suppress the
        # "attr-defined" error that would otherwise be raised.
        _aiosqlite.Connection.is_alive = _is_alive  # type: ignore[attr-defined]

    _aiosqlite_patched = True


@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    """Import aiosqlite, apply the compatibility patch, and connect.

    Centralizes the deferred import + patch + connect sequence used by every
    database function in this module.

    Yields:
        An open aiosqlite connection to the sessions database.
    """
    import aiosqlite as _aiosqlite

    _patch_aiosqlite()

    async with _aiosqlite.connect(str(get_db_path()), timeout=30.0) as conn:
        yield conn


class LoopInfo(TypedDict, total=False):
    """Loop metadata returned by `list_loops_via_daemon_rpc`."""

    loop_id: str
    """Unique identifier for the StrangeLoop."""

    status: str
    """Loop status (running, paused, completed, etc.)."""

    threads: int
    """Number of checkpoint contexts reported by the daemon for this loop."""

    goals: int
    """Total goals completed in the loop."""

    switches: int
    """Total checkpoint context switches in the loop."""

    created: str
    """ISO timestamp of loop creation (truncated to [:16])."""

    updated: str
    """ISO timestamp of last loop activity (truncated to [:16])."""

    prompt: str
    """First user-visible prompt of the loop (the initial goal text)."""

    messages: int
    """Total user + assistant turns recorded in the loop."""

    duration_ms: int
    """Cumulative agent execution time across all goals (milliseconds)."""

    live: bool
    """True when an active runner stream is currently attached to the loop."""


def _parse_iso_to_local(iso_timestamp: str) -> datetime | None:
    """Parse an ISO 8601 timestamp and convert it to local time.

    Naive timestamps (no offset suffix) are assumed to be UTC — the daemon
    stores all timestamps as UTC, and historic wire payloads truncated the
    offset away. Treating them as local instead would render UTC clocks as
    if they were already local, producing an N-hour drift in any non-UTC
    timezone.
    """
    from datetime import UTC

    try:
        dt = datetime.fromisoformat(iso_timestamp)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone()


def format_timestamp(iso_timestamp: str | None) -> str:
    """Format ISO timestamp for display (e.g., 'Dec 30, 6:10pm').

    Args:
        iso_timestamp: ISO 8601 timestamp string, or `None`.

    Returns:
        Formatted timestamp string or empty string if invalid.
    """
    if not iso_timestamp:
        return ""
    dt = _parse_iso_to_local(iso_timestamp)
    if dt is None:
        logger.debug("Failed to parse timestamp %r; displaying as blank", iso_timestamp)
        return ""
    return dt.strftime("%b %d, %-I:%M%p").lower().replace("am", "am").replace("pm", "pm")


def format_relative_timestamp(iso_timestamp: str | None) -> str:
    """Format ISO timestamp as relative time (e.g., '5m ago', '2h ago').

    Args:
        iso_timestamp: ISO 8601 timestamp string, or `None`.

    Returns:
        Relative time string or empty string if invalid.
    """
    if not iso_timestamp:
        return ""
    dt = _parse_iso_to_local(iso_timestamp)
    if dt is None:
        logger.debug("Failed to parse timestamp %r; displaying as blank", iso_timestamp)
        return ""

    delta = datetime.now(tz=dt.tzinfo) - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:  # noqa: PLR2004
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:  # noqa: PLR2004
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:  # noqa: PLR2004
        return f"{days}d ago"
    months = days // 30
    if months < 12:  # noqa: PLR2004
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


_db_path: Path | None = None


def get_db_path() -> Path:
    """Get path to global database.

    The result is cached after the first successful call to avoid repeated
    filesystem operations.

    Returns:
        Path to the SQLite database file.
    """
    global _db_path  # noqa: PLW0603  # Module-level cache requires global statement
    if _db_path is not None:
        return _db_path
    db_dir = Path(SOOTHE_HOME)
    db_dir.mkdir(parents=True, exist_ok=True)
    _db_path = db_dir / "sessions.db"
    return _db_path


def generate_loop_id() -> str:
    """Generate a new loop ID as a full UUID7 string.

    Returns:
        UUID7 string (time-ordered for natural sort by creation time).
    """
    from uuid_utils import uuid7

    return str(uuid7())


async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
    """Check if a table exists in the database.

    Returns:
        True if table exists, False otherwise.
    """
    query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
    async with conn.execute(query, (table,)) as cursor:
        return await cursor.fetchone() is not None


async def list_loops_via_daemon_rpc(
    daemon_session: Any,
    limit: int = 20,
    sort_by: str = "updated",
) -> list[LoopInfo]:
    """List StrangeLoop instances via daemon WebSocket RPC (RFC-504).

    Queries daemon's loop persistence (per-loop metadata.json files)
    instead of only local SQLite checkpoint walks.

    Args:
        daemon_session: TuiDaemonSession instance for WebSocket RPC.
        limit: Maximum number of loops to return.
        sort_by: Sort field — `"updated"` or `"created"`.

    Returns:
        List of `LoopInfo` dicts with `loop_id`, `status`, context counts,
            `goals`, `switches`, `created`.

    Raises:
        ValueError: If `sort_by` is not `"updated"` or `"created"`.
        RuntimeError: If daemon session is not available.
    """
    if daemon_session is None:
        raise RuntimeError("Daemon session required for loop listing")

    if sort_by not in {"updated", "created"}:
        msg = f"Invalid sort_by {sort_by!r}; expected 'updated' or 'created'"
        raise ValueError(msg)

    list_method = getattr(daemon_session, "list_loops", None)
    if not callable(list_method):
        raise RuntimeError("Daemon session does not support loop_list RPC")

    try:
        resp = await list_method(limit=limit)
    except Exception:
        logger.warning("loop_list RPC failed", exc_info=True)
        return []

    loops_data = resp.get("loops", [])
    if not isinstance(loops_data, list):
        loops_data = []

    # Convert daemon response to LoopInfo format
    loops: list[LoopInfo] = []
    for loop_data in loops_data[:limit]:  # Apply limit
        if not isinstance(loop_data, dict):
            continue
        loop_info: LoopInfo = {
            "loop_id": str(loop_data.get("loop_id", "")),
            "status": str(loop_data.get("status", "unknown")),
            "threads": int(loop_data.get("threads", 0)),
            "goals": int(loop_data.get("goals", 0)),
            "switches": int(loop_data.get("switches", 0)),
            "created": str(loop_data.get("created", "")),
        }
        updated_raw = loop_data.get("updated_at") or loop_data.get("last_message_at")
        if isinstance(updated_raw, str) and updated_raw:
            # Keep the full ISO string (with the ``+HH:MM`` suffix) so
            # ``format_timestamp`` / ``format_relative_timestamp`` can parse
            # it as an aware datetime and convert to local time. Truncating
            # to [:16] here would silently strip the timezone offset and
            # render UTC as local — the same bug we just fixed daemon-side
            # for ``created``.
            loop_info["updated"] = updated_raw
        prompt_text = loop_data.get("prompt")
        if isinstance(prompt_text, str) and prompt_text.strip():
            loop_info["prompt"] = prompt_text.strip()
        human = loop_data.get("human_messages")
        ai = loop_data.get("ai_messages")
        if isinstance(human, int) or isinstance(ai, int):
            loop_info["messages"] = int(human or 0) + int(ai or 0)
        dur = loop_data.get("duration_ms")
        if isinstance(dur, int):
            loop_info["duration_ms"] = dur
        live = loop_data.get("live")
        if isinstance(live, bool):
            loop_info["live"] = live
        loops.append(loop_info)

    return loops


async def get_most_recent(agent_name: str | None = None) -> str | None:
    """Return the most recent loop id from local SQLite, optionally filtered by agent.

    Returns:
        Loop id (``checkpoints.thread_id``), or `None` when the database is empty.
    """
    async with _connect() as conn:
        if not await _table_exists(conn, "checkpoints"):
            return None

        if agent_name:
            query = """
                SELECT thread_id FROM checkpoints
                WHERE json_extract(metadata, '$.agent_name') = ?
                ORDER BY checkpoint_id DESC
                LIMIT 1
            """
            params: tuple = (agent_name,)
        else:
            query = "SELECT thread_id FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1"
            params = ()

        async with conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def get_loop_agent(loop_id: str) -> str | None:
    """Return ``agent_name`` metadata for a loop id.

    Returns:
        Agent name from checkpoint row metadata, or `None` if not found.
    """
    async with _connect() as conn:
        if not await _table_exists(conn, "checkpoints"):
            return None

        query = """
            SELECT json_extract(metadata, '$.agent_name')
            FROM checkpoints
            WHERE thread_id = ?
            LIMIT 1
        """
        async with conn.execute(query, (loop_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def loop_exists(loop_id: str) -> bool:
    """Return True if any checkpoint row exists for this loop id.

    Returns:
        True if a checkpoint row exists, False otherwise.
    """
    async with _connect() as conn:
        if not await _table_exists(conn, "checkpoints"):
            return False

        query = "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1"
        async with conn.execute(query, (loop_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def find_similar_loops(loop_id: str, limit: int = 3) -> list[str]:
    """Find loop ids that share the given prefix.

    Args:
        loop_id: Prefix to match against `checkpoints.thread_id`.
        limit: Maximum number of matches.

    Returns:
        Matching loop ids (SQLite ``thread_id`` column values).
    """
    async with _connect() as conn:
        if not await _table_exists(conn, "checkpoints"):
            return []

        query = """
            SELECT DISTINCT thread_id
            FROM checkpoints
            WHERE thread_id LIKE ?
            ORDER BY thread_id
            LIMIT ?
        """
        prefix = loop_id + "%"
        async with conn.execute(query, (prefix, limit)) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


def get_loop_limit() -> int:
    """Default maximum loops to load for `/resume` when no explicit limit is set.

    Reads ``DA_CLI_RECENT_LOOPS``, then the legacy alias ``DA_CLI_RECENT_THREADS``,
    then defaults to ``20``.

    Returns:
        A positive integer (falls back to ``20`` when unset or invalid).
    """
    import os

    raw = os.environ.get("DA_CLI_RECENT_LOOPS") or os.environ.get("DA_CLI_RECENT_THREADS", "20")
    try:
        n = int(str(raw).strip(), 10)
    except ValueError:
        return 20
    return max(1, n)
