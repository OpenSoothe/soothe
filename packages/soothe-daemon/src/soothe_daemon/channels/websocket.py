"""WebSocket channel implementation (RFC-620).

WebSocket channel as a proper Channel subclass with streaming support.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import time
from collections.abc import Callable
from typing import Any

import uvicorn
import websockets.exceptions
from fastapi import FastAPI, WebSocket
from soothe_sdk.client.protocol import decode_websocket_text, encode_websocket_text
from starlette.websockets import WebSocketDisconnect, WebSocketState
from websockets.frames import Close

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config.models import WebSocketConfig
from soothe_daemon.protocol import ErrorCode, build_error_response, validate_message

logger = logging.getLogger(__name__)


class WebSocketChannel(Channel):
    """WebSocket channel with full streaming support.

    This channel implements the RFC-620 Channel interface for WebSocket.
    It supports:
    - Bidirectional messaging (supports_inbound=True, supports_outbound=True)
    - Real-time streaming (supports_streaming=True)
    - Multiple concurrent clients
    - Command handlers for autopilot, cron, and memory profiling

    Args:
        config: WebSocket configuration.
        manager: ChannelManager for inbound routing.
        unified_app: Optional shared FastAPI app for unified listener.
        session_manager: Optional ClientSessionManager for session management.
        autopilot_service: Optional AutopilotService for command handling.
        cron_service: Optional CronService for command handling.
        memory_profiler: Optional MemoryProfiler for command handling.
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
        autopilot_service: Any | None = None,
        cron_service: Any | None = None,
        memory_profiler: Any | None = None,
    ) -> None:
        """Initialize WebSocket channel.

        Args:
            config: WebSocket configuration.
            manager: ChannelManager for inbound routing.
            unified_app: Optional shared FastAPI app.
            session_manager: Optional ClientSessionManager.
            autopilot_service: Optional AutopilotService for WebSocket command handlers.
            cron_service: Optional CronService for WebSocket command handlers.
            memory_profiler: Optional MemoryProfiler for WebSocket command handlers.
        """
        super().__init__(config, manager)
        self._ws_config = config
        self._unified_parent_app = unified_app
        self._session_manager = session_manager
        self._autopilot_service = autopilot_service
        self._cron_service = cron_service
        self._memory_profiler = memory_profiler
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

        # Get handlers from manager (set before start_all)
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

    async def send(self, chat_id_or_client: Any, message: ChannelMessage | dict[str, Any]) -> None:
        """Send to a WebSocket client (wire dict) or deliver a ChannelMessage by loop id.

        SessionManager uses ``send(websocket, wire_dict)``. ChannelManager uses
        ``send(chat_id, ChannelMessage)``.
        """
        if isinstance(message, dict):
            await self._send_wire(chat_id_or_client, message)
            return

        chat_id = str(chat_id_or_client)
        if self._session_manager:
            session = await self._session_manager.get_session(chat_id)
            if session:
                await self._session_manager.send_to_client(
                    session,
                    self._channel_message_to_wire(message),
                )
                return

        for ws, info in self._clients.items():
            if info.get("client_id") == chat_id:
                await ws.send_text(encode_websocket_text(self._channel_message_to_wire(message)))
                return

        logger.warning("[WS] No client found for chat_id %s", chat_id)

    async def _send_wire(self, client: Any, message: dict[str, Any]) -> None:
        """Send a wire-format dict to one WebSocket connection."""
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
            "handshake_complete": False,
            "proto_version": None,
            "negotiated_capabilities": [],
            "last_pong_time": 0.0,
        }

        self._clients[websocket] = client_info
        remote = websocket.client.host if websocket.client else "unknown"
        logger.info("[WS] Client connected from %s (%d active)", remote, len(self._clients))

        try:
            # Send the initial status message (handshake_callback now returns
            # only the status message — the ack is sent by the router when it
            # processes connection_init).
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
                except (
                    WebSocketDisconnect,
                    websockets.exceptions.ConnectionClosedOK,
                    websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.ConnectionClosedError,
                ):
                    return
                except Exception:
                    logger.exception("Failed to send initial handshake to WebSocket client")
                    if websocket.client_state != WebSocketState.CONNECTED:
                        return

            # Start server-side heartbeat ping task (RFC-450 §8.3)
            heartbeat_task: asyncio.Task[None] | None = None
            if self._ws_config.heartbeat_interval_ms > 0:
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_pinger(websocket, client_id, client_info),
                    name=f"ws-heartbeat-{client_id}",
                )

            try:
                while self._running:
                    try:
                        message_str = await websocket.receive_text()
                    except WebSocketDisconnect:
                        break
                    except RuntimeError as e:
                        # Starlette raises RuntimeError when WebSocket is not connected
                        # (e.g., client disconnected before accept completed)
                        if "not connected" in str(e).lower():
                            logger.debug("[WS] Client disconnected before receive: %s", e)
                            break
                        raise

                    try:
                        msg_dict = decode_websocket_text(message_str)
                        if msg_dict is None:
                            continue

                        # -- Handshake enforcement (RFC-450 §8.2) ----------------
                        msg_type = msg_dict.get("type", "")
                        if msg_type == "connection_init":
                            # Route through the router which builds connection_ack
                            if self._message_handler:
                                self._message_handler(client_id, msg_dict)
                            continue

                        if msg_type not in ("ping", "pong"):
                            # Any pre-handshake message (except connection_init/ping/pong)
                            # is rejected with -32600 INVALID_REQUEST.
                            if not client_info.get("handshake_complete"):
                                err_msg = {
                                    "proto": "1",
                                    "type": "error",
                                    "error": {
                                        "code": -32600,
                                        "message": "Handshake must complete before sending messages",
                                        "data": {"type": msg_type},
                                    },
                                }
                                session = (
                                    await self._session_manager.get_session(client_id)
                                    if client_id and self._session_manager
                                    else None
                                )
                                if session is not None:
                                    await self._session_manager.send_to_client(session, err_msg)
                                else:
                                    await websocket.send_text(encode_websocket_text(err_msg))
                                continue

                        # -- Heartbeat ping/pong (RFC-450 §8.3) ------------------
                        if msg_type == "ping":
                            pong_msg = {"proto": "1", "type": "pong"}
                            session = (
                                await self._session_manager.get_session(client_id)
                                if client_id and self._session_manager
                                else None
                            )
                            if session is not None:
                                await self._session_manager.send_to_client(session, pong_msg)
                            else:
                                await websocket.send_text(encode_websocket_text(pong_msg))
                            continue

                        if msg_type == "pong":
                            client_info["last_pong_time"] = time.monotonic()
                            continue

                        errors = validate_message(msg_dict)
                        if errors:
                            error_msg = build_error_response(
                                ErrorCode.INVALID_PARAMS,
                                "Invalid params",
                                request_id=msg_dict.get("id") or msg_dict.get("request_id"),
                                data={"errors": errors},
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

                        # -- Receipt mechanism (RFC-450 §5.7) -------------------------
                        # If the message carried a `receipt` field and the client
                        # declared `receipts` capability, send receipt_response.
                        receipt_id = msg_dict.get("receipt")
                        if receipt_id is not None and isinstance(receipt_id, str):
                            # Check if client declared receipts capability
                            caps = client_info.get("negotiated_capabilities", [])
                            if "receipts" in caps:
                                receipt_msg = {
                                    "proto": "1",
                                    "type": "receipt_response",
                                    "receipt": receipt_id,
                                }
                                session = (
                                    await self._session_manager.get_session(client_id)
                                    if client_id and self._session_manager
                                    else None
                                )
                                if session is not None:
                                    await self._session_manager.send_to_client(session, receipt_msg)
                                else:
                                    await websocket.send_text(encode_websocket_text(receipt_msg))

                        # Handle command messages (WebSocket command client)
                        if msg_dict.get("type") == "command":
                            await self._handle_command_message(websocket, msg_dict, client_id)

                    except Exception:
                        logger.exception("Error processing WebSocket message")
                        continue
            finally:
                if heartbeat_task is not None and not heartbeat_task.done():
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task

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

    async def _heartbeat_pinger(
        self,
        websocket: WebSocket,
        client_id: str | None,
        client_info: dict[str, Any],
    ) -> None:
        """Periodically send protocol-level ping frames (RFC-450 §8.3).

        If no pong is received within ``heartbeat_timeout_ms``, the connection
        is considered dead and closed with code 1001.

        Args:
            websocket: The WebSocket connection to ping.
            client_id: Client identifier for logging.
            client_info: Per-connection info dict tracking ``last_pong_time``.
        """
        interval_s = self._ws_config.heartbeat_interval_ms / 1000.0
        timeout_s = self._ws_config.heartbeat_timeout_ms / 1000.0
        client_info["last_pong_time"] = time.monotonic()

        try:
            while self._running and websocket.client_state == WebSocketState.CONNECTED:
                await asyncio.sleep(interval_s)
                if not self._running or websocket.client_state != WebSocketState.CONNECTED:
                    break

                # Check for liveness: if we haven't received a pong since the
                # last interval, send a ping. If we sent a ping and no pong
                # arrived within the timeout, close the connection.
                now = time.monotonic()
                last_pong = client_info.get("last_pong_time", 0.0)
                if now - last_pong > interval_s + timeout_s:
                    logger.warning(
                        "[WS] Heartbeat timeout for client %s (no pong in %.1fs), closing",
                        client_id,
                        now - last_pong,
                    )
                    with contextlib.suppress(Exception):
                        await websocket.close(code=1001, reason="Heartbeat timeout")
                    return

                ping_msg = {"proto": "1", "type": "ping"}
                session = (
                    await self._session_manager.get_session(client_id)
                    if client_id and self._session_manager
                    else None
                )
                try:
                    if session is not None:
                        await self._session_manager.send_to_client(session, ping_msg)
                    else:
                        await websocket.send_text(encode_websocket_text(ping_msg))
                except (
                    WebSocketDisconnect,
                    websockets.exceptions.ConnectionClosedOK,
                    websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.ConnectionClosedError,
                ):
                    return
                except Exception:
                    logger.debug("[WS] Failed to send ping to client %s", client_id)
                    return
        except asyncio.CancelledError:
            raise

    def _mark_pong_received(self, client_id: Any) -> None:
        """Mark that a pong was received from a client (heartbeat liveness).

        Args:
            client_id: Client identifier to look up in ``_clients``.
        """
        for ws, info in self._clients.items():
            if info.get("client_id") == client_id:
                info["last_pong_time"] = time.monotonic()
                return

    @property
    def client_count(self) -> int:
        """Return number of connected clients."""
        return len(self._clients)

    async def _handle_command_message(
        self,
        websocket: WebSocket,
        msg_dict: dict[str, Any],
        client_id: str,
    ) -> None:
        """Handle WebSocket command messages for autopilot, cron, and memory.

        Args:
            websocket: WebSocket connection.
            msg_dict: Command message dict.
            client_id: Client identifier.
        """
        command = msg_dict.get("command", "")
        request_id = msg_dict.get("request_id", "")
        payload = msg_dict.get("payload", {})

        try:
            result = await self._dispatch_command(command, payload)
            response = {
                "type": "command_response",
                "request_id": request_id,
                "result": result,
                "error": None,
            }
        except Exception as exc:
            logger.exception("Command %s failed", command)
            response = {
                "type": "command_response",
                "request_id": request_id,
                "result": None,
                "error": str(exc),
            }

        await websocket.send_text(encode_websocket_text(response))

    async def _dispatch_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatch command to appropriate service.

        Args:
            command: Command name.
            payload: Command payload.

        Returns:
            Command result dict.

        Raises:
            RuntimeError: If service unavailable or command fails.
        """
        # Autopilot commands
        if command.startswith("autopilot_"):
            if self._autopilot_service is None:
                raise RuntimeError("Autopilot service unavailable")

            action = command[len("autopilot_") :]
            return await self._handle_autopilot_command(action, payload)

        # Cron commands
        if command.startswith("cron_"):
            if self._cron_service is None:
                raise RuntimeError("Cron service unavailable")

            action = command[len("cron_") :]
            return await self._handle_cron_command(action, payload)

        # Memory commands
        if command.startswith("memory_"):
            if self._memory_profiler is None:
                raise RuntimeError("Memory profiling not enabled")

            action = command[len("memory_") :]
            return await self._handle_memory_command(action, payload)

        raise RuntimeError(f"Unknown command: {command}")

    async def _handle_autopilot_command(
        self, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle autopilot command.

        Args:
            action: Autopilot action name.
            payload: Command payload.

        Returns:
            Result dict.
        """
        service = self._autopilot_service

        if action == "status":
            status = service.status()
            return {
                "state": "dreaming" if status.get("dreaming") else "active",
                "running": status.get("running", False),
                "dreaming": status.get("dreaming", False),
                "loop_pool": status.get("loop_pool", {}),
            }

        if action == "submit":
            description = payload.get("description", "")
            priority = payload.get("priority", 50)
            workspace = payload.get("workspace")
            if not description:
                raise RuntimeError("description is required")
            goal = await service.submit_task(description, priority=priority, workspace=workspace)
            return {"status": "submitted", "goal_id": goal.id}

        if action == "list_goals":
            goals = await service.list_goals()
            return {
                "goals": [g.model_dump(mode="json") for g in goals],
                "source": "autopilot_service",
            }

        if action == "get_goal":
            goal_id = payload.get("goal_id")
            goal = await service.get_goal(goal_id)
            if goal:
                return {"goal": goal.model_dump(mode="json"), "source": "autopilot_service"}
            raise RuntimeError("Goal not found")

        if action == "cancel_goal":
            goal_id = payload.get("goal_id")
            cancelled = await service.cancel_goal(goal_id, reason="ws_command")
            if cancelled is None:
                raise RuntimeError("Goal not found")
            return {"status": "cancelled", "goal_id": cancelled.id, "new_status": cancelled.status}

        if action == "approve":
            confirmation_id = payload.get("confirmation_id")
            approved = await service.approve_confirmation(confirmation_id)
            if approved:
                return {"status": "approved", "goal_id": confirmation_id}
            raise RuntimeError("Confirmation not found")

        if action == "reject":
            confirmation_id = payload.get("confirmation_id")
            rejected = await service.reject_confirmation(confirmation_id)
            if rejected:
                return {"status": "rejected", "goal_id": confirmation_id}
            raise RuntimeError("Confirmation not found")

        if action == "resume":
            goal_id = payload.get("goal_id")
            goal_engine = service._ce
            goal = await goal_engine.get_goal(goal_id)
            if goal is None:
                raise RuntimeError("Goal not found")
            if goal.status not in ("suspended", "blocked"):
                raise RuntimeError(f"Goal is not paused (status: {goal.status})")
            reactivated = await goal_engine.reactivate_goal(goal_id)
            return {"status": "reactivated", "goal_id": goal_id, "new_status": reactivated.status}

        if action == "wake":
            await service.wake_from_dreaming(trigger="ws_command")
            return {"status": "wake_sent"}

        if action == "dream":
            await service.force_dream()
            return {"status": "dream_sent"}

        if action == "list_jobs":
            goals = await service.list_goals()
            jobs = [g for g in goals if g.parent_id is None]
            return {
                "jobs": [j.model_dump(mode="json") for j in jobs],
                "source": "autopilot_service",
            }

        if action == "get_job":
            job_id = payload.get("job_id")
            job = await service.get_goal(job_id)
            if not job:
                raise RuntimeError("Job not found")
            if job.parent_id is not None:
                raise RuntimeError("Not a root goal (job)")
            dag = await service.dag_snapshot(job_id)
            nodes = dag.get("nodes", [])
            active = sum(1 for n in nodes if n.get("status") == "active")
            completed = sum(1 for n in nodes if n.get("status") in ("completed", "validated"))
            return {
                "job": job.model_dump(mode="json"),
                "dag": dag,
                "active_goals": active,
                "completed_goals": completed,
                "total_goals": len(nodes),
                "source": "autopilot_service",
            }

        raise RuntimeError(f"Unknown autopilot action: {action}")

    async def _handle_cron_command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle cron command.

        Args:
            action: Cron action name.
            payload: Command payload.

        Returns:
            Result dict.
        """

        from soothe.foundation.cron import ExtractionError
        from soothe.foundation.cron.extraction import AutopilotDisabledError
        from soothe.foundation.cron.models import DEFAULT_CRON_USER_ID

        service = self._cron_service

        if action == "add":
            text = payload.get("text", "")
            priority = payload.get("priority")
            if not text:
                raise RuntimeError("text is required")
            try:
                job = await service.add_job(text, DEFAULT_CRON_USER_ID, priority=priority)
            except AutopilotDisabledError as exc:
                raise RuntimeError(exc.message) from exc
            except ExtractionError as exc:
                raise RuntimeError(exc.message) from exc
            return {"job": job.to_dict(), "source": "cron_service"}

        if action == "list_jobs":
            status = payload.get("status")
            jobs = await service.list_jobs(DEFAULT_CRON_USER_ID, status=status)
            return {"jobs": [j.to_dict() for j in jobs], "source": "cron_service"}

        if action == "show":
            job_id = payload.get("job_id")
            job = await service.show_job(job_id, DEFAULT_CRON_USER_ID)
            if job:
                return {"job": job.to_dict(), "source": "cron_service"}
            raise RuntimeError("Job not found")

        if action == "cancel":
            job_id = payload.get("job_id")
            cancelled = await service.cancel_job(job_id, DEFAULT_CRON_USER_ID)
            if cancelled:
                return {"cancelled": True, "job_id": job_id}
            raise RuntimeError("Job not found or cannot be cancelled")

        raise RuntimeError(f"Unknown cron action: {action}")

    async def _handle_memory_command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle memory profiling command.

        Args:
            action: Memory action name.
            payload: Command payload.

        Returns:
            Result dict.
        """
        loop = asyncio.get_running_loop()
        profiler = self._memory_profiler
        mode = payload.get("mode", "daemon")

        if mode == "daemon":
            stats = await loop.run_in_executor(None, profiler.get_current_stats)
            return {"memory_stats": stats}

        if mode == "gc":
            stats = await loop.run_in_executor(None, profiler.force_gc_and_report)
            return {"memory_stats": stats}

        if mode == "snapshot":
            await loop.run_in_executor(None, profiler.update_last_snapshot)
            stats = await loop.run_in_executor(None, profiler.get_current_stats)
            return {"memory_stats": stats}

        if mode == "objects":
            counts = await loop.run_in_executor(None, profiler.get_object_counts)
            return {"memory_stats": {"object_counts": counts}}

        if mode == "compare":
            try:
                stats = await loop.run_in_executor(None, profiler.compare_snapshots)
                return {"memory_stats": stats}
            except ValueError as e:
                raise RuntimeError(str(e)) from e

        if mode == "queues":
            metrics = await loop.run_in_executor(None, profiler.get_queue_metrics)
            return {"memory_stats": {"queue_metrics": metrics}}

        if mode == "large":
            large = await loop.run_in_executor(None, profiler.get_large_allocations)
            return {"memory_stats": {"large_allocations": large}}

        raise RuntimeError(f"Unknown memory mode: {mode}")
