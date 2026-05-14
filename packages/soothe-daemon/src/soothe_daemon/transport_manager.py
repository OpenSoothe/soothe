"""Transport manager for coordinating multiple transports (RFC-0013).

The transport manager coordinates multiple transport servers (WebSocket, HTTP REST)
and provides unified message handling and broadcasting.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI

from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)


class TransportManager:
    """Manages multiple transport servers and coordinates message handling.

    The transport manager:
    1. Initializes enabled transports from configuration
    2. Routes incoming messages to a unified handler
    3. Broadcasts events to all connected clients across all transports

    When HTTP REST and WebSocket are both enabled, a single FastAPI ASGI app and
    one uvicorn listener are used (WebSocket bind host/port and TLS settings are
    authoritative).

    Args:
        config: Daemon configuration.
        runner: Optional SootheRunner for HTTP REST transport.
        soothe_config: Optional SootheConfig for HTTP REST transport.
    """

    def __init__(
        self,
        config: SootheDaemonConfig,
        runner: Any | None = None,
        soothe_config: Any | None = None,
        session_manager: Any | None = None,
    ) -> None:
        """Initialize transport manager.

        Args:
            config: Daemon configuration.
            runner: Optional SootheRunner for HTTP REST transport.
            soothe_config: Optional SootheConfig for HTTP REST transport.
            session_manager: Optional ClientSessionManager for session management.
        """
        self._config = config
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._transports: list[TransportServer] = []
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None
        self._started = False
        self._unified_app: FastAPI | None = None
        self._unified_server: uvicorn.Server | None = None
        self._unified_serve_task: asyncio.Task[None] | None = None

    def set_message_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Set the unified message handler for all transports.

        Args:
            handler: Callback to handle incoming messages from any transport.
                Takes (client_id, message) as arguments.
        """
        self._message_handler = handler

    def set_handshake_callback(self, callback: Callable[[Any], list[dict[str, Any]]]) -> None:
        """Set the handshake callback for initial client messages.

        Args:
            callback: Callback to generate initial handshake messages.
                Takes transport client object, returns list of messages to send.
        """
        self._handshake_callback = callback

    def _build_transports(self) -> None:
        """Build transport instances based on configuration."""
        self._unified_app = None

        if not self._config.transports.websocket.enabled:
            raise RuntimeError("WebSocket transport is required - enable it in configuration")

        from soothe_daemon.transports.websocket import WebSocketTransport

        http_enabled = self._config.transports.http_rest.enabled
        if http_enabled:
            self._unified_app = FastAPI(
                title="Soothe Daemon",
                description="Unified WebSocket and REST API for Soothe",
                version="1.0.0",
                docs_url="/docs",
                redoc_url="/redoc",
            )

        ws_transport = WebSocketTransport(
            self._config.transports.websocket,
            unified_app=self._unified_app,
        )
        if self._session_manager:
            ws_transport._session_manager = self._session_manager
        self._transports.append(ws_transport)
        logger.debug("Configured WebSocket transport")

        if http_enabled:
            from soothe_daemon.transports.http_rest import HttpRestTransport

            http_transport = HttpRestTransport(
                self._config.transports.http_rest,
                runner=self._runner,
                soothe_config=self._soothe_config,
                session_manager=self._session_manager,
                unified_app=self._unified_app,
            )
            self._transports.append(http_transport)
            logger.debug("Configured HTTP REST transport (unified ASGI listener)")

    async def _start_unified_listener(self) -> None:
        """Bind one uvicorn server for the shared FastAPI app (WS + HTTP)."""
        if self._unified_app is None:
            return

        ws = self._config.transports.websocket
        http = self._config.transports.http_rest
        if (http.host, http.port) != (ws.host, ws.port):
            logger.warning(
                "HTTP REST shares the WebSocket listener; binding %s:%s "
                "(http_rest was configured as %s:%s)",
                ws.host,
                ws.port,
                http.host,
                http.port,
            )
        if http.tls_enabled != ws.tls_enabled or (
            ws.tls_enabled and (http.tls_cert, http.tls_key) != (ws.tls_cert, ws.tls_key)
        ):
            logger.warning(
                "TLS settings differ between websocket and http_rest; using websocket TLS "
                "for the unified listener",
            )

        ssl_keyfile = None
        ssl_certfile = None
        if ws.tls_enabled and ws.tls_cert and ws.tls_key:
            ssl_certfile = ws.tls_cert
            ssl_keyfile = ws.tls_key
        elif ws.tls_enabled:
            logger.warning("TLS enabled but no certificate/key configured on WebSocket transport")

        uv_cfg = uvicorn.Config(
            app=self._unified_app,
            host=ws.host,
            port=ws.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
            ws_max_size=ws.max_frame_size,
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
        self._unified_server = uvicorn.Server(uv_cfg)
        self._unified_serve_task = asyncio.create_task(self._unified_server.serve())

        protocol = "wss" if ws.tls_enabled else "ws"
        logger.info(
            "Unified transport listening on %s://%s:%d (WebSocket / + REST /api)",
            protocol,
            ws.host,
            ws.port,
        )

    async def start_all(self) -> None:
        """Start all enabled transports.

        Raises:
            RuntimeError: If no message handler is set or if WebSocket is not enabled.
        """
        if self._started:
            logger.warning("Transport manager already started")
            return

        if not self._message_handler:
            raise RuntimeError("Message handler not set - call set_message_handler() first")

        self._build_transports()

        start_tasks = [
            transport.start(self._message_handler, self._handshake_callback)
            for transport in self._transports
        ]

        try:
            await asyncio.gather(*start_tasks)
            if self._unified_app is not None:
                await self._start_unified_listener()
            self._started = True
            logger.debug(
                "Started %d transport(s): %s",
                len(self._transports),
                ", ".join(t.transport_type for t in self._transports),
            )
        except Exception:
            await self.stop_all()
            raise

    async def stop_all(self) -> None:
        """Stop all transports."""
        if self._unified_server is not None:
            self._unified_server.should_exit = True
            if self._unified_serve_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(self._unified_serve_task, timeout=30.0)
                self._unified_serve_task = None
            self._unified_server = None

        if self._transports:
            try:
                await asyncio.gather(
                    *[transport.stop() for transport in self._transports],
                    return_exceptions=True,
                )
            except Exception:
                logger.exception("Error stopping transports")

            self._transports.clear()

        self._started = False
        self._unified_app = None
        logger.info("All transports stopped")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all clients across all transports.

        Args:
            message: Message dict to broadcast.
        """
        if not self._started:
            logger.warning("Broadcast called but transport manager not started")
            return

        logger.debug("Broadcasting to %d transports", len(self._transports))

        broadcast_tasks = [transport.broadcast(message) for transport in self._transports]

        results = await asyncio.gather(*broadcast_tasks, return_exceptions=True)

        failure_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failure_count += 1
                logger.exception(
                    "Failed to broadcast to %s",
                    self._transports[i].transport_type,
                    exc_info=result,
                )

        logger.debug("Broadcast completed, %d failures", failure_count)

    @property
    def client_count(self) -> int:
        """Return total number of connected clients across all transports.

        Returns:
            Total client count.
        """
        return sum(t.client_count for t in self._transports)

    @property
    def transport_count(self) -> int:
        """Return number of active transports.

        Returns:
            Number of active transports.
        """
        return len(self._transports)

    def get_transport_info(self) -> list[dict[str, Any]]:
        """Get information about all transports.

        Returns:
            List of transport info dicts.
        """
        return [
            {
                "type": transport.transport_type,
                "client_count": transport.client_count,
            }
            for transport in self._transports
        ]
