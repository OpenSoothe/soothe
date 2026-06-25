"""Channel module (RFC-620).

Provides unified Channel abstraction for all communication endpoints:
- WebSocket (built-in, supports streaming)
- External plugins (Telegram, Discord, Slack, etc.) via entry_points

Key exports:
- Channel: Abstract base class for all channels
- ChannelMessage: Channel-layer message for platform routing
- WebSocketChannel: WebSocket implementation with streaming
- TelegramChannel: Telegram bot implementation (migrated from nanoBot)
- DiscordChannel: Discord bot implementation (migrated from nanoBot)
- SlackChannel: Slack bot implementation (migrated from nanoBot)
- EmailChannel: Email IMAP/SMTP implementation
- WhatsAppChannel: WhatsApp via Node.js bridge
- DingTalkChannel: DingTalk via Stream Mode
- QQChannel: QQ via qq-botpy SDK
- MatrixChannel: Matrix/Element via matrix-nio (optional)
- SignalChannel: Signal via signal-cli HTTP JSON-RPC
- FeishuChannel: Feishu/Lark via lark-oapi SDK
- WeixinChannel: WeChat via iLink HTTP API (optional crypto deps)
- WecomChannel: WeCom via wecom-aibot-sdk (optional)
- MSTeamsChannel: Microsoft Teams via Bot Framework (optional)
- MochatChannel: Mochat via Socket.IO + HTTP fallback
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
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.registry import (
    discover_all,
    discover_channel_names,
    discover_enabled,
    discover_plugins,
    load_channel_class,
)
from soothe_daemon.channels.websocket import WebSocketChannel

# External channels migrated from nanoBot (optional imports)
# Core channels (dependencies in base package)
try:
    from soothe_daemon.channels.telegram import TelegramChannel
except ImportError:
    TelegramChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.discord import DiscordChannel
except ImportError:
    DiscordChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.slack import SlackChannel
except ImportError:
    SlackChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.email import EmailChannel
except ImportError:
    EmailChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.whatsapp import WhatsAppChannel
except ImportError:
    WhatsAppChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.dingtalk import DingTalkChannel
except ImportError:
    DingTalkChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.qq import QQChannel
except ImportError:
    QQChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.feishu import FeishuChannel
except ImportError:
    FeishuChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.signal import SignalChannel
except ImportError:
    SignalChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.mochat import MochatChannel
except ImportError:
    MochatChannel = None  # type: ignore[misc,assignment]

# Optional dependency channels (require extra deps)
try:
    from soothe_daemon.channels.matrix import MatrixChannel
except ImportError:
    MatrixChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.weixin import WeixinChannel
except ImportError:
    WeixinChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.wecom import WecomChannel
except ImportError:
    WecomChannel = None  # type: ignore[misc,assignment]

try:
    from soothe_daemon.channels.msteams import MSTeamsChannel
except ImportError:
    MSTeamsChannel = None  # type: ignore[misc,assignment]

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
    "TelegramChannel",
    "DiscordChannel",
    "SlackChannel",
    "EmailChannel",
    "WhatsAppChannel",
    "DingTalkChannel",
    "QQChannel",
    "FeishuChannel",
    "SignalChannel",
    "MochatChannel",
    "MatrixChannel",
    "WeixinChannel",
    "WecomChannel",
    "MSTeamsChannel",
    # Registry
    "discover_all",
    "discover_channel_names",
    "discover_enabled",
    "discover_plugins",
    "load_channel_class",
]
