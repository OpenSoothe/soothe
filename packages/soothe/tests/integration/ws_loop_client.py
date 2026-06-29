"""Loop-scoped WebSocket helpers for integration tests (RFC-503, RFC-450).

These wrap the protocol-1 ``request`` / ``subscribe`` / ``notify`` flows so
tests use the daemon's ``loop_*`` RPC methods directly — no legacy
backward-compat layer.
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
    """Create a loop and return ``loop_id`` (waits for the protocol-1 response)."""
    params: dict[str, Any] = {}
    if workspace:
        params["workspace"] = workspace
    resp = await client.request("loop_new", params, timeout=timeout)
    return str(resp["loop_id"])


async def loop_new_with_initial_input(
    client: WebSocketClient,
    *,
    initial_message: str | None = None,
    workspace: str | None = None,
) -> str:
    """Create a loop, subscribe for events, and optionally send the first ``loop_input``.

    Subscription is required so the daemon accepts ``loop_input`` (it rejects
    input from unsubscribed clients with ``LOOP_NOT_SUBSCRIBED``) and so the
    caller receives the turn's stream events.
    """
    loop_id = await loop_new(client, workspace=workspace)
    await subscribe_loop_stream(client, loop_id)
    if initial_message:
        await client.notify("loop_input", {"loop_id": loop_id, "content": initial_message})
    return loop_id


async def subscribe_loop_stream(
    client: WebSocketClient,
    loop_id: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Subscribe and wait until ``subscription_confirmed`` matches ``loop_id``."""
    await client.subscribe(
        "loop_events",
        {"loop_id": loop_id},
        timeout=timeout,
    )
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
    """Return the ``loop_list`` result dict (protocol-1 response ``result``)."""
    return await client.request("loop_list", {"limit": limit}, timeout=timeout)


async def request_loop_get(
    client: WebSocketClient,
    loop_id: str,
    *,
    verbose: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return the ``loop_get`` result dict (protocol-1 response ``result``)."""
    return await client.request(
        "loop_get",
        {"loop_id": loop_id, "verbose": verbose},
        timeout=timeout,
    )


async def request_loop_delete(
    client: WebSocketClient,
    loop_id: str,
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Return the ``loop_delete`` result dict (protocol-1 response ``result``)."""
    return await client.request("loop_delete", {"loop_id": loop_id}, timeout=timeout)
