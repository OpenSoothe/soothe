"""Loop-scoped WebSocket helpers for integration tests (RFC-503).

These wrap ``request_response`` / subscribe flows so tests use the daemon's
``loop_*`` RPC types directly—no production backward-compat layer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from soothe_sdk.client import WebSocketClient


async def loop_new(
    client: WebSocketClient,
    *,
    workspace: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Create a loop and return ``loop_id`` (waits for ``loop_new_response``)."""
    payload: dict[str, Any] = {"type": "loop_new"}
    if workspace:
        payload["workspace"] = workspace
    resp = await client.request_response(
        payload,
        response_type="loop_new_response",
        timeout=timeout,
    )
    return str(resp["loop_id"])


async def loop_new_with_initial_input(
    client: WebSocketClient,
    *,
    initial_message: str | None = None,
    workspace: str | None = None,
) -> str:
    """Create a loop and optionally send the first ``loop_input``."""
    loop_id = await loop_new(client, workspace=workspace)
    if initial_message:
        await client.send_loop_input(loop_id, initial_message)
    return loop_id


async def subscribe_loop_stream(
    client: WebSocketClient,
    loop_id: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Subscribe and wait until ``subscription_confirmed`` matches ``loop_id``."""
    await client.send_loop_subscribe(loop_id)
    deadline = asyncio.get_running_loop().time() + timeout
    msg = f"Timed out waiting for subscription_confirmed for loop {loop_id!r}"
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(msg)
        try:
            ev = await asyncio.wait_for(
                client.read_event(),
                timeout=max(remaining, 0.001),
            )
        except TimeoutError as e:
            raise TimeoutError(msg) from e
        if ev is None:
            continue
        if ev.get("type") == "subscription_confirmed" and ev.get("loop_id") == loop_id:
            return ev


async def request_loop_list(
    client: WebSocketClient,
    *,
    limit: int = 20,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return ``loop_list_response``."""
    return await client.request_response(
        {"type": "loop_list", "limit": limit},
        response_type="loop_list_response",
        timeout=timeout,
    )


async def request_loop_get(
    client: WebSocketClient,
    loop_id: str,
    *,
    verbose: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return ``loop_get_response``."""
    return await client.request_response(
        {"type": "loop_get", "loop_id": loop_id, "verbose": verbose},
        response_type="loop_get_response",
        timeout=timeout,
    )


async def request_loop_delete(
    client: WebSocketClient,
    loop_id: str,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Return ``loop_delete_response``."""
    return await client.request_response(
        {"type": "loop_delete", "loop_id": loop_id},
        response_type="loop_delete_response",
        timeout=timeout,
    )
