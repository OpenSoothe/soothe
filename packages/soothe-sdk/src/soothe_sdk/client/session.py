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
    workspace: str | Path | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    stream_delivery: str = "adaptive",
    is_ephemeral: bool = False,
    daemon_ready_timeout_s: float = _DAEMON_READY_TIMEOUT_S,
    subscribe_timeout_s: float = _SESSION_BOOTSTRAP_TIMEOUT_S,
) -> dict[str, Any]:
    """Handshake with the daemon, create or attach to a loop, and subscribe for events.

    Args:
        client: ``WebSocketClient`` instance (connected).
        resume_loop_id: If set, subscribe to this existing loop. Otherwise create ``loop_new``.
        stream_delivery: Daemon stream shaping — one of ``batch`` | ``adaptive``
            (default, IG-441) | ``streaming``.
        is_ephemeral: When True, loop execution data is GC'd after idle period.
        workspace: Optional client project directory (e.g. user's CWD). Sent as
            ``client_workspace`` on ``loop_new`` and used directly by the runner when set.
            Ignored on resume when the loop already has workspace metadata.
        user_id: Optional user id for ``$SOOTHE_HOME/workspaces/<user>/`` layout.
        client_workspace_id: Optional stable scope when ``workspace`` is omitted.
        daemon_ready_timeout_s: Max seconds for daemon ready handshake.
        subscribe_timeout_s: Max seconds for ``loop_new`` / ``loop_subscribe`` RPCs.

    Returns:
        A dict with at least ``loop_id`` on success, or an ``error`` event-shaped dict.

    Raises:
        TimeoutError: If a waited step times out.
        RuntimeError: If daemon reports not-ready during handshake.
        ConnectionError: If the WebSocket is closed and cannot be re-established.
    """
    alive_check = getattr(client, "is_connection_alive", None)
    if alive_check is not None and not alive_check():
        await client.close()
        await connect_websocket_with_retries(client)

    await client.request_daemon_ready()
    await client.wait_for_daemon_ready(ready_timeout_s=daemon_ready_timeout_s)

    mapping_data: dict[str, Any] | None = None
    autopilot_mode: str | None = None

    if resume_loop_id:
        loop_id = resume_loop_id
    else:
        loop_new_payload: dict[str, Any] = {"type": "loop_new"}
        if workspace is not None:
            workspace_str = str(workspace).strip()
            if workspace_str:
                loop_new_payload["client_workspace"] = workspace_str
        if user_id is not None and str(user_id).strip():
            loop_new_payload["user_id"] = str(user_id).strip()
        if client_workspace_id is not None and str(client_workspace_id).strip():
            loop_new_payload["client_workspace_id"] = str(client_workspace_id).strip()
        if is_ephemeral:
            loop_new_payload["is_ephemeral"] = True
        new_resp = await client.request_response(
            loop_new_payload,
            response_type="loop_new_response",
            timeout=subscribe_timeout_s,
        )
        loop_id = str(new_resp.get("loop_id") or "")
        if not loop_id:
            raise ValueError("loop_new_response missing loop_id")
        raw_mode = new_resp.get("autopilot_mode")
        autopilot_mode = str(raw_mode) if raw_mode in ("solo", "autopilot") else None

        # RFC-621: parse workspace mapping for container path translation
        mapping_data = new_resp.get("workspace_mapping")
        if mapping_data and mapping_data.get("host_root") and mapping_data.get("container_root"):
            from soothe_sdk.client.protocol import WorkspaceMapping

            workspace_mapping = WorkspaceMapping(
                host_root=mapping_data["host_root"],
                container_root=mapping_data["container_root"],
            )
            # Store on client for use in event path translation
            if hasattr(client, "workspace_mapping"):
                client.workspace_mapping = workspace_mapping

    # IG-441: three first-class modes (batch / adaptive / streaming). Unknown
    # values fall back to ``adaptive`` (the new bootstrap default).
    delivery = (
        stream_delivery if stream_delivery in ("batch", "adaptive", "streaming") else "adaptive"
    )
    sub_resp = await client.request_response(
        {
            "type": "loop_subscribe",
            "loop_id": loop_id,
            "stream_delivery": delivery,
        },
        response_type="loop_subscribe_response",
        timeout=subscribe_timeout_s,
    )
    if not sub_resp.get("success", True):
        raise RuntimeError(str(sub_resp.get("message", "loop_subscribe failed")))

    sub_mode = sub_resp.get("autopilot_mode")
    if sub_mode in ("solo", "autopilot"):
        autopilot_mode = str(sub_mode)

    logger.info(
        "Subscribed to loop %s with stream_delivery=%s autopilot_mode=%s",
        loop_id,
        delivery,
        autopilot_mode,
    )
    result: dict[str, Any] = {"type": "session_ready", "loop_id": loop_id, "success": True}
    if autopilot_mode in ("solo", "autopilot"):
        result["autopilot_mode"] = autopilot_mode
    if mapping_data and mapping_data.get("host_root"):
        result["workspace_mapping"] = mapping_data
    return result


__all__ = [
    "bootstrap_loop_session",
    "connect_websocket_with_retries",
]
