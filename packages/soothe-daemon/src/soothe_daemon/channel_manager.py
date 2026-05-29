"""Channel manager for coordinating all communication channels (RFC-620).

Evolved from TransportManager, with added responsibilities:
- Inbound routing: Channel calls handle_inbound() → publish to EventBus
- Outbound routing: Subscribe to loop topics → translate → dispatch to channel
- Streaming: Coalesce deltas, buffer for non-streaming channels
- Retry policy: Exponential backoff on send failures
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.event import EventBus, loop_event_topic

logger = logging.getLogger(__name__)

# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)


class ChannelManager:
    """Manages all channels and coordinates message routing (RFC-620).

    The channel manager:
    1. Initializes enabled channels from configuration (via registry)
    2. Routes inbound messages to EventBus loop topics
    3. Subscribes to loop topics, translates events, dispatches outbound
    4. Handles streaming: coalesces deltas, buffers for non-streaming
    5. Applies retry policy on send failures

    When HTTP REST and WebSocket are both enabled, a single FastAPI ASGI app
    and one uvicorn listener are used (WebSocket bind host/port authoritative).

    Args:
        config: Daemon configuration.
        event_bus: EventBus for routing events.
        runner: Optional SootheRunner for HTTP REST transport.
        soothe_config: Optional SootheConfig for HTTP REST transport.
        session_manager: Optional ClientSessionManager for WebSocket sessions.
        autopilot_service: Optional AutopilotService for HTTP REST endpoints.
    """

    def __init__(
        self,
        config: SootheDaemonConfig,
        event_bus: EventBus,
        runner: Any | None = None,
        soothe_config: Any | None = None,
        session_manager: Any | None = None,
        autopilot_service: Any | None = None,
    ) -> None:
        """Initialize channel manager.

        Args:
            config: Daemon configuration.
            event_bus: EventBus for routing events.
            runner: Optional SootheRunner for HTTP REST transport.
            soothe_config: Optional SootheConfig for HTTP REST transport.
            session_manager: Optional ClientSessionManager for session management.
            autopilot_service: Optional daemon-owned AutopilotService.
        """
        self._config = config
        self._event_bus = event_bus
        self._runner = runner
        self._soothe_config = soothe_config
        self._session_manager = session_manager
        self._autopilot_service = autopilot_service

        # Channel instances
        self._channels: dict[str, Any] = {}  # name → Channel instance

        # Identity mapping (RFC-620 §4)
        self._loop_to_channel: dict[str, tuple[str, str]] = {}  # loop_id → (channel, chat_id)
        self._channel_to_loop: dict[tuple[str, str], str] = {}  # (channel, chat_id) → loop_id

        # Streaming state
        self._stream_buffers: dict[tuple[str, str], list[Any]] = {}  # (channel, chat_id) → delta list
        self._stream_coalesce_lock = asyncio.Lock()

        # Outbound dispatch
        self._outbound_task: asyncio.Task[None] | None = None
        self._started = False

        # Unified ASGI app (when WS + HTTP both enabled)
        self._unified_app: FastAPI | None = None
        self._unified_server: uvicorn.Server | None = None
        self._unified_serve_task: asyncio.Task[None] | None = None

        # Message handler for compatibility with TransportServer interface
        self._message_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._handshake_callback: Callable[[Any], list[dict[str, Any]]] | None = None

        # Transcription config (global)
        self._transcription_provider = getattr(config.channels, "transcription_provider", "groq")
        self._transcription_api_key = ""
        self._transcription_api_base = ""

    def set_message_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Set the unified message handler for all channels.

        Args:
            handler: Callback to handle incoming messages from any channel.
                Takes (client_id, message) as arguments.
        """
        self._message_handler = handler

    def set_handshake_callback(self, callback: Callable[[Any], list[dict[str, Any]]]) -> None:
        """Set the handshake callback for initial client messages.

        Args:
            callback: Callback to generate initial handshake messages.
        """
        self._handshake_callback = callback

    async def handle_inbound(
        self,
        channel: str,
        chat_id: str,
        sender_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Handle inbound message from a channel (RFC-620 §6.1).

        Called by Channel._handle_message(). Creates or retrieves loop_id,
        publishes ChannelMessageReceived to EventBus.

        Args:
            channel: Channel name (e.g., "websocket", "telegram").
            chat_id: Conversation identifier on the platform.
            sender_id: User identifier on the platform.
            content: Message text.
            media: Optional attachments.
            metadata: Optional channel-specific metadata.

        Returns:
            loop_id for this conversation.
        """
        # Create or retrieve loop_id
        loop_id = self._get_or_create_loop_id(channel, chat_id)

        # Create ChannelMessageReceived event
        from soothe_daemon.channels.events import ChannelMessageReceived

        event = ChannelMessageReceived(
            channel=channel,
            chat_id=chat_id,
            sender_id=sender_id,
            content=content,
            media=media or [],
            metadata=metadata or {},
        )

        # Publish to loop topic
        topic = loop_event_topic(loop_id)
        await self._event_bus.publish(topic, event.to_dict())

        logger.debug(
            "Inbound message from %s:%s routed to loop %s",
            channel,
            chat_id,
            loop_id,
        )

        return loop_id

    def _get_or_create_loop_id(self, channel: str, chat_id: str) -> str:
        """Get existing loop_id or create new one for (channel, chat_id).

        Args:
            channel: Channel name.
            chat_id: Conversation identifier.

        Returns:
            loop_id for this conversation.
        """
        key = (channel, chat_id)

        if key in self._channel_to_loop:
            return self._channel_to_loop[key]

        # Create new loop_id based on channel pattern (RFC-620 §4)
        if channel == "websocket":
            # WebSocket uses explicit loop_id from client
            loop_id = chat_id  # chat_id IS the loop_id for WebSocket
        else:
            # External channels: "{channel}:{chat_id}"
            loop_id = f"{channel}:{chat_id}"

        # Store mapping
        self._channel_to_loop[key] = loop_id
        self._loop_to_channel[loop_id] = key

        return loop_id

    def _build_channels(self) -> None:
        """Build channel instances based on configuration (RFC-620 §7)."""
        self._unified_app = None

        # Use new Channel implementations
        from soothe_daemon.channels.http_rest import HttpRestChannel
        from soothe_daemon.channels.websocket import WebSocketChannel

        # Check WebSocket config
        if not self._config.transports.websocket.enabled:
            raise RuntimeError("WebSocket channel is required - enable it in configuration")

        # Check HTTP REST config
        http_enabled = self._config.transports.http_rest.enabled
        if http_enabled:
            self._unified_app = FastAPI(
                title="Soothe Daemon",
                description="Unified WebSocket and REST API for Soothe",
                version="1.0.0",
                docs_url="/docs",
                redoc_url="/redoc",
            )

        # Create WebSocket channel
        ws_channel = WebSocketChannel(
            self._config.transports.websocket,
            manager=self,
            unified_app=self._unified_app,
            session_manager=self._session_manager,
        )
        self._channels["websocket"] = ws_channel
        logger.debug("Configured WebSocket channel")

        # Create HTTP REST channel if enabled
        if http_enabled:
            http_channel = HttpRestChannel(
                self._config.transports.http_rest,
                manager=self,
                runner=self._runner,
                soothe_config=self._soothe_config,
                session_manager=self._session_manager,
                unified_app=self._unified_app,
                autopilot_service=self._autopilot_service,
            )
            self._channels["http_rest"] = http_channel
            logger.debug("Configured HTTP REST channel (unified ASGI listener)")

        # Apply global channel settings to all channels
        for channel in self._channels.values():
            channel.send_progress = getattr(self._config.channels, "send_progress", True)
            channel.send_tool_hints = getattr(self._config.channels, "send_tool_hints", False)
            channel.show_reasoning = getattr(self._config.channels, "show_reasoning", True)

    async def _start_unified_listener(self) -> None:
        """Bind one uvicorn server for the shared FastAPI app (WS + HTTP)."""
        if self._unified_app is None:
            return

        ws = self._config.transports.websocket
        # Note: http_rest shares WebSocket listener when both enabled

        ssl_keyfile = None
        ssl_certfile = None
        if ws.tls_enabled and ws.tls_cert and ws.tls_key:
            ssl_certfile = ws.tls_cert
            ssl_keyfile = ws.tls_key
        elif ws.tls_enabled:
            logger.warning("TLS enabled but no certificate/key configured")

        uv_cfg = uvicorn.Config(
            app=self._unified_app,
            host=ws.host,
            port=ws.port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level="warning",
            ws_max_size=ws.max_frame_size,
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
        self._unified_server = uvicorn.Server(uv_cfg)
        self._unified_serve_task = asyncio.create_task(self._unified_server.serve())

        protocol = "wss" if ws.tls_enabled else "ws"
        logger.info(
            "Unified channels listening on %s://%s:%d (WebSocket / + REST /api)",
            protocol,
            ws.host,
            ws.port,
        )

    async def start_all(self) -> None:
        """Start all enabled channels.

        Raises:
            RuntimeError: If no message handler set or WebSocket not enabled.
        """
        if self._started:
            logger.warning("Channel manager already started")
            return

        if not self._message_handler:
            raise RuntimeError("Message handler not set - call set_message_handler() first")

        self._build_channels()

        # Start each channel with message handler
        start_tasks = []
        for name, channel in self._channels.items():
            # Channels need message_handler for compatibility
            if hasattr(channel, "start"):
                start_tasks.append(
                    channel.start(self._message_handler, self._handshake_callback)
                )

        try:
            await asyncio.gather(*start_tasks)
            if self._unified_app is not None:
                await self._start_unified_listener()
            self._started = True
            logger.debug(
                "Started %d channel(s): %s",
                len(self._channels),
                ", ".join(self._channels.keys()),
            )
        except Exception:
            await self.stop_all()
            raise

    async def stop_all(self) -> None:
        """Stop all channels."""
        if self._unified_server is not None:
            self._unified_server.should_exit = True
            if self._unified_serve_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(self._unified_serve_task, timeout=30.0)
                self._unified_serve_task = None
            self._unified_server = None

        if self._channels:
            try:
                await asyncio.gather(
                    *[channel.stop() for channel in self._channels.values()],
                    return_exceptions=True,
                )
            except Exception:
                logger.exception("Error stopping channels")

            self._channels.clear()

        # Clear mappings
        self._loop_to_channel.clear()
        self._channel_to_loop.clear()
        self._stream_buffers.clear()

        self._started = False
        self._unified_app = None
        logger.info("All channels stopped")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all channels.

        Args:
            message: Message dict to broadcast.
        """
        if not self._started:
            logger.warning("Broadcast called but channel manager not started")
            return

        logger.debug("Broadcasting to %d channels", len(self._channels))

        broadcast_tasks = [
            channel.broadcast(message) for channel in self._channels.values()
            if hasattr(channel, "broadcast")
        ]

        results = await asyncio.gather(*broadcast_tasks, return_exceptions=True)

        failure_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failure_count += 1
                logger.exception(
                    "Failed to broadcast to %s",
                    list(self._channels.keys())[i],
                    exc_info=result,
                )

        logger.debug("Broadcast completed, %d failures", failure_count)

    async def send_to_channel(
        self,
        channel_name: str,
        chat_id: str,
        message: Any,
    ) -> None:
        """Send message to specific channel/chat (RFC-620 outbound dispatch).

        Args:
            channel_name: Target channel name.
            chat_id: Target conversation identifier.
            message: ChannelMessage or dict to send.
        """
        channel = self._channels.get(channel_name)
        if channel is None:
            logger.warning("Unknown channel: %s", channel_name)
            return

        if not hasattr(channel, "supports_outbound") or not getattr(channel, "supports_outbound", True):
            logger.debug("Channel %s doesn't support outbound", channel_name)
            return

        await self._send_with_retry(channel, chat_id, message)

    async def _send_with_retry(
        self,
        channel: Any,
        chat_id: str,
        message: Any,
    ) -> None:
        """Send with exponential backoff retry (RFC-620 §3).

        Args:
            channel: Channel instance.
            chat_id: Target conversation.
            message: Message to send.
        """
        max_retries = getattr(self._config.channels, "send_max_retries", 3)
        max_attempts = max(max_retries, 1)

        for attempt in range(max_attempts):
            try:
                if hasattr(channel, "send"):
                    await channel.send(chat_id, message)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.exception(
                        "Failed to send to %s after %d attempts",
                        getattr(channel, "name", "unknown"),
                        max_attempts,
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Send to %s failed (attempt %d/%d): %s, retrying in %ds",
                    getattr(channel, "name", "unknown"),
                    attempt + 1,
                    max_attempts,
                    type(e).__name__,
                    delay,
                )
                await asyncio.sleep(delay)

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """Transcribe audio via configured provider.

        Args:
            file_path: Path to audio file.

        Returns:
            Transcribed text, or empty string on failure.
        """
        # TODO: Implement transcription using configured provider
        # (moved from nanobot channel-level to manager-level)
        return ""

    def get_channel(self, name: str) -> Any | None:
        """Get channel by name.

        Args:
            name: Channel name.

        Returns:
            Channel instance, or None if not found.
        """
        return self._channels.get(name)

    def get_loop_for_channel_chat(self, channel: str, chat_id: str) -> str | None:
        """Get loop_id for a (channel, chat_id) pair.

        Args:
            channel: Channel name.
            chat_id: Conversation identifier.

        Returns:
            loop_id, or None if not mapped.
        """
        return self._channel_to_loop.get((channel, chat_id))

    def get_channel_chat_for_loop(self, loop_id: str) -> tuple[str, str] | None:
        """Get (channel, chat_id) for a loop_id.

        Args:
            loop_id: Loop identifier.

        Returns:
            (channel, chat_id) tuple, or None if not mapped.
        """
        return self._loop_to_channel.get(loop_id)

    @property
    def client_count(self) -> int:
        """Return total connected clients across all channels."""
        return sum(
            getattr(ch, "client_count", 0) for ch in self._channels.values()
        )

    @property
    def channel_count(self) -> int:
        """Return number of active channels."""
        return len(self._channels)

    def get_channel_info(self) -> list[dict[str, Any]]:
        """Get information about all channels.

        Returns:
            List of channel info dicts.
        """
        return [
            {
                "type": getattr(ch, "transport_type", getattr(ch, "name", "unknown")),
                "client_count": getattr(ch, "client_count", 0),
            }
            for ch in self._channels.values()
        ]

    # Compatibility aliases (for gradual migration)
    @property
    def transport_count(self) -> int:
        """Alias for channel_count (compatibility with TransportManager)."""
        return self.channel_count

    def get_transport_info(self) -> list[dict[str, Any]]:
        """Alias for get_channel_info (compatibility with TransportManager)."""
        return self.get_channel_info()

    @property
    def channels(self) -> dict[str, Any]:
        """Return channels dict."""
        return self._channels

    @property
    def enabled_channels(self) -> list[str]:
        """Return list of enabled channel names."""
        return list(self._channels.keys())

    # -------------------------------------------------------------------------
    # Streaming Support (RFC-620 §6.3)
    # -------------------------------------------------------------------------

    async def send_streaming_message(
        self,
        channel_name: str,
        chat_id: str,
        message: ChannelMessage,
    ) -> None:
        """Send message with streaming support (RFC-620 §6.3).

        For streaming channels, sends deltas directly (optionally coalesced).
        For non-streaming channels, buffers deltas until stream end.

        Args:
            channel_name: Target channel name.
            chat_id: Target conversation.
            message: ChannelMessage with streaming metadata.
        """
        channel = self._channels.get(channel_name)
        if channel is None:
            logger.warning("Unknown channel for streaming: %s", channel_name)
            return

        if not getattr(channel, "supports_outbound", True):
            return

        # Check if channel supports streaming
        supports_streaming = getattr(channel, "supports_streaming", False)

        if message.is_stream_delta() and not message.is_stream_end():
            # Delta chunk (not end)
            if supports_streaming:
                # Streaming channel: send delta (may coalesce)
                await self._send_stream_delta(channel, chat_id, message)
            else:
                # Non-streaming channel: buffer
                await self._buffer_stream_delta(channel_name, chat_id, message)
        elif message.is_stream_end():
            # Stream end marker
            if supports_streaming:
                # Send final delta with end marker
                await self._send_stream_end(channel, chat_id, message)
            else:
                # Flush buffer as complete message
                await self._flush_stream_buffer(channel_name, chat_id)
        else:
            # Non-streaming message: send directly
            await self._send_with_retry(channel, chat_id, message)

    async def _send_stream_delta(
        self,
        channel: Any,
        chat_id: str,
        message: ChannelMessage,
    ) -> None:
        """Send streaming delta to channel (with optional coalescing).

        Args:
            channel: Channel instance.
            chat_id: Target conversation.
            message: Delta message.
        """
        # Coalesce deltas if enabled
        coalesced = await self._coalesce_stream_delta(channel, chat_id, message)

        if hasattr(channel, "send_delta"):
            try:
                await channel.send_delta(
                    chat_id,
                    coalesced.content,
                    coalesced.metadata,
                )
            except Exception as e:
                logger.warning("Failed to send delta: %s", e)
                await self._send_with_retry(channel, chat_id, message)

    async def _send_stream_end(
        self,
        channel: Any,
        chat_id: str,
        message: ChannelMessage,
    ) -> None:
        """Send stream end marker.

        Args:
            channel: Channel instance.
            chat_id: Target conversation.
            message: End marker message.
        """
        # Send any remaining delta content with end flag
        if hasattr(channel, "send_delta"):
            try:
                metadata = dict(message.metadata)
                metadata["_stream_end"] = True
                await channel.send_delta(chat_id, message.content or "", metadata)
            except Exception as e:
                logger.warning("Failed to send stream end: %s", e)

    async def _coalesce_stream_delta(
        self,
        channel: Any,
        chat_id: str,
        message: ChannelMessage,
    ) -> ChannelMessage:
        """Coalesce consecutive deltas for same stream.

        Reduces API calls when LLM generates faster than channel can process.
        Simple implementation: just return the message (coalescing is optional).

        Args:
            channel: Channel instance.
            chat_id: Target conversation.
            message: Incoming delta.

        Returns:
            Coalesced message (or original if no coalescing).
        """
        # For now, return original message
        # Full coalescing implementation would buffer and merge consecutive deltas
        return message

    async def _buffer_stream_delta(
        self,
        channel_name: str,
        chat_id: str,
        message: ChannelMessage,
    ) -> None:
        """Buffer delta for non-streaming channel.

        Args:
            channel_name: Channel name.
            chat_id: Target conversation.
            message: Delta to buffer.
        """
        key = (channel_name, chat_id)
        if key not in self._stream_buffers:
            self._stream_buffers[key] = []
        self._stream_buffers[key].append(message)

    async def _flush_stream_buffer(
        self,
        channel_name: str,
        chat_id: str,
    ) -> None:
        """Flush buffered deltas as complete message.

        Args:
            channel_name: Channel name.
            chat_id: Target conversation.
        """
        key = (channel_name, chat_id)
        if key not in self._stream_buffers:
            return

        buffered = self._stream_buffers[key]
        if not buffered:
            return

        # Combine all buffered deltas into one message
        combined_content = "".join(m.content for m in buffered)
        # Use metadata from last delta
        final_metadata = dict(buffered[-1].metadata) if buffered else {}
        final_metadata.pop("_stream_delta", None)
        final_metadata["_streamed"] = True  # Mark as combined stream

        # Create combined message
        from soothe_daemon.channels.message import ChannelMessage

        combined_message = ChannelMessage(
            channel=channel_name,
            chat_id=chat_id,
            content=combined_content,
            metadata=final_metadata,
        )

        # Clear buffer
        del self._stream_buffers[key]

        # Send combined message
        channel = self._channels.get(channel_name)
        if channel:
            await self._send_with_retry(channel, chat_id, combined_message)
