"""Channel base class (RFC-620 §1).

All communication endpoints (WebSocket, HTTP REST, Telegram, Discord, etc.)
implement this single Channel abstract class with capability flags.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_daemon.channel_manager import ChannelManager
    from soothe_daemon.channels.message import ChannelMessage

logger = logging.getLogger(__name__)


class Channel(ABC):
    """Abstract base class for all communication channels.

    Each channel implementation must define:
    - `name`: Unique identifier (e.g., "websocket", "telegram")
    - `display_name`: Human-readable name
    - Capability flags: `supports_inbound`, `supports_outbound`, `supports_streaming`
    - Abstract methods: `start()`, `stop()`, `send()`

    Optional streaming methods can be overridden:
    - `send_delta()`: Incremental text chunks
    - `send_reasoning_delta()`: Model thinking/reasoning
    """

    name: str = "base"
    display_name: str = "Base"

    # Capability flags
    supports_inbound: bool = True   # Can receive messages from platform
    supports_outbound: bool = True  # Can send messages to platform
    supports_streaming: bool = False  # Can handle incremental text deltas

    # Channel-level settings (set by ChannelManager from global config)
    send_progress: bool = True
    send_tool_hints: bool = False
    show_reasoning: bool = True

    def __init__(
        self,
        config: Any,
        manager: ChannelManager,
    ) -> None:
        """Initialize channel.

        Args:
            config: Channel-specific configuration.
            manager: ChannelManager for inbound routing.
        """
        self.config = config
        self._manager = manager
        self._running = False
        self.logger = logger.bind(channel=self.name) if hasattr(logger, "bind") else logger

    @abstractmethod
    async def start(self) -> None:
        """Start channel and begin listening for messages.

        This should be a long-running async task that:
        1. Connects to the platform
        2. Listens for incoming messages
        3. Calls `_handle_message()` for each incoming message

        For channels that don't receive messages (supports_inbound=False),
        this may just initialize resources and return.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop channel and clean up resources.

        This method should:
        1. Stop accepting new connections/messages
        2. Close existing connections
        3. Release all resources
        """

    @abstractmethod
    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message to platform.

        Args:
            chat_id: Conversation identifier on this platform.
            message: Message to deliver.

        Raises:
            Exception: On delivery failure (ChannelManager will retry).
        """

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream incremental text chunk.

        Override in subclasses to enable streaming. Implementations should
        raise on delivery failure so ChannelManager can retry.

        Args:
            chat_id: Conversation identifier.
            delta: Text chunk to stream.
            metadata: Optional metadata (e.g., _stream_id, _stream_end).
        """
        pass

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream reasoning/thinking content.

        Override in subclasses with native low-emphasis UI affordances
        (Slack context block, Telegram expandable blockquote, etc.).

        Args:
            chat_id: Conversation identifier.
            delta: Reasoning text chunk.
            metadata: Optional metadata.
        """
        pass

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark end of reasoning stream segment.

        Override in subclasses that buffer reasoning deltas for in-place updates.

        Args:
            chat_id: Conversation identifier.
            metadata: Optional metadata.
        """
        pass

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """Transcribe audio file via configured provider.

        Returns empty string on failure. Override to customize provider.

        Args:
            file_path: Path to audio file.

        Returns:
            Transcribed text, or empty string on failure.
        """
        # Defer to ChannelManager's transcription provider
        if hasattr(self._manager, "transcribe_audio"):
            return await self._manager.transcribe_audio(file_path)
        return ""

    async def login(self, force: bool = False) -> bool:
        """Perform interactive login (QR scan, OAuth, etc.).

        Override in subclasses that support interactive authentication.

        Args:
            force: Force re-authentication even if already authenticated.

        Returns:
            True if authenticated or login succeeds.
        """
        return True

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        is_dm: bool = False,
    ) -> str | None:
        """Handle incoming message from platform.

        Calls ChannelManager.handle_inbound() for routing. Permission check
        via is_allowed() is performed by manager.

        Args:
            sender_id: User identifier on this platform.
            chat_id: Conversation/thread identifier.
            content: Message text.
            media: Optional media attachments (URLs or file paths).
            metadata: Optional channel-specific metadata.
            is_dm: Whether this is a direct message.

        Returns:
            loop_id assigned to this conversation, or None if denied.
        """
        # Permission check
        if not self.is_allowed(sender_id):
            self.logger.warning(
                "Access denied for sender %s in chat %s",
                sender_id,
                chat_id,
            )
            return None

        # Add streaming hint if channel supports it
        meta = metadata or {}
        if self.supports_streaming:
            meta["_wants_stream"] = True

        # Route through manager
        loop_id = await self._manager.handle_inbound(
            channel=self.name,
            chat_id=chat_id,
            sender_id=sender_id,
            content=content,
            media=media or [],
            metadata=meta,
        )
        return loop_id

    def is_allowed(self, sender_id: str) -> bool:
        """Check sender permission via allow_from whitelist.

        Args:
            sender_id: User identifier.

        Returns:
            True if sender is allowed.
        """
        allow_list = self._get_allow_list()
        if "*" in allow_list:
            return True
        return str(sender_id) in allow_list

    def _get_allow_list(self) -> list[str]:
        """Extract allow_from list from config."""
        if isinstance(self.config, dict):
            return self.config.get("allow_from", [])
        return getattr(self.config, "allow_from", [])

    @property
    def is_running(self) -> bool:
        """Check if channel is running."""
        return self._running

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        """Return default configuration for onboarding.

        Override in subclasses to provide sensible defaults.
        """
        return {"enabled": False}

    @property
    def client_count(self) -> int:
        """Return number of connected clients (for compatibility with TransportServer)."""
        # Default implementation; override in subclasses
        return 0

    @property
    def transport_type(self) -> str:
        """Return transport type (for compatibility with TransportServer)."""
        return self.name
