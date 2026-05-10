"""WebSocket helper functions for daemon communication."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from soothe_sdk.client.websocket import WebSocketClient

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from soothe.config import SootheConfig


def websocket_url_from_config(cfg: SootheConfig) -> str:
    """Construct WebSocket URL from config (standard helper).

    Args:
        cfg: SootheConfig with daemon.transports.websocket settings

    Returns:
        WebSocket URL string (e.g., "ws://127.0.0.1:8765")
    """
    host = cfg.daemon.transports.websocket.host
    port = cfg.daemon.transports.websocket.port
    return f"ws://{host}:{port}"


async def check_daemon_status(
    client: WebSocketClient,
    timeout: float = 5.0,
    *,
    min_interval_s: float = 1.0,
) -> dict:
    """Check daemon status via RPC.

    Uses ``WebSocketClient.fetch_daemon_status`` so rapid or overlapping polls
    on the same connection coalesce into one wire request per ``min_interval_s``.

    Args:
        client: Connected WebSocketClient
        timeout: Request timeout in seconds
        min_interval_s: Minimum seconds between real ``daemon_status`` RPCs; ``0``
            always queries the daemon.

    Returns:
        Parsed `daemon_status_response` payload (typically includes `running`,
        `port_live`, and a numeric count of in-flight client query work).

    Raises:
        ConnectionError: If daemon not reachable
    """
    return await client.fetch_daemon_status(timeout=timeout, min_interval_s=min_interval_s)


def _daemon_status_indicates_live(status: dict) -> bool:
    """Infer liveness from a ``daemon_status_response`` payload.

    Prefer an explicit ``running`` field when present. Older or alternate
    implementations may omit it; a successful RPC response should not be
    treated as dead solely due to a missing key.
    """
    if "running" in status:
        return bool(status["running"])
    return bool(status.get("port_live", True))


async def is_daemon_live(ws_url: str, timeout: float = 5.0) -> bool:
    """Composite health check: connection + status RPC.

    Args:
        ws_url: WebSocket URL to check
        timeout: Total timeout for connection + RPC

    Returns:
        True if daemon is live and responsive, False otherwise
    """
    attempts = 3
    delay_s = 0.35
    last_error: Exception | None = None

    for attempt in range(attempts):
        client: WebSocketClient | None = None
        try:
            client = WebSocketClient(url=ws_url)
            await client.connect()
            status = await check_daemon_status(client, timeout=timeout)
            return _daemon_status_indicates_live(status)
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(delay_s)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.close()

    if last_error is not None:
        logger.debug("Daemon health check failed for %s: %s", ws_url, last_error)
    return False


async def request_daemon_shutdown(client: WebSocketClient, timeout: float = 10.0) -> None:
    """Request daemon shutdown via RPC.

    Args:
        client: Connected WebSocketClient
        timeout: Shutdown timeout in seconds

    Raises:
        RuntimeError: If shutdown fails
    """
    try:
        response = await client.request_response(
            {"type": "daemon_shutdown"}, response_type="shutdown_ack", timeout=timeout
        )
        if response.get("status") != "acknowledged":
            raise RuntimeError(f"Shutdown failed: {response}")
    except Exception as e:
        # Fallback: HTTP REST shutdown endpoint
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post("http://127.0.0.1:8765/api/v1/system/shutdown") as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Shutdown failed: {e}")


async def fetch_skills_catalog(client: WebSocketClient, timeout: float = 15.0) -> list[dict]:
    """Fetch skills catalog via RPC.

    Args:
        client: Connected WebSocketClient
        timeout: Request timeout in seconds

    Returns:
        List of skill metadata dicts (wire-safe, no local parsing)

    Raises:
        ConnectionError: If daemon not reachable
    """
    response = await client.request_response(
        {"type": "skills_list"}, response_type="skills_list_response", timeout=timeout
    )
    return response.get("skills", [])


async def fetch_config_section(client: WebSocketClient, section: str, timeout: float = 5.0) -> dict:
    """Fetch daemon config section via RPC.

    Args:
        client: Connected WebSocketClient
        section: Config section name (e.g., "providers", "defaults")
        timeout: Request timeout in seconds

    Returns:
        Wire-safe config section dict

    Raises:
        ConnectionError: If daemon not reachable
    """
    response = await client.request_response(
        {"type": "config_get", "section": section},
        response_type="config_get_response",
        timeout=timeout,
    )
    return response.get(section, {})
