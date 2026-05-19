"""Shared WebSocket session bootstrap for CLI headless and TUI."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONNECT_RETRY_COUNT = 40
_CONNECT_RETRY_DELAY_S = 0.25
_CONNECT_TIMEOUT_S = 5.0
_DAEMON_READY_TIMEOUT_S = 20.0
_SESSION_BOOTSTRAP_TIMEOUT_S = 30.0


async def connect_websocket_with_retries(client: Any) -> None:
    """Connect to the daemon with bounded retries for cold-start races.

    Args:
        client: WebSocketClient instance.

    Raises:
        ConnectionError: If connection fails after all retries.
    """
    last_error: OSError | ConnectionError | TimeoutError | None = None
    for attempt in range(_CONNECT_RETRY_COUNT):
        try:
            await asyncio.wait_for(client.connect(), timeout=_CONNECT_TIMEOUT_S)
        except (ConnectionRefusedError, OSError, ConnectionError, TimeoutError) as exc:
            last_error = exc
            if attempt == _CONNECT_RETRY_COUNT - 1:
                raise
            await asyncio.sleep(_CONNECT_RETRY_DELAY_S)
        else:
            return

    if last_error is not None:
        raise last_error


async def bootstrap_loop_session(
    client: Any,
    *,
    resume_loop_id: str | None,
    verbosity: str,
    workspace: str | Path | None = None,
    stream_delivery: str = "merged",
    daemon_ready_timeout_s: float = _DAEMON_READY_TIMEOUT_S,
    subscribe_timeout_s: float = _SESSION_BOOTSTRAP_TIMEOUT_S,
) -> dict[str, Any]:
    """Handshake with the daemon, create or attach to a loop, and subscribe for events.

    Args:
        client: ``WebSocketClient`` instance (connected).
        resume_loop_id: If set, subscribe to this existing loop. Otherwise create ``loop_new``.
        verbosity: Event verbosity for ``loop_subscribe``.
        stream_delivery: Daemon stream shaping — ``merged`` (default), ``batch``, or ``full``.
        workspace: Optional client workspace hint (e.g., user's CWD). Forwarded to the
            daemon on ``loop_new`` so filesystem tools default to the user's project
            directory instead of the per-loop daemon scratch dir (IG-409). Ignored on
            resume since the existing loop already has a workspace recorded.
        daemon_ready_timeout_s: Max seconds for daemon ready handshake.
        subscribe_timeout_s: Max seconds for ``loop_new`` / ``loop_subscribe`` RPCs.

    Returns:
        A dict with at least ``loop_id`` on success, or an ``error`` event-shaped dict.

    Raises:
        TimeoutError: If a waited step times out.
        RuntimeError: If daemon reports not-ready during handshake.
    """
    await client.request_daemon_ready()
    await client.wait_for_daemon_ready(ready_timeout_s=daemon_ready_timeout_s)

    if resume_loop_id:
        loop_id = resume_loop_id
    else:
        loop_new_payload: dict[str, Any] = {"type": "loop_new"}
        if workspace is not None:
            workspace_str = str(workspace).strip()
            if workspace_str:
                loop_new_payload["workspace"] = workspace_str
        new_resp = await client.request_response(
            loop_new_payload,
            response_type="loop_new_response",
            timeout=subscribe_timeout_s,
        )
        loop_id = str(new_resp.get("loop_id") or "")
        if not loop_id:
            raise ValueError("loop_new_response missing loop_id")

    delivery = stream_delivery if stream_delivery in ("batch", "merged", "full") else "merged"
    sub_resp = await client.request_response(
        {
            "type": "loop_subscribe",
            "loop_id": loop_id,
            "verbosity": verbosity,
            "stream_delivery": delivery,
        },
        response_type="loop_subscribe_response",
        timeout=subscribe_timeout_s,
    )
    if not sub_resp.get("success", True):
        raise RuntimeError(str(sub_resp.get("message", "loop_subscribe failed")))

    logger.info(
        "Subscribed to loop %s with verbosity=%s stream_delivery=%s",
        loop_id,
        verbosity,
        delivery,
    )
    return {"type": "session_ready", "loop_id": loop_id, "success": True}


__all__ = [
    "bootstrap_loop_session",
    "connect_websocket_with_retries",
]
