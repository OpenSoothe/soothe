"""Message store for virtualized chat history (DOM window only).

Transcript models live in ``soothe_cli.runtime.state.transcript``. Widget
construction uses ``soothe_cli.tui.binding``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_cli.runtime.state.transcript import (
    UPDATABLE_FIELDS as _UPDATABLE_FIELDS,
)
from soothe_cli.runtime.state.transcript import (
    MessageData,
    MessageType,
    ToolStatus,
)
from soothe_cli.tui.binding import message_from_widget, message_to_widget

logger = logging.getLogger(__name__)

__all__ = [
    "MessageData",
    "MessageStore",
    "MessageType",
    "ToolStatus",
    "message_from_widget",
    "message_to_widget",
]


class MessageStore:
    """Manages message data and widget window for virtualization.

    This class stores all messages as data and manages a sliding window
    of widgets that are actually mounted in the DOM.

    Attributes:
        WINDOW_SIZE: Maximum number of widgets to keep in DOM.

            Balances DOM performance with smooth scrolling experience.
        HYDRATE_BUFFER: Number of messages to hydrate when scrolling near edge.

            Provides enough buffer to avoid visible loading pauses.
    """

    WINDOW_SIZE: int = 200
    HYDRATE_BUFFER: int = 8

    def __init__(self) -> None:
        """Initialize the message store."""
        self._messages: list[MessageData] = []
        self._index: dict[str, MessageData] = {}
        """ID -> MessageData lookup.

        Must contain exactly one entry per element of `_messages`. Any method
        that adds to or removes from `_messages` must update `_index`
        in lockstep.
        """
        self._visible_start: int = 0
        self._visible_end: int = 0

        # Track active streaming message - never archive this
        self._active_message_id: str | None = None

    @property
    def total_count(self) -> int:
        """Total number of messages stored."""
        return len(self._messages)

    @property
    def visible_count(self) -> int:
        """Number of messages currently visible (as widgets)."""
        return self._visible_end - self._visible_start

    @property
    def has_messages_above(self) -> bool:
        """Check if there are archived messages above the visible window."""
        return self._visible_start > 0

    @property
    def has_messages_below(self) -> bool:
        """Check if there are archived messages below the visible window."""
        return self._visible_end < len(self._messages)

    def append(self, message: MessageData) -> None:
        """Add a new message to the store.

        Args:
            message: The message data to add.
        """
        if message.id in self._index:
            logger.warning(
                "Duplicate message ID %r appended; previous entry will be unreachable via get_message()",
                message.id,
            )
        self._messages.append(message)
        self._index[message.id] = message
        self._visible_end = len(self._messages)

    def bulk_load(
        self,
        messages: list[MessageData],
        *,
        replace: bool = False,
    ) -> tuple[list[MessageData], list[MessageData]]:
        """Load many messages at once, keeping only the tail visible.

        This is optimized for thread resumption: all messages are stored as
        lightweight data, but only the last `WINDOW_SIZE` entries are marked
        visible (i.e. will need DOM widgets).

        Args:
            messages: Ordered list of message data to load.
            replace: When ``True``, discard any prior store contents first.
                Use for loop resume so repeated loads do not append duplicates.

        Returns:
            Tuple of (archived, visible) message lists.
        """
        if replace:
            self.clear()
        self._messages.extend(messages)
        for msg in messages:
            if msg.id in self._index:
                logger.warning(
                    "Duplicate message ID %r in bulk_load; previous entry will be unreachable via get_message()",
                    msg.id,
                )
            self._index[msg.id] = msg
        total = len(self._messages)

        if total <= self.WINDOW_SIZE:
            self._visible_start = 0
        else:
            self._visible_start = total - self.WINDOW_SIZE

        self._visible_end = total

        archived = self._messages[: self._visible_start]
        visible = self._messages[self._visible_start : self._visible_end]
        return archived, visible

    def get_message(self, message_id: str) -> MessageData | None:
        """Get a message by its ID.

        Args:
            message_id: The ID of the message to find.

        Returns:
            The message data, or None if not found.
        """
        return self._index.get(message_id)

    def get_message_at_index(self, index: int) -> MessageData | None:
        """Get a message by its index.

        Args:
            index: The index of the message.

        Returns:
            The message data, or None if index is out of bounds.
        """
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    def update_message(self, message_id: str, **updates: Any) -> bool:
        """Update a message's data.

        Only fields in `_UPDATABLE_FIELDS` may be updated. Unknown field
        names raise `ValueError` to catch typos early.

        Args:
            message_id: The ID of the message to update.
            **updates: Fields to update.

        Returns:
            True if the message was found and updated.

        Raises:
            ValueError: If any key in `updates` is not in the updatable
                allowlist.
        """
        unknown = set(updates) - _UPDATABLE_FIELDS
        if unknown:
            msg = f"Cannot update unknown or protected fields: {unknown}"
            raise ValueError(msg)

        msg_data = self._index.get(message_id)
        if msg_data is None:
            logger.warning(
                "update_message called for unknown ID %r; update discarded",
                message_id,
            )
            return False
        for key, value in updates.items():
            setattr(msg_data, key, value)
        return True

    def set_active_message(self, message_id: str | None) -> None:
        """Set the currently active (streaming) message.

        Active messages are never archived.

        Args:
            message_id: The ID of the active message, or None to clear.
        """
        self._active_message_id = message_id

    def is_active(self, message_id: str) -> bool:
        """Check if a message is the active streaming message.

        Args:
            message_id: The message ID to check.

        Returns:
            True if this is the active message.
        """
        return message_id == self._active_message_id

    def window_exceeded(self) -> bool:
        """Check if the visible window exceeds the maximum size.

        Returns:
            True if we should prune some widgets.
        """
        return self.visible_count > self.WINDOW_SIZE

    def get_messages_to_prune(self, count: int | None = None) -> list[MessageData]:
        """Get the oldest visible messages that should be pruned.

        Returns a contiguous run of messages from the START of the visible
        window. Stops at the active streaming message to avoid creating gaps
        in the visible window (which would desync store state from the DOM).

        Args:
            count: Number of messages to prune, or None to prune
                enough to get back to WINDOW_SIZE.

        Returns:
            List of messages to prune (remove widgets for).
        """
        if count is None:
            count = max(0, self.visible_count - self.WINDOW_SIZE)

        if count <= 0:
            return []

        to_prune: list[MessageData] = []
        idx = self._visible_start

        while len(to_prune) < count and idx < self._visible_end:
            msg = self._messages[idx]
            # Stop at the active message to keep the window contiguous
            if msg.id == self._active_message_id:
                break
            to_prune.append(msg)
            idx += 1

        return to_prune

    def mark_pruned(self, message_ids: list[str]) -> None:
        """Mark messages as pruned (widgets removed).

        Advances `_visible_start` past consecutive pruned messages at the front
        of the window.

        Args:
            message_ids: IDs of messages that were pruned.
        """
        pruned_set = set(message_ids)
        while (
            self._visible_start < self._visible_end
            and self._messages[self._visible_start].id in pruned_set
        ):
            self._visible_start += 1

    def get_messages_to_hydrate(self, count: int | None = None) -> list[MessageData]:
        """Get messages above the visible window to hydrate.

        Args:
            count: Number of messages to hydrate, or None for `HYDRATE_BUFFER`.

        Returns:
            List of messages to hydrate (create widgets for), in order.
        """
        if count is None:
            count = self.HYDRATE_BUFFER

        if self._visible_start <= 0:
            return []

        hydrate_start = max(0, self._visible_start - count)
        return self._messages[hydrate_start : self._visible_start]

    def mark_hydrated(self, count: int) -> None:
        """Mark that messages above were hydrated.

        Args:
            count: Number of messages that were hydrated.
        """
        self._visible_start = max(0, self._visible_start - count)

    def should_hydrate_above(self, scroll_position: float, viewport_height: int) -> bool:
        """Check if we should hydrate messages above the current view.

        Args:
            scroll_position: Current scroll Y position.
            viewport_height: Height of the viewport.

        Returns:
            True if user is scrolling near the top and we have archived messages.
        """
        if not self.has_messages_above:
            return False

        # Hydrate when within 2x viewport height of the top
        threshold = viewport_height * 2
        return scroll_position < threshold

    def should_prune_below(
        self, scroll_position: float, viewport_height: int, content_height: int
    ) -> bool:
        """Check if we should prune messages below the current view.

        Note:
            Not yet integrated into the scroll handler. Intended for future
            pruning of messages below the viewport when the user scrolls far up.

        Args:
            scroll_position: Current scroll Y position.
            viewport_height: Height of the viewport.
            content_height: Total height of all content.

        Returns:
            True if we have too many widgets and bottom ones are far from view.
        """
        if self.visible_count <= self.WINDOW_SIZE:
            return False

        # Only prune if user is far from the bottom
        distance_from_bottom = content_height - scroll_position - viewport_height
        threshold = viewport_height * 3
        return distance_from_bottom > threshold

    def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()
        self._index.clear()
        self._visible_start = 0
        self._visible_end = 0
        self._active_message_id = None

    def get_visible_range(self) -> tuple[int, int]:
        """Get the range of visible message indices.

        Returns:
            Tuple of (start_index, end_index).
        """
        return (self._visible_start, self._visible_end)

    def get_all_messages(self) -> list[MessageData]:
        """Get all stored messages.

        Returns:
            List of all message data (shallow copy).
        """
        return list(self._messages)

    def get_visible_messages(self) -> list[MessageData]:
        """Get messages in the visible window.

        Returns:
            List of visible message data.
        """
        return self._messages[self._visible_start : self._visible_end]
