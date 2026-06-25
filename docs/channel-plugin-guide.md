# Channel Plugin Development Guide

This guide explains how to create new channel plugins for the Soothe daemon. Channels enable the agent to communicate with external platforms like Telegram, Discord, Matrix, Slack, and more.

## Overview

Soothe uses a unified `Channel` abstraction (RFC-620) where all communication endpoints—WebSocket, HTTP REST, and external chat platforms—implement the same interface. This enables:

- **Plugin discovery**: Built-in and external channels loaded via registry
- **Unified routing**: All messages flow through EventBus
- **Streaming support**: Real-time token streaming where supported
- **Capability flags**: Channels declare what they support (inbound, outbound, streaming)

## Architecture

```
External Platform (e.g., Telegram)
         ↓
Channel._handle_message()
         ↓
ChannelManager.handle_inbound()
         ↓
EventBus.publish("loop:{loop_id}")
         ↓
Agent receives → processes → emits OutputEvent
         ↓
ChannelManager translates → dispatches
         ↓
Channel.send() → Platform API
```

## Channel Interface

All channels inherit from `soothe_daemon.channels.base.Channel`:

```python
from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage

class MyChannel(Channel):
    # Required: unique identifier
    name = "my_channel"
    display_name = "My Channel"

    # Capability flags (override defaults)
    supports_inbound = True   # Can receive messages from platform
    supports_outbound = True  # Can send messages to platform
    supports_streaming = False  # Can handle real-time text deltas

    async def start(self) -> None:
        """Start channel, begin listening. Blocks indefinitely."""
        # Connect to platform, listen for messages

    async def stop(self) -> None:
        """Stop channel, cleanup resources."""

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message to platform."""
        # Send via platform API

    # Optional: streaming support
    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream incremental text chunk. Override for streaming channels."""
```

## Creating a Channel

### Step 1: Create the Package

Create a new Python package with your channel implementation:

```bash
mkdir soothe_my_channel
cd soothe_my_channel
touch __init__.py
```

### Step 2: Implement the Channel

```python
# soothe_my_channel/channel.py

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage

class MyChannel(Channel):
    name = "my_channel"
    display_name = "My Channel"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False  # Platform doesn't support editing

    def __init__(self, config, manager):
        super().__init__(config, manager)
        self._client = None  # Platform API client

    async def start(self) -> None:
        """Connect to platform and listen for messages."""
        # Initialize platform client
        self._client = MyPlatformClient(self.config.api_token)
        self._running = True

        # Listen for messages (typically in a loop)
        while self._running:
            message = await self._client.receive_message()
            await self._handle_message(
                sender_id=message.sender_id,
                chat_id=message.chat_id,
                content=message.text,
                metadata={"platform_msg_id": message.id},
            )

    async def stop(self) -> None:
        """Disconnect from platform."""
        self._running = False
        if self._client:
            await self._client.disconnect()

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send message to platform."""
        await self._client.send_message(
            chat_id=chat_id,
            text=message.content,
            attachments=message.media,
        )
```

### Step 3: Register as Entry Point

In your `pyproject.toml`:

```toml
[project.entry-points."soothe.channels"]
my_channel = "soothe_my_channel:MyChannel"
```

### Step 4: Configure in daemon.yml

```yaml
channels:
  my_channel:
    enabled: true
    api_token: "${MY_CHANNEL_API_TOKEN}"
    allow_from: ["*"]  # Or specific user IDs
```

## Key Concepts

### ChannelMessage

The `ChannelMessage` dataclass carries platform routing and content:

```python
@dataclass
class ChannelMessage:
    channel: str              # Target channel name
    chat_id: str              # Conversation identifier
    content: str              # Markdown text
    media: list[str]          # Attachments
    buttons: list[list[str]]  # Interactive buttons
    metadata: dict            # Flags: _progress, _stream_delta, etc.
```

Helper methods:
- `is_stream_delta()` - Check if streaming chunk
- `is_stream_end()` - Check if stream end marker
- `is_progress()` - Check if progress indicator
- `is_reasoning()` - Check if reasoning content

### Loop Identity

All conversations map to a loop ID for agent routing:
- WebSocket: `loop_id` is explicit (client-subscribed)
- External channels: `loop_id = "{channel}:{chat_id}"`

### Access Control

Use `allow_from` whitelist to control who can interact with the agent:

```yaml
channels:
  telegram:
    enabled: true
    allow_from: ["user123", "user456"]  # Only these users
    # Or:
    allow_from: ["*"]  # Everyone
```

In your channel, use `is_allowed()`:

```python
async def _handle_message(self, sender_id, chat_id, content, ...):
    if not self.is_allowed(sender_id):
        # Deny access or send pairing code
        return
    # Proceed with message
```

## Streaming Channels

Platforms that support message editing (Telegram, Discord, Slack) can show real-time token streaming:

```python
class StreamingChannel(Channel):
    supports_streaming = True

    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream incremental text chunk."""
        # Edit existing message or append to buffer
        message_id = self._get_stream_message_id(chat_id, metadata.get("_stream_id"))
        await self._client.edit_message(
            message_id=message_id,
            text=self._accumulate_delta(chat_id, delta),
        )
```

The ChannelManager handles buffering for non-streaming channels automatically.

## Best Practices

### 1. Error Handling

Raise exceptions on send failures—ChannelManager will retry with exponential backoff:

```python
async def send(self, chat_id: str, message: ChannelMessage) -> None:
    try:
        await self._client.send(chat_id, message.content)
    except ConnectionError:
        raise  # Manager will retry
```

### 2. Permission Checks

Always check `is_allowed()` before processing inbound messages:

```python
async def _handle_message(self, sender_id, ...):
    if not self.is_allowed(sender_id):
        logger.warning("Access denied for sender %s", sender_id)
        return None
    # Continue processing
```

### 3. Metadata Preservation

Pass platform-specific metadata through to help with replies:

```python
await self._handle_message(
    sender_id=msg.sender_id,
    chat_id=msg.chat_id,
    content=msg.text,
    metadata={
        "platform_msg_id": msg.id,
        "reply_to": msg.reply_to_id,
    },
)
```

### 4. Graceful Shutdown

Handle `CancelledError` properly in your message loop:

```python
async def start(self) -> None:
    try:
        while self._running:
            msg = await self._client.receive()
            await self._handle_message(...)
    except asyncio.CancelledError:
        logger.info("Channel cancelled, shutting down")
        raise
```

## Testing

See test examples in `packages/soothe-daemon/tests/unit/channels/`:

- `test_base.py` - Channel ABC tests
- `test_websocket_channel.py` - WebSocket channel tests
- `test_streaming.py` - Streaming support tests

## Example: Full Telegram Channel

See `soothe_daemon.channels.websocket.py` for a complete reference implementation demonstrating:

- Connection lifecycle
- CORS validation
- Session management integration
- Streaming support
- Message conversion