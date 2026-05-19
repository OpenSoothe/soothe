"""WebSocket client for daemon connections (RFC-0013)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from typing import Any

import websockets.asyncio.client
import websockets.exceptions

from soothe_sdk.client.protocol import decode_websocket_text, encode_websocket_text
from soothe_sdk.core.types import VerbosityLevel

logger = logging.getLogger(__name__)

# Align with soothe_daemon.config.models.WebSocketConfig.max_frame_size (default 10 MiB).
# The websockets library defaults max_size to 1 MiB, which closes the connection (1009)
# when the daemon streams larger JSON events to the client.
_DEFAULT_MAX_FRAME_SIZE = 10 * 1024 * 1024

# RFC-450: clients must wait (bounded) while the daemon is still starting; it does not
# necessarily push another ``daemon_ready`` when transitioning to ready, so we re-request.
_TRANSITIONAL_DAEMON_READY_STATES = frozenset({"starting", "warming"})
_DAEMON_READY_POLL_INTERVAL_S = 0.05


class WebSocketClient:
    """WebSocket client for communicating with Soothe daemon.

    This client connects to the daemon via WebSocket and provides
    streaming event access and bidirectional message passing.

    Args:
        url: WebSocket URL (e.g., ``ws://localhost:8765``).
        client_id: Optional client identifier for log differentiation. If not
            provided, a short random ID is generated (8 hex chars).
        max_frame_size: Maximum incoming WebSocket message size in bytes. Should be
            at least the daemon's ``transport.websocket.max_frame_size`` when that
            is customized.
    """

    def __init__(
        self,
        url: str = "ws://localhost:8765",
        *,
        client_id: str | None = None,
        max_frame_size: int = _DEFAULT_MAX_FRAME_SIZE,
    ) -> None:
        """Initialize WebSocket client.

        Args:
            url: WebSocket URL.
            client_id: Optional client identifier for log differentiation.
            max_frame_size: Max size for frames received from the daemon.
        """
        self._url = url
        self._client_id = client_id or uuid.uuid4().hex[:8]
        self._max_frame_size = max_frame_size
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._connected = False
        self._pending_events: deque[dict[str, Any]] = deque()
        # Coalesce high-frequency daemon_status polls on a long-lived connection.
        self._daemon_status_cache: tuple[float, dict[str, Any]] | None = None
        self._daemon_status_lock = asyncio.Lock()
        self._daemon_status_inflight: asyncio.Task[dict[str, Any]] | None = None

    async def connect(self) -> None:
        """Connect to the daemon.

        Raises:
            ConnectionError: If connection fails.
        """
        try:
            # Disable WebSocket ping/pong to use application-level heartbeats (RFC-0013)
            self._ws = await websockets.asyncio.client.connect(
                self._url,
                ping_interval=None,  # Disable client-side ping/pong
                ping_timeout=None,  # Use daemon heartbeats instead
                max_size=self._max_frame_size,
            )
            self._connected = True

            logger.info("[Client:%s] Connected to daemon at %s", self._client_id, self._url)
        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to daemon: {e}"
            raise ConnectionError(msg) from e

    async def close(self) -> None:
        """Close the connection with timeout to prevent exit hangs."""
        inflight: asyncio.Task[dict[str, Any]] | None = None
        async with self._daemon_status_lock:
            inflight = self._daemon_status_inflight
            self._daemon_status_inflight = None
            self._daemon_status_cache = None

        if inflight is not None and not inflight.done():
            inflight.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await inflight

        if self._ws:
            try:
                # Wait up to 2s for close handshake to prevent indefinite hangs
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except TimeoutError:
                # Force close on timeout - daemon will handle graceful cleanup
                logger.debug("WebSocket close timed out after 2s, forcing closure")
            except Exception:
                # Suppress other errors (connection closed, network issues)
                logger.debug("WebSocket close error (connection likely already closed)")
            self._ws = None
            self._connected = False
            self._pending_events.clear()

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the daemon.

        Args:
            message: Message dict to send.

        Raises:
            ConnectionError: If not connected or send fails.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to daemon")

        try:
            await self._ws.send(encode_websocket_text(message))
        except websockets.exceptions.ConnectionClosed as e:
            self._connected = False
            raise ConnectionError("Connection closed") from e
        except Exception as e:
            msg = f"Failed to send message: {e}"
            raise ConnectionError(msg) from e

    async def receive(self) -> AsyncGenerator[dict[str, Any]]:
        """Receive messages from the daemon.

        Yields:
            Message dicts received from the daemon.

        Raises:
            ConnectionError: If not connected or receive fails.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to daemon")

        try:
            async for message in self._ws:
                try:
                    message_str = message.decode("utf-8") if isinstance(message, bytes) else message
                    msg_dict = decode_websocket_text(message_str)
                    if msg_dict:
                        yield msg_dict
                except Exception:
                    logger.exception("Error parsing message")
                    continue
        except websockets.exceptions.ConnectionClosed:
            self._connected = False
        except Exception as e:
            self._connected = False
            msg = f"Connection error: {e}"
            raise ConnectionError(msg) from e

    @property
    def client_id(self) -> str:
        """Get the client identifier.

        Returns:
            Client identifier string (8 hex chars).
        """
        return self._client_id

    @property
    def is_connected(self) -> bool:
        """Check if connected to the daemon.

        Returns:
            True if connected, False otherwise.
        """
        return self._connected

    def is_connection_alive(self) -> bool:
        """Check if WebSocket connection is actually alive (not closed).

        This is a deeper check than is_connected - it verifies the actual
        WebSocket state, not just the client-side flag.

        Returns:
            True if WebSocket is open and not closed, False otherwise.
        """
        from websockets.asyncio.connection import State

        return self._ws is not None and self._ws.state == State.OPEN

    async def send_input(
        self,
        loop_id: str,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        interactive: bool = False,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        attachments: list[dict[str, str]] | None = None,
        intent_hint: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        response_schema_strict: bool | None = None,
    ) -> None:
        """Send user input to the daemon for a subscribed loop (``loop_input``).

        Args:
            loop_id: Loop identifier for the subscribed loop.
            text: User input text.
            autonomous: Enable autonomous iteration mode.
            max_iterations: Maximum iterations for autonomous mode.
            preferred_subagent: Preferred subagent hint for routing.
            interactive: Enable interactive HITL mode.
            model: Provider:model override string.
            model_params: Additional model parameters.
            attachments: Image attachments (mime_type + base64 data).
            intent_hint: Suggested intent. Standard values bypass in-agent classification:
                ``quiz``, ``continue_thread``, ``new_goal``. Daemon-only
                values ``direct_llm`` and ``image_to_text`` invoke a configured chat
                model directly (no Soothe agent graph); ``image_to_text`` requires
                ``attachments``. With ``intent_hint=direct_llm``, ``response_schema`` requests
                strict JSON output matching the client JSON Schema.
        """
        payload: dict[str, Any] = {
            "type": "loop_input",
            "loop_id": loop_id,
            "content": text,
        }
        if autonomous:
            payload["autonomous"] = True
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
        if preferred_subagent is not None:
            payload["preferred_subagent"] = preferred_subagent
        if interactive:
            payload["interactive"] = True
        if model:
            payload["model"] = model
        if model_params:
            payload["model_params"] = model_params
        if attachments:
            payload["attachments"] = attachments
        if intent_hint:
            payload["intent_hint"] = intent_hint
        if response_schema:
            payload["response_schema"] = response_schema
        if response_schema_name:
            payload["response_schema_name"] = response_schema_name
        if response_schema_strict is not None:
            payload["response_schema_strict"] = response_schema_strict
        await self.send(payload)

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon.

        Args:
            cmd: Command string.
        """
        await self.send({"type": "command", "cmd": cmd})

    # ---------------------------------------------------------------------------
    # Loop RPC Methods (RFC-504 Loop Management CLI Commands)
    # ---------------------------------------------------------------------------

    async def send_loop_list(
        self,
        filter_dict: dict[str, Any] | None = None,
        *,
        limit: int = 20,
        request_id: str | None = None,
    ) -> None:
        """Request AgentLoop instances via daemon RPC (RFC-504 ``loop_list``).

        Args:
            filter_dict: Optional filter (e.g., {"status": "running"}).
            limit: Maximum number of results.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_list", "limit": limit}
        if filter_dict:
            payload["filter"] = filter_dict
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_get(
        self,
        loop_id: str,
        *,
        verbose: bool = False,
        request_id: str | None = None,
    ) -> None:
        """Request loop details via daemon RPC (RFC-504 ``loop_get``).

        Args:
            loop_id: Loop identifier.
            verbose: Show detailed branch analysis.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {
            "type": "loop_get",
            "loop_id": loop_id,
            "verbose": verbose,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_tree(
        self,
        loop_id: str,
        *,
        format: str = "ascii",
        request_id: str | None = None,
    ) -> None:
        """Request checkpoint tree visualization via daemon RPC (RFC-504 ``loop_tree``).

        Args:
            loop_id: Loop identifier.
            format: Visualization format (ascii, json, dot).
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {
            "type": "loop_tree",
            "loop_id": loop_id,
            "format": format,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_prune(
        self,
        loop_id: str,
        *,
        retention_days: int = 30,
        dry_run: bool = False,
        request_id: str | None = None,
    ) -> None:
        """Request branch pruning via daemon RPC (RFC-504 ``loop_prune``).

        Args:
            loop_id: Loop identifier.
            retention_days: Retention period in days.
            dry_run: Show what would be pruned without making changes.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {
            "type": "loop_prune",
            "loop_id": loop_id,
            "retention_days": retention_days,
            "dry_run": dry_run,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_delete(
        self,
        loop_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Request loop deletion via daemon RPC (RFC-504 ``loop_delete``).

        Args:
            loop_id: Loop identifier.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_delete", "loop_id": loop_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_reattach(
        self,
        loop_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Request loop reattachment via daemon RPC (RFC-411 ``loop_reattach``).

        Reconstructs event history and replays to client for loop reattachment.

        Args:
            loop_id: Loop identifier.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_reattach", "loop_id": loop_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_subscribe(
        self,
        loop_id: str,
        *,
        verbosity: VerbosityLevel = "normal",
        stream_delivery: str = "streaming",
        request_id: str | None = None,
    ) -> None:
        """Subscribe client to loop events via daemon RPC (RFC-503 ``loop_subscribe``).

        Subscribes client to loop topic for real-time event streaming.
        Used by loop continue and loop attach commands.

        Args:
            loop_id: Loop identifier.
            verbosity: Event verbosity (RFC-0022).
            stream_delivery: ``batch`` or ``streaming`` (default) stream shaping for this loop.
            request_id: Optional request correlation ID.
        """
        delivery = stream_delivery if stream_delivery in ("batch", "streaming") else "streaming"
        payload: dict[str, Any] = {
            "type": "loop_subscribe",
            "loop_id": loop_id,
            "verbosity": verbosity,
            "stream_delivery": delivery,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_detach(
        self,
        loop_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Detach loop via daemon RPC (RFC-503 ``loop_detach``).

        Unsubscribes client from loop events while loop continues running.
        Saves detachment checkpoint for later reattachment.

        Args:
            loop_id: Loop identifier.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_detach", "loop_id": loop_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_new(
        self,
        *,
        workspace: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Create new loop via daemon RPC (RFC-503 ``loop_new``).

        Creates fresh loop with new loop_id for new query/conversation.

        Args:
            workspace: Optional client workspace path (e.g., user's CWD). When provided,
                the daemon validates and records it as the loop's filesystem workspace
                (IG-409); otherwise the daemon falls back to a per-loop scratch dir.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_new"}
        if workspace:
            payload["workspace"] = workspace
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_loop_input(
        self,
        loop_id: str,
        content: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Send input to loop via daemon RPC (RFC-503 ``loop_input``).

        Sends user prompt/input to active loop for processing.

        Args:
            loop_id: Loop identifier.
            content: User input/prompt content.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {
            "type": "loop_input",
            "loop_id": loop_id,
            "content": content,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_resume_interrupts(
        self,
        loop_id: str,
        resume_payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        """Send interactive continuation payload for a paused daemon turn (loop-scoped)."""
        payload: dict[str, Any] = {
            "type": "resume_interrupts",
            "loop_id": loop_id,
            "resume_payload": resume_payload,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def request_response(
        self,
        payload: dict[str, Any],
        *,
        response_type: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send a request and wait for a matching response type.

        Args:
            payload: Request payload to send.
            response_type: Expected response message type.
            timeout: Maximum seconds to wait.

        Returns:
            Matching response dict.

        Raises:
            TimeoutError: If no matching response is received.
            RuntimeError: If the daemon returns an error for this request.
        """
        request_id = uuid.uuid4().hex
        payload = dict(payload)
        payload["request_id"] = request_id
        await self.send(payload)

        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await self._read_from_socket()
                    if not event:
                        raise TimeoutError(
                            f"WebSocket closed while waiting for {response_type} "
                            f"(request_id={request_id})"
                        )
                    if event.get("request_id") != request_id:
                        self._pending_events.append(event)
                        continue
                    if event.get("type") == "error":
                        raise RuntimeError(str(event.get("message", "daemon error")))
                    if event.get("type") == response_type:
                        return event
        except TimeoutError:
            raise TimeoutError(
                f"Daemon did not respond to {payload.get('type', 'unknown')} "
                f"within {timeout}s (request_id={request_id}, expected={response_type})"
            ) from None

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self.send({"type": "detach"})

    async def list_skills(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Request wire-safe skill metadata from the daemon (RFC-400 ``skills_list``)."""
        return await self.request_response(
            {"type": "skills_list"},
            response_type="skills_list_response",
            timeout=timeout,
        )

    async def list_models(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Request model catalog rows from the daemon host ``SootheConfig`` (RFC-400 ``models_list``)."""
        return await self.request_response(
            {"type": "models_list"},
            response_type="models_list_response",
            timeout=timeout,
        )

    async def invoke_skill(
        self,
        skill: str,
        args: str = "",
        *,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Resolve a skill on the daemon host and receive echo before streaming (RFC-400)."""
        return await self.request_response(
            {"type": "invoke_skill", "skill": skill, "args": args},
            response_type="invoke_skill_response",
            timeout=timeout,
        )

    async def fetch_daemon_status(
        self,
        *,
        timeout: float = 5.0,
        min_interval_s: float = 1.0,
    ) -> dict[str, Any]:
        """Fetch ``daemon_status_response`` with TTL cache and in-flight coalescing.

        Pollers that call this several times per second only trigger one RPC per
        ``min_interval_s`` window; concurrent callers share a single in-flight
        request.

        Args:
            timeout: Per-request timeout passed to ``request_response``.
            min_interval_s: Minimum seconds between real RPCs. Use ``0`` to
                disable caching and always hit the daemon.

        Returns:
            Parsed daemon status response dict.

        Raises:
            Same as ``request_response`` (timeout, connection errors, etc.).
        """
        if min_interval_s <= 0:
            return await self.request_response(
                {"type": "daemon_status"},
                response_type="daemon_status_response",
                timeout=timeout,
            )

        async with self._daemon_status_lock:
            now = time.monotonic()
            if self._daemon_status_cache is not None:
                ts, cached = self._daemon_status_cache
                if now - ts < min_interval_s:
                    return dict(cached)

            if self._daemon_status_inflight is None:
                self._daemon_status_inflight = asyncio.create_task(
                    self.request_response(
                        {"type": "daemon_status"},
                        response_type="daemon_status_response",
                        timeout=timeout,
                    )
                )
            inflight = self._daemon_status_inflight

        assert inflight is not None
        try:
            result = await inflight
        except BaseException:
            async with self._daemon_status_lock:
                if self._daemon_status_inflight is inflight:
                    self._daemon_status_inflight = None
            raise

        async with self._daemon_status_lock:
            if self._daemon_status_inflight is inflight:
                self._daemon_status_inflight = None
                self._daemon_status_cache = (time.monotonic(), dict(result))
        return dict(result)

    async def send_daemon_status(self, request_id: str | None = None) -> None:
        """Request daemon status check (IG-174 Phase 0).

        Args:
            request_id: Optional request correlation ID.
        """
        await self.send({"type": "daemon_status", "request_id": request_id or uuid.uuid4().hex})

    async def send_daemon_shutdown(self, request_id: str | None = None) -> None:
        """Request daemon shutdown (IG-174 Phase 0).

        Args:
            request_id: Optional request correlation ID.
        """
        await self.send({"type": "daemon_shutdown", "request_id": request_id or uuid.uuid4().hex})

    async def send_config_get(self, section: str, request_id: str | None = None) -> None:
        """Request config section from daemon (IG-174 Phase 0).

        Args:
            section: Config section name (e.g., "providers", "defaults", "all").
            request_id: Optional request correlation ID.
        """
        await self.send(
            {"type": "config_get", "section": section, "request_id": request_id or uuid.uuid4().hex}
        )

    async def request_daemon_ready(self) -> None:
        """Request the daemon's readiness state."""
        await self.send({"type": "daemon_ready"})

    async def wait_for_daemon_ready(self, ready_timeout_s: float = 10.0) -> dict[str, Any]:
        """Wait for a daemon readiness message and require ready state.

        Args:
            ready_timeout_s: Maximum seconds to wait.

        Returns:
            The daemon_ready event on success.

        Raises:
            RuntimeError: If daemon reports ``error``, ``degraded``, or another non-ready
                terminal state.
            TimeoutError: If timeout expires.
        """
        async with asyncio.timeout(ready_timeout_s):
            while True:
                event = self._pop_pending_event_by_type("daemon_ready")
                if event is None:
                    if self._ws and self._connected:
                        event = await self._read_from_socket()
                    else:
                        # Test/mocked clients may not initialize websocket transport.
                        event = await self.read_event()
                if not event:
                    raise ValueError("No event received")
                if event.get("type") != "daemon_ready":
                    self._pending_events.append(event)
                    continue
                state = event.get("state")
                if state == "ready":
                    return event
                if state == "error":
                    message = event.get("message") or "Daemon startup failed"
                    raise RuntimeError(str(message))
                if state == "degraded":
                    message = event.get("message") or "Daemon is degraded"
                    raise RuntimeError(str(message))
                if state in _TRANSITIONAL_DAEMON_READY_STATES:
                    await asyncio.sleep(_DAEMON_READY_POLL_INTERVAL_S)
                    await self.request_daemon_ready()
                    continue
                message = event.get("message") or f"Daemon state is {state}"
                raise RuntimeError(str(message))

    def _pop_pending_event_by_type(self, event_type: str) -> dict[str, Any] | None:
        """Pop the first pending event of ``event_type`` while preserving queue order."""
        if not self._pending_events:
            return None

        kept_events: deque[dict[str, Any]] = deque()
        matched: dict[str, Any] | None = None

        while self._pending_events:
            event = self._pending_events.popleft()
            if matched is None and event.get("type") == event_type:
                matched = event
                continue
            kept_events.append(event)

        self._pending_events = kept_events
        return matched

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if self._pending_events:
            return self._pending_events.popleft()

        return await self._read_from_socket()

    def clear_pending_events(self) -> None:
        """Clear all pending events from the internal queue.

        Useful in tests to discard setup-phase events that should not
        affect isolation verification.
        """
        self._pending_events.clear()

    async def _read_from_socket(self) -> dict[str, Any] | None:
        """Read one event directly from the websocket transport."""

        if not self._ws or not self._connected:
            return None

        try:
            message = await self._ws.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            return decode_websocket_text(message)
        except websockets.exceptions.ConnectionClosed:
            return None
        except Exception:
            logger.exception("Error reading event")
            return None


__all__ = ["WebSocketClient"]
