"""Shared WebSocket session bootstrap for CLI headless and TUI."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_CONNECT_RETRY_COUNT = 40
_CONNECT_RETRY_DELAY_S = 0.25
_CONNECT_TIMEOUT_S = 5.0
_DAEMON_READY_TIMEOUT_S = 20.0
_SESSION_BOOTSTRAP_TIMEOUT_S = 5.0


def websocket_url_from_config(cfg: SootheConfig) -> str:
    """Build WebSocket URL from daemon transport settings."""
    host = cfg.daemon.transports.websocket.host
    port = cfg.daemon.transports.websocket.port
    return f"ws://{host}:{port}"


async def connect_websocket_with_retries(client: object) -> None:
    """Connect to the daemon with bounded retries for cold-start races."""
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


async def _wait_for_thread_status(client: object, *, timeout_s: float) -> dict[str, Any]:
    """Wait for a status event that includes ``thread_id``, skipping empty handshakes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for thread status from daemon")

        event = await asyncio.wait_for(client.read_event(), timeout=remaining)
        if not event:
            raise ValueError("No event received")

        if event.get("type") == "error":
            return event

        if event.get("type") != "status":
            continue

        thread_id = event.get("thread_id")
        if thread_id:
            return event


async def bootstrap_thread_session(
    client: object,
    *,
    resume_thread_id: str | None,
    verbosity: str,
    daemon_ready_timeout_s: float = _DAEMON_READY_TIMEOUT_S,
    thread_status_timeout_s: float = _SESSION_BOOTSTRAP_TIMEOUT_S,
    subscription_timeout_s: float = _SESSION_BOOTSTRAP_TIMEOUT_S,
) -> dict[str, Any]:
    """Run daemon ready handshake, create or resume a thread, and subscribe.

    Args:
        client: ``WebSocketClient`` instance (connected).
        resume_thread_id: If set, send ``resume_thread``; else ``new_thread``.
        verbosity: Subscription / progress verbosity string.
        daemon_ready_timeout_s: Max seconds for daemon ready handshake.
        thread_status_timeout_s: Max seconds to obtain a status with ``thread_id``.
        subscription_timeout_s: Max seconds for subscription confirmation.

    Returns:
        The terminal ``status`` event dict (includes ``thread_id``) on success,
        or an ``error`` event dict if the daemon reported an error (e.g. thread
        not found).

    Raises:
        TimeoutError: If a waited step times out.
        ValueError: On unexpected protocol responses.
        RuntimeError: If daemon reports not-ready during handshake.
    """
    await client.request_daemon_ready()
    await client.wait_for_daemon_ready(ready_timeout_s=daemon_ready_timeout_s)

    if resume_thread_id:
        await client.send_resume_thread(resume_thread_id)
    else:
        await client.send_new_thread()

    status_event = await _wait_for_thread_status(client, timeout_s=thread_status_timeout_s)

    if status_event.get("type") == "error":
        return status_event

    actual_thread_id = status_event.get("thread_id")
    if not actual_thread_id:
        raise ValueError("No thread_id in status message")

    await client.subscribe_thread(actual_thread_id, verbosity=verbosity)
    await client.wait_for_subscription_confirmed(
        actual_thread_id,
        verbosity=verbosity,
        timeout=subscription_timeout_s,
    )
    logger.info("Subscribed to thread %s with verbosity=%s", actual_thread_id, verbosity)

    return status_event
