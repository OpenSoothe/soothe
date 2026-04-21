"""WebSocket transport implementation (RFC-0013).

This transport implements WebSocket server for web/remote clients
with CORS validation.
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import websockets.asyncio.server
import websockets.exceptions
from soothe_sdk.client.protocol import decode, encode

from soothe.config.daemon_config import WebSocketConfig
from soothe.daemon.protocol_v2 import create_error_response, validate_message
from soothe.daemon.transports.base import TransportServer

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

logger = logging.getLogger(__name__)


class WebSocketTransport(TransportServer):
    """WebSocket transport server.

    This transport implements the RFC-0013 protocol over WebSocket.
    It uses native WebSocket text frames (no newline delimiter).

    Args:
        config: WebSocket configuration.
    """

    def __init__(self, config: WebSocketConfig) -> None:
        """Initialize WebSocket transport.

        Args:
            config: WebSocket configuration.
        """
        self._config = config
        self._server: websockets.asyncio.server.Server | None = None
        self._clients: dict[ServerConnection, dict[str, Any]] = {}
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None

    async def start(
        self,
        message_handler: Callable[[str, dict[str, Any]], None],
        handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None,
    ) -> None:
        """Start the WebSocket server.

        Args:
            message_handler: Callback to handle incoming messages. Takes (client_id, message).
            handshake_callback: Optional callback for initial handshake messages.
        """
        if not self._config.enabled:
            logger.info("[WS] Transport disabled")
            return

        self._message_handler = message_handler
        self._handshake_callback = handshake_callback

        # Determine SSL context
        ssl_context = None
        if self._config.tls_enabled:
            import ssl

            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            if self._config.tls_cert and self._config.tls_key:
                ssl_context.load_cert_chain(self._config.tls_cert, self._config.tls_key)
            else:
                logger.warning("TLS enabled but no certificate/key configured")

        # Start WebSocket server
        # Disable WebSocket library ping/pong since daemon uses application-level heartbeats
        # (RFC-0013: daemon sends heartbeat events every 5 seconds during query execution)
        self._server = await websockets.asyncio.server.serve(
            self._handle_client,
            host=self._config.host,
            port=self._config.port,
            ssl=ssl_context,
            ping_interval=None,  # Disable ping/pong mechanism
            ping_timeout=None,  # Use application-level heartbeats instead
            max_size=self._config.max_frame_size,  # Set maximum frame size
        )

        protocol = "wss" if self._config.tls_enabled else "ws"
        logger.debug(
            "WebSocket transport listening on %s://%s:%d",
            protocol,
            self._config.host,
            self._config.port,
        )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients.

        Args:
            message: Message dict to broadcast.
        """
        if not self._server:
            return

        data = encode(message)
        # Remove newline for WebSocket (native framing)
        data = data.rstrip(b"\n")

        dead_clients = []
        for client in self._clients:
            try:
                await client.send(data.decode("utf-8"))
            except Exception:
                dead_clients.append(client)

        # Remove dead clients
        for dead in dead_clients:
            self._clients.pop(dead, None)

    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific WebSocket client.

        Args:
            client: WebSocket ServerConnection object
            message: Message dictionary to send

        Raises:
            ConnectionError: If send fails
        """
        try:
            data = encode(message)
            await client.send(data)
        except (
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.ConnectionClosedOK,
            websockets.exceptions.ConnectionClosedError,
        ) as e:
            logger.debug("WebSocket client already closed while sending: %s", e)
            error_msg = f"Failed to send: {e}"
            raise ConnectionError(error_msg) from e
        except Exception as e:
            logger.exception("Failed to send to WebSocket client")
            error_msg = f"Failed to send: {e}"
            raise ConnectionError(error_msg) from e

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        if not self._server:
            return

        # Close all client connections
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.close()

        self._clients.clear()

        # Close server
        self._server.close()
        await self._server.wait_closed()
        self._server = None

        logger.info("[WS] Transport stopped")

    @property
    def transport_type(self) -> str:
        """Return transport type identifier."""
        return "websocket"

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        return len(self._clients)

    def _validate_cors(self, origin: str | None) -> bool:
        """Validate CORS origin against allowed patterns.

        Args:
            origin: Origin header value.

        Returns:
            True if origin is allowed, False otherwise.
        """
        if not origin:
            # Allow connections without Origin header (non-browser clients)
            return True

        for pattern in self._config.cors_origins:
            if fnmatch.fnmatch(origin, pattern):
                return True

        logger.warning("CORS validation failed for origin: %s", origin)
        return False

    async def _handle_client(self, websocket: ServerConnection) -> None:
        """Handle a new WebSocket client connection.

        Args:
            websocket: WebSocket connection.
        """
        # Validate CORS
        origin = websocket.request.headers.get("Origin")
        if not self._validate_cors(origin):
            await websocket.close(code=1008, reason="Origin not allowed")
            return

        # Create a session for this client if session manager is available
        client_id: str | None = None
        if hasattr(self, "_session_manager") and self._session_manager:
            try:
                client_id = await self._session_manager.create_session(self, websocket)
            except Exception:
                logger.exception("Failed to create session for WebSocket client")
                await websocket.close(code=1011, reason="Internal error")
                return
        else:
            # Fallback to generated client ID
            client_id = f"ws:{websocket.remote_address}"

        # Initialize client state
        client_info: dict[str, Any] = {
            "remote_addr": websocket.remote_address,
            "origin": origin,
            "client_id": client_id,
        }

        # Register client
        self._clients[websocket] = client_info
        logger.info(
            "[WS] Client connected from %s (%d active)",
            websocket.remote_address[0] if websocket.remote_address else "unknown",
            len(self._clients),
        )

        try:
            # Send initial handshake messages
            if self._handshake_callback:
                try:
                    handshake_msgs = self._handshake_callback(websocket)
                    for msg in handshake_msgs:
                        await websocket.send(encode(msg).decode("utf-8").strip())
                except Exception:
                    logger.exception("Failed to send initial handshake to WebSocket client")

            # Message loop
            async for message in websocket:
                try:
                    # Parse message
                    message_str = message.decode("utf-8") if isinstance(message, bytes) else message
                    msg_dict = decode(message_str.encode("utf-8"))
                    if msg_dict is None:
                        continue

                    # Validate message
                    errors = validate_message(msg_dict)
                    if errors:
                        error_msg = create_error_response(
                            "INVALID_MESSAGE",
                            errors[0],
                            {"errors": errors},
                        )
                        await websocket.send(encode(error_msg).decode("utf-8").strip())
                        continue

                    # Pass message to handler with client_id
                    if self._message_handler:
                        try:
                            self._message_handler(client_id, msg_dict)
                        except Exception:
                            logger.exception("Error handling WebSocket message")

                except Exception:
                    logger.exception("Error processing WebSocket message")
                    continue

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception:
            logger.exception("WebSocket client error")
        finally:
            # Remove session if we created one
            if hasattr(self, "_session_manager") and self._session_manager and client_id:
                await self._session_manager.remove_session(client_id)
            # Unregister client
            self._clients.pop(websocket, None)
            logger.info(
                "[WS] Client disconnected from %s (%d active)",
                websocket.remote_address[0] if websocket.remote_address else "unknown",
                len(self._clients),
            )
