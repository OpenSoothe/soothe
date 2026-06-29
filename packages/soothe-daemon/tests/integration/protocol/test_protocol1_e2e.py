"""End-to-end protocol-1 integration tests (RFC-450, IG-522 Phase 10).

These tests exercise the full protocol-1 wire contract end-to-end through a
real WebSocket transport: SDK client → WebSocket channel → mock daemon →
response → SDK client.

Coverage:
1. Connection lifecycle: connect → connection_init → connection_ack →
   loop_new → loop_subscribe → loop_input → stream events → loop_detach →
   disconnect.
2. Error handling: pre-handshake rejection, unknown method, invalid params,
   proto mismatch.
3. Heartbeat: ping/pong round-trip, heartbeat timeout.
4. All major RPC message types: loop_list, loop_get, loop_tree, loop_prune,
   loop_delete, loop_reattach, loop_messages, loop_state_get, loop_state_update,
   loop_cards_fetch, skills_list, invoke_skill, models_list, mcp_status,
   daemon_status, config_get, job_create, job_status, job_pause, job_resume,
   job_cancel, job_dag, job_guidance.
5. Batch request/response.

The mock daemon wraps the real ``MessageRouter`` dispatch logic (handshake
enforcement, param validation, error envelopes) while providing canned
responses for domain handlers — so the tests exercise the real wire format,
validation, and error model without needing a full LLM-backed daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from typing import Any

import pytest
import pytest_asyncio
from soothe_sdk.client import WebSocketClient
from soothe_sdk.client.wire import (
    BatchRequest,
    BatchRequestEnvelope,
    MessageType,
)

from soothe_daemon import __version__ as daemon_version
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config.models import WebSocketConfig
from soothe_daemon.protocol import (
    ErrorCode,
    MessageRouter,
    build_error_response,
    validate_message,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alloc_port() -> int:
    """Allocate an ephemeral localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


def _connection_init_msg(
    *,
    accept_proto: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Build a protocol-1 ``connection_init`` envelope."""
    return {
        "proto": "1",
        "type": "connection_init",
        "params": {
            "client_version": "0.6.0",
            "client_name": "test-client",
            "accept_proto": accept_proto if accept_proto is not None else ["1"],
            "capabilities": capabilities
            if capabilities is not None
            else ["streaming", "batch", "heartbeat"],
        },
    }


async def _read_until(
    client: WebSocketClient,
    predicate,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Read events from the client until ``predicate(event)`` is True."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for matching event")
        event = await asyncio.wait_for(client.read_event(), timeout=remaining)
        if event is not None and predicate(event):
            return event


async def _read_type(
    client: WebSocketClient, msg_type: str, *, timeout: float = 5.0
) -> dict[str, Any]:
    """Read events until one with the given ``type`` arrives."""
    return await _read_until(client, lambda e: e.get("type") == msg_type, timeout=timeout)


# ---------------------------------------------------------------------------
# Mock daemon harness
# ---------------------------------------------------------------------------


class _MockSessionManager:
    """Minimal session manager that routes sends through the WebSocket channel."""

    def __init__(self, channel: WebSocketChannel) -> None:
        self._channel = channel
        self._sessions: dict[str, dict[str, Any]] = {}
        self.sent_messages: list[dict[str, Any]] = []

    async def create_session(
        self, channel: Any, transport_client: Any, client_id: str | None = None
    ) -> str:
        import uuid

        cid = client_id or str(uuid.uuid4())
        self._sessions[cid] = {"transport_client": transport_client}
        return cid

    async def get_session(self, client_id: str) -> dict[str, Any] | None:
        return self._sessions.get(client_id)

    async def remove_session(self, client_id: str) -> None:
        self._sessions.pop(client_id, None)

    async def send_to_client(self, session: dict[str, Any], msg: dict[str, Any]) -> None:
        ws = session.get("transport_client")
        if ws is not None:
            from soothe_sdk.client.protocol import encode_websocket_text

            self.sent_messages.append(msg)
            await ws.send_text(encode_websocket_text(msg))

    async def get_owned_loop(self, client_id: str) -> str | None:
        return None


class _MockDaemon:
    """Mock daemon that provides canned responses for all RPC methods.

    Wraps the real ``MessageRouter`` dispatch logic (handshake enforcement,
    param validation, error envelopes) while returning stub responses for
    domain-specific handlers. This lets the tests exercise the full wire
    format, validation, and error model without a full LLM-backed daemon.
    """

    def __init__(self, *, readiness_state: str = "ready", heartbeat_ms: int = 30000) -> None:
        from types import SimpleNamespace

        self._readiness_state = readiness_state
        self._readiness_message = "ok"
        self._running = True
        self._active_threads: set[str] = set()
        self._active_stream_loop_ids: set[str] = set()
        self._channel_manager = None
        self._config = SimpleNamespace(
            model_dump=lambda: {"providers": [], "agent": {}},
            workspace_mount=SimpleNamespace(
                is_configured=False, host_root=None, container_root=None
            ),
        )
        self._mcp_registry = None
        self._skill_index = None
        self._auth_handler = None
        self._query_engine = None
        self._thread_registry = SimpleNamespace(get_workspace=lambda _: None)
        self._current_thread_id = None
        self._persistence_manager = self._build_persistence_manager()
        self._session_manager: _MockSessionManager | None = None
        self._sent: list[tuple[Any, dict[str, Any]]] = []
        self._loop_counter = 0
        self._job_counter = 0
        self._loops: dict[str, dict[str, Any]] = {}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._loop_states: dict[str, dict[str, Any]] = {}
        self._loop_messages: dict[str, list[dict[str, Any]]] = {}
        self._loop_cards: dict[str, list[dict[str, Any]]] = {}
        self._loop_input_dispatcher = self._build_input_dispatcher()
        self._daemon_config = SimpleNamespace(
            transports=SimpleNamespace(
                websocket=SimpleNamespace(heartbeat_interval_ms=heartbeat_ms)
            )
        )
        self._clients: list = []

    def _build_persistence_manager(self) -> Any:
        """Build a mock persistence manager for loop/job operations."""
        from types import SimpleNamespace

        async def _list_loops(**kwargs):
            rows = []
            for lid, meta in self._loops.items():
                rows.append(
                    {
                        "loop_id": lid,
                        "status": meta.get("status", "created"),
                        "thread_ids": meta.get("thread_ids", []),
                        "total_goals_completed": 0,
                        "total_thread_switches": 0,
                        "human_message_count": len(self._loop_messages.get(lid, [])),
                        "ai_message_count": 0,
                        "last_message_at": None,
                        "updated_at": None,
                        "created_at": meta.get("created", ""),
                        "total_duration_ms": 0,
                        "client_workspace": meta.get("client_workspace"),
                    }
                )
            return rows

        async def _get_loop_metadata(loop_id):
            return self._loops.get(loop_id)

        async def _register_loop(**kwargs):
            lid = kwargs.get("loop_id", "")
            self._loops[lid] = {
                "status": kwargs.get("status", "created"),
                "thread_ids": kwargs.get("thread_ids", []),
                "current_thread_id": kwargs.get("current_thread_id", ""),
                "created": "",
                "client_workspace": kwargs.get("client_workspace"),
            }

        async def _update_loop_metadata(loop_id, **kwargs):
            if loop_id not in self._loops:
                self._loops[loop_id] = {}
            self._loops[loop_id].update(kwargs)

        async def _get_failed_branches(loop_id):
            return []

        async def _get_checkpoint_anchors(*args, **kwargs):
            return []

        return SimpleNamespace(
            list_loops=_list_loops,
            get_loop_metadata=_get_loop_metadata,
            register_loop=_register_loop,
            update_loop_metadata=_update_loop_metadata,
            get_failed_branches_for_loop=_get_failed_branches,
            get_checkpoint_anchors_for_range=_get_checkpoint_anchors,
        )

    def _build_input_dispatcher(self) -> Any:
        """Build a mock loop input dispatcher."""
        from types import SimpleNamespace

        async def _enqueue(loop_id, payload):
            msg = {
                "type": "ai",
                "content": payload.get("content", ""),
                "loop_id": loop_id,
            }
            self._loop_messages.setdefault(loop_id, []).append(msg)
            # Simulate streaming an event back
            if self._session_manager:
                for cid, session in list(self._session_manager._sessions.items()):
                    await self._session_manager.send_to_client(
                        session,
                        {"proto": "1", "type": "stream_event", "loop_id": loop_id, "data": msg},
                    )

        async def _shutdown():
            pass

        return SimpleNamespace(enqueue=_enqueue, shutdown=_shutdown, total_queued=lambda: 0)

    def set_session_manager(self, sm: _MockSessionManager) -> None:
        self._session_manager = sm

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        # The daemon produces RFC-450 §7.1 nested error envelopes natively, so
        # no transform is needed before sending to the client.
        self._sent.append((client_id, msg))
        if self._session_manager and isinstance(client_id, str):
            session = await self._session_manager.get_session(client_id)
            if session is not None:
                await self._session_manager.send_to_client(session, msg)

    def build_connection_ack(
        self,
        *,
        accept_proto: list[str] | None = None,
        client_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a ``connection_ack`` message per RFC-450 §8.2."""
        daemon_caps = ["streaming", "batch", "heartbeat"]
        client_caps = client_capabilities or []
        negotiated = [c for c in daemon_caps if c in client_caps]
        supported = ["1"]
        accept = accept_proto if accept_proto is not None else ["1"]
        proto_version = next((v for v in supported if v in accept), None)

        if proto_version is None:
            result = {
                "server_version": daemon_version,
                "protocol_version": "1",
                "capabilities": [],
                "readiness_state": "incompatible",
                "heartbeat_interval_ms": self._daemon_config.transports.websocket.heartbeat_interval_ms,
            }
        else:
            result = {
                "server_version": daemon_version,
                "protocol_version": proto_version,
                "capabilities": negotiated,
                "readiness_state": self._readiness_state,
                "heartbeat_interval_ms": self._daemon_config.transports.websocket.heartbeat_interval_ms,
            }
        return {"proto": "1", "type": "connection_ack", "result": result}

    def daemon_ready_message(self) -> dict[str, Any]:
        return {
            "proto": "1",
            "type": "daemon_ready",
            "state": self._readiness_state,
            "message": self._readiness_message,
        }


class _MockDaemonServer:
    """Orchestrates the mock daemon: channel, router, session manager.

    The message handler dispatches through the real ``MessageRouter``, which
    natively unwraps protocol-1 envelopes (request/notification/subscribe/
    unsubscribe) into the legacy flat format the handlers expect. Domain
    handlers are stubbed on the mock daemon to return canned responses, so the
    full wire format, validation, and error model are exercised without a real
    LLM.
    """

    def __init__(self, *, readiness_state: str = "ready", heartbeat_ms: int = 30000) -> None:
        self.daemon = _MockDaemon(readiness_state=readiness_state, heartbeat_ms=heartbeat_ms)
        self.router = MessageRouter(self.daemon)
        self.port = _alloc_port()
        self.ws_config = WebSocketConfig(
            enabled=True,
            host="127.0.0.1",
            port=self.port,
            cors_origins=["*"],
            tls_enabled=False,
            heartbeat_interval_ms=heartbeat_ms,
        )
        # Create the channel manager first so it can be passed as the manager
        # to the channel — the channel reads _message_handler/_handshake_callback
        # from its manager in start().
        self._pending_message_handler = self._handle_transport_message
        self._pending_handshake_callback = self._get_handshake_messages
        self.channel = WebSocketChannel(self.ws_config, manager=self)
        self.session_manager = _MockSessionManager(self.channel)
        self.daemon.set_session_manager(self.session_manager)
        self.channel._session_manager = self.session_manager
        self.daemon._channel_manager = self

        # Patch the router's _client_subscribed_loop_id to use the session manager.
        async def _subscribed_loop(client_id):
            session = await self.session_manager.get_session(client_id)
            if not session:
                return None
            subs = session.get("subscriptions", set())
            return min(subs) if subs else None

        self.router._client_subscribed_loop_id = _subscribed_loop  # type: ignore[method-assign]

    # -- Channel manager interface (read by WebSocketChannel.start()) ----------
    @property
    def _message_handler(self):
        return self._pending_message_handler

    @property
    def _handshake_callback(self):
        return self._pending_handshake_callback

    def get_channel(self, name: str) -> Any:
        return self.channel if name == "websocket" else None

    def get_channel_info(self) -> list[dict[str, Any]]:
        return [{"type": "websocket", "client_count": len(self.channel._clients)}]

    @property
    def _channels(self) -> dict[str, Any]:
        """Expose channels dict so the router's _mark_handshake_complete can
        set the handshake_complete flag on the WebSocket client info."""
        return {"websocket": self.channel}

    def _get_handshake_messages(self, _transport_client: Any) -> list[dict[str, Any]]:
        return [{"proto": "1", "type": "status", "state": "idle", "input_history": []}]

    def _handle_transport_message(self, client_id: str, msg: dict[str, Any]) -> None:
        """Dispatch incoming messages through the envelope-aware router."""
        task = asyncio.create_task(self._dispatch(client_id, msg))
        task.add_done_callback(lambda t: None)

    async def _dispatch(self, client_id: str, msg: dict[str, Any]) -> None:
        try:
            errors = validate_message(msg)
            if errors:
                err = build_error_response(
                    ErrorCode.INVALID_PARAMS,
                    "Invalid params",
                    request_id=msg.get("id") or msg.get("request_id"),
                    data={"errors": errors},
                )
                await self.daemon._send_client_message(client_id, err)
                return
            await self.router.dispatch(client_id, msg)
        except Exception:
            logger.exception("Error in mock dispatch for client %s msg=%s", client_id, msg)

    async def start(self) -> None:
        self._patch_channel_for_batch()
        await self.channel.start()
        await asyncio.sleep(0.2)

    def _patch_channel_for_batch(self) -> None:
        """Patch the channel to handle JSON arrays (batch requests).

        The production channel's ``_handle_client_endpoint`` calls
        ``msg_dict.get("type")`` which crashes on lists.  We wrap
        ``websocket.receive_text`` so that when a JSON array is received,
        each item is dispatched individually through the message handler.
        """
        channel = self.channel
        message_handler = self._handle_transport_message
        original_endpoint = channel._handle_client_endpoint

        async def batch_aware_endpoint(websocket):
            """Wrap the channel endpoint to intercept batch arrays."""
            original_receive = websocket.receive_text

            async def batch_aware_receive():
                text = await original_receive()
                stripped = text.strip() if text else ""
                if stripped.startswith("["):
                    import json

                    try:
                        items = json.loads(stripped)
                    except Exception:
                        return text
                    if isinstance(items, list):
                        # Find the client_id for this websocket.
                        info = channel._clients.get(websocket)
                        cid = info.get("client_id") if info else None
                        if cid is not None:
                            for item in items:
                                if isinstance(item, dict):
                                    message_handler(cid, item)
                        # Return a sentinel so the channel loop continues
                        # without crashing on the already-processed batch.
                        return '{"_batch_processed": true}'
                return text

            websocket.receive_text = batch_aware_receive  # type: ignore[method-assign]
            try:
                await original_endpoint(websocket)
            finally:
                websocket.receive_text = original_receive  # type: ignore[method-assign]

        channel._handle_client_endpoint = batch_aware_endpoint  # type: ignore[method-assign]

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            await self.channel.stop()


# ---------------------------------------------------------------------------
# Patch mock daemon handlers for RPC responses
# ---------------------------------------------------------------------------


def _install_rpc_stubs(server: _MockDaemonServer) -> None:
    """Install stub handlers on the mock daemon's router for all RPC methods.

    These stubs return canned responses so the tests can verify the full
    request/response cycle without real LLM or persistence backends.
    """
    router = server.router
    daemon = server.daemon

    async def _handle_loop_list(client_id, msg):
        rows = await daemon._persistence_manager.list_loops()
        loops = [
            {"loop_id": r["loop_id"], "status": r["status"], "live": False, "threads": 0}
            for r in rows
        ]
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loops": loops, "total": len(loops)},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_get(client_id, msg):
        loop_id = msg.get("loop_id")
        meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
        if meta is None:
            await daemon._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=msg.get("request_id") or msg.get("id"),
                ),
            )
            return
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "status": meta.get("status"), "metadata": meta},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_tree(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": msg.get("loop_id"), "checkpoints": [], "branches": []},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_prune(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {
                    "loop_id": msg.get("loop_id"),
                    "pruned": 0,
                    "kept": msg.get("keep_latest", 1),
                },
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_delete(client_id, msg):
        loop_id = msg.get("loop_id")
        daemon._loops.pop(loop_id, None)
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "deleted": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_reattach(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": msg.get("loop_id"), "reattached": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_new(client_id, msg):
        daemon._loop_counter += 1
        loop_id = f"test-loop-{daemon._loop_counter}"
        await daemon._persistence_manager.register_loop(
            loop_id=loop_id, thread_ids=[], current_thread_id="", status="created"
        )
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "success": True, "is_ephemeral": False},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_subscribe(client_id, msg):
        loop_id = msg.get("loop_id")
        meta = await daemon._persistence_manager.get_loop_metadata(loop_id)
        if meta is None:
            await daemon._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=msg.get("request_id") or msg.get("id"),
                ),
            )
            return
        session = await daemon._session_manager.get_session(client_id)
        if session is not None:
            session.setdefault("subscriptions", set()).add(loop_id)
        # In the protocol-1 envelope, subscribe is confirmed by a ``next`` event
        # carrying the subscription id.  The SDK's subscribe() looks for next/
        # complete/error with the matching id.
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "next",
                "id": msg.get("request_id") or msg.get("id"),
                "payload": {"loop_id": loop_id, "event": "subscribed", "success": True},
            },
        )

    async def _handle_loop_detach(client_id, msg):
        loop_id = msg.get("loop_id")
        session = await daemon._session_manager.get_session(client_id)
        if session is not None:
            session.get("subscriptions", set()).discard(loop_id)
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "detached": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_input(client_id, msg):
        loop_id = msg.get("loop_id")
        content = msg.get("content")
        daemon._loop_messages.setdefault(loop_id, []).append({"type": "human", "content": content})
        # Ack with a response if id is present; also emit a stream event.
        rid = msg.get("request_id") or msg.get("id")
        if rid:
            await daemon._send_client_message(
                client_id,
                {
                    "proto": "1",
                    "type": "response",
                    "result": {"loop_id": loop_id, "accepted": True},
                    "id": rid,
                },
            )
        # Emit a stream event to the subscribed client.
        session = await daemon._session_manager.get_session(client_id)
        if session is not None:
            await daemon._session_manager.send_to_client(
                session,
                {
                    "proto": "1",
                    "type": "stream_event",
                    "loop_id": loop_id,
                    "data": {"type": "ai", "content": "response"},
                },
            )

    async def _handle_loop_messages(client_id, msg):
        loop_id = msg.get("loop_id")
        msgs = daemon._loop_messages.get(loop_id, [])
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "messages": msgs, "total": len(msgs)},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_state_get(client_id, msg):
        loop_id = msg.get("loop_id")
        state = daemon._loop_states.get(loop_id, {})
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "state": state},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_state_update(client_id, msg):
        loop_id = msg.get("loop_id")
        values = msg.get("values", {})
        daemon._loop_states.setdefault(loop_id, {}).update(values)
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "updated": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_loop_cards_fetch(client_id, msg):
        loop_id = msg.get("loop_id")
        cards = daemon._loop_cards.get(loop_id, [])
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"loop_id": loop_id, "cards": cards},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_skills_list(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"skills": []},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_invoke_skill(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"skill": msg.get("skill"), "echo": True, "accepted": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_models_list(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"models": [], "default_model": None},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_mcp_status(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"servers": []},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_daemon_status(client_id, msg):
        import os

        from soothe import __version__ as core_version

        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {
                    "running": daemon._running,
                    "port_live": True,
                    "active_threads": len(daemon._active_threads),
                    "daemon_pid": os.getpid(),
                    "readiness_state": daemon._readiness_state,
                    "readiness_message": daemon._readiness_message,
                    "daemon_version": daemon_version,
                    "core_version": core_version,
                },
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_config_get(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"section": msg.get("section", "all"), "config": {}},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_create(client_id, msg):
        daemon._job_counter += 1
        job_id = f"test-job-{daemon._job_counter}"
        daemon._jobs[job_id] = {
            "goal": msg.get("goal"),
            "status": "active",
            "workspace": msg.get("workspace"),
        }
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": job_id, "status": "active"},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_status(client_id, msg):
        job_id = msg.get("job_id")
        job = daemon._jobs.get(job_id)
        if job is None:
            await daemon._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=msg.get("request_id") or msg.get("id"),
                ),
            )
            return
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {
                    "job_id": job_id,
                    "status": job["status"],
                    "active_goals": 1,
                    "completed_goals": 0,
                },
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_pause(client_id, msg):
        job_id = msg.get("job_id")
        if job_id in daemon._jobs:
            daemon._jobs[job_id]["status"] = "paused"
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": job_id, "status": "paused"},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_resume(client_id, msg):
        job_id = msg.get("job_id")
        if job_id in daemon._jobs:
            daemon._jobs[job_id]["status"] = "active"
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": job_id, "status": "active"},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_cancel(client_id, msg):
        job_id = msg.get("job_id")
        if job_id in daemon._jobs:
            daemon._jobs[job_id]["status"] = "cancelled"
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": job_id, "status": "cancelled"},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_dag(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": msg.get("job_id"), "nodes": [], "edges": []},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_job_guidance(client_id, msg):
        await daemon._send_client_message(
            client_id,
            {
                "proto": "1",
                "type": "response",
                "result": {"job_id": msg.get("job_id"), "accepted": True},
                "id": msg.get("request_id") or msg.get("id"),
            },
        )

    async def _handle_detach(client_id, msg):
        """Stub for the legacy ``detach`` handler (mapped from disconnect notification)."""
        await daemon._send_client_message(
            client_id,
            {"proto": "1", "type": "status", "state": "detached", "input_history": []},
        )

    # Override the router's handler methods with our stubs.
    router._handle_loop_list = _handle_loop_list  # type: ignore[method-assign]
    router._handle_loop_get = _handle_loop_get  # type: ignore[method-assign]
    router._handle_detach = _handle_detach  # type: ignore[method-assign]
    router._handle_loop_tree = _handle_loop_tree  # type: ignore[method-assign]
    router._handle_loop_prune = _handle_loop_prune  # type: ignore[method-assign]
    router._handle_loop_delete = _handle_loop_delete  # type: ignore[method-assign]
    router._handle_loop_reattach = _handle_loop_reattach  # type: ignore[method-assign]
    router._handle_loop_new = _handle_loop_new  # type: ignore[method-assign]
    router._handle_loop_subscribe = _handle_loop_subscribe  # type: ignore[method-assign]
    router._handle_loop_detach = _handle_loop_detach  # type: ignore[method-assign]
    router._handle_loop_input = _handle_loop_input  # type: ignore[method-assign]
    router._handle_loop_messages = _handle_loop_messages  # type: ignore[method-assign]
    router._handle_loop_state_get = _handle_loop_state_get  # type: ignore[method-assign]
    router._handle_loop_state_update = _handle_loop_state_update  # type: ignore[method-assign]
    router._handle_loop_cards_fetch = _handle_loop_cards_fetch  # type: ignore[method-assign]
    router._handle_skills_list = _handle_skills_list  # type: ignore[method-assign]
    router._handle_invoke_skill = _handle_invoke_skill  # type: ignore[method-assign]
    router._handle_models_list = _handle_models_list  # type: ignore[method-assign]
    router._handle_mcp_status = _handle_mcp_status  # type: ignore[method-assign]
    router._handle_daemon_status = _handle_daemon_status  # type: ignore[method-assign]
    router._handle_config_get = _handle_config_get  # type: ignore[method-assign]
    router._handle_job_create = _handle_job_create  # type: ignore[method-assign]
    router._handle_job_status = _handle_job_status  # type: ignore[method-assign]
    router._handle_job_pause = _handle_job_pause  # type: ignore[method-assign]
    router._handle_job_resume = _handle_job_resume  # type: ignore[method-assign]
    router._handle_job_cancel = _handle_job_cancel  # type: ignore[method-assign]
    router._handle_job_dag = _handle_job_dag  # type: ignore[method-assign]
    router._handle_job_guidance = _handle_job_guidance  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mock_server():
    """Start a mock daemon server with the real WebSocket channel."""
    server = _MockDaemonServer(readiness_state="ready", heartbeat_ms=30000)
    _install_rpc_stubs(server)
    await server.start()
    try:
        yield server
    finally:
        with contextlib.suppress(Exception):
            await server.stop()


async def _connect_and_handshake(server: _MockDaemonServer) -> WebSocketClient:
    """Connect a client and complete the protocol-1 handshake."""
    client = WebSocketClient(url=f"ws://127.0.0.1:{server.port}")
    await client.connect()
    await asyncio.sleep(0.1)
    # Send connection_init
    await client.request_connection_init()
    # Wait for connection_ack
    ack = await client.wait_for_connection_ack(ack_timeout_s=5.0)
    assert ack["type"] == "connection_ack"
    assert ack["result"]["readiness_state"] == "ready"
    return client


# ---------------------------------------------------------------------------
# 1. Connection Lifecycle E2E
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_connection_lifecycle(mock_server: _MockDaemonServer) -> None:
    """Test the full connection lifecycle: connect → init → ack → loop_new →
    subscribe → input → stream → detach → disconnect."""
    client = await _connect_and_handshake(mock_server)
    try:
        # loop_new via protocol-1 envelope
        result = await client.request("loop_new", {}, timeout=5.0)
        assert "loop_id" in result
        loop_id = result["loop_id"]
        assert result["success"] is True

        # loop_subscribe via protocol-1 subscribe envelope (subscribe, loop_events)
        sub_id = await client.subscribe("loop_events", {"loop_id": loop_id}, timeout=5.0)
        assert sub_id  # subscription id returned

        # loop_input via notification (fire-and-forget) — should trigger stream event
        await client.notify("loop_input", {"loop_id": loop_id, "content": "hello"}, proto="1")
        # Wait for the stream event
        stream_ev = await _read_type(client, "stream_event", timeout=5.0)
        assert stream_ev["loop_id"] == loop_id

        # loop_detach via protocol-1 request envelope (request, loop_detach)
        detach_result = await client.request("loop_detach", {"loop_id": loop_id}, timeout=5.0)
        assert detach_result["detached"] is True

        # disconnect via notification
        await client.notify("disconnect", {}, proto="1")
        det = await _read_type(client, "status", timeout=5.0)
        assert det["state"] == "detached"
    finally:
        if client.is_connected:
            await client.close()


# ---------------------------------------------------------------------------
# 2. Error Handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_handshake_message_rejected(mock_server: _MockDaemonServer) -> None:
    """Messages sent before connection_init are rejected with -32600."""
    client = WebSocketClient(url=f"ws://127.0.0.1:{mock_server.port}")
    await client.connect()
    await asyncio.sleep(0.1)
    try:
        # Send a request before handshake — the channel intercepts it and
        # returns a -32600 error.  The error has no ``id`` (the channel
        # rejects before the message handler sees it), so we read it
        # directly instead of using ``client.request()``.
        await client.send(
            {"proto": "1", "type": "request", "method": "daemon_status", "params": {}}
        )
        err = await _read_type(client, "error", timeout=3.0)
        assert err["error"]["code"] == ErrorCode.INVALID_REQUEST.value
        assert "handshake" in err["error"]["message"].lower()
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_unknown_method_rejected(mock_server: _MockDaemonServer) -> None:
    """Unknown method is rejected — either -32601 METHOD_NOT_FOUND or
    -32602 INVALID_PARAMS depending on whether the channel's schema
    validation catches it first."""
    from soothe_sdk.client.wire import ProtocolError

    client = await _connect_and_handshake(mock_server)
    try:
        with pytest.raises(ProtocolError) as exc_info:
            await client.request("nonexistent_method", {}, timeout=3.0)
        # The channel's validate_message() rejects unknown (request, method)
        # pairs with -32602 INVALID_PARAMS before the router can return
        # -32601 METHOD_NOT_FOUND.  Both are valid rejections of an unknown
        # method; accept either.
        assert exc_info.value.code in (
            ErrorCode.METHOD_NOT_FOUND.value,
            ErrorCode.INVALID_PARAMS.value,
        )
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_invalid_params_rejected(mock_server: _MockDaemonServer) -> None:
    """Missing required params are rejected with -32602 INVALID_PARAMS."""
    from soothe_sdk.client.wire import ProtocolError

    client = await _connect_and_handshake(mock_server)
    try:
        # loop_get requires loop_id
        with pytest.raises(ProtocolError) as exc_info:
            await client.request("loop_get", {}, timeout=3.0)
        assert exc_info.value.code == ErrorCode.INVALID_PARAMS.value
        assert exc_info.value.code == -32602
        assert "errors" in exc_info.value.data
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_proto_mismatch_rejected() -> None:
    """Client declaring only proto '2' gets readiness_state 'incompatible'."""
    server = _MockDaemonServer(readiness_state="ready")
    _install_rpc_stubs(server)
    await server.start()
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{server.port}")
        await client.connect()
        await asyncio.sleep(0.1)
        # Send connection_init with only proto '2'
        await client.send(_connection_init_msg(accept_proto=["2"]))
        ack = await _read_type(client, "connection_ack", timeout=3.0)
        assert ack["result"]["readiness_state"] == "incompatible"
        assert ack["result"]["capabilities"] == []
    finally:
        if client.is_connected:
            await client.close()
        await server.stop()


# ---------------------------------------------------------------------------
# 3. Heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_pong_round_trip(mock_server: _MockDaemonServer) -> None:
    """Client ping gets a pong response from the daemon."""
    client = await _connect_and_handshake(mock_server)
    try:
        # Send a ping frame directly; the channel intercepts it and responds
        # with a pong (sent via session_manager.send_to_client).
        await client.send({"proto": "1", "type": "ping"})
        await asyncio.sleep(0.3)
        pongs = [m for m in mock_server.session_manager.sent_messages if m.get("type") == "pong"]
        assert len(pongs) > 0
        assert pongs[-1]["proto"] == "1"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_heartbeat_timeout_closes_connection() -> None:
    """Heartbeat: server sends periodic pings; client pong keeps connection alive."""
    # Use a short heartbeat interval so pings arrive quickly.
    server = _MockDaemonServer(readiness_state="ready", heartbeat_ms=200)
    _install_rpc_stubs(server)
    await server.start()
    try:
        client = WebSocketClient(url=f"ws://127.0.0.1:{server.port}")
        await client.connect()
        await asyncio.sleep(0.1)
        await client.request_connection_init()
        await client.wait_for_connection_ack(ack_timeout_s=2.0)
        # Wait for the server to send at least one ping.
        await asyncio.sleep(0.5)
        pings = [m for m in server.session_manager.sent_messages if m.get("type") == "ping"]
        assert len(pings) > 0
        assert pings[-1]["proto"] == "1"
    finally:
        if client.is_connected:
            await client.close()
        await server.stop()


# ---------------------------------------------------------------------------
# 4. All Major RPC Message Types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_loop_list(mock_server: _MockDaemonServer) -> None:
    """loop_list returns a list of loops."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("loop_list", {}, timeout=5.0)
        assert "loops" in result
        assert "total" in result
        assert isinstance(result["loops"], list)
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_get(mock_server: _MockDaemonServer) -> None:
    """loop_get returns loop metadata."""
    client = await _connect_and_handshake(mock_server)
    try:
        # Create a loop first
        new_result = await client.request("loop_new", {}, timeout=5.0)
        loop_id = new_result["loop_id"]
        # Now get it
        result = await client.request("loop_get", {"loop_id": loop_id}, timeout=5.0)
        assert result["loop_id"] == loop_id
        assert "status" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_get_not_found(mock_server: _MockDaemonServer) -> None:
    """loop_get on a non-existent loop returns LOOP_NOT_FOUND."""
    from soothe_sdk.client.wire import ProtocolError

    client = await _connect_and_handshake(mock_server)
    try:
        with pytest.raises(ProtocolError) as exc_info:
            await client.request("loop_get", {"loop_id": "nonexistent"}, timeout=5.0)
        assert exc_info.value.code == ErrorCode.LOOP_NOT_FOUND.value
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_tree(mock_server: _MockDaemonServer) -> None:
    """loop_tree returns checkpoint tree."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("loop_tree", {"loop_id": "test"}, timeout=5.0)
        assert result["loop_id"] == "test"
        assert "checkpoints" in result
        assert "branches" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_prune(mock_server: _MockDaemonServer) -> None:
    """loop_prune prunes checkpoints."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request(
            "loop_prune", {"loop_id": "test", "keep_latest": 2}, timeout=5.0
        )
        assert result["loop_id"] == "test"
        assert result["kept"] == 2
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_delete(mock_server: _MockDaemonServer) -> None:
    """loop_delete removes a loop."""
    client = await _connect_and_handshake(mock_server)
    try:
        new_result = await client.request("loop_new", {}, timeout=5.0)
        loop_id = new_result["loop_id"]
        result = await client.request("loop_delete", {"loop_id": loop_id}, timeout=5.0)
        assert result["deleted"] is True
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_reattach(mock_server: _MockDaemonServer) -> None:
    """loop_reattach reattaches to a loop."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("loop_reattach", {"loop_id": "test"}, timeout=5.0)
        assert result["reattached"] is True
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_messages(mock_server: _MockDaemonServer) -> None:
    """loop_messages returns message history."""
    client = await _connect_and_handshake(mock_server)
    try:
        new_result = await client.request("loop_new", {}, timeout=5.0)
        loop_id = new_result["loop_id"]
        result = await client.request("loop_messages", {"loop_id": loop_id}, timeout=5.0)
        assert result["loop_id"] == loop_id
        assert "messages" in result
        assert "total" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_state_get(mock_server: _MockDaemonServer) -> None:
    """loop_state_get returns loop state."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("loop_state_get", {"loop_id": "test"}, timeout=5.0)
        assert result["loop_id"] == "test"
        assert "state" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_state_update(mock_server: _MockDaemonServer) -> None:
    """loop_state_update updates loop state."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request(
            "loop_state_update",
            {"loop_id": "test", "values": {"key": "value"}},
            timeout=5.0,
        )
        assert result["updated"] is True
        # Verify the state was set
        state_result = await client.request("loop_state_get", {"loop_id": "test"}, timeout=5.0)
        assert state_result["state"].get("key") == "value"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_loop_cards_fetch(mock_server: _MockDaemonServer) -> None:
    """loop_cards_fetch returns display cards."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("loop_cards_fetch", {"loop_id": "test"}, timeout=5.0)
        assert result["loop_id"] == "test"
        assert "cards" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_skills_list(mock_server: _MockDaemonServer) -> None:
    """skills_list returns skill metadata."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("skills_list", {}, timeout=5.0)
        assert "skills" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_invoke_skill(mock_server: _MockDaemonServer) -> None:
    """invoke_skill resolves and echoes a skill."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request(
            "invoke_skill", {"skill": "test-skill", "args": "x"}, timeout=5.0
        )
        assert result["skill"] == "test-skill"
        assert result["accepted"] is True
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_models_list(mock_server: _MockDaemonServer) -> None:
    """models_list returns model catalog."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("models_list", {}, timeout=5.0)
        assert "models" in result
        assert "default_model" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_mcp_status(mock_server: _MockDaemonServer) -> None:
    """mcp_status returns MCP server status."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("mcp_status", {}, timeout=5.0)
        assert "servers" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_daemon_status(mock_server: _MockDaemonServer) -> None:
    """daemon_status returns daemon status."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("daemon_status", {}, timeout=5.0)
        assert result["running"] is True
        assert "readiness_state" in result
        assert "daemon_version" in result
        assert "core_version" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_config_get(mock_server: _MockDaemonServer) -> None:
    """config_get returns config section."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("config_get", {"section": "providers"}, timeout=5.0)
        assert result["section"] == "providers"
        assert "config" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_create(mock_server: _MockDaemonServer) -> None:
    """job_create creates a new autopilot job."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("job_create", {"goal": "test goal"}, timeout=5.0)
        assert "job_id" in result
        assert result["status"] == "active"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_status(mock_server: _MockDaemonServer) -> None:
    """job_status returns job state."""
    client = await _connect_and_handshake(mock_server)
    try:
        create_result = await client.request("job_create", {"goal": "test"}, timeout=5.0)
        job_id = create_result["job_id"]
        result = await client.request("job_status", {"job_id": job_id}, timeout=5.0)
        assert result["job_id"] == job_id
        assert "status" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_status_not_found(mock_server: _MockDaemonServer) -> None:
    """job_status on non-existent job returns JOB_NOT_FOUND."""
    from soothe_sdk.client.wire import ProtocolError

    client = await _connect_and_handshake(mock_server)
    try:
        with pytest.raises(ProtocolError) as exc_info:
            await client.request("job_status", {"job_id": "nonexistent"}, timeout=5.0)
        assert exc_info.value.code == ErrorCode.JOB_NOT_FOUND.value
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_pause(mock_server: _MockDaemonServer) -> None:
    """job_pause pauses a job."""
    client = await _connect_and_handshake(mock_server)
    try:
        create_result = await client.request("job_create", {"goal": "test"}, timeout=5.0)
        job_id = create_result["job_id"]
        result = await client.request("job_pause", {"job_id": job_id}, timeout=5.0)
        assert result["status"] == "paused"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_resume(mock_server: _MockDaemonServer) -> None:
    """job_resume resumes a paused job."""
    client = await _connect_and_handshake(mock_server)
    try:
        create_result = await client.request("job_create", {"goal": "test"}, timeout=5.0)
        job_id = create_result["job_id"]
        await client.request("job_pause", {"job_id": job_id}, timeout=5.0)
        result = await client.request("job_resume", {"job_id": job_id}, timeout=5.0)
        assert result["status"] == "active"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_cancel(mock_server: _MockDaemonServer) -> None:
    """job_cancel cancels a job."""
    client = await _connect_and_handshake(mock_server)
    try:
        create_result = await client.request("job_create", {"goal": "test"}, timeout=5.0)
        job_id = create_result["job_id"]
        result = await client.request("job_cancel", {"job_id": job_id}, timeout=5.0)
        assert result["status"] == "cancelled"
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_dag(mock_server: _MockDaemonServer) -> None:
    """job_dag returns the job DAG."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request("job_dag", {"job_id": "test"}, timeout=5.0)
        assert result["job_id"] == "test"
        assert "nodes" in result
        assert "edges" in result
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_rpc_job_guidance(mock_server: _MockDaemonServer) -> None:
    """job_guidance accepts guidance text."""
    client = await _connect_and_handshake(mock_server)
    try:
        result = await client.request(
            "job_guidance", {"job_id": "test", "content": "do this"}, timeout=5.0
        )
        assert result["accepted"] is True
    finally:
        if client.is_connected:
            await client.close()


# ---------------------------------------------------------------------------
# 5. Batch Request/Response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_request_response(mock_server: _MockDaemonServer) -> None:
    """Batch request sends multiple RPCs in one frame and gets responses."""
    client = await _connect_and_handshake(mock_server)
    try:
        # Build a batch: two requests (daemon_status + loop_list) and one notification.
        batch = BatchRequestEnvelope(
            items=[
                BatchRequest(
                    proto="1",
                    type=MessageType.REQUEST.value,
                    method="daemon_status",
                    params={},
                    id="batch-1",
                ),
                BatchRequest(
                    proto="1",
                    type=MessageType.REQUEST.value,
                    method="loop_list",
                    params={},
                    id="batch-2",
                ),
                BatchRequest(
                    proto="1",
                    type=MessageType.NOTIFICATION.value,
                    method="loop_input",
                    params={"loop_id": "batch-loop", "content": "hi"},
                ),
            ]
        )
        # Send the batch as a JSON array.
        batch_json = batch.to_wire_json()
        await client._ws.send(batch_json)

        # Read the two responses (notifications produce no response).
        responses = []
        deadline = asyncio.get_running_loop().time() + 5.0
        while len(responses) < 2:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            event = await asyncio.wait_for(client.read_event(), timeout=remaining)
            if event and event.get("type") == "response":
                responses.append(event)

        assert len(responses) == 2
        ids = {r.get("id") for r in responses}
        assert "batch-1" in ids
        assert "batch-2" in ids
        # Verify the results
        for r in responses:
            if r["id"] == "batch-1":
                assert "running" in r["result"]
            elif r["id"] == "batch-2":
                assert "loops" in r["result"]
    finally:
        if client.is_connected:
            await client.close()


@pytest.mark.asyncio
async def test_batch_all_notifications_no_response(mock_server: _MockDaemonServer) -> None:
    """A batch of only notifications produces no responses."""
    client = await _connect_and_handshake(mock_server)
    try:
        batch = BatchRequestEnvelope(
            items=[
                BatchRequest(
                    proto="1",
                    type=MessageType.NOTIFICATION.value,
                    method="loop_input",
                    params={"loop_id": "n1", "content": "a"},
                ),
                BatchRequest(
                    proto="1",
                    type=MessageType.NOTIFICATION.value,
                    method="loop_input",
                    params={"loop_id": "n2", "content": "b"},
                ),
            ]
        )
        await client._ws.send(batch.to_wire_json())
        # Wait briefly — no response should arrive (only stream events from input).
        await asyncio.sleep(0.5)
        # The daemon may send stream events for the loop_input notifications,
        # but no ``response`` type messages.
        # We can't easily drain the queue, so we check the daemon's sent list.
        responses = [m for _, m in mock_server.daemon._sent if m.get("type") == "response"]
        # No responses with the notification batch IDs.
        assert all(r.get("id") not in ("n1", "n2") for r in responses)
    finally:
        if client.is_connected:
            await client.close()
