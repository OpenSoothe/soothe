"""ACP (Agent Client Protocol) channel — stdio JSON-RPC server.

This channel implements the ACP server as a daemon channel, conforming to
the ``Channel`` ABC. It listens on stdio (NDJSON JSON-RPC 2.0) and translates
ACP ``session/*`` methods into daemon-internal calls:

- ``session/new`` → ``ChannelManager.handle_inbound()`` (creates a loop) +
  EventBus subscription for output events.
- ``session/prompt`` → ``ChannelManager.handle_inbound()`` (enqueues a user turn).
- ``session/cancel`` → publishes a cancel wire event on the loop topic.
- ``session/load`` → resume path (stub for v1).

Daemon EventBus output events (``OUTPUT_TEXT_DELTA``, ``OUTPUT_TEXT_COMPLETE``,
``OUTPUT_PROGRESS``, ``OUTPUT_REASONING``) are translated to ACP
``session/update`` notifications written to stdout.

Plan projection is lossy: Soothe plans are DAGs with dependencies; ACP plans
are flat lists of ``{content, priority, status}``. The projection drops
dependency/concurrency info — acceptable for editor UX.

Permission model bridge:
    When the daemon's StrangeLoop raises a LangGraph ``__interrupt__`` with
    ``action_requests`` (tool-approval), the ACP channel translates it to an
    ACP ``session/request_permission`` request sent to the client. The client's
    response (allow/deny) is routed back to resume the interrupted graph via
    the daemon's loop input path (``loop_input`` with resume payload).

    Soothe's ``PolicyProtocol`` uses structured permissions (category+action+scope,
    ``PermissionSet``). ACP's ``session/request_permission`` is per-tool-call
    and ad-hoc. The bridge translates Soothe's structured decision into ACP's
    single permission request and routes ACP client responses back.

The ``agent-client-protocol`` package is an optional ``[acp]`` extra. When
installed, its ``helpers`` builders (``text_block``, etc.) are used for ACP
block construction. When not installed, the channel falls back to manual
dict construction — JSON-RPC 2.0 framing is simple enough to implement directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import uuid
from logging import getLogger
from typing import TYPE_CHECKING, Any

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config.models import ACPConfig
from soothe_daemon.event import loop_event_topic
from soothe_daemon.events.constants import (
    OUTPUT_PROGRESS,
    OUTPUT_REASONING,
    OUTPUT_TEXT_COMPLETE,
    OUTPUT_TEXT_DELTA,
    OUTPUT_TEXT_END,
)

if TYPE_CHECKING:
    from soothe_daemon.channel_manager import ChannelManager

logger = getLogger(__name__)

# Try to import ACP helpers for block construction (optional).
# Falls back to manual dict construction when the SDK is not installed.
try:
    from agent_client_protocol import helpers as _acp_helpers  # type: ignore[import-not-found]
except ImportError:
    _acp_helpers = None  # type: ignore[assignment]

# Default timeout for permission responses from the ACP client (seconds).
_PERMISSION_TIMEOUT_S = 120.0


def _make_text_block(content: str) -> dict[str, Any]:
    """Build an ACP text block, using SDK helper if available."""
    if _acp_helpers is not None and hasattr(_acp_helpers, "text_block"):
        return _acp_helpers.text_block(content)  # type: ignore[no-any-return]
    return {"type": "text", "text": content}


def _make_reasoning_block(content: str) -> dict[str, Any]:
    """Build an ACP reasoning block."""
    # ACP spec uses "reasoning" block type; SDK helper may not exist yet.
    if _acp_helpers is not None and hasattr(_acp_helpers, "reasoning_block"):
        return _acp_helpers.reasoning_block(content)  # type: ignore[no-any-return]
    return {"type": "reasoning", "text": content}


def _make_progress_block(message: str) -> dict[str, Any]:
    """Build an ACP progress block."""
    # ACP doesn't have a dedicated progress block; use text with marker.
    # This is a best-effort projection for editor UX.
    return {"type": "progress", "text": message}


class ACPChannel(Channel):
    """ACP stdio channel — JSON-RPC 2.0 over stdin/stdout.

    When enabled as the sole channel (WebSocket disabled), the daemon runs in
    standalone ACP mode. The ``soothe-acp`` console script boots this mode.
    """

    name = "acp"
    display_name = "ACP"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    def __init__(self, config: ACPConfig, manager: ChannelManager) -> None:
        """Initialize ACP channel.

        Args:
            config: ACP channel configuration.
            manager: Channel manager that owns this channel.
        """
        super().__init__(config, manager)
        self._acp_config = config

        # ACP session_id → daemon loop_id
        self._session_map: dict[str, str] = {}

        # loop_id → EventBus event queue
        self._event_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

        # loop_id → event consumer task
        self._consumer_tasks: dict[str, asyncio.Task[None]] = {}

        # Stdin reader task
        self._stdin_task: asyncio.Task[None] | None = None

        # Running flag
        self._running = False

        # Pending permission requests: request_id → future that the consumer task awaits.
        # The stdin reader resolves these futures when the client responds.
        self._pending_permissions: dict[int, asyncio.Future[dict[str, Any]]] = {}

        # Monotonic request ID counter for outbound JSON-RPC requests.
        self._next_request_id = 1

    async def start(self) -> None:
        """Start the ACP stdio server — launch stdin reader loop."""
        if not self._acp_config.enabled:
            logger.info("[ACP] Channel disabled")
            return

        self._running = True
        self._stdin_task = asyncio.create_task(self._read_stdin_loop())
        logger.info(
            "[ACP] Channel started (agent_name=%s, stdio JSON-RPC)",
            self._acp_config.agent_name,
        )

    async def stop(self) -> None:
        """Stop the ACP channel — cancel all tasks and clean up."""
        self._running = False

        # Cancel stdin reader
        if self._stdin_task is not None:
            self._stdin_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stdin_task
            self._stdin_task = None

        # Cancel all consumer tasks and unsubscribe
        event_bus = getattr(self._manager, "_event_bus", None)
        for loop_id, task in list(self._consumer_tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            queue = self._event_queues.pop(loop_id, None)
            if queue is not None and event_bus is not None:
                topic = loop_event_topic(loop_id)
                with contextlib.suppress(Exception):
                    await event_bus.unsubscribe(topic, queue)

        self._consumer_tasks.clear()
        self._session_map.clear()

        # Resolve any pending permission futures with a cancellation error
        for fut in list(self._pending_permissions.values()):
            if not fut.done():
                fut.cancel()
        self._pending_permissions.clear()

        # Flush stdout
        await _flush_stdout()

        logger.info("[ACP] Channel stopped")

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message as ACP ``session/update`` notification.

        Args:
            chat_id: ACP session_id (maps to loop_id via _session_map).
            message: ChannelMessage to deliver.
        """
        session_id = self._loop_to_session(chat_id)
        if session_id is None:
            logger.warning("[ACP] No session for loop_id %s", chat_id)
            return

        block = _make_text_block(message.content)
        await self._send_session_update(session_id, [block])

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream incremental text chunk as ACP ``session/update``.

        Args:
            chat_id: Loop ID identifying the session.
            delta: Text chunk to stream.
            metadata: Stream metadata (_stream_id, _stream_end, etc.).
        """
        session_id = self._loop_to_session(chat_id)
        if session_id is None:
            return

        block = _make_text_block(delta)
        await self._send_session_update(session_id, [block], metadata=metadata)

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream reasoning content as ACP ``session/update``.

        Args:
            chat_id: Loop ID identifying the session.
            delta: Reasoning text chunk.
            metadata: Stream metadata.
        """
        if not self.show_reasoning:
            return

        session_id = self._loop_to_session(chat_id)
        if session_id is None:
            return

        block = _make_reasoning_block(delta)
        await self._send_session_update(session_id, [block], metadata=metadata)

    # ------------------------------------------------------------------
    # JSON-RPC stdio loop
    # ------------------------------------------------------------------

    async def _read_stdin_loop(self) -> None:
        """Read NDJSON lines from stdin and dispatch JSON-RPC requests."""
        while self._running:
            try:
                line = await asyncio.to_thread(self._read_line)
                if line is None:
                    # EOF on stdin — client disconnected
                    logger.info("[ACP] stdin EOF, shutting down")
                    self._running = False
                    break
                line = line.strip()
                if not line:
                    continue

                request = json.loads(line)
                await self._dispatch_request(request)
            except asyncio.CancelledError:
                raise
            except json.JSONDecodeError as e:
                await self._write_jsonrpc(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": f"Parse error: {e}",
                        },
                    }
                )
            except Exception:
                logger.exception("[ACP] Error processing stdin line")

    def _read_line(self) -> str | None:
        """Read one line from stdin (blocking). Returns None on EOF."""
        line = sys.stdin.readline()
        if not line:
            return None
        return line

    async def _dispatch_request(self, request: dict[str, Any]) -> None:
        """Dispatch a JSON-RPC 2.0 request to the appropriate handler.

        Handles both inbound requests (from the ACP client) and responses
        to outbound requests (e.g., ``session/request_permission`` responses).

        Args:
            request: Parsed JSON-RPC request dict.
        """
        # If this is a response to a pending permission request, resolve it.
        req_id = request.get("id")
        if "method" not in request and req_id is not None:
            await self._handle_response(request)
            return

        method = request.get("method", "")
        params = request.get("params", {})

        handlers = {
            "initialize": self._handle_initialize,
            "session/new": self._handle_session_new,
            "session/prompt": self._handle_session_prompt,
            "session/cancel": self._handle_session_cancel,
            "session/load": self._handle_session_load,
        }

        handler = handlers.get(method)
        if handler is None:
            await self._write_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            )
            return

        try:
            result = await handler(params)
            await self._write_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
            )
        except Exception as e:
            logger.exception("[ACP] Handler error for %s", method)
            await self._write_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {e}",
                    },
                }
            )

    async def _handle_response(self, response: dict[str, Any]) -> None:
        """Handle a JSON-RPC response to an outbound request.

        Resolves the pending future for the corresponding request ID.
        Used for ``session/request_permission`` responses from the ACP client.

        Args:
            response: Parsed JSON-RPC response dict with ``id``, ``result`` or ``error``.
        """
        req_id = response.get("id")
        if not isinstance(req_id, int):
            logger.warning("[ACP] Response with non-integer id: %s", req_id)
            return

        fut = self._pending_permissions.pop(req_id, None)
        if fut is None:
            logger.warning("[ACP] No pending permission for request id %s", req_id)
            return

        if "error" in response:
            fut.set_result({"outcome": "cancelled"})
        else:
            result = response.get("result", {})
            fut.set_result(result if isinstance(result, dict) else {"outcome": "cancelled"})

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``initialize`` — return server capabilities and agent info.

        ACP assumes the agent may use client fs/terminal. Soothe has its own
        workspace tools — we must NOT advertise client fs/terminal capabilities.
        """
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {
                "streaming": True,
            },
            "agent": {
                "name": self._acp_config.agent_name,
                "description": self._acp_config.agent_description,
            },
        }

    async def _handle_session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``session/new`` — create a daemon loop and subscribe to events.

        Args:
            params: ACP session/new params (may contain ``model``).

        Returns:
            ACP session info with session_id.
        """
        session_id = str(uuid.uuid4())

        # Create a daemon loop via ChannelManager.handle_inbound
        loop_id = await self._manager.handle_inbound(
            channel="acp",
            chat_id=session_id,
            sender_id="acp-client",
            content="",
            metadata={},
        )

        self._session_map[session_id] = loop_id

        # Subscribe to the loop's EventBus topic
        event_bus = getattr(self._manager, "_event_bus", None)
        if event_bus is not None:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
            self._event_queues[loop_id] = queue
            topic = loop_event_topic(loop_id)
            await event_bus.subscribe(topic, queue)

            # Start consumer task to drain events and translate to ACP
            consumer = asyncio.create_task(self._consume_loop_events(loop_id, queue))
            self._consumer_tasks[loop_id] = consumer

        logger.info("[ACP] session/new: session=%s → loop=%s", session_id, loop_id)

        return {
            "sessionId": session_id,
        }

    async def _handle_session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``session/prompt`` — enqueue a user turn.

        Args:
            params: ACP session/prompt params with ``sessionId`` and ``prompt``.
        """
        session_id = params.get("sessionId", "")
        prompt_text = ""

        # Extract text from prompt (ACP uses a list of content parts)
        prompt_parts = params.get("prompt", [])
        if isinstance(prompt_parts, str):
            prompt_text = prompt_parts
        elif isinstance(prompt_parts, list):
            for part in prompt_parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    prompt_text += part.get("text", "")
                elif isinstance(part, str):
                    prompt_text += part

        loop_id = self._session_map.get(session_id)
        if loop_id is None:
            raise ValueError(f"Unknown session: {session_id}")

        await self._manager.handle_inbound(
            channel="acp",
            chat_id=session_id,
            sender_id="acp-client",
            content=prompt_text,
            metadata={},
        )

        logger.debug("[ACP] session/prompt: session=%s, loop=%s", session_id, loop_id)
        return {}

    async def _handle_session_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``session/cancel`` — publish a cancel event on the loop topic.

        Args:
            params: ACP session/cancel params with ``sessionId``.
        """
        session_id = params.get("sessionId", "")
        loop_id = self._session_map.get(session_id)
        if loop_id is None:
            raise ValueError(f"Unknown session: {session_id}")

        event_bus = getattr(self._manager, "_event_bus", None)
        if event_bus is not None:
            cancel_msg = {
                "type": "command",
                "command": "cancel",
                "loop_id": loop_id,
            }
            topic = loop_event_topic(loop_id)
            await event_bus.publish(topic, cancel_msg)

        logger.info("[ACP] session/cancel: session=%s, loop=%s", session_id, loop_id)
        return {}

    async def _handle_session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``session/load`` — resume path (stub for v1).

        Args:
            params: ACP session/load params.
        """
        # TODO: Implement checkpoint replay via DurabilityProtocol
        session_id = params.get("sessionId", "")
        return {
            "sessionId": session_id,
            "state": "loaded",
        }

    # ------------------------------------------------------------------
    # EventBus event consumer — translate wire events to ACP notifications
    # ------------------------------------------------------------------

    async def _consume_loop_events(
        self,
        loop_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        """Drain EventBus events and translate to ACP ``session/update``.

        Also detects tool-approval interrupts (``__interrupt__`` with
        ``action_requests``) and bridges them to ACP
        ``session/request_permission`` requests.

        Args:
            loop_id: Daemon loop identifier.
            queue: EventBus subscription queue for this loop.
        """
        while self._running:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            # EventBus delivers 2-tuples (event_dict, event_meta) or just event_dict
            if isinstance(item, tuple) and len(item) == 2:
                event = item[0]
            elif isinstance(item, dict):
                event = item
            else:
                continue

            session_id = self._loop_to_session(loop_id)
            if not session_id:
                continue

            # Check for tool-approval interrupt (permission bridge)
            if self._is_tool_approval_event(event):
                await self._bridge_permission_request(session_id, loop_id, event)
                continue

            blocks = self._translate_event(event)
            if blocks:
                await self._send_session_update(session_id, blocks)

    def _is_tool_approval_event(self, event: dict[str, Any]) -> bool:
        """Check if an EventBus wire event contains a tool-approval interrupt.

        Tool-approval interrupts arrive as ``updates`` mode stream tuples with
        ``__interrupt__`` key containing ``action_requests``.

        Args:
            event: Wire-format event dict from EventBus.

        Returns:
            True if the event contains a tool-approval interrupt.
        """
        # The wire event may be a broadcast message with type "event" and data
        # containing the stream tuple, or it may be the raw stream tuple itself.
        data = event.get("data", event)
        if not isinstance(data, dict):
            return False

        # Check for __interrupt__ key in updates data
        if "__interrupt__" not in data:
            # Also check nested data structures
            inner = data.get("data", {})
            if isinstance(inner, dict) and "__interrupt__" in inner:
                data = inner
            else:
                return False

        interrupt_data = data.get("__interrupt__")
        if not isinstance(interrupt_data, dict):
            return False

        # Check for action_requests (deepagents tool-approval interrupt shape)
        return "action_requests" in interrupt_data

    async def _bridge_permission_request(
        self,
        session_id: str,
        loop_id: str,
        event: dict[str, Any],
    ) -> None:
        """Bridge a tool-approval interrupt to ACP ``session/request_permission``.

        Sends a ``session/request_permission`` request to the ACP client and
        awaits the response. The response determines whether the tool call
        is approved or denied. The decision is routed back to the daemon
        via the loop input path to resume the interrupted graph.

        Args:
            session_id: ACP session identifier.
            loop_id: Daemon loop identifier.
            event: Wire-format event dict containing the interrupt.
        """
        # Extract action_requests from the interrupt
        data = event.get("data", event)
        if not isinstance(data, dict):
            return
        interrupt_data = data.get("__interrupt__", {})
        if not isinstance(interrupt_data, dict):
            return

        action_requests = interrupt_data.get("action_requests", [])
        if not isinstance(action_requests, list) or not action_requests:
            return

        # Get the interrupt_id for resume routing
        interrupt_id = interrupt_data.get("interrupt_id", "")
        if not interrupt_id:
            # Try to get it from the event metadata
            interrupt_id = event.get("interrupt_id", str(uuid.uuid4()))

        # Build ACP permission options
        options = [
            {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
            {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
            {"optionId": "reject_once", "name": "Deny once", "kind": "reject_once"},
            {"optionId": "reject_always", "name": "Always deny", "kind": "reject_always"},
        ]

        # Build tool_call update for each action request
        for ar in action_requests:
            if not isinstance(ar, dict):
                continue

            tool_call_id = ar.get("tool_call_id", str(uuid.uuid4()))
            tool_name = ar.get("tool_name", "unknown")
            tool_args = ar.get("args", {})

            # Build the ToolCallUpdate for the permission request
            tool_call_update = {
                "toolCallId": tool_call_id,
                "title": f"Tool call: {tool_name}",
                "rawInput": {"tool": tool_name, "args": tool_args},
            }

            # Send session/request_permission and await response
            req_id = self._next_request_id
            self._next_request_id += 1

            fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending_permissions[req_id] = fut

            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "session/request_permission",
                "params": {
                    "sessionId": session_id,
                    "toolCall": tool_call_update,
                    "options": options,
                },
            }

            logger.info(
                "[ACP] Permission request: session=%s, tool=%s, loop=%s",
                session_id,
                tool_name,
                loop_id,
            )

            await self._write_jsonrpc(request)

            try:
                response = await asyncio.wait_for(fut, timeout=_PERMISSION_TIMEOUT_S)
            except TimeoutError:
                logger.warning(
                    "[ACP] Permission request timed out for session=%s, tool=%s",
                    session_id,
                    tool_name,
                )
                response = {"outcome": "cancelled"}
            except asyncio.CancelledError:
                logger.info("[ACP] Permission request cancelled for session=%s", session_id)
                return

            # Route the response back to the daemon to resume the interrupted graph
            await self._route_permission_response(
                session_id,
                loop_id,
                interrupt_id,
                response,
                tool_call_id,
            )

    async def _route_permission_response(
        self,
        session_id: str,
        loop_id: str,
        interrupt_id: str,
        response: dict[str, Any],
        tool_call_id: str,
    ) -> None:
        """Route the ACP client's permission response back to the daemon.

        Translates the ACP permission outcome (allowed/denied) into a
        LangGraph resume payload and publishes it on the loop's EventBus topic
        so the StrangeLoop can resume the interrupted graph.

        Args:
            session_id: ACP session identifier.
            loop_id: Daemon loop identifier.
            interrupt_id: LangGraph interrupt ID for resume routing.
            response: ACP permission response dict with ``outcome`` key.
            tool_call_id: The tool call ID from the action request.
        """
        outcome = response.get("outcome", "cancelled")

        if outcome == "selected":
            # User selected an option — check if it's allow or deny
            option_id = response.get("optionId", "")
            if option_id.startswith("allow"):
                decision = {"type": "approve"}
                logger.info(
                    "[ACP] Permission allowed: session=%s, tool=%s", session_id, tool_call_id
                )
            else:
                decision = {"type": "reject"}
                logger.info(
                    "[ACP] Permission denied: session=%s, tool=%s", session_id, tool_call_id
                )
        else:
            # Cancelled or denied
            decision = {"type": "reject"}
            logger.info("[ACP] Permission cancelled: session=%s, tool=%s", session_id, tool_call_id)

        # Build the resume payload for the deepagents HumanInTheLoopMiddleware
        # The shape is {interrupt_id: {"decisions": [decision]}}
        resume_payload = {
            interrupt_id: {"decisions": [decision]},
        }

        # Publish the resume command on the loop's EventBus topic
        event_bus = getattr(self._manager, "_event_bus", None)
        if event_bus is not None:
            resume_msg = {
                "type": "command",
                "command": "resume",
                "loop_id": loop_id,
                "resume_payload": resume_payload,
            }
            topic = loop_event_topic(loop_id)
            await event_bus.publish(topic, resume_msg)

    def _translate_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Translate a daemon wire event to ACP content blocks.

        Args:
            event: Wire-format event dict from EventBus.

        Returns:
            List of ACP content blocks (may be empty if event is not translatable).
        """
        # Wire events have structure: {"type": "event", "loop_id": ..., "data": {...}}
        data = event.get("data", {})
        if not isinstance(data, dict):
            return []

        event_type = data.get("type", "")

        if event_type == OUTPUT_TEXT_DELTA:
            content = data.get("content", "")
            if content:
                return [_make_text_block(content)]

        elif event_type == OUTPUT_TEXT_COMPLETE:
            content = data.get("content", "")
            if content:
                return [_make_text_block(content)]

        elif event_type == OUTPUT_TEXT_END:
            # Stream end marker — no content block needed
            return []

        elif event_type == OUTPUT_PROGRESS:
            if self.send_progress:
                message = data.get("message", "")
                if message:
                    return [_make_progress_block(message)]

        elif event_type == OUTPUT_REASONING:
            if self.show_reasoning:
                content = data.get("content", "")
                if content:
                    return [_make_reasoning_block(content)]

        return []

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    async def _send_session_update(
        self,
        session_id: str,
        blocks: list[dict[str, Any]],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write an ACP ``session/update`` notification to stdout.

        Args:
            session_id: ACP session identifier.
            blocks: List of ACP content blocks.
            metadata: Optional stream metadata to include in the update params.
        """
        update: dict[str, Any] = {"blocks": blocks}
        if metadata:
            # Filter internal metadata keys — only pass ACP-visible fields.
            update["metadata"] = {k: v for k, v in metadata.items() if not k.startswith("_")}
        notification = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": update,
            },
        }
        await self._write_jsonrpc(notification)

    async def _write_jsonrpc(self, msg: dict[str, Any]) -> None:
        """Serialize dict to JSON and write to stdout with newline delimiter.

        Args:
            msg: JSON-RPC message dict.
        """
        text = json.dumps(msg) + "\n"
        await asyncio.to_thread(_write_stdout, text)

    # ------------------------------------------------------------------
    # Session mapping helpers
    # ------------------------------------------------------------------

    def _loop_to_session(self, loop_id: str) -> str | None:
        """Look up ACP session_id from daemon loop_id.

        Args:
            loop_id: Daemon loop identifier.

        Returns:
            ACP session_id, or None if not found.
        """
        for session_id, lid in self._session_map.items():
            if lid == loop_id:
                return session_id
        return None

    @property
    def client_count(self) -> int:
        """Return number of active ACP sessions."""
        return len(self._session_map)


# ---------------------------------------------------------------------------
# Module-level helpers (avoid blocking the event loop)
# ---------------------------------------------------------------------------


def _write_stdout(text: str) -> None:
    """Write text to stdout (blocking, called via asyncio.to_thread)."""
    sys.stdout.write(text)
    sys.stdout.flush()


async def _flush_stdout() -> None:
    """Flush stdout via to_thread to avoid blocking."""
    await asyncio.to_thread(sys.stdout.flush)
