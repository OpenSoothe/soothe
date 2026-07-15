"""Loop-scoped WebSocket helpers for integration tests (RFC-503, RFC-450).

These wrap the protocol-1 ``request`` / ``subscribe`` / ``notify`` flows so
tests use the daemon's ``loop_*`` RPC methods directly — no legacy
backward-compat layer.

Under protocol-1, the daemon's ``MessageRouter`` sends response envelopes of
the form ``{proto: "1", type: "response", result: {...}, id: request_id}``.
The SDK's ``request()`` returns ``event.get("result")`` — the ``result`` dict
from the envelope — so every helper here returns the *result* dict, not the
full envelope.
"""

from __future__ import annotations

import asyncio
from typing import Any

from soothe_client import WebSocketClient

from tests.integration.test_timeouts import (
    timeout_default,
    timeout_delete,
    timeout_subscribe,
)


async def loop_new(
    client: WebSocketClient,
    *,
    workspace: str | None = None,
    is_ephemeral: bool = False,
    timeout: float | None = None,
) -> str:
    """Create a loop and return ``loop_id`` (waits for the protocol-1 response)."""
    params: dict[str, Any] = {}
    if workspace:
        params["workspace"] = workspace
    if is_ephemeral:
        params["is_ephemeral"] = True
    effective_timeout = timeout if timeout is not None else timeout_default()
    resp = await client.request("loop_new", params, timeout=effective_timeout)
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
    timeout: float | None = None,
) -> dict[str, Any]:
    """Subscribe to a loop stream and return the protocol-1 subscribe-ack.

    Under protocol-1 (RFC-450 §9.3) the daemon confirms a ``loop_events``
    subscription with a ``next`` envelope carrying ``payload.event == "subscribed"``
    and the subscription ``id``. The SDK ``subscribe()`` already waits for that
    ack (or an error); this helper drains it from the inbound queue so callers
    start a turn with a clean event stream.
    """
    effective_timeout = timeout if timeout is not None else timeout_subscribe()
    sub_id = await client.subscribe(
        "loop_events",
        {"loop_id": loop_id},
        timeout=effective_timeout,
    )
    deadline = asyncio.get_running_loop().time() + effective_timeout
    msg = f"Timed out waiting for subscribe-ack for loop {loop_id!r}"
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
        if ev.get("type") == "next" and ev.get("id") == sub_id:
            payload = ev.get("payload") or {}
            if payload.get("event") == "subscribed":
                return ev
        # Tolerate the first streamed frame arriving before the ack was drained.
        if ev.get("type") == "next":
            return ev


async def request_loop_list(
    client: WebSocketClient,
    *,
    limit: int = 20,
    exclude_empty: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Return the ``loop_list`` result dict (protocol-1 response ``result``)."""
    effective_timeout = timeout if timeout is not None else timeout_default()
    return await client.request(
        "loop_list",
        {"limit": limit, "filter": {"exclude_empty": exclude_empty}},
        timeout=effective_timeout,
    )


async def request_loop_get(
    client: WebSocketClient,
    loop_id: str,
    *,
    verbose: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Return the ``loop_get`` result dict (protocol-1 response ``result``)."""
    effective_timeout = timeout if timeout is not None else timeout_default()
    return await client.request(
        "loop_get",
        {"loop_id": loop_id, "verbose": verbose},
        timeout=effective_timeout,
    )


async def request_loop_delete(
    client: WebSocketClient,
    loop_id: str,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Return the ``loop_delete`` result dict (protocol-1 response ``result``)."""
    effective_timeout = timeout if timeout is not None else timeout_delete()
    return await client.request(
        "loop_delete",
        {"loop_id": loop_id},
        timeout=effective_timeout,
    )
