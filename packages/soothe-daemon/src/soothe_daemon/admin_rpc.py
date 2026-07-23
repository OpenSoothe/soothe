"""One-shot admin RPCs over the daemon WebSocket (sdk wire only).

Used by `soothed` admin commands that must talk to a running daemon without
depending on soothe-client-python (client sits above the daemon in the DAG).
"""

from __future__ import annotations

import asyncio
import importlib.metadata
from typing import Any, cast
from uuid import uuid4

from soothe_sdk.wire.codec import (
    ConnectionInitEnvelope,
    ConnectionInitParams,
    ErrorEnvelope,
    MessageType,
    WireEnvelope,
    decode_envelope,
    encode_envelope,
)

_TRANSITIONAL_STATES = frozenset({"starting", "warming"})
_READY_POLL_INTERVAL_S = 0.05


def _client_version() -> str:
    try:
        return importlib.metadata.version("soothe-daemon")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


async def _perform_handshake(ws: Any, *, timeout: float) -> None:
    """Complete protocol-1 ``connection_init`` / ``connection_ack``."""
    init = ConnectionInitEnvelope(
        params=ConnectionInitParams(
            client_version=_client_version(),
            client_name="soothed",
            accept_proto=["1"],
            capabilities=["streaming", "batch", "heartbeat"],
        )
    )

    async with asyncio.timeout(timeout):
        await ws.send(encode_envelope(init))
        while True:
            response_str = await ws.recv()
            response = decode_envelope(response_str)
            if not isinstance(response, dict):
                continue

            msg_type = response.get("type")
            if msg_type == "status":
                continue

            if msg_type == MessageType.ERROR.value:
                err = ErrorEnvelope.from_wire_dict(response)
                raise RuntimeError(
                    f"[{err.code}] {err.message}" + (f" ({err.data})" if err.data else "")
                )

            if msg_type != "connection_ack":
                continue

            result = response.get("result") or {}
            state = result.get("readiness_state")
            if state == "ready":
                return
            if state == "incompatible":
                raise RuntimeError(
                    "Protocol version incompatible: "
                    f"daemon returned {result.get('protocol_version')!r}"
                )
            if state == "error":
                raise RuntimeError(
                    "Daemon startup failed. Check soothed logs, then restart and retry."
                )
            if state == "degraded":
                raise RuntimeError(
                    "Daemon is degraded. Check soothed health, then restart and retry."
                )
            if state == "stopped":
                raise RuntimeError(
                    "Daemon is stopped (not accepting clients). "
                    "Start or restart soothed, then retry."
                )
            if state in _TRANSITIONAL_STATES:
                await asyncio.sleep(_READY_POLL_INTERVAL_S)
                await ws.send(encode_envelope(init))
                continue
            raise RuntimeError(f"Daemon state is {state}")


async def send_admin_request(
    ws_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send a protocol-1 request and return the ``result`` dict.

    Args:
        ws_url: Daemon WebSocket URL (e.g. ``ws://127.0.0.1:8765``).
        method: RPC method name (e.g. ``memory_stats``).
        params: Structured parameters for the method.
        timeout: Per-command timeout in seconds.

    Returns:
        The ``result`` payload from the matching ``response`` envelope.

    Raises:
        RuntimeError: On handshake failure, error envelope, timeout, or disconnect.
    """
    import websockets

    req_id = str(uuid4())
    envelope = WireEnvelope(
        type=MessageType.REQUEST.value,
        method=method,
        params=params or {},
        id=req_id,
    )

    try:
        async with websockets.connect(ws_url, open_timeout=timeout) as ws:
            await _perform_handshake(ws, timeout=timeout)
            await ws.send(encode_envelope(envelope))

            while True:
                response_str = await asyncio.wait_for(ws.recv(), timeout=timeout)
                response = decode_envelope(response_str)
                if not isinstance(response, dict):
                    raise RuntimeError(f"Unexpected response: {response_str!r}")

                msg_type = response.get("type")
                if msg_type == MessageType.ERROR.value:
                    err = ErrorEnvelope.from_wire_dict(response)
                    raise RuntimeError(
                        f"[{err.code}] {err.message}" + (f" ({err.data})" if err.data else "")
                    )

                if msg_type == MessageType.RESPONSE.value:
                    if response.get("id") != req_id:
                        continue
                    result = response.get("result") or {}
                    if not isinstance(result, dict):
                        raise RuntimeError(f"Unexpected result payload: {result!r}")
                    return cast(dict[str, Any], result)

    except TimeoutError:
        raise RuntimeError(f"Command timeout after {timeout}s") from None
    except websockets.exceptions.ConnectionClosedError as exc:
        raise RuntimeError(f"WebSocket connection closed: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Command failed: {exc}") from exc


def memory_stats(ws_url: str, mode: str = "daemon", *, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch daemon memory profiling stats (sync wrapper for ``soothed memory``)."""
    return asyncio.run(send_admin_request(ws_url, "memory_stats", {"mode": mode}, timeout=timeout))
