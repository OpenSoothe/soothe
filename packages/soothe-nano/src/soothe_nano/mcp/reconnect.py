"""Exponential-backoff reconnect scheduler for remote transports (RFC-412).

Remote transports (SSE, streamable_http, websocket) auto-reconnect on disconnect.
Stdio servers do NOT auto-reconnect (parity with Claude Code).

Constants:
- MAX_RECONNECT_ATTEMPTS = 5
- INITIAL_BACKOFF_S = 1.0
- MAX_BACKOFF_S = 30.0
- JITTER_S = 0.5

Algorithm:
backoff = min(MAX, INITIAL * 2^attempt) + random(0, JITTER)
"""

from __future__ import annotations

import asyncio
import logging
import random

from soothe_nano.config.models import MCPServerConfig

logger = logging.getLogger(__name__)

__all__ = ["schedule_reconnect", "cancel_reconnect"]

# Constants (mirrors Claude Code)
MAX_RECONNECT_ATTEMPTS = 5
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 30.0
JITTER_S = 0.5

# Active reconnect tasks
_active_reconnects: dict[str, asyncio.Task] = {}


def compute_backoff(attempt: int) -> float:
    """Compute exponential backoff with jitter.

    Args:
        attempt: Reconnect attempt number (0-indexed).

    Returns:
        Backoff duration in seconds.
    """
    base = INITIAL_BACKOFF_S * (2**attempt)
    capped = min(base, MAX_BACKOFF_S)
    jitter = random.uniform(0, JITTER_S)
    return capped + jitter


async def schedule_reconnect(
    registry: object,
    name: str,
    server_cfg: MCPServerConfig,
) -> None:
    """Schedule exponential-backoff reconnect for a remote server.

    Args:
        registry: MCPRegistry instance.
        name: Server name.
        server_cfg: MCPServerConfig for the server.
    """
    # Cancel any existing reconnect task
    cancel_reconnect(name)

    async def reconnect_loop():
        from soothe_nano.mcp.mcp_events import (
            emit_server_connect_failed,
            emit_server_reconnecting,
        )

        mcp_registry = registry  # type: MCPRegistry
        conn = mcp_registry._connections.get(name)

        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            backoff_s = compute_backoff(attempt)

            logger.info(
                "[MCP] Reconnecting %s (attempt %d/%d, backoff %.1fs)",
                name,
                attempt + 1,
                MAX_RECONNECT_ATTEMPTS,
                backoff_s,
            )

            emit_server_reconnecting(name, attempt + 1, backoff_s)

            # Wait with backoff
            await asyncio.sleep(backoff_s)

            # Update connection status
            if conn:
                conn.status = "reconnecting"
                conn.reconnect_attempt = attempt + 1

            # Try to reconnect
            try:
                await mcp_registry._connect_server(name)
                # Success — update status and exit loop
                if conn:
                    conn.status = "connected"
                    conn.reconnect_attempt = 0
                logger.info("[MCP] %s reconnected successfully", name)
                return

            except Exception as e:
                logger.warning("[MCP] Reconnect attempt %d failed for %s: %s", attempt + 1, name, e)

        # Exhausted attempts — mark terminal
        logger.error("[MCP] %s reconnect exhausted (terminal failure)", name)
        if conn:
            conn.status = "connect_failed_terminal"

        emit_server_connect_failed(
            name,
            server_cfg.transport.value,
            "reconnect_exhausted",
            attempt=MAX_RECONNECT_ATTEMPTS,
            is_terminal=True,
        )

    # Spawn reconnect task
    task = asyncio.create_task(reconnect_loop())
    _active_reconnects[name] = task

    try:
        await task
    except asyncio.CancelledError:
        logger.debug("[MCP] Reconnect cancelled for %s", name)


def cancel_reconnect(name: str) -> None:
    """Cancel any active reconnect task for a server.

    Args:
        name: Server name.
    """
    task = _active_reconnects.pop(name, None)
    if task and not task.done():
        task.cancel()
        logger.debug("[MCP] Cancelled reconnect for %s", name)


def force_reconnect(name: str, registry: object, server_cfg: MCPServerConfig) -> asyncio.Task:
    """Force an immediate reconnect attempt (user-initiated via /mcp reconnect).

    Args:
        name: Server name.
        registry: MCPRegistry instance.
        server_cfg: MCPServerConfig for the server.

    Returns:
        asyncio.Task for the reconnect.
    """
    cancel_reconnect(name)

    async def do_reconnect():

        mcp_registry = registry  # type: MCPRegistry
        conn = mcp_registry._connections.get(name)

        if conn:
            conn.status = "reconnecting"
            conn.reconnect_attempt = 0

        logger.info("[MCP] Force reconnecting %s", name)

        try:
            await mcp_registry._connect_server(name)
            if conn:
                conn.status = "connected"
            logger.info("[MCP] %s force reconnected", name)
        except Exception as e:
            logger.error("[MCP] Force reconnect failed for %s: %s", name, e)
            if conn:
                conn.status = "connect_failed"

    task = asyncio.create_task(do_reconnect())
    _active_reconnects[name] = task
    return task
