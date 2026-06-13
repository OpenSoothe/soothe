"""WebSocket helper functions for daemon communication."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from soothe_sdk.client.websocket import WebSocketClient

logger = logging.getLogger(__name__)


def websocket_url_from_config(cfg: Any) -> str:
    """Construct WebSocket URL from a config-like object.

    Duck-typed across the three workspace configs:

    * ``CLIConfig`` (`soothe-cli`) exposes ``daemon_host`` / ``daemon_port``
      and a ``websocket_url()`` helper.
    * ``SootheDaemonConfig`` (`soothe-daemon`) exposes
      ``transports.websocket.host`` / ``.port``.
    * Legacy callers may still pass an object with
      ``daemon.transports.websocket.host`` / ``.port``.

    The SDK deliberately does not import any of those classes — keeping
    `soothe_sdk` independent of `soothe`, `soothe_cli`, and `soothe_daemon`.

    Args:
        cfg: Any object exposing one of the shapes above.

    Returns:
        WebSocket URL string (e.g., ``"ws://127.0.0.1:8765"``).

    Raises:
        AttributeError: If ``cfg`` exposes none of the supported shapes.
    """
    if hasattr(cfg, "websocket_url") and callable(cfg.websocket_url):
        url = cfg.websocket_url()
        if isinstance(url, str) and url:
            return url

    if hasattr(cfg, "daemon_host") and hasattr(cfg, "daemon_port"):
        return f"ws://{cfg.daemon_host}:{cfg.daemon_port}"

    transports = getattr(cfg, "transports", None)
    if transports is None:
        daemon = getattr(cfg, "daemon", None)
        transports = getattr(daemon, "transports", None) if daemon is not None else None

    if transports is not None:
        websocket = getattr(transports, "websocket", None)
        if websocket is not None:
            return f"ws://{websocket.host}:{websocket.port}"

    raise AttributeError(
        "websocket_url_from_config: object does not expose websocket settings; "
        "expected daemon_host/daemon_port, transports.websocket, or "
        "daemon.transports.websocket"
    )


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

    Checks readiness_state first (IG-489): transitional states (starting, warming)
    indicate the daemon is not yet ready to handle loops. Falls back to legacy
    ``running``/``port_live`` check for older daemons without this field.

    Args:
        status: Daemon status response dict.

    Returns:
        True if daemon is live and ready for loop operations, False otherwise.
    """
    # Check readiness_state first (new field, IG-489)
    readiness_state = status.get("readiness_state")
    if readiness_state:
        # Transitional states mean daemon is not ready for loops
        if readiness_state in {"starting", "warming"}:
            return False
        # Terminal error/degraded/stopped states
        if readiness_state in {"error", "degraded", "stopped"}:
            return False
        # Only "ready" is truly live for loop operations
        if readiness_state == "ready":
            return True
        # Unknown state - fall through to legacy check

    # Legacy check (for older daemons without readiness_state)
    if "running" in status:
        return bool(status["running"])
    return bool(status.get("port_live", True))


async def is_daemon_live(
    ws_url: str,
    timeout: float = 5.0,
    wait_for_ready: bool = False,
    ready_timeout: float = 30.0,
) -> bool:
    """Composite health check: connection + status RPC.

    Optionally waits for daemon to reach "ready" state (IG-489), polling during
    transitional states like "starting" and "warming".

    Args:
        ws_url: WebSocket URL to check
        timeout: Per-request timeout for connection + RPC
        wait_for_ready: If True, poll until daemon is "ready" (not transitional)
        ready_timeout: Max seconds to wait for ready state when wait_for_ready=True

    Returns:
        True if daemon is live (and ready if wait_for_ready=True), False otherwise
    """
    attempts = 3
    delay_s = 0.35
    last_error: Exception | None = None

    # When waiting for ready, we need to poll during transitional states
    if wait_for_ready:
        # Use monotonic time via asyncio for consistent timing
        try:
            loop = asyncio.get_running_loop()
            start_time = loop.time()
        except RuntimeError:
            start_time = 0.0

        while True:
            for attempt in range(attempts):
                client: WebSocketClient | None = None
                try:
                    client = WebSocketClient(url=ws_url)
                    await client.connect()
                    status = await check_daemon_status(client, timeout=timeout)

                    # Check if daemon is ready
                    readiness_state = status.get("readiness_state")
                    if readiness_state == "ready":
                        return True

                    # Check if transitional - continue polling
                    if readiness_state in {"starting", "warming"}:
                        # Calculate remaining time
                        try:
                            loop = asyncio.get_running_loop()
                            elapsed = loop.time() - start_time
                        except RuntimeError:
                            elapsed = 0.0

                        if elapsed >= ready_timeout:
                            logger.debug(
                                "Daemon not ready after %s seconds (state: %s)",
                                ready_timeout,
                                readiness_state,
                            )
                            return False
                        # Wait and retry
                        await asyncio.sleep(delay_s)
                        break  # Exit attempt loop, continue polling

                    # Terminal state (error, degraded, stopped) or unknown
                    return _daemon_status_indicates_live(status)
                except Exception as exc:
                    last_error = exc
                    if attempt < attempts - 1:
                        await asyncio.sleep(delay_s)
                finally:
                    if client is not None:
                        with contextlib.suppress(Exception):
                            await client.close()

            # Check timeout after exhausting attempts
            try:
                loop = asyncio.get_running_loop()
                elapsed = loop.time() - start_time
            except RuntimeError:
                elapsed = 0.0

            if elapsed >= ready_timeout:
                break

        if last_error is not None:
            logger.debug("Daemon health check failed for %s: %s", ws_url, last_error)
        return False

    # Standard liveness check without waiting
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
