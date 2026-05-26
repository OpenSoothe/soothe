"""WebSocket transport implementation (RFC-0013).

This transport implements WebSocket server for web/remote clients
with CORS validation using FastAPI and uvicorn (native WebSocket text frames).
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
from collections.abc import Callable
from typing import Any

import uvicorn
import websockets.exceptions
from fastapi import FastAPI, WebSocket
from soothe_sdk.client.protocol import decode_websocket_text, encode_websocket_text
from starlette.websockets import WebSocketDisconnect
from websockets.frames import Close

from soothe_daemon.config.models import WebSocketConfig
from soothe_daemon.protocol import create_error_response, validate_message
from soothe_daemon.transports.base import TransportServer

logger = logging.getLogger(__name__)


class WebSocketTransport(TransportServer):
    """WebSocket transport server.

    This transport implements the RFC-0013 protocol over WebSocket.
    It uses native WebSocket text frames (no newline delimiter).

    Args:
        config: WebSocket configuration.
    """

    def __init__(
        self,
        config: WebSocketConfig,
        *,
        unified_app: FastAPI | None = None,
    ) -> None:
        """Initialize WebSocket transport.

        Args:
            config: WebSocket configuration.
            unified_app: When set, WebSocket is registered on this shared ASGI app
                and the transport manager owns a single uvicorn listener.
        """
        self._config = config
        self._unified_parent_app = unified_app
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._clients: dict[WebSocket, dict[str, Any]] = {}
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None
        self._ws_route_registered = False

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

        if self._unified_parent_app is not None:
            if not self._ws_route_registered:

                @self._unified_parent_app.websocket("/")
                async def _ws_endpoint(websocket: WebSocket) -> None:
                    await self._handle_client_endpoint(websocket)

                self._ws_route_registered = True
            self._app = self._unified_parent_app
            return

        app = FastAPI(
            title="Soothe Daemon WebSocket", version="1.0.0", docs_url=None, redoc_url=None
        )

        @app.websocket("/")
        async def _ws_endpoint_standalone(websocket: WebSocket) -> None:
            await self._handle_client_endpoint(websocket)

        self._app = app

        ssl_keyfile = None
        ssl_certfile = None
        if self._config.tls_enabled and self._config.tls_cert and self._config.tls_key:
            ssl_certfile = self._config.tls_cert
            ssl_keyfile = self._config.tls_key
        elif self._config.tls_enabled:
            logger.warning("TLS enabled but no certificate/key configured")

        uv_cfg = uvicorn.Config(
            app=app,
            host=self._config.host,
            port=self._config.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
            ws_max_size=self._config.max_frame_size,
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
        self._server = uvicorn.Server(uv_cfg)
        self._serve_task = asyncio.create_task(self._server.serve())

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

    async def _send_with_timeout(self, client: WebSocket, text: str, timeout: float = 1.0) -> None:
        """Send a text frame to WebSocket client with timeout (IG-258).

        Args:
            client: Starlette/FastAPI WebSocket connection.
            text: JSON payload for a single text frame.
            timeout: Send timeout in seconds.

        Raises:
            asyncio.TimeoutError: If send exceeds timeout.
            Exception: If send fails.
        """
        try:
            await asyncio.wait_for(client.send_text(text), timeout=timeout)
        except TimeoutError:
            logger.warning("WebSocket send timeout for client %s", client)
            raise

    async def send(self, client: Any, message: dict[str, Any]) -> None:
        """Send message to specific WebSocket client.

        Args:
            client: Starlette/FastAPI WebSocket connection.
            message: Message dictionary to send.

        Raises:
            ConnectionError: If send fails (except normal disconnects).
            websockets.exceptions.ConnectionClosedOK: For normal disconnects (code 1000).
        """
        websocket = client
        try:
            await websocket.send_text(encode_websocket_text(message))
        except WebSocketDisconnect as e:
            close = Close(e.code, e.reason or "")
            if e.code == 1000:
                logger.debug("WebSocket client disconnected normally: %s", e)
                raise websockets.exceptions.ConnectionClosedOK(rcvd=close, sent=None) from e
            logger.warning("WebSocket client disconnected unexpectedly: %s", e)
            raise websockets.exceptions.ConnectionClosedError(rcvd=close, sent=None) from e
        except (
            websockets.exceptions.ConnectionClosedOK,
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.ConnectionClosedError,
        ):
            raise
        except (RuntimeError, OSError, ConnectionError) as e:
            logger.warning("WebSocket client disconnected unexpectedly: %s", e)
            raise ConnectionError(f"Failed to send: {e}") from e
        except Exception as e:
            logger.exception("Failed to send to WebSocket client")
            raise ConnectionError(f"Failed to send: {e}") from e

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
            return True

        for pattern in self._config.cors_origins:
            if fnmatch.fnmatch(origin, pattern):
                return True

        logger.warning("CORS validation failed for origin: %s", origin)
        return False

    async def _handle_client_endpoint(self, websocket: WebSocket) -> None:
        """Handle a new WebSocket client connection (FastAPI endpoint)."""
        origin = websocket.headers.get("origin")
        if not self._validate_cors(origin):
            await websocket.close(code=1008, reason="Origin not allowed")
            return

        await websocket.accept()

        client_id: str | None = None
        if hasattr(self, "_session_manager") and self._session_manager:
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
                        if client_id and hasattr(self, "_session_manager") and self._session_manager
                        else None
                    )
                    for msg in handshake_msgs:
                        if session is not None:
                            await self._session_manager.send_to_client(session, msg)
                        else:
                            await websocket.send_text(encode_websocket_text(msg))
                except Exception:
                    logger.exception("Failed to send initial handshake to WebSocket client")

            while True:
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
                            if client_id
                            and hasattr(self, "_session_manager")
                            and self._session_manager
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
            if hasattr(self, "_session_manager") and self._session_manager and client_id:
                await self._session_manager.remove_session(client_id)
            self._clients.pop(websocket, None)
            logger.info(
                "[WS] Client disconnected from %s (%d active)",
                remote,
                len(self._clients),
            )
