"""WebSocket channel implementation (RFC-620).

WebSocket channel as a proper Channel subclass with streaming support.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket
from soothe_sdk.client.protocol import decode_websocket_text, encode_websocket_text
from starlette.websockets import WebSocketDisconnect

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config.models import WebSocketConfig
from soothe_daemon.protocol import create_error_response, validate_message

logger = logging.getLogger(__name__)


class WebSocketChannel(Channel):
    """WebSocket channel with full streaming support.

    This channel implements the RFC-620 Channel interface for WebSocket.
    It supports:
    - Bidirectional messaging (supports_inbound=True, supports_outbound=True)
    - Real-time streaming (supports_streaming=True)
    - Multiple concurrent clients

    Args:
        config: WebSocket configuration.
        manager: ChannelManager for inbound routing.
        unified_app: Optional shared FastAPI app for unified listener.
        session_manager: Optional ClientSessionManager for session management.
    """

    name = "websocket"
    display_name = "WebSocket"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    def __init__(
        self,
        config: WebSocketConfig,
        manager: Any,
        *,
        unified_app: FastAPI | None = None,
        session_manager: Any | None = None,
    ) -> None:
        """Initialize WebSocket channel.

        Args:
            config: WebSocket configuration.
            manager: ChannelManager for inbound routing.
            unified_app: Optional shared FastAPI app.
            session_manager: Optional ClientSessionManager.
        """
        super().__init__(config, manager)
        self._ws_config = config
        self._unified_parent_app = unified_app
        self._session_manager = session_manager
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._clients: dict[WebSocket, dict[str, Any]] = {}
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None
        self._ws_route_registered = False

    async def start(self) -> None:
        """Start the WebSocket server.

        Note: This is called by ChannelManager which passes message_handler via
        set_message_handler() before start_all(). We need to receive those
        handlers from the manager.
        """
        if not self._ws_config.enabled:
            logger.info("[WS] Channel disabled")
            return

        # Get handlers from manager (set via compatibility methods)
        self._message_handler = getattr(self._manager, "_message_handler", None)
        self._handshake_callback = getattr(self._manager, "_handshake_callback", None)

        if self._unified_parent_app is not None:
            if not self._ws_route_registered:

                @self._unified_parent_app.websocket("/")
                async def _ws_endpoint(websocket: WebSocket) -> None:
                    await self._handle_client_endpoint(websocket)

                self._ws_route_registered = True
            self._app = self._unified_parent_app
            self._running = True
            return

        app = FastAPI(
            title="Soothe Daemon WebSocket",
            version="1.0.0",
            docs_url=None,
            redoc_url=None,
        )

        @app.websocket("/")
        async def _ws_endpoint_standalone(websocket: WebSocket) -> None:
            await self._handle_client_endpoint(websocket)

        self._app = app

        ssl_keyfile = None
        ssl_certfile = None
        if self._ws_config.tls_enabled and self._ws_config.tls_cert and self._ws_config.tls_key:
            ssl_certfile = self._ws_config.tls_cert
            ssl_keyfile = self._ws_config.tls_key
        elif self._ws_config.tls_enabled:
            logger.warning("TLS enabled but no certificate/key configured")

        uv_cfg = uvicorn.Config(
            app=app,
            host=self._ws_config.host,
            port=self._ws_config.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
            ws_max_size=self._ws_config.max_frame_size,
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
        self._server = uvicorn.Server(uv_cfg)
        self._serve_task = asyncio.create_task(self._server.serve())

        protocol = "wss" if self._ws_config.tls_enabled else "ws"
        logger.debug(
            "WebSocket channel listening on %s://%s:%d",
            protocol,
            self._ws_config.host,
            self._ws_config.port,
        )
        self._running = True

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.close()

        self._clients.clear()

        if self._server is not None:
            self._server.should_exit = True
            if self._serve_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(self._serve_task, timeout=30.0)
                self._serve_task = None
            self._server = None

        if self._unified_parent_app is None:
            self._app = None

        self._running = False
        logger.info("[WS] Channel stopped")

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send message to specific WebSocket client (chat_id = loop_id).

        Args:
            chat_id: Loop ID identifying the client session.
            message: ChannelMessage to deliver.

        Raises:
            ConnectionError: If send fails.
        """
        # Find WebSocket client by chat_id (loop_id)
        # In WebSocket, chat_id maps to client_id which maps to session
        if self._session_manager:
            session = await self._session_manager.get_session(chat_id)
            if session:
                # Send via session manager (handles the WebSocket connection)
                await self._session_manager.send_to_client(
                    session,
                    self._channel_message_to_wire(message),
                )
                return

        # Fallback: direct WebSocket send (for clients not in session manager)
        for ws, info in self._clients.items():
            if info.get("client_id") == chat_id:
                await ws.send_text(encode_websocket_text(self._channel_message_to_wire(message)))
                return

        logger.warning("[WS] No client found for chat_id %s", chat_id)

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream incremental text chunk to WebSocket client.

        Args:
            chat_id: Loop ID identifying the client session.
            delta: Text chunk to stream.
            metadata: Stream metadata (_stream_id, _stream_end, etc.).
        """
        wire_msg = {
            "type": "event",
            "loop_id": chat_id,
            "namespace": [],
            "mode": "custom",
            "data": {
                "type": "soothe.output.text.delta",
                "content": delta,
                "_stream_delta": True,
            },
        }
        if metadata:
            wire_msg["data"].update(metadata)

        # Find and send to client
        if self._session_manager:
            session = await self._session_manager.get_session(chat_id)
            if session:
                await self._session_manager.send_to_client(session, wire_msg)
                return

        for ws, info in self._clients.items():
            if info.get("client_id") == chat_id:
                await ws.send_text(encode_websocket_text(wire_msg))
                return

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients.

        Args:
            message: Wire-format message dict to broadcast.
        """
        text = encode_websocket_text(message)

        send_tasks = [
            asyncio.create_task(self._send_with_timeout(client, text, timeout=1.0))
            for client in self._clients
        ]

        if not send_tasks:
            return

        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        clients_to_remove = []
        for client, result in zip(self._clients.keys(), results):
            if isinstance(result, Exception):
                clients_to_remove.append(client)

        for client in clients_to_remove:
            self._clients.pop(client, None)

    async def _send_with_timeout(
        self,
        client: WebSocket,
        text: str,
        timeout: float = 1.0,
    ) -> None:
        """Send text frame with timeout.

        Args:
            client: WebSocket connection.
            text: JSON payload.
            timeout: Send timeout in seconds.

        Raises:
            asyncio.TimeoutError: If send exceeds timeout.
        """
        try:
            await asyncio.wait_for(client.send_text(text), timeout=timeout)
        except TimeoutError:
            logger.warning("WebSocket send timeout for client %s", client)
            raise

    def _channel_message_to_wire(self, message: ChannelMessage) -> dict[str, Any]:
        """Convert ChannelMessage to wire format.

        Args:
            message: ChannelMessage to convert.

        Returns:
            Wire-format dict for WebSocket transmission.
        """
        wire = {
            "type": "event",
            "loop_id": message.chat_id,
            "namespace": [],
            "mode": "custom",
            "data": {
                "type": "soothe.output.text.complete",
                "content": message.content,
            },
        }

        # Add metadata flags
        if message.metadata:
            wire["data"].update(message.metadata)

        return wire

    def _validate_cors(self, origin: str | None) -> bool:
        """Validate CORS origin against allowed patterns.

        Args:
            origin: Origin header value.

        Returns:
            True if origin is allowed.
        """
        if not origin:
            return True

        for pattern in self._ws_config.cors_origins:
            if fnmatch.fnmatch(origin, pattern):
                return True

        logger.warning("CORS validation failed for origin: %s", origin)
        return False

    async def _handle_client_endpoint(self, websocket: WebSocket) -> None:
        """Handle WebSocket client connection lifecycle."""
        origin = websocket.headers.get("origin")
        if not self._validate_cors(origin):
            await websocket.close(code=1008, reason="Origin not allowed")
            return

        await websocket.accept()

        client_id: str | None = None
        if self._session_manager:
            try:
                client_id = await self._session_manager.create_session(self, websocket)
            except Exception:
                logger.exception("Failed to create session for WebSocket client")
                await websocket.close(code=1011, reason="Internal error")
                return
        else:
            remote = (websocket.client.host, websocket.client.port) if websocket.client else None
            client_id = f"ws:{remote}"

        client_info: dict[str, Any] = {
            "remote_addr": (websocket.client.host, websocket.client.port)
            if websocket.client
            else None,
            "origin": origin,
            "client_id": client_id,
        }

        self._clients[websocket] = client_info
        remote = websocket.client.host if websocket.client else "unknown"
        logger.info("[WS] Client connected from %s (%d active)", remote, len(self._clients))

        try:
            if self._handshake_callback:
                try:
                    handshake_msgs = self._handshake_callback(websocket)
                    session = (
                        await self._session_manager.get_session(client_id)
                        if client_id and self._session_manager
                        else None
                    )
                    for msg in handshake_msgs:
                        if session is not None:
                            await self._session_manager.send_to_client(session, msg)
                        else:
                            await websocket.send_text(encode_websocket_text(msg))
                except Exception:
                    logger.exception("Failed to send initial handshake to WebSocket client")

            while self._running:
                try:
                    message_str = await websocket.receive_text()
                except WebSocketDisconnect:
                    break

                try:
                    msg_dict = decode_websocket_text(message_str)
                    if msg_dict is None:
                        continue

                    errors = validate_message(msg_dict)
                    if errors:
                        error_msg = create_error_response(
                            "INVALID_MESSAGE",
                            errors[0],
                            {"errors": errors},
                        )
                        session = (
                            await self._session_manager.get_session(client_id)
                            if client_id and self._session_manager
                            else None
                        )
                        if session is not None:
                            await self._session_manager.send_to_client(session, error_msg)
                        else:
                            await websocket.send_text(encode_websocket_text(error_msg))
                        continue

                    if self._message_handler:
                        try:
                            self._message_handler(client_id, msg_dict)
                        except Exception:
                            logger.exception("Error handling WebSocket message")

                except Exception:
                    logger.exception("Error processing WebSocket message")
                    continue

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WebSocket client error")
        finally:
            if self._session_manager and client_id:
                await self._session_manager.remove_session(client_id)
            self._clients.pop(websocket, None)
            logger.info(
                "[WS] Client disconnected from %s (%d active)",
                remote,
                len(self._clients),
            )

    @property
    def transport_type(self) -> str:
        """Return transport type (compatibility alias)."""
        return self.name

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        return len(self._clients)
