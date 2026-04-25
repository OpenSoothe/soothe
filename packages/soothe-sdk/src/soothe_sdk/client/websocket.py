"""WebSocket client for daemon connections (RFC-0013)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from typing import Any

import websockets.asyncio.client
import websockets.exceptions

from soothe_sdk.client.protocol import decode, encode
from soothe_sdk.core.types import VerbosityLevel

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for communicating with Soothe daemon.

    This client connects to the daemon via WebSocket and provides
    streaming event access and bidirectional message passing.

    Args:
        url: WebSocket URL (e.g., "ws://localhost:8765").
    """

    def __init__(self, url: str = "ws://localhost:8765") -> None:
        """Initialize WebSocket client.

        Args:
            url: WebSocket URL.
        """
        self._url = url
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._connected = False
        self._pending_events: deque[dict[str, Any]] = deque()

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
            )
            self._connected = True

            logger.info("[Client] Connected to daemon at %s", self._url)
        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to daemon: {e}"
            raise ConnectionError(msg) from e

    async def close(self) -> None:
        """Close the connection with timeout to prevent exit hangs."""
        if self._ws:
            try:
                # Wait up to 2s for close handshake to prevent indefinite hangs
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except (TimeoutError, asyncio.TimeoutError):
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
            data = encode(message)
            # Remove newline for WebSocket (native framing)
            data = data.rstrip(b"\n")
            await self._ws.send(data.decode("utf-8"))
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
                    msg_dict = decode(message_str.encode("utf-8"))
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
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        interactive: bool = False,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        """Send user input to the daemon.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
            model: Optional ``provider:model`` override for this turn (daemon host config).
            model_params: Optional extra kwargs for model construction (JSON-serializable dict).
        """
        payload: dict[str, Any] = {"type": "input", "text": text}
        if autonomous:
            payload["autonomous"] = True
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
        if subagent is not None:
            payload["subagent"] = subagent
        if interactive:
            payload["interactive"] = True
        if model:
            payload["model"] = model
        if model_params:
            payload["model_params"] = model_params
        await self.send(payload)

    async def send_command(self, cmd: str) -> None:
        """Send a slash command to the daemon.

        Args:
            cmd: Command string.
        """
        await self.send({"type": "command", "cmd": cmd})

    async def send_thread_list(
        self,
        filter_dict: dict[str, Any] | None = None,
        *,
        include_stats: bool = False,
        include_last_message: bool = True,
        request_id: str | None = None,
    ) -> None:
        """Request persisted threads (RFC-402 ``thread_list`` / ``thread_list_response``)."""
        payload: dict[str, Any] = {
            "type": "thread_list",
            "include_stats": include_stats,
            "include_last_message": include_last_message,
        }
        if filter_dict:
            payload["filter"] = filter_dict
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_get(self, thread_id: str, *, request_id: str | None = None) -> None:
        """Request thread metadata for a specific thread."""
        payload: dict[str, Any] = {"type": "thread_get", "thread_id": thread_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        request_id: str | None = None,
    ) -> None:
        """Request persisted thread messages."""
        payload: dict[str, Any] = {
            "type": "thread_messages",
            "thread_id": thread_id,
            "limit": limit,
            "offset": offset,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_state(self, thread_id: str, *, request_id: str | None = None) -> None:
        """Request raw checkpoint state values for a thread."""
        payload: dict[str, Any] = {"type": "thread_state", "thread_id": thread_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_update_state(
        self,
        thread_id: str,
        values: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        """Persist partial state values for a thread."""
        payload: dict[str, Any] = {
            "type": "thread_update_state",
            "thread_id": thread_id,
            "values": values,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_archive(self, thread_id: str, *, request_id: str | None = None) -> None:
        """Request thread archival via daemon RPC."""
        payload: dict[str, Any] = {"type": "thread_archive", "thread_id": thread_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_delete(self, thread_id: str, *, request_id: str | None = None) -> None:
        """Request thread deletion via daemon RPC."""
        payload: dict[str, Any] = {"type": "thread_delete", "thread_id": thread_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_create(
        self,
        *,
        initial_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        """Request creation of a persisted thread via daemon RPC (RFC-402 ``thread_create``).

        Args:
            initial_message: Optional seed message for the new thread.
            metadata: Optional metadata dict (e.g., tags, workspace).
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "thread_create"}
        if initial_message is not None:
            payload["initial_message"] = initial_message
        if metadata is not None:
            payload["metadata"] = metadata
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

    async def send_thread_artifacts(self, thread_id: str, *, request_id: str | None = None) -> None:
        """Request thread artifacts via daemon RPC (RFC-402 ``thread_artifacts``).

        Args:
            thread_id: Thread ID to retrieve artifacts for.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "thread_artifacts", "thread_id": thread_id}
        if request_id is not None:
            payload["request_id"] = request_id
        await self.send(payload)

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
        request_id: str | None = None,
    ) -> None:
        """Subscribe client to loop events via daemon RPC (RFC-503 ``loop_subscribe``).

        Subscribes client to loop topic for real-time event streaming.
        Used by loop continue and loop attach commands.

        Args:
            loop_id: Loop identifier.
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_subscribe", "loop_id": loop_id}
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
        request_id: str | None = None,
    ) -> None:
        """Create new loop via daemon RPC (RFC-503 ``loop_new``).

        Creates fresh loop with new loop_id for new query/conversation.

        Args:
            request_id: Optional request correlation ID.
        """
        payload: dict[str, Any] = {"type": "loop_new"}
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
        thread_id: str,
        resume_payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> None:
        """Send interactive continuation payload for a paused daemon turn."""
        payload: dict[str, Any] = {
            "type": "resume_interrupts",
            "thread_id": thread_id,
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

        async with asyncio.timeout(timeout):
            while True:
                event = await self._read_from_socket()
                if not event:
                    raise TimeoutError(f"Timed out waiting for {response_type}")
                if event.get("request_id") != request_id:
                    self._pending_events.append(event)
                    continue
                if event.get("type") == "error":
                    raise RuntimeError(str(event.get("message", "daemon error")))
                if event.get("type") == response_type:
                    return event

    async def send_detach(self) -> None:
        """Notify the daemon that this client is detaching."""
        await self.send({"type": "detach"})

    async def send_resume_thread(
        self,
        thread_id: str,
        workspace: str | None = None,
    ) -> None:
        """Request the daemon to resume a specific thread.

        Args:
            thread_id: The thread ID to resume.
            workspace: Optional workspace override. Defaults to client's cwd.
        """
        from anyio import Path as AsyncPath

        workspace = (
            str(await AsyncPath.cwd())
            if workspace is None
            else str(await AsyncPath(workspace).resolve())
        )

        await self.send(
            {
                "type": "resume_thread",
                "thread_id": thread_id,
                "workspace": workspace,
            }
        )

    async def send_new_thread(self, workspace: str | None = None) -> None:
        """Request the daemon to start a new thread.

        Args:
            workspace: Optional workspace path. Defaults to client's cwd.
        """
        from anyio import Path as AsyncPath

        workspace = (
            str(await AsyncPath.cwd())
            if workspace is None
            else str(await AsyncPath(workspace).resolve())
        )

        await self.send(
            {
                "type": "new_thread",
                "workspace": workspace,
            }
        )

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
            RuntimeError: If daemon is not in ready state.
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

    async def subscribe_thread(
        self,
        thread_id: str,
        verbosity: VerbosityLevel = "normal",
    ) -> None:
        """Subscribe to receive events for a thread.

        Args:
            thread_id: Thread identifier to subscribe to
            verbosity: Verbosity preference (quiet|minimal|normal|detailed|debug)

        Raises:
            ConnectionError: If not connected
        """
        if not self._ws:
            raise ConnectionError("Not connected to daemon")

        msg = {
            "type": "subscribe_thread",
            "thread_id": thread_id,
            "verbosity": verbosity,
        }
        await self.send(msg)
        logger.info("[Client] Subscribed to thread %s (%s)", thread_id[:8], verbosity)

    async def wait_for_subscription_confirmed(
        self,
        thread_id: str,
        verbosity: VerbosityLevel = "normal",
        timeout: float = 5.0,  # noqa: ASYNC109
    ) -> None:
        """Wait for subscription confirmation message.

        Args:
            thread_id: Expected thread ID
            verbosity: Expected verbosity level
            timeout: Maximum seconds to wait

        Raises:
            TimeoutError: If confirmation not received
            ValueError: If confirmation has different thread_id or verbosity
        """
        async with asyncio.timeout(timeout):
            while True:
                event = await self._read_from_socket()
                if not event:
                    raise ValueError("No event received")
                if event.get("type") != "subscription_confirmed":
                    self._pending_events.append(event)
                    continue
                if event.get("thread_id") != thread_id:
                    self._pending_events.append(event)
                    continue
                echoed_verbosity = event.get("verbosity", "normal")
                if echoed_verbosity != verbosity:
                    logger.warning(
                        "Verbosity mismatch: requested=%s, received=%s",
                        verbosity,
                        echoed_verbosity,
                    )
                logger.debug(
                    "Subscription confirmed for thread %s with verbosity=%s",
                    thread_id,
                    echoed_verbosity,
                )
                return

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
        if self._pending_events:
            return self._pending_events.popleft()

        return await self._read_from_socket()

    async def _read_from_socket(self) -> dict[str, Any] | None:
        """Read one event directly from the websocket transport."""

        if not self._ws or not self._connected:
            return None

        try:
            message = await self._ws.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            return decode(message.encode("utf-8"))
        except websockets.exceptions.ConnectionClosed:
            return None
        except Exception:
            logger.exception("Error reading event")
            return None


__all__ = ["WebSocketClient"]
