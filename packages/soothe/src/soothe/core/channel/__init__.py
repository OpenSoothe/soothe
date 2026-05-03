"""RFC-204: Channel Protocol for user ↔ Soothe communication.

Message-centric, file-based inbox/outbox with optional acknowledgment
for critical messages.
"""

from .inbox import ChannelInbox
from .models import (
    CHANNEL_SOOTHE_TO_USER,
    CHANNEL_USER_TO_SOOTHE,
    ChannelMessage,
)
from .outbox import ChannelOutbox

__all__ = [
    "CHANNEL_SOOTHE_TO_USER",
    "CHANNEL_USER_TO_SOOTHE",
    "ChannelInbox",
    "ChannelMessage",
    "ChannelOutbox",
]
