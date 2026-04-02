"""WebSocket client for daemon connections (RFC-0013)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any, Literal

import websockets.asyncio.client
import websockets.exceptions

from soothe.daemon.protocol import decode, encode

# Type alias for verbosity levels (RFC-0015, RFC-0022)
VerbosityLevel = Literal["quiet", "minimal", "normal", "detailed", "debug"]

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for connecting to the daemon.

    This client connects to the daemon via WebSocket and provides
    the same interface as the legacy Unix socket client.

    Args:
        url: WebSocket URL (e.g., "ws://localhost:8765").
        token: Optional authentication token.
    """

    def __init__(self, url: str = "ws://localhost:8765", token: str | None = None) -> None:
        """Initialize WebSocket client.

        Args:
            url: WebSocket URL.
            token: Optional authentication token.
        """
        self._url = url
        self._token = token
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to the daemon.

        Raises:
            ConnectionError: If connection fails.
        """
        try:
            self._ws = await websockets.asyncio.client.connect(self._url)
            self._connected = True

            # Send auth message if token provided
            if self._token:
                auth_msg = {"type": "auth", "token": self._token}
                await self._ws.send(encode(auth_msg).decode("utf-8").strip())

                # Wait for auth response
                response = await self._ws.recv()
                if isinstance(response, bytes):
                    response = response.decode("utf-8")
                auth_response = decode(response.encode("utf-8"))

                if not auth_response or not auth_response.get("success"):
                    await self.close()
                    raise ConnectionError("Authentication failed")

            logger.info("[Client] Connected to daemon at %s", self._url)
        except Exception as e:
            self._connected = False
            msg = f"Failed to connect to daemon: {e}"
            raise ConnectionError(msg) from e

    async def close(self) -> None:
        """Close the connection."""
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
            self._connected = False

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

    # Convenience methods matching DaemonClient interface

    async def send_input(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
    ) -> None:
        """Send user input to the daemon.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
        """
        payload: dict[str, Any] = {"type": "input", "text": text}
        if autonomous:
            payload["autonomous"] = True
            if max_iterations is not None:
                payload["max_iterations"] = max_iterations
        if subagent is not None:
            payload["subagent"] = subagent
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
    ) -> None:
        """Request persisted threads (RFC-0017 ``thread_list`` / ``thread_list_response``)."""
        payload: dict[str, Any] = {
            "type": "thread_list",
            "include_stats": include_stats,
            "include_last_message": include_last_message,
        }
        if filter_dict:
            payload["filter"] = filter_dict
        await self.send(payload)

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

        workspace = str(await AsyncPath.cwd()) if workspace is None else str(await AsyncPath(workspace).resolve())

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

        workspace = str(await AsyncPath.cwd()) if workspace is None else str(await AsyncPath(workspace).resolve())

        await self.send(
            {
                "type": "new_thread",
                "workspace": workspace,
            }
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
                event = await self.read_event()
                if not event:
                    raise ValueError("No event received")
                if event.get("type") != "daemon_ready":
                    continue
                state = event.get("state")
                if state == "ready":
                    return event
                message = event.get("message") or f"Daemon state is {state}"
                raise RuntimeError(str(message))

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
            event = await self.read_event()

        if not event:
            raise ValueError("No event received")

        if event.get("type") != "subscription_confirmed":
            msg = f"Expected subscription_confirmed, got {event.get('type')}"
            raise ValueError(msg)

        if event.get("thread_id") != thread_id:
            msg = f"Subscription thread_id mismatch: expected {thread_id}, got {event.get('thread_id')}"
            raise ValueError(msg)

        echoed_verbosity = event.get("verbosity", "normal")
        if echoed_verbosity != verbosity:
            logger.warning(
                "Verbosity mismatch: requested=%s, received=%s",
                verbosity,
                echoed_verbosity,
            )

        logger.debug("Subscription confirmed for thread %s with verbosity=%s", thread_id, echoed_verbosity)

    async def read_event(self) -> dict[str, Any] | None:
        """Read the next event from the daemon.

        Returns:
            Parsed event dict, or ``None`` on EOF.
        """
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
