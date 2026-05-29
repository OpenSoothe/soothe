"""Channel module (RFC-620).

Provides unified Channel abstraction for all communication endpoints:
- WebSocket (built-in, supports streaming)
- HTTP REST (built-in, supports_inbound only)
- External plugins (Telegram, Discord, Matrix, etc.) via entry_points

Key exports:
- Channel: Abstract base class for all channels
- ChannelMessage: Channel-layer message for platform routing
- WebSocketChannel: WebSocket implementation with streaming
- HttpRestChannel: HTTP REST implementation (inbound only)
- discover_channel_names(): List available channel modules (no imports)
- discover_enabled(): Load enabled channels (built-in + plugins)
"""

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.events import (
    AgentUIEvent,
    ChannelMessageReceived,
    ProgressEvent,
    ReasoningEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextEvent,
)
from soothe_daemon.channels.http_rest import HttpRestChannel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.registry import (
    discover_all,
    discover_channel_names,
    discover_enabled,
    discover_plugins,
    load_channel_class,
)
from soothe_daemon.channels.websocket import WebSocketChannel

__all__ = [
    # Base
    "Channel",
    # Message
    "ChannelMessage",
    # Events
    "AgentUIEvent",
    "ChannelMessageReceived",
    "ProgressEvent",
    "ReasoningEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "TextEvent",
    # Channel implementations
    "WebSocketChannel",
    "HttpRestChannel",
    # Registry
    "discover_all",
    "discover_channel_names",
    "discover_enabled",
    "discover_plugins",
    "load_channel_class",
]
