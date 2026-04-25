"""Transport manager for coordinating multiple transports (RFC-0013).

The transport manager coordinates multiple transport servers (WebSocket, HTTP REST)
and provides unified message handling and broadcasting.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from soothe.config.daemon_config import DaemonConfig
from soothe.daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)


class TransportManager:
    """Manages multiple transport servers and coordinates message handling.

    The transport manager:
    1. Initializes enabled transports from configuration
    2. Routes incoming messages to a unified handler
    3. Broadcasts events to all connected clients across all transports

    Args:
        config: Daemon configuration.
        thread_manager: Optional ThreadContextManager for HTTP REST transport.
        runner: Optional SootheRunner for HTTP REST transport.
        soothe_config: Optional SootheConfig for HTTP REST transport.
    """

    def __init__(
        self,
        config: DaemonConfig,
        thread_manager: Any | None = None,
        runner: Any | None = None,
        soothe_config: Any | None = None,
        session_manager: Any | None = None,
    ) -> None:
        """Initialize transport manager.

        Args:
            config: Daemon configuration.
            thread_manager: Optional ThreadContextManager for HTTP REST transport.
            runner: Optional SootheRunner for HTTP REST transport.
            soothe_config: Optional SootheConfig for HTTP REST transport.
            session_manager: Optional ClientSessionManager for session management.
        """
        self._config = config
        self._thread_manager = thread_manager
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._transports: list[TransportServer] = []
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None
        self._started = False

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
        # WebSocket transport (required for bidirectional streaming)
        if not self._config.transports.websocket.enabled:
            raise RuntimeError("WebSocket transport is required - enable it in configuration")

        from soothe.daemon.transports.websocket import WebSocketTransport

        ws_transport = WebSocketTransport(self._config.transports.websocket)
        if self._session_manager:
            ws_transport._session_manager = self._session_manager
        self._transports.append(ws_transport)
        logger.debug("Configured WebSocket transport")

        # HTTP REST transport (optional, for health checks and CRUD)
        if self._config.transports.http_rest.enabled:
            from soothe.daemon.transports.http_rest import HttpRestTransport

            http_transport = HttpRestTransport(
                self._config.transports.http_rest,
                thread_manager=self._thread_manager,
                runner=self._runner,
                soothe_config=self._soothe_config,
                session_manager=self._session_manager,
            )
            self._transports.append(http_transport)
            logger.debug("Configured HTTP REST transport")

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

        # Start all transports with message handler and handshake callback
        start_tasks = [
            transport.start(self._message_handler, self._handshake_callback)
            for transport in self._transports
        ]

        try:
            await asyncio.gather(*start_tasks)
            self._started = True
            logger.debug(
                "Started %d transport(s): %s",
                len(self._transports),
                ", ".join(t.transport_type for t in self._transports),
            )
        except Exception:
            # Stop any transports that started successfully
            await self.stop_all()
            raise

    async def stop_all(self) -> None:
        """Stop all transports."""
        if not self._started:
            return

        stop_tasks = [transport.stop() for transport in self._transports]

        try:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        except Exception:
            logger.exception("Error stopping transports")

        self._transports.clear()
        self._started = False
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

        # Broadcast to all transports concurrently
        broadcast_tasks = [transport.broadcast(message) for transport in self._transports]

        # Use gather with return_exceptions to ensure one failure doesn't block others
        results = await asyncio.gather(*broadcast_tasks, return_exceptions=True)

        # Log any broadcast failures
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
