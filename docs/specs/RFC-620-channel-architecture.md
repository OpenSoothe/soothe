# RFC-620: Unified Channel Architecture

**RFC**: 620
**Title**: Unified Channel Architecture for Extensible Communication Endpoints
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-29
**Updated**: 2026-05-29
**Dependencies**: RFC-450, RFC-0015, RFC-000
**Author**: Xiaming Chen

## Abstract

Evolve soothe-daemon's `TransportManager` into a unified `ChannelManager` that treats WebSocket and HTTP REST as channels rather than special transports. Establish a two-layer message system separating channel routing from agent event processing, enabling integration of external chat platforms (Telegram, Discord, Matrix, Slack, WhatsApp, etc.) as first-class channels with plugin discovery support.

This RFC supersedes the hardcoded transport pattern in RFC-450 §"WebSocket Server" and §"HTTP REST Server", replacing special-case transports with a plugin-friendly `Channel` abstraction while preserving EventBus routing and ClientSession semantics.

## Problem & Solution

### Problem: Hardcoded Transport Limitations

1. **Special-case transports**: WebSocket and HTTP REST hardcoded in `TransportManager._build_transports()`, not extensible
2. **No plugin mechanism**: Adding new communication platforms (Telegram, Discord) requires modifying daemon code
3. **Parallel message systems**: SootheEvent (agent-centric) vs nanobot's `InboundMessage/OutboundMessage` (channel-centric) are incompatible
4. **Inconsistent identity model**: WebSocket routes by `loop_id`, chat platforms route by `chat_id` — no unified multi-user routing

### Solution: Channel Abstraction + Unified Routing

- Single `Channel` ABC with capability flags (`supports_inbound`, `supports_outbound`, `supports_streaming`)
- Plugin discovery via pkgutil scan + Python entry points (`soothe.channels` group)
- EventBus topics: `loop:{loop_id}` as primary routing, `channel:{name}` for channel-wide broadcast
- Loop as universal session identifier: `telegram:{chat_id}`, `discord:{chat_id}`, WebSocket explicit `loop_id`
- Two-layer message system: `ChannelMessage` (channel routing) ↔ `SootheEvent` (agent processing), translation at ChannelManager

**Design Goals**: Extensibility (plugins), unified routing (EventBus), backward compatibility (existing WebSocket/HTTP behavior unchanged), multi-user support (loop identity), streaming flexibility.

**Non-Goals**: Replacing SootheEvent system, changing agent loop architecture, modifying client SDK, authentication/authorization (external services).

## Guiding Principles

1. **Channel as Universal Endpoint** - WebSocket, HTTP REST, Telegram, Discord all implement same `Channel` interface
2. **Loop-Centric Routing** - `loop:{loop_id}` topic is primary; channels map conversations to loops
3. **Two-Layer Separation** - Channel routing concerns (platform, chat_id) separate from agent concerns (events, domain)
4. **Plugin-First Design** - Built-in channels discovered same way as external plugins (entry_points)
5. **Backward Compatibility** - Existing WebSocket/HTTP behavior preserved; config migration path

## Architectural Constraints

1. Channel capability flags determine behavior (no special-case logic per channel type)
2. EventBus is sole routing mechanism (no separate MessageBus)
3. ChannelManager intermediates all inbound/outbound translation
4. Loop ID format: `{channel}:{chat_id}` for external channels, explicit for WebSocket
5. Only `OutputEvent` domain events delivered to users (internal events stay in daemon)
6. Streaming optional per channel; buffering for non-streaming channels

## Specification

### 1. Channel Base Class

All communication endpoints implement a single `Channel` abstract class:

```python
class Channel(ABC):
    """Abstract base class for all communication channels."""

    name: str                       # Identifier: "websocket", "telegram"
    display_name: str               # Human-readable: "WebSocket", "Telegram"
    supports_inbound: bool = True   # Can receive messages from platform
    supports_outbound: bool = True  # Can send messages to platform
    supports_streaming: bool = False # Can handle incremental text deltas

    @abstractmethod
    async def start(self) -> None:
        """Start channel, begin listening. Blocks indefinitely."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop channel, cleanup resources."""

    @abstractmethod
    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message. Raises on failure."""

    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream incremental text chunk. Optional override."""

    async def send_reasoning_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream reasoning/thinking. Optional override."""
```

### 2. Two-Layer Message System

#### 2.1 Channel Layer

`ChannelMessage` handles platform routing and delivery:

```python
@dataclass
class ChannelMessage:
    channel: str              # Target channel name
    chat_id: str              # Conversation identifier
    content: str              # Text content (markdown)
    media: list[str]          # Attachments (file paths/URLs)
    buttons: list[list[str]]  # Interactive buttons
    metadata: dict            # Flags: _progress, _tool_hint, _stream_delta, _stream_end
```

#### 2.2 Agent Layer

Agent uses `SootheEvent` subclasses. Translation occurs at ChannelManager boundary:

```python
class ChannelMessageReceived(ProtocolEvent):
    """User message from any channel."""
    type: str = "soothe.channel.message.received"
    channel: str
    chat_id: str
    sender_id: str
    content: str
    media: list[str]
    metadata: dict

class TextEvent(OutputEvent):
    """Complete text output."""
    type: str = "soothe.output.text.complete"
    content: str

class TextDeltaEvent(OutputEvent):
    """Incremental text chunk."""
    type: str = "soothe.output.text.delta"
    content: str
    stream_id: str

class TextEndEvent(OutputEvent):
    """End text stream marker."""
    type: str = "soothe.output.text.end"
    stream_id: str
```

Only `OutputEvent` domain events translate to `ChannelMessage` for delivery.

### 3. ChannelManager

Replaces `TransportManager` with expanded responsibilities:

```python
class ChannelManager:
    # Identity mapping
    _loop_to_channel: dict[str, tuple[str, str]]  # loop_id → (channel, chat_id)
    _channel_to_loop: dict[tuple[str, str], str]  # (channel, chat_id) → loop_id

    # Inbound routing
    async def handle_inbound(
        self, channel: str, chat_id: str, sender_id: str, content: str, ...
    ) -> str:
        """
        Called by Channel._handle_message().
        Returns loop_id, publishes ChannelMessageReceived to EventBus.
        """

    # Outbound routing
    async def _handle_outbound_event(self, loop_id: str, event: SootheEvent) -> None:
        """
        EventBus callback. Translates OutputEvent → ChannelMessage.
        Handles streaming: coalesces deltas, buffers for non-streaming.
        """

    # Retry policy
    async def _send_with_retry(self, channel: Channel, chat_id: str, message: ChannelMessage) -> None:
        """Exponential backoff: 1s, 2s, 4s."""
```

### 4. Loop Identity Model

All channels use loop as universal session identifier:

| Channel | Loop ID |
|---------|---------|
| WebSocket | Explicit `loop_id` per client |
| Telegram | `"telegram:{chat_id}"` |
| Discord | `"discord:{chat_id}"` |
| Matrix | `"matrix:{room_id}"` |
| HTTP REST | Ephemeral or routed to existing |

### 5. EventBus Topics

| Topic | Purpose |
|-------|---------|
| `loop:{loop_id}` | Agent execution context (primary) |
| `channel:{name}` | Channel-wide broadcast |
| `channel:{name}:{chat_id}` | Specific conversation |
| `global` | Daemon-wide events |

### 6. Message Flows

#### 6.1 Inbound

```
Platform → Channel._handle_message()
         → ChannelManager.handle_inbound()
         → Map (channel, chat_id) → loop_id
         → Publish ChannelMessageReceived to "loop:{loop_id}"
         → Agent receives, processes
```

#### 6.2 Outbound

```
Agent emits OutputEvent
         → EventBus.publish("loop:{loop_id}", event)
         → ChannelManager receives
         → Lookup loop_id → (channel, chat_id)
         → Translate to ChannelMessage
         → Check channel.supports_streaming
         → Send (delta or buffered complete)
         → Channel.send() → Platform API
```

#### 6.3 Streaming

```
TextDeltaEvent:
  channel.supports_streaming=True → coalesce, send_delta()
  channel.supports_streaming=False → buffer

TextEndEvent:
  True → send final delta with _stream_end
  False → flush buffer as complete message
```

### 7. Channel Discovery

Plugin discovery via pkgutil + entry points:

```python
def discover_channel_names() -> list[str]:
    """Scan channels/ directory. No imports."""

def discover_enabled(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """Return enabled channels. Built-in + entry_points plugins."""
```

Entry points registration:
```toml
[project.entry-points."soothe.channels"]
websocket = "soothe_daemon.channels.websocket:WebSocketChannel"
http_rest = "soothe_daemon.channels.http_rest:HttpRestChannel"
```

### 8. Configuration

Rename `transports` → `channels`:

```yaml
channels:
  websocket:
    enabled: true
    host: "0.0.0.0"
    port: 8765

  http_rest:
    enabled: true

  telegram:
    enabled: false
    api_token: "${TELEGRAM_BOT_TOKEN}"
    streaming: true

  # Global settings
  transcription_provider: "groq"
  send_progress: true
```

### 9. Access Control

`allow_from` whitelist for sender permission:

```python
def is_allowed(self, sender_id: str) -> bool:
    allow_list = self.config.get("allow_from", [])
    if "*" in allow_list:
        return True
    return str(sender_id) in allow_list
```

## Implementation

### Phase 1: Core Infrastructure

| Task | File |
|------|------|
| Channel ABC | `soothe_daemon/channels/base.py` |
| ChannelMessage | `soothe_daemon/channels/message.py` |
| Event types | `soothe_daemon/channels/events.py` |
| Registry | `soothe_daemon/channels/registry.py` |
| OutputEvent subclasses | `soothe_sdk.core.events` |

### Phase 2: Convert Existing Transports

| Task | File |
|------|------|
| WebSocketChannel | `soothe_daemon/channels/websocket.py` (from transports/) |
| HttpRestChannel | `soothe_daemon/channels/http_rest.py` (from transports/) |
| ChannelManager | `soothe_daemon/channel_manager.py` (rename from transport_manager.py) |
| Config update | `soothe_daemon/config.py` |
| Server update | `soothe_daemon/server.py` |

### Phase 3: External Channels

| Task | Notes |
|------|-------|
| Telegram channel | Reference implementation |
| Plugin test | Mock entry_points |
| Integration test | Multi-channel routing |

### Phase 4: Streaming and Polish

| Task | Notes |
|------|-------|
| Delta coalescing | In ChannelManager |
| Buffering | For non-streaming channels |
| Retry policy | Exponential backoff |
| Documentation | Plugin guide |

## Testing

- **Unit**: Channel ABC compliance, message translation, registry
- **Integration**: Multi-channel routing, streaming, retry
- **Existing**: All daemon tests pass with ChannelManager

## Backward Compatibility

- Config migration: `transports.websocket` → `channels.websocket`
- Existing WebSocket client behavior unchanged
- HTTP REST endpoints unchanged
- ClientSessionManager continues to work with loop subscriptions

## Security Considerations

- `allow_from` whitelist restricts sender access
- Optional pairing system for DM approval
- Channel credentials (API tokens) via environment variables

## References

- RFC-450: Daemon communication protocol (WebSocket/HTTP REST architecture)
- RFC-0015: Event type naming conventions (`soothe.<domain>.<component>.<action>` format)
- RFC-000: System conceptual design
- IG-258: EventBus lock-free publishing
- IG-408: Loop-scoped subscriptions