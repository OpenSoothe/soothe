"""WebSocket client for daemon connections (RFC-0013)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncGenerator, Callable
from typing import Any

import websockets.asyncio.client
import websockets.exceptions

from soothe_sdk.client.intent_hints import validate_loop_input_intent_hint
from soothe_sdk.client.protocol import decode_websocket_text, encode_websocket_text

logger = logging.getLogger(__name__)

# IG-535 Optimization 1: Priority-aware drop policy for inbound queue.
# Lower values = keep, higher values = drop candidate.
_DROP_PRIORITY_CRITICAL = 0  # Never drop: goal_completion, terminal status, errors
_DROP_PRIORITY_HIGH = 1  # Prefer keep: tool call updates, step events
_DROP_PRIORITY_NORMAL = 2  # Default drop candidate: streaming text, updates


def _inbound_frame_drop_priority(event: dict[str, Any] | None) -> int:
    """Return priority for drop decision (lower = keep, higher = drop candidate).

    IG-535: Ensures terminal frames and goal_completion are never dropped
    even when inbound queue is full.

    Args:
        event: Wire frame dict or None sentinel.

    Returns:
        Priority level: 0 (never drop) to 2 (drop candidate).
    """
    if event is None:
        return _DROP_PRIORITY_CRITICAL  # Sentinel - never drop

    event_type = event.get("type", "")

    # Unwrap protocol-1 next envelope (RFC-450 §9.3)
    if event_type == "next":
        payload = event.get("payload")
        if isinstance(payload, dict):
            inner_type = payload.get("type", "")
            inner_mode = payload.get("mode", "")
            inner_data = payload.get("data")

            # Check for goal_completion in inner messages frame
            if inner_mode == "messages" and isinstance(inner_data, (tuple, list)):
                if inner_data and isinstance(inner_data[0], dict):
                    if inner_data[0].get("phase") == "goal_completion":
                        return _DROP_PRIORITY_CRITICAL

            # Recurse with inner frame type
            event_type = inner_type

    # Terminal frames - never drop
    if event_type == "status":
        state = event.get("state", "")
        if state in ("idle", "running", "stopped", "detached"):
            return _DROP_PRIORITY_CRITICAL

    # Error frames - never drop
    if event_type == "error":
        return _DROP_PRIORITY_CRITICAL

    # Connection ack - never drop
    if event_type == "connection_ack":
        return _DROP_PRIORITY_CRITICAL

    # Custom events with specific types - prefer keep
    if event_type == "event" or event.get("type") == "event":
        mode = event.get("mode", "")
        if mode == "custom":
            data = event.get("data")
            if isinstance(data, dict):
                custom_type = data.get("type", "")
                # Cognition events (step started/completed) - prefer keep
                if custom_type.startswith("soothe.cognition."):
                    return _DROP_PRIORITY_HIGH
                # Error events - never drop
                if custom_type.startswith("soothe.error."):
                    return _DROP_PRIORITY_CRITICAL
                # Stream degraded signal - never drop
                if custom_type == "stream_degraded":
                    return _DROP_PRIORITY_CRITICAL
                # Tool call updates batch - prefer keep
                if custom_type == "soothe.ux.stream_tool_wire.tool_call_updates_batch":
                    return _DROP_PRIORITY_HIGH

        # Messages mode - check for goal_completion phase in unwrapped data
        if mode == "messages":
            data = event.get("data")
            if isinstance(data, (tuple, list)) and data:
                first = data[0]
                if isinstance(first, dict) and first.get("phase") == "goal_completion":
                    return _DROP_PRIORITY_CRITICAL

    # Default - acceptable drop candidate
    return _DROP_PRIORITY_NORMAL


# Align with soothe_daemon.config.models.WebSocketConfig.max_frame_size (default 10 MiB).
# The websockets library defaults max_size to 1 MiB, which closes the connection (1009)
# when the daemon streams larger JSON events to the client.
_DEFAULT_MAX_FRAME_SIZE = 10 * 1024 * 1024

# RFC-450: clients must wait (bounded) while the daemon is still starting; it does not
# necessarily push another ``daemon_ready`` when transitioning to ready, so we re-request.
_TRANSITIONAL_DAEMON_READY_STATES = frozenset({"starting", "warming"})
_DAEMON_READY_POLL_INTERVAL_S = 0.05

# Client version reported in the connection_init handshake (RFC-450 §8.2).
try:
    from soothe_sdk import __version__ as client_version  # noqa: N812
except Exception:  # pragma: no cover
    client_version = "0.0.0"  # noqa: N812


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
        # Background reader drains the socket so daemon sends are not blocked by a
        # stalled consumer (e.g. heavy Textual UI work on the same event loop).
        # IG-535: Increased from 10_000 to 20_000 for 32 concurrent loops with dense streaming
        self._inbound_maxsize = 20_000
        self._inbound_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=self._inbound_maxsize
        )
        self._inbound_dropped = 0
        # IG-534: Optional callback for stream degradation events
        self._on_stream_degraded: Callable[[int, str], None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        # Coalesce high-frequency daemon_status polls on a long-lived connection.
        self._daemon_status_cache: tuple[float, dict[str, Any]] | None = None
        self._daemon_status_lock = asyncio.Lock()
        self._daemon_status_inflight: asyncio.Task[dict[str, Any]] | None = None
        # Protocol-1 handshake state (RFC-450 §8.2)
        self._negotiated_capabilities: set[str] = set()
        self._protocol_version: str | None = None
        self._handshake_complete: bool = False
        self._heartbeat_interval_ms: int = 0
        self._heartbeat_timeout_ms: int = 10000
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._last_pong_monotonic: float = 0.0

    async def connect(self) -> None:
        """Connect to the daemon.

        Raises:
            ConnectionError: If connection fails.
        """
        if self._ws is not None:
            await self.close()

        try:
            # Transport-level keepalive: daemon heartbeats are loop-scoped and only
            # while a query runs; without client pings, long idle TCP can be dropped.
            self._ws = await websockets.asyncio.client.connect(
                self._url,
                ping_interval=30,
                ping_timeout=60,
                max_size=self._max_frame_size,
            )
            self._connected = True
            self._reader_task = asyncio.create_task(
                self._socket_reader_loop(),
                name=f"soothe-ws-reader-{self._client_id}",
            )

            logger.info("[Client:%s] Connected to daemon at %s", self._client_id, self._url)
        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to daemon: {e}"
            raise ConnectionError(msg) from e

    async def _stop_reader(self) -> None:
        """Cancel the background reader and clear queued inbound events."""
        task = self._reader_task
        self._reader_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        while True:
            try:
                self._inbound_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _socket_reader_loop(self) -> None:
        """Continuously read frames from the transport into ``_inbound_queue``."""
        try:
            while self._connected and self._ws is not None:
                event = await self._read_from_socket()
                if event is None:
                    await self._enqueue_inbound(None)
                    break
                # Intercept heartbeat frames (RFC-450 §8.3): respond to ping
                # with pong and swallow pong (liveness tracked by heartbeat loop).
                etype = event.get("type")
                if etype == "ping":
                    await self._respond_pong()
                    continue
                if etype == "pong":
                    self._handle_pong()
                    continue
                await self._enqueue_inbound(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[Client:%s] WebSocket reader loop failed",
                self._client_id,
            )
            with contextlib.suppress(asyncio.QueueFull):
                await self._enqueue_inbound(None)
        finally:
            self._connected = False

    async def _respond_pong(self) -> None:
        """Respond to a daemon ``ping`` with ``pong`` (RFC-450 §8.3)."""
        if not self._ws or not self._connected:
            return
        try:
            await self._ws.send(encode_websocket_text({"proto": "1", "type": "pong"}))
        except websockets.exceptions.ConnectionClosed:
            self._connected = False
        except Exception:
            logger.debug("[Client:%s] Failed to send pong", self._client_id)

    async def _enqueue_inbound(self, event: dict[str, Any] | None) -> None:
        """Queue one or more inbound wire messages (expands ``event_batch``)."""
        if event is None:
            await self._put_inbound_queue(None)
            return
        if event.get("type") == "event_batch":
            sub_events = event.get("events")
            if isinstance(sub_events, list):
                for sub in sub_events:
                    if isinstance(sub, dict):
                        await self._put_inbound_queue(sub)
            return
        await self._put_inbound_queue(event)

    async def _put_inbound_queue(self, event: dict[str, Any] | None) -> None:
        """Put event into inbound queue with priority-aware drop policy.

        IG-535: When queue is full, find and drop a NORMAL priority frame
        (streaming text/updates) instead of blindly dropping oldest, which
        could lose terminal frames (goal_completion, status:idle).
        """
        event_priority = _inbound_frame_drop_priority(event)

        if self._inbound_queue.full():
            # Priority-aware drop: find best drop candidate (highest priority value)
            # by temporarily draining and scanning the queue.
            temp_items: list[dict[str, Any] | None] = []
            drop_candidate: dict[str, Any] | None = None
            drop_priority = -1  # Will only drop if we find priority >= _DROP_PRIORITY_NORMAL

            # Drain queue to scan for drop candidate
            while True:
                try:
                    item = self._inbound_queue.get_nowait()
                    temp_items.append(item)
                except asyncio.QueueEmpty:
                    break

            # Find highest-priority drop candidate (NORMAL = acceptable to drop)
            for item in temp_items:
                p = _inbound_frame_drop_priority(item)
                if p > drop_priority:
                    drop_priority = p
                    drop_candidate = item

            # Requeue all except drop candidate (if found with acceptable priority)
            requeued_critical_or_high = False
            for item in temp_items:
                if item is drop_candidate and drop_priority >= _DROP_PRIORITY_NORMAL:
                    # Skip - this is our drop target
                    continue
                self._inbound_queue.put_nowait(item)
                p = _inbound_frame_drop_priority(item)
                if p <= _DROP_PRIORITY_HIGH:
                    requeued_critical_or_high = True

            if drop_candidate is not None and drop_priority >= _DROP_PRIORITY_NORMAL:
                # Successfully found and dropped a NORMAL frame
                self._inbound_dropped += 1
                # IG-534: Emit stream_degraded callback on first drop
                if self._on_stream_degraded and self._inbound_dropped == 1:
                    try:
                        self._on_stream_degraded(1, "inbound_queue_overflow")
                    except Exception:
                        logger.debug("Stream degraded callback error", exc_info=True)
                if self._inbound_dropped == 1 or self._inbound_dropped % 1000 == 0:
                    logger.warning(
                        "[Client:%s] Stream degraded: inbound queue overflow "
                        "(dropped NORMAL frame, dropped=%d)",
                        self._client_id,
                        self._inbound_dropped,
                    )
            else:
                # No acceptable drop candidate - queue contains only CRITICAL/HIGH frames
                # Briefly yield and retry, or if incoming frame is also CRITICAL/HIGH,
                # force a slot by dropping oldest (rare edge case)
                if event_priority >= _DROP_PRIORITY_NORMAL and requeued_critical_or_high:
                    # Incoming is NORMAL, but queue is full of CRITICAL/HIGH
                    # This shouldn't happen under normal operation; log and yield
                    logger.debug(
                        "[Client:%s] Inbound queue full of critical frames, "
                        "yielding for drain (incoming_priority=%d)",
                        self._client_id,
                        event_priority,
                    )
                    await asyncio.sleep(0.001)
                elif event_priority < _DROP_PRIORITY_NORMAL:
                    # Incoming is CRITICAL/HIGH, force a slot by dropping oldest
                    # even if it's also critical (rare, but necessary to avoid deadlock)
                    if temp_items:
                        # Drop the first item we drained (oldest)
                        self._inbound_dropped += 1
                        logger.warning(
                            "[Client:%s] Force drop oldest to admit CRITICAL/HIGH frame "
                            "(queue full of critical, dropped=%d)",
                            self._client_id,
                            self._inbound_dropped,
                        )
                        # Requeue all but the first (oldest)
                        for item in temp_items[1:]:
                            self._inbound_queue.put_nowait(item)

        await self._inbound_queue.put(event)

    async def close(self, *, handshake_timeout: float = 2.0) -> None:
        """Close the connection with timeout to prevent exit hangs.

        Args:
            handshake_timeout: Seconds to wait for the WebSocket close handshake.
                Use a small value (e.g. 0.3) on interactive client exit.
        """
        # Cancel heartbeat task
        hb_task = self._heartbeat_task
        self._heartbeat_task = None
        if hb_task is not None and not hb_task.done():
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb_task

        await self._stop_reader()
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
                await asyncio.wait_for(self._ws.close(), timeout=handshake_timeout)
            except TimeoutError:
                # Force close on timeout - daemon will handle graceful cleanup
                logger.debug(
                    "WebSocket close timed out after %.1fs, forcing closure",
                    handshake_timeout,
                )
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

        if not self.is_connection_alive():
            self._connected = False
            raise ConnectionError("Connection closed")

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

    @property
    def inbound_dropped(self) -> int:
        """Cumulative inbound frames evicted due to queue overflow."""
        return self._inbound_dropped

    def set_stream_degraded_callback(self, callback: Callable[[int, str], None] | None) -> None:
        """Set callback for stream degradation notifications (IG-534).

        Args:
            callback: Function called with (dropped_count, reason) when frames
                are dropped due to inbound queue overflow. Pass None to disable.
        """
        self._on_stream_degraded = callback

    def is_connection_alive(self) -> bool:
        """Check if WebSocket connection is actually alive (not closed).

        This is a deeper check than is_connected - it verifies the actual
        WebSocket state, not just the client-side flag.

        Returns:
            True if WebSocket is open and not closed, False otherwise.
        """
        from websockets.asyncio.connection import State

        return self._ws is not None and self._ws.state == State.OPEN

    # -----------------------------------------------------------------------
    # Protocol-1 client API (RFC-450 §5/§9, IG-522 Phase 5)
    # -----------------------------------------------------------------------

    def _next_request_id(self) -> str:
        """Generate a unique request correlation ID (RFC-450 §5.2).

        Uses :func:`uuid.uuid4` to produce a globally unique hex string. The
        same ID space serves ``request`` and ``subscribe`` operations.

        Returns:
            32-character hex string.
        """
        return uuid.uuid4().hex

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        proto: str = "1",
    ) -> dict[str, Any]:
        """Send a blocking RPC request and await the matching response (RFC-450 §5/§9).

        Constructs a ``WireEnvelope`` with ``type='request'``, sends it over
        the transport, and waits for a ``response`` or ``error`` message
        whose ``id`` matches the generated correlation ID.

        Args:
            method: RPC method name (e.g. ``"loop_get"``, ``"daemon_status"``).
            params: Structured parameters object for the method.
            timeout: Maximum seconds to wait for a response.
            proto: Protocol version string (default ``"1"``).

        Returns:
            The ``result`` dict from the matching ``response`` envelope.

        Raises:
            ConnectionError: If not connected or the connection closes while
                waiting.
            ProtocolError: If the daemon returns an ``error`` envelope with a
                matching ``id``.
            TimeoutError: If no matching response arrives within ``timeout``.
        """
        from soothe_sdk.client.wire import MessageType, ProtocolError, WireEnvelope

        req_id = self._next_request_id()
        envelope = WireEnvelope(
            proto=proto,
            type=MessageType.REQUEST.value,
            method=method,
            params=params or {},
            id=req_id,
        )
        await self.send(envelope.to_wire_dict())

        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await self._read_inbound_event()
                    if not event:
                        if not self.is_connection_alive():
                            self._connected = False
                            raise ConnectionError("Connection closed")
                        raise TimeoutError(
                            f"WebSocket closed while waiting for response to {method} (id={req_id})"
                        )
                    event_id = event.get("id")
                    event_type = event.get("type")
                    # Route responses/errors by id; queue non-matching for later.
                    if event_id != req_id:
                        self._pending_events.append(event)
                        continue
                    if event_type == MessageType.ERROR.value:
                        err_obj = event.get("error") or {}
                        raise ProtocolError(
                            code=int(err_obj.get("code", -32603)),
                            message=str(err_obj.get("message", "daemon error")),
                            data=err_obj.get("data"),
                        )
                    if event_type == MessageType.RESPONSE.value:
                        return event.get("result") or {}
                    # complete/unsubscribe/etc with same id — unexpected for
                    # a blocking request; keep waiting.
                    continue
        except TimeoutError:
            raise TimeoutError(
                f"Daemon did not respond to {method} within {timeout}s (id={req_id})"
            ) from None

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        proto: str = "1",
    ) -> None:
        """Send a fire-and-forget notification (RFC-450 §5/§9).

        Notifications carry no ``id`` and the daemon does not reply. Use for
        operations like ``loop_input`` (fire-and-forget) and ``disconnect``.

        Args:
            method: Notification method name (e.g. ``"loop_input"``).
            params: Structured parameters object.
            proto: Protocol version string (default ``"1"``).

        Raises:
            ConnectionError: If not connected or send fails.
        """
        from soothe_sdk.client.wire import MessageType, WireEnvelope

        envelope = WireEnvelope(
            proto=proto,
            type=MessageType.NOTIFICATION.value,
            method=method,
            params=params or {},
        )
        await self.send(envelope.to_wire_dict())

    async def subscribe(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        proto: str = "1",
    ) -> str:
        """Start a subscription stream (RFC-450 §5/§9).

        Sends a ``subscribe`` envelope with a generated correlation ``id``.
        The daemon delivers stream events as ``next`` messages carrying the
        same ``id``; the stream terminates with ``complete`` or ``error``.
        Subscription confirmation is implicit — if the daemon cannot honour
        the subscription it sends an ``error`` with the subscription ``id``.

        Args:
            method: Subscription target (e.g. ``"loop_events"``).
            params: Subscription parameters (e.g. ``{"loop_id": "abc"}``).
            timeout: Maximum seconds to wait for an initial error if the
                daemon rejects the subscription. If no error arrives within
                this window the subscription is assumed accepted.
            proto: Protocol version string (default ``"1"``).

        Returns:
            The subscription ``id`` for later correlation and ``unsubscribe()``.

        Raises:
            ConnectionError: If not connected.
            ProtocolError: If the daemon sends an ``error`` with the matching
                ``id`` within the ``timeout`` window.
        """
        from soothe_sdk.client.wire import MessageType, ProtocolError, WireEnvelope

        sub_id = self._next_request_id()
        envelope = WireEnvelope(
            proto=proto,
            type=MessageType.SUBSCRIBE.value,
            method=method,
            params=params or {},
            id=sub_id,
        )
        await self.send(envelope.to_wire_dict())

        # Check for an immediate rejection (error with matching id). We poll
        # inbound events with a short timeout; if no error arrives we assume
        # the subscription was accepted and return the id for stream reading.
        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await self._read_inbound_event()
                    if not event:
                        # Connection closed before any response — assume
                        # accepted; caller will discover closure via next().
                        break
                    event_id = event.get("id")
                    event_type = event.get("type")
                    if event_id == sub_id and event_type == MessageType.ERROR.value:
                        err_obj = event.get("error") or {}
                        raise ProtocolError(
                            code=int(err_obj.get("code", -32603)),
                            message=str(err_obj.get("message", "subscription rejected")),
                            data=err_obj.get("data"),
                        )
                    # Re-queue: a next/complete or unrelated event.
                    self._pending_events.append(event)
                    # If we already got a next or complete, subscription is live.
                    if event_id == sub_id and event_type in (
                        MessageType.NEXT.value,
                        MessageType.COMPLETE.value,
                    ):
                        break
        except TimeoutError:
            pass  # No error within timeout — subscription assumed accepted.

        return sub_id

    async def unsubscribe(
        self,
        subscription_id: str,
        *,
        proto: str = "1",
    ) -> None:
        """Cancel an active subscription (RFC-450 §5/§9).

        Sends an ``unsubscribe`` envelope carrying the subscription ``id``.
        The daemon stops delivering ``next`` events for that ``id`` and may
        send a final ``complete``.

        Args:
            subscription_id: The ``id`` returned by :meth:`subscribe`.
            proto: Protocol version string (default ``"1"``).

        Raises:
            ConnectionError: If not connected.
        """
        from soothe_sdk.client.wire import MessageType, WireEnvelope

        envelope = WireEnvelope(
            proto=proto,
            type=MessageType.UNSUBSCRIBE.value,
            id=subscription_id,
        )
        await self.send(envelope.to_wire_dict())

    async def next(self) -> dict[str, Any] | None:
        """Read the next protocol-1 stream event from the daemon (RFC-450 §5/§9).

        This is the primary stream-event reader for protocol-1 messages. It
        replaces :meth:`read_event` for protocol-1 consumers. For ``next``
        messages (subscription stream events) the ``payload`` is returned.
        For ``complete`` and ``error`` messages the full envelope is returned
        so the caller can inspect the ``id`` and error details. For all other
        messages (e.g. ``response``, ``connection_ack``) the full envelope
        is returned.

        Returns:
            The event ``payload`` for ``next`` messages, or the full envelope
            dict for other message types. Returns ``None`` on EOF (connection
            closed).

        Raises:
            ConnectionError: If not connected (only when no reader task is
                active; the background reader returns ``None`` on EOF).
        """
        from soothe_sdk.client.wire import MessageType

        if self._pending_events:
            event = self._pending_events.popleft()
        else:
            event = await self._read_inbound_event()

        if not event:
            return None

        event_type = event.get("type")
        if event_type == MessageType.NEXT.value:
            return event.get("payload") or {}
        return event

    async def send_input(
        self,
        loop_id: str,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        attachments: list[dict[str, str]] | None = None,
        intent_hint: str | None = None,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
        response_schema_strict: bool | None = None,
        clarification_mode: str | None = None,
        clarification_answer: bool = False,
        clarification_answers: list[str] | None = None,
    ) -> None:
        """Send user input to the daemon for a subscribed loop (``loop_input``).

        Args:
            loop_id: Loop identifier for the subscribed loop.
            text: User input text.
            autonomous: Enable autonomous iteration mode.
            max_iterations: Maximum iterations for autonomous mode.
            preferred_subagent: Preferred subagent hint for routing.
            model: Provider:model override string.
            model_params: Additional model parameters.
            attachments: Image attachments (mime_type + base64 data).
            intent_hint: Daemon-only direct model hint. Supported values:
                ``text_completion`` (``default`` role, text-only),
                ``image_to_text`` (``image`` role, attachments required),
                ``ocr`` (``ocr`` role, attachments required),
                ``embed`` (``embedding`` role, text-only; returns JSON vector).
                ``response_schema`` is supported for ``text_completion`` and
                ``image_to_text``. Agent-path pass-through hints (e.g.
                ``resume_clarification``, ``skill:foo``) are forwarded unchanged.
                Legacy ``direct_llm`` and ``quiz`` are rejected before send.

        Raises:
            ValueError: When ``intent_hint`` is a removed legacy value.
            clarification_mode: RFC-622 clarification relay mode for this turn
                (``"auto"`` / ``"manual"``). ``None`` lets the daemon fall back
                to its configured default.
            clarification_answer: When True, the daemon treats this input as the
                answer to the loop's currently pending clarification interrupt
                (RFC-622) and resumes the graph via ``Command(resume=...)``
                instead of starting a new turn. Hint only — daemon verifies via
                the loop's persisted state and falls back to a normal turn when
                no clarification is pending.
            clarification_answers: Optional per-question answer list paired with
                ``clarification_answer=True`` for multi-question clarifications.
                When set, the daemon resumes with one answer per question (no
                broadcast), so the step card and working memory carry exactly
                what the user typed — instead of a single concatenated string
                being broadcast to every question.
        """
        params: dict[str, Any] = {
            "loop_id": loop_id,
            "content": text,
        }
        if autonomous:
            params["autonomous"] = True
            if max_iterations is not None:
                params["max_iterations"] = max_iterations
        if preferred_subagent is not None:
            params["preferred_subagent"] = preferred_subagent
        if model:
            params["model"] = model
        if model_params:
            params["model_params"] = model_params
        if attachments:
            params["attachments"] = attachments
        if intent_hint:
            hint_error = validate_loop_input_intent_hint(intent_hint)
            if hint_error is not None:
                raise ValueError(hint_error)
            params["intent_hint"] = intent_hint
        if response_schema:
            params["response_schema"] = response_schema
        if response_schema_name:
            params["response_schema_name"] = response_schema_name
        if response_schema_strict is not None:
            params["response_schema_strict"] = response_schema_strict
        if clarification_mode is not None:
            params["clarification_mode"] = clarification_mode
        if clarification_answer:
            params["clarification_answer"] = True
        if clarification_answers is not None:
            params["clarification_answers"] = list(clarification_answers)
        await self.notify("loop_input", params)

    async def list_skills(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Request wire-safe skill metadata from the daemon (RFC-400 ``skills_list``)."""
        return await self.request("skills_list", {}, timeout=timeout)

    async def list_models(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Request model catalog rows from the daemon host ``SootheConfig`` (RFC-400 ``models_list``)."""
        return await self.request("models_list", {}, timeout=timeout)

    async def get_mcp_status(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Request MCP server status from the daemon."""
        return await self.request("mcp_status", {}, timeout=timeout)

    async def invoke_skill(
        self,
        skill: str,
        args: str = "",
        *,
        timeout: float = 120.0,
        clarification_mode: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a skill on the daemon host and receive echo before streaming (RFC-400).

        Args:
            skill: Skill identifier (e.g. ``"my-plugin:my-skill"``).
            args: Free-form argument string appended after the skill name.
            timeout: RPC timeout in seconds.
            clarification_mode: RFC-622 clarification relay mode for the
                synthetic turn the daemon will enqueue (``"auto"`` /
                ``"manual"``). ``None`` lets the daemon fall back to its
                configured default. Without this, slash-skill turns ignore
                the client's Manual badge and always defer to the config
                default — typically ``"auto"`` (veritas).
        """
        params: dict[str, Any] = {"skill": skill, "args": args}
        if clarification_mode is not None:
            params["clarification_mode"] = clarification_mode
        return await self.request("invoke_skill", params, timeout=timeout)

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
            timeout: Per-request timeout passed to :meth:`request`.
            min_interval_s: Minimum seconds between real RPCs. Use ``0`` to
                disable caching and always hit the daemon.

        Returns:
            Parsed daemon status response dict.

        Raises:
            Same as :meth:`request` (timeout, connection errors, etc.).
        """
        if min_interval_s <= 0:
            return await self.request("daemon_status", {}, timeout=timeout)

        async with self._daemon_status_lock:
            now = time.monotonic()
            if self._daemon_status_cache is not None:
                ts, cached = self._daemon_status_cache
                if now - ts < min_interval_s:
                    return dict(cached)

            if self._daemon_status_inflight is None:
                self._daemon_status_inflight = asyncio.create_task(
                    self.request("daemon_status", {}, timeout=timeout)
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

    async def request_connection_init(self) -> None:
        """Send ``connection_init`` to the daemon (RFC-450 §8.2).

        This is the first message the client sends after the WebSocket upgrade.
        The daemon responds with ``connection_ack`` containing readiness state,
        negotiated protocol version, and capabilities.

        This method is safe to call even if the connection may be closed.
        If the connection is closed, this method silently succeeds —
        ``wait_for_connection_ack()`` will either find a pending ack or timeout.
        """
        from soothe_sdk.client.wire import ConnectionInitEnvelope, ConnectionInitParams

        envelope = ConnectionInitEnvelope(
            params=ConnectionInitParams(
                client_version=client_version,
                client_name="soothe-sdk",
                accept_proto=["1"],
                capabilities=["streaming", "batch", "heartbeat"],
            )
        )
        try:
            await self.send(envelope.to_wire_dict())
        except ConnectionError:
            logger.debug(
                "[Client:%s] request_connection_init failed (connection closed), "
                "will check pending events",
                self._client_id,
            )

    async def wait_for_connection_ack(self, ack_timeout_s: float = 10.0) -> dict[str, Any]:
        """Wait for ``connection_ack`` and require ready state (RFC-450 §8.2).

        Args:
            ack_timeout_s: Maximum seconds to wait for the ack.

        Returns:
            The ``connection_ack`` result dict on success.

        Raises:
            ConnectionError: If protocol version is incompatible.
            RuntimeError: If daemon reports ``error``, ``degraded``, or another
                non-ready terminal state.
            TimeoutError: If timeout expires.
        """
        async with asyncio.timeout(ack_timeout_s):
            while True:
                event = self._pop_pending_event_by_type("connection_ack")
                if event is None:
                    event = await self._read_inbound_event()
                if not event:
                    if not self.is_connection_alive():
                        self._connected = False
                        raise ConnectionError("Connection closed")
                    raise TimeoutError("No connection_ack received")
                if event.get("type") != "connection_ack":
                    # Discard the initial ``status`` frame — keeping it in
                    # ``_pending_events`` would block ``connection_ack`` in
                    # the inbound queue.
                    if event.get("type") != "status":
                        self._pending_events.append(event)
                    continue

                result = event.get("result") or {}
                state = result.get("readiness_state")
                proto_ver = result.get("protocol_version")
                caps = result.get("capabilities", [])
                hb_interval = result.get("heartbeat_interval_ms", 0)

                # Store negotiated values
                self._protocol_version = proto_ver
                self._negotiated_capabilities = set(caps)
                self._heartbeat_interval_ms = int(hb_interval) if hb_interval else 0
                self._handshake_complete = True

                if state == "incompatible":
                    raise ConnectionError(
                        f"Protocol version incompatible: daemon returned {proto_ver!r}"
                    )
                if state == "ready":
                    # Start heartbeat if negotiated
                    if (
                        "heartbeat" in self._negotiated_capabilities
                        and self._heartbeat_interval_ms > 0
                    ):
                        self._start_heartbeat()
                    return event
                if state == "error":
                    raise RuntimeError("Daemon startup failed")
                if state == "degraded":
                    raise RuntimeError("Daemon is degraded")
                if state in _TRANSITIONAL_DAEMON_READY_STATES:
                    await asyncio.sleep(_DAEMON_READY_POLL_INTERVAL_S)
                    await self.request_connection_init()
                    continue
                raise RuntimeError(f"Daemon state is {state}")

    def _start_heartbeat(self) -> None:
        """Start the client-side heartbeat ping sender (RFC-450 §8.3).

        Sends ``ping`` frames at the negotiated interval. If no ``pong`` is
        received within the timeout window, the connection is considered dead.
        """
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        interval_s = self._heartbeat_interval_ms / 1000.0
        if interval_s <= 0:
            return
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(interval_s),
            name=f"soothe-ws-heartbeat-{self._client_id}",
        )

    async def _heartbeat_loop(self, interval_s: float) -> None:
        """Send periodic ping frames and detect dead connections (RFC-450 §8.3).

        Args:
            interval_s: Ping interval in seconds.
        """
        import time

        timeout_s = max(self._heartbeat_timeout_ms / 1000.0, interval_s * 2)
        try:
            while self._connected and self._ws is not None:
                await asyncio.sleep(interval_s)
                if not self._connected or self._ws is None:
                    break
                now = time.monotonic()
                last_pong = self._last_pong_monotonic or now
                if now - last_pong > interval_s + timeout_s:
                    logger.warning(
                        "[Client:%s] Heartbeat timeout (no pong in %.1fs), closing",
                        self._client_id,
                        now - last_pong,
                    )
                    self._connected = False
                    with contextlib.suppress(Exception):
                        await self._ws.close()
                    return
                try:
                    await self._ws.send(encode_websocket_text({"proto": "1", "type": "ping"}))
                except websockets.exceptions.ConnectionClosed:
                    self._connected = False
                    return
                except Exception:
                    logger.debug("[Client:%s] Failed to send heartbeat ping", self._client_id)
                    return
        except asyncio.CancelledError:
            raise

    def _handle_pong(self) -> None:
        """Mark that a pong was received from the daemon (heartbeat liveness)."""
        import time

        self._last_pong_monotonic = time.monotonic()

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

    async def _read_inbound_event(self) -> dict[str, Any] | None:
        """Read the next frame from the transport queue, ignoring ``_pending_events``.

        Used for RPC/handshake waits so a stray ``status`` frame cannot block matching
        responses that arrive later on the inbound queue.
        """
        if self._reader_task is not None:
            return await self._inbound_queue.get()

        return await self._read_from_socket()

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if self._pending_events:
            return self._pending_events.popleft()

        return await self._read_inbound_event()

    def clear_pending_events(self) -> None:
        """Clear all pending events from the internal queue.

        Useful in tests to discard setup-phase events that should not
        affect isolation verification.
        """
        self._pending_events.clear()

    # Handshake / RPC responses that must not count as turn progress (TUI stall detection).
    # ``card.replay_*`` / ``card.created`` are emitted by the daemon during
    # ``loop_subscribe`` for non-TUI clients (RFC-413). The TUI consumes its
    # cards via the synchronous ``loop_cards_fetch`` RPC so these frames are
    # peeled silently here. Under protocol-1, RPC responses arrive as
    # ``type:"response"`` correlated by ``id`` (peeled by the reader loop), so
    # the legacy ``*_response`` type entries are gone. Under protocol-1 (RFC-450
    # §9.3) card replay frames arrive wrapped in ``next`` envelopes with
    # ``payload.mode`` set to the originating frame type; the peel logic below
    # inspects both the raw ``type`` and the wrapped ``payload.mode``.
    _STALE_TURN_PENDING_TYPES = frozenset(
        {
            "connection_ack",
            "card.replay_begin",
            "card.replay_end",
            "card.created",
        }
    )

    def peel_stale_pending_control_events(self) -> list[str]:
        """Remove stale handshake/RPC frames left in ``_pending_events`` before a turn.

        ``request`` queues unrelated inbound frames while waiting for a matching
        ``id``. If a handshake/control frame remains at turn start, the TUI can
        mistake it for live progress and never log a stalled stream.

        Returns:
            List of removed frame types (in order).
        """
        if not self._pending_events:
            return []

        kept: deque[dict[str, Any]] = deque()
        removed: list[str] = []
        while self._pending_events:
            event = self._pending_events.popleft()
            event_type = str(event.get("type") or "")
            # Protocol-1 wraps card replay frames in ``next`` envelopes; peel
            # them by inspecting ``payload.mode`` so they don't masquerade as
            # live progress at turn start.
            stale_mode = ""
            if event_type == "next":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    stale_mode = str(payload.get("mode") or "")
            if event_type in self._STALE_TURN_PENDING_TYPES:
                removed.append(event_type)
                continue
            if stale_mode and stale_mode in self._STALE_TURN_PENDING_TYPES:
                removed.append(stale_mode)
                continue
            kept.append(event)
        self._pending_events = kept
        return removed

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


__all__ = [
    "WebSocketClient",
    "_inbound_frame_drop_priority",  # IG-535: Exported for testing
    "_DROP_PRIORITY_CRITICAL",
    "_DROP_PRIORITY_HIGH",
    "_DROP_PRIORITY_NORMAL",
]
