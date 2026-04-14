"""Backend adapter for connecting Soothe TUI to Soothe daemon.

This adapter presents a Soothe-like interface to the TUI while
connecting to Soothe's daemon WebSocket backend, thread persistence,
and protocol orchestration.

RFC-606: Soothe CLI TUI Migration
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.thread.manager import ThreadContextManager
    from soothe.daemon.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

# Verbosity filtering per RFC-501
VerbosityTier = str  # "quiet", "minimal", "normal", "detailed"


class SootheBackendAdapter:
    """Adapter for Soothe TUI to connect to Soothe daemon.

    Replaces: Soothe agent.astream() with daemon WebSocket stream
    Implements: Message streaming, thread management, metadata provision

    This adapter mimics the interface of Soothe' agent.astream()
    while connecting to Soothe's backend infrastructure:
    - Daemon WebSocket for message streaming
    - ThreadContextManager for thread persistence
    - SootheConfig for configuration

    All modifications marked with '# SOOTHE:' comments.
    """

    def __init__(
        self,
        daemon_client: WebSocketClient,
        config: SootheConfig,
        thread_manager: ThreadContextManager,
    ) -> None:
        """Initialize adapter with Soothe backend components.

        Args:
            daemon_client: WebSocket client connected to Soothe daemon
            config: Soothe configuration (verbosity, etc.)
            thread_manager: Thread persistence manager
        """
        self._daemon_client = daemon_client
        self._config = config
        self._thread_manager = thread_manager

    async def stream_messages(
        self,
        user_input: str,
    ) -> AsyncIterator[Tuple[str, str, dict]]:
        """Stream messages from daemon in Soothe format.

        Mimics: agent.astream(stream_mode=["messages", "updates", "custom"])
        Returns: AsyncIterator of (namespace, mode, data) tuples
        Protocol events: Filtered by verbosity tier (RFC-501)

        Args:
            user_input: User's input message

        Yields:
            Tuple of (namespace, mode, data) in Soothe format
        """
        # SOOTHE: Send input to daemon
        await self._daemon_client.send({"type": "user_input", "content": user_input})

        # SOOTHE: Receive events from daemon WebSocket
        async for event_data in self._daemon_client.recv_stream():
            event = self._parse_daemon_event(event_data)

            if event is None:
                continue

            namespace, mode, data = event

            # SOOTHE: Apply protocol event filtering by verbosity tier
            if mode == "custom" and data.get("type", "").startswith("soothe."):
                filtered_event = self._adapt_protocol_event(data)
                if filtered_event is None:
                    # Event suppressed by verbosity filter
                    continue
                data = filtered_event

            yield (namespace, mode, data)

    def _parse_daemon_event(
        self,
        event_data: dict[str, Any],
    ) -> Optional[Tuple[str, str, dict]]:
        """Parse WebSocket event into (namespace, mode, data) format.

        Args:
            event_data: Raw event from daemon WebSocket

        Returns:
            Tuple of (namespace, mode, data) in Soothe format,
            or None if event should be skipped
        """
        event_type = event_data.get("type", "")

        # SOOTHE: Map daemon event types to Soothe stream modes
        if event_type in ("message", "tool_call", "tool_result"):
            # Message events
            return ("", "messages", event_data)
        elif event_type in ("update", "status"):
            # Update events
            return ("", "updates", event_data)
        elif event_type.startswith("soothe."):
            # SOOTHE: Protocol events
            return ("", "custom", event_data)
        else:
            # Unknown event type
            logger.warning("Unknown daemon event type: %s", event_type)
            return None

    def _adapt_protocol_event(
        self,
        event: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Filter protocol event by verbosity tier (RFC-501).

        Args:
            event: Protocol event dict

        Returns:
            Filtered event dict, or None if suppressed
        """
        verbosity = self._config.verbosity  # RFC-501 tier
        event_type = event.get("type", "")

        # SOOTHE: Verbosity filtering rules
        # quiet: suppress all protocol events
        if verbosity == "quiet":
            return None

        # minimal: show only plan events
        if verbosity == "minimal":
            if not event_type.startswith("soothe.plan"):
                return None

        # normal: show plan + context + memory
        if verbosity == "normal":
            if event_type.startswith("soothe.policy"):
                return None  # Policy too detailed for normal mode

        # detailed: show all
        return event

    async def get_thread_history(
        self,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Load thread messages for resume.

        Uses: ThreadContextManager backend
        Returns: Soothe message format

        Args:
            thread_id: Thread ID to load

        Returns:
            List of message dicts in Soothe format
        """
        # SOOTHE: Load thread from ThreadContextManager
        thread_info = await self._thread_manager.load_thread(thread_id)

        # SOOTHE: Convert to Soothe message format
        messages = []
        for msg in thread_info.messages:
            messages.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
            )

        return messages

    async def list_threads(self) -> list[dict[str, Any]]:
        """List available threads for resume UI.

        Returns:
            List of thread metadata dicts in Soothe format
        """
        # SOOTHE: List threads from ThreadContextManager
        threads = await self._thread_manager.list_threads()

        # SOOTHE: Convert to Soothe thread_selector format
        thread_list = []
        for t in threads:
            thread_list.append(
                {
                    "id": t.id,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.last_activity.isoformat(),
                    "message_count": len(t.messages),
                    "preview": t.messages[0].content[:100] if t.messages else "",
                    "tags": t.tags or [],
                    # SOOTHE: Additional metadata
                    "has_plan": t.has_active_plan,
                    "status": t.status,  # running/completed/archived
                }
            )

        return thread_list

    def get_agent_metadata(self) -> dict[str, Any]:
        """Provide agent info for UI display.

        Returns: model name, available tools, subagents
        """
        # SOOTHE: Return Soothe agent metadata
        return {
            "model": self._config.resolve_model("default"),
            "tools": [],  # SOOTHE: Would query from registry
            "subagents": [],  # SOOTHE: Would query from registry
        }
