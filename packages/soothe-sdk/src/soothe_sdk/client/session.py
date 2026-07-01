"""Shared WebSocket session bootstrap for CLI headless and TUI."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from soothe_sdk.client.wire import ProtocolError

logger = logging.getLogger(__name__)

_CONNECT_RETRY_COUNT = 40
_CONNECT_RETRY_DELAY_S = 0.25
_CONNECT_TIMEOUT_S = 5.0
_DAEMON_READY_TIMEOUT_S = 20.0
_SESSION_BOOTSTRAP_TIMEOUT_S = 30.0

# Wire-compat: interactive loops are always solo; daemon jobs use AutopilotService.
_LEGACY_LOOP_AUTOPILOT_MODE = "solo"


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

    Uses the protocol-1 wire contract (RFC-450): ``connection_init``/``ack``
    handshake, then ``request('loop_new')`` or ``request('loop_reattach')`` for
    resume, then ``subscribe('loop_events')`` for the event stream.

    Args:
        client: ``WebSocketClient`` instance (connected).
        resume_loop_id: If set, reattach to this existing loop via
            ``loop_reattach``. Otherwise create a new loop via ``loop_new``.
        stream_delivery: Daemon stream shaping — one of ``batch`` | ``adaptive``
            (default, IG-441) | ``streaming``.
        is_ephemeral: When True, loop execution data is GC'd after idle period.
        workspace: Optional client project directory (e.g. user's CWD). Sent as
            ``workspace`` on ``loop_new`` and used directly by the runner when set.
            Ignored on resume when the loop already has workspace metadata.
        user_id: Optional user id for ``$SOOTHE_HOME/workspaces/<user>/`` layout.
        client_workspace_id: Optional stable scope when ``workspace`` is omitted.
        daemon_ready_timeout_s: Max seconds for connection_ack handshake.
        subscribe_timeout_s: Max seconds for ``loop_new`` / ``loop_reattach`` /
            ``loop_events`` RPCs.

    Returns:
        A dict with at least ``loop_id`` on success, or an ``error`` event-shaped dict.

    Raises:
        TimeoutError: If a waited step times out.
        RuntimeError: If daemon reports not-ready during handshake.
        ConnectionError: If the WebSocket is closed and cannot be re-established.
        ProtocolError: If the daemon returns a protocol-level error for
            ``loop_new``, ``loop_reattach``, or the ``loop_events`` subscription.
    """
    alive_check = getattr(client, "is_connection_alive", None)
    if alive_check is not None and not alive_check():
        await client.close()
        await connect_websocket_with_retries(client)

    await client.request_connection_init()
    await client.wait_for_connection_ack(ack_timeout_s=daemon_ready_timeout_s)

    mapping_data: dict[str, Any] | None = None

    if resume_loop_id:
        # Resume path: reattach to the existing loop via ``loop_reattach`` so the
        # daemon replays card history before we subscribe to the live event stream.
        reattach_params: dict[str, Any] = {"loop_id": resume_loop_id}
        try:
            await client.request(
                "loop_reattach",
                reattach_params,
                timeout=subscribe_timeout_s,
            )
        except ProtocolError:
            logger.warning(
                "loop_reattach failed for loop %s; subscribing without replay",
                resume_loop_id,
                exc_info=True,
            )
        loop_id = resume_loop_id
    else:
        # New-loop path: ``loop_new`` creates the conversation. Per RFC-450 §10.1
        # the field is ``workspace`` (renamed from ``client_workspace``).
        loop_new_params: dict[str, Any] = {}
        if workspace is not None:
            workspace_str = str(workspace).strip()
            if workspace_str:
                loop_new_params["workspace"] = workspace_str
        if user_id is not None and str(user_id).strip():
            loop_new_params["user_id"] = str(user_id).strip()
        if client_workspace_id is not None and str(client_workspace_id).strip():
            loop_new_params["client_workspace_id"] = str(client_workspace_id).strip()
        if is_ephemeral:
            loop_new_params["is_ephemeral"] = True
        # ``request`` raises ``ProtocolError`` if the daemon returns an error
        # envelope (e.g. INVALID_PARAMS, WORKSPACE_RESOLUTION_FAILED). Let it
        # propagate — bootstrap cannot continue without a valid loop_id.
        new_resp = await client.request(
            "loop_new",
            loop_new_params,
            timeout=subscribe_timeout_s,
        )
        loop_id = str(new_resp.get("loop_id") or "")
        if not loop_id:
            raise ValueError("loop_new response missing loop_id")

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
    # Subscribe to the loop's event stream. Protocol-1 uses ``subscribe`` with
    # the ``loop_events`` target — the subscription is confirmed implicitly
    # (RFC-450 §9.4). If the daemon cannot honour it, an ``error`` with the
    # subscription ``id`` arrives within the timeout window and ``subscribe``
    # raises ``ProtocolError``.
    await client.subscribe(
        "loop_events",
        {
            "loop_id": loop_id,
            "stream_delivery": delivery,
            "wire_tier": "full",
        },
        timeout=subscribe_timeout_s,
    )

    logger.info(
        "Subscribed to loop %s with stream_delivery=%s",
        loop_id,
        delivery,
    )
    result: dict[str, Any] = {
        "type": "session_ready",
        "loop_id": loop_id,
        "success": True,
        # Deprecated wire field: interactive loops are always solo.
        "autopilot_mode": _LEGACY_LOOP_AUTOPILOT_MODE,
    }
    if mapping_data and mapping_data.get("host_root"):
        result["workspace_mapping"] = mapping_data
    return result


__all__ = [
    "bootstrap_loop_session",
    "connect_websocket_with_retries",
]
